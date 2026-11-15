# Content-Addressed Store

`appinfra.cas` stores immutable objects identified by the hash of their content, and named refs
that point at commits. The model follows git: blobs hold bytes, trees name blobs and subtrees,
commits point at a tree and the commits they follow. Vectors add long lists of object ids whose
versions share storage. It is a storage layer for versioned content and its history, not a git
implementation; git cannot read its repositories.

## Quick Start

```python
from appinfra.cas import Blob, Commit, FileStore, Tree, TreeEntry, canonical_json

store = FileStore(lg, "/var/lib/app/cas")
repo = store.repo("docs")

readme = repo.put(Blob(b"hello"))
tree = repo.put(Tree((TreeEntry("readme", "blob", readme),)))

# Add a commit on top of a ref and move the ref, in one call
commit_id = repo.commit(
    "main", tree, payload=canonical_json({"message": "first version"})
)

# Read it back
commit = repo.get(commit_id, Commit)
for ancestor in repo.ancestors(commit_id):  # Commit objects, newest first
    print(ancestor.id, ancestor.tree)
```

## Objects

| Class | Holds |
|-------|-------|
| `Blob(data)` | Opaque bytes |
| `Tree(entries)` | `TreeEntry(name, type, id)` entries, `type` is `"blob"`, `"tree"` or `"vector"`; sorted by name, names unique |
| `Commit(tree, parents=(), payload=b"")` | A tree id, parent commit ids, and caller-owned payload bytes |
| `VectorNode(level, children, counts=())` | One chunk of a [vector](#vectors); built and read by `Vector` |

All derive from `Object` and are frozen dataclasses. `obj.id` is the sha256 hex digest of
`"<type> <length>\0"` followed by `obj.serialize()`, so a blob and a tree with the same bytes get
different ids. A commit has no author or timestamp: the same tree, parents and payload always give
the same id. `obj.links()` returns the `(id, type)` pairs an object points at; a type of `None`
accepts any type (a vector's elements).
`canonical_json(value)` gives stable bytes for structured data and payloads; NaN and infinities
raise `ValueError`, having no JSON form.

Building an object from invalid values (an empty entry name, a malformed id, duplicate names or
parents) raises `ValueError`. The same problems found in bytes read back from storage raise
`CorruptObjectError`.

## Repositories

A store holds repositories by name; each has its own objects and refs. `store.repo(name)` returns
a `Repo`. A repository exists while it holds an object or a ref: its first write creates it, and
reads, locks and failed writes do not. `store.list_repos()` lists the repositories that exist;
`store.delete_repo(name)` deletes one with everything in it.

Repository and ref names are non-empty strings of at most 255 UTF-8 bytes, other than `.` and
`..`, without NUL. A `/` is part of a name. `FileStore` allows less: see below.

| Method | Does |
|--------|------|
| `put(obj) -> id` | Stores an object. What it points at (a tree's entries, a commit's tree and parents, a vector node's children) must already be stored with the right type |
| `batch()` | A context manager whose `Batch` stores every object put on it when the block ends; see [Batches](#batches) |
| `get(id)`, `get(id, Commit)` | Returns the object or `None`; with a class, raises `ObjectTypeError` on another type. The bytes are hashed again: content that does not match its id raises `CorruptObjectError` |
| `id in repo` | Whether the object is stored |
| `get_ref(name)` | The commit a ref points at, or `None` |
| `set_ref(name, new, old) -> bool` | Moves a ref from `old` to `new`; `old=None` means the ref must not exist |
| `delete_ref(name, old) -> bool` | Deletes a ref that points at `old` |
| `refs(prefix="")` | Refs by name prefix, sorted |
| `commit(ref, tree, payload=b"") -> id` | Commits on top of the ref's current commit and moves the ref |
| `ancestors(*ids)` | The commits of the history, each once and read once, every commit before its parents. Reads the whole history before yielding |
| `first_parents(id)` | The commit, then each first parent back to a root, read one at a time: stopping early reads only that far |
| `prune(expire)` | Deletes unreachable objects older than `expire` seconds |

### Refs and concurrent writers

Refs move only with compare-and-set: `set_ref` and `delete_ref` return `False` and change nothing
when the ref no longer points at `old`. `commit()` raises `RefConflictError` in that case; the new
commit stays stored without a ref. A `/` is part of a ref name; `refs("branches/")` lists by prefix.

To store a commit without moving a ref yet, put it and move the ref later:

```python
commit_id = repo.put(Commit(tree, (tip,), payload))
...  # e.g. once the change is approved
repo.set_ref("main", commit_id, tip)
```

### Batches

`repo.batch()` stores several objects together: `batch.put(obj)` queues an object and returns its
id, and the block's end writes every queued object under one hold of the shared lock, with one
lookup for all their links and one `Store.write_objects` call. Objects are written children first,
whatever order they were put in; a queued object may point at objects queued in the same batch or
already stored. A missing or mistyped link raises when the block ends and nothing is written; an
exception inside the block also writes nothing. `batch.get(id)` returns queued objects too, so code
can read back what it just put. After the block, reads go to the repository and `put` raises
`RuntimeError`. Refs move afterwards, as usual:

```python
with repo.batch() as batch:
    blob_id = batch.put(Blob(b"hello"))
    tree_id = batch.put(Tree((TreeEntry("greeting", "blob", blob_id),)))
repo.commit("main", tree_id)
```

### Pruning

`prune(expire)` deletes objects that are unreachable and were last written more than `expire`
seconds ago, and returns how many it deleted. It keeps everything a ref reaches and everything a
recent object reaches: a tree or commit still waiting for its ref keeps what it points at, however
old. Putting an existing object again refreshes its write time.

Every stored object's links are always stored. `put` checks an object's links and stores it under
the repository's shared lock; `prune` decides and deletes under the exclusive lock, so writers wait
for it and it never removes a link between a writer's check and write. A writer that holds an id
across a prune that deleted it gets `ObjectNotFoundError` from its next `put` or `set_ref`, never
a dangling link.

A commit held without a ref for longer than `expire` is deleted: give it a ref of its own (for
example `pending/<id>`) if a later `set_ref` can take longer. `expire=0` deletes everything without
a ref, including objects a writer stored but has not referenced yet. If an object to keep is
missing, `prune` raises `ObjectNotFoundError` and deletes nothing.

## Vectors

A `Vector` is an immutable list of object ids that stores each new version for about the size of
the change, whatever the length of the list. Its elements live in leaf chunks with interior nodes
above them (`VectorNode` objects), and versions share every unchanged chunk. It suits a list that
is committed at every step and edited mostly at its ends, such as an agent's message history:
append the new messages, and from time to time drop, summarize or trim old ones.

```python
from appinfra.cas import Blob, Tree, TreeEntry, Vector, canonical_json

with repo.batch() as batch:
    ids = [batch.put(Blob(canonical_json(m))) for m in messages]
    vector = Vector.build(batch, ids)
    tree = batch.put(Tree((TreeEntry("messages", "vector", vector.id),)))
repo.commit("session", tree)

# Later steps: store the new elements, edit, commit
with repo.batch() as batch:
    new = [batch.put(Blob(canonical_json(m))) for m in new_messages]
    vector = vector.on(batch).append(new)
    tree = batch.put(Tree((TreeEntry("messages", "vector", vector.id),)))
repo.commit("session", tree)
```

| Method | Does |
|--------|------|
| `Vector.build(source, ids)`, `Vector.empty(source)` | Stores a new vector |
| `Vector(source, root_id)` | Opens a stored vector; its root is read on first use |
| `v.id` | The root node's id. The same list always has the same id, however it was edited; vectors compare equal by it |
| `len(v)`, `v[i]`, `iter(v)`, `v.ids(start, stop)` | Reads; iteration reads one leaf at a time, only the leaves of the range |
| `v.append(ids)`, `v.splice(start, stop, ids=())` | Returns the edited vector: insert, delete, replace or point edit |
| `v.assign(ids)` | Returns the vector holding `ids`, sharing every chunk it has in common with `v` |
| `v.diff(other)` | `Splice(start, stop, ids)` edits that turn `v` into `other`, ascending; apply them last to first |
| `v.on(source)` | The same vector, reading and writing through another repository or batch |

`source` is a `Repo` or a `Batch`. With a batch, new nodes are written when its block ends; with a
repository, each is stored at once. Elements are ids of objects of any type, which must be stored
(or queued on the same batch) when the nodes listing them are written. A vector-bound batch whose
block has ended still reads; to edit further, rebind with `on(repo)`.

What an edit costs:

- `append` and `splice` read the paths to the edit and store the chunks it touches plus one path
  up to the root. A commit that appends to a 20,000-element vector stores three nodes, as does
  dropping or replacing a prefix.
- `assign` takes the whole new list, for code that has the list rather than the edit (a list
  rebuilt by a compaction step, say). It stores the same nodes the matching splices would, reads
  only this vector's interior nodes, and hashes the whole list: CPU time grows with the length.
- Several splices in one batch each store their own path; the intermediate roots are left
  unreferenced for `prune`. `assign` of the final list stores only the final version.

`diff` compares the two vectors' interior nodes and reads only the leaves that differ. A single
contiguous edit comes back as exactly that edit. To find what an edit replaced, diff a commit's
vector against its parent's: the parent still holds the old elements for as long as the history
reaching it is kept.

Put a vector in a tree entry of type `"vector"` to commit it. Refs then reach every node and
element, `prune` keeps them, and dropping the history that reaches an old version releases the
elements only it held.

### Chunking

A chunk ends after an entry whose id's first 32 bits are divisible by 48, once the chunk holds at
least 16 entries, or when it reaches 256 entries; interior levels are cut the same way over their
child ids. Because the cut points depend on the ids and not on positions, an edit changes the
chunks around it and nowhere else, and identical lists get identical roots. The minimum keeps
chunks at 16 entries or more whatever the ids (a long run of one id included); the maximum bounds
a node's size. Chunks hold about 63 entries on average. These numbers, and the node encoding, are
part of the format: changing them changes every root id.

A leaf is serialized as one level byte followed by the 32-byte binary digests of its elements; an
interior node adds the 8-byte big-endian element count after each child's digest.

## Stores

| Store | Use |
|-------|-----|
| `MemoryStore(lg)` | Tests and single-process use; thread-safe |
| `FileStore(lg, root, fsync=True)` | One directory per repository; safe across threads and processes on a local filesystem. `fsync=False` skips flushing, for test suites |

`FileStore` writes every file to a `tmp/` directory, fsyncs it and renames it into place, so a
reader never sees a partial file. It also fsyncs the directory after every rename, unlink and new
directory, so a write or delete that returned survives power loss; that costs a second fsync per
write (committing a few small objects measured around 20 ms on NVMe). With `fsync=False` writes
stay atomic and locked but are not flushed; use it for test suites, or put the store on tmpfs.
A writer waiting on a lock that `delete_repo` renamed away notices and locks the live one.
`delete_repo` renames the repository away before removing it, so a crash never leaves part
of a repository; the next `delete_repo` of that name removes such a leftover. `prune` also deletes
temp files a writer that died left in `tmp/`, once older than `expire`. Its locks are `flock`
locks, which need a local filesystem rather than NFS.

Names are URL-quoted into one path segment, where each byte outside `A-Z a-z 0-9 - . _ ~` takes
three. A quoted ref name must fit 255 bytes and a quoted repository name 214 (room for the rename
on delete); longer names raise `InvalidNameError`. Layout:

```
<root>/<repo>/
    objects/<id[:2]>/<id[2:]>    "<type> <length>\0" followed by the serialized bytes
    refs/<ref>                   the commit id
    repo.lock                    shared for writers, exclusive for prune and delete
    refs.lock                    held while a ref is compared and written
    tmp/
```

### Writing a store

Subclass `Store` and implement its storage primitives (`lock`, `read_object`, `object_type`,
`write_object`, `list_objects`, `delete_objects`, `read_ref`, `write_ref`, `list_refs`,
`delete_repo`, `list_repos`). `Repo` builds everything else on them. `write_ref` must be atomic,
and `lock(repo, exclusive)` must be a shared/exclusive lock that holds across every thread and
process using the store. A backend whose write times come from another clock than the local one
(a database server's `now()`) overrides `now()` to return that clock, so `prune` measures age on
the same clock it compares against. A backend that can leave debris behind (temp files, partial
uploads) overrides `sweep(repo, cutoff)`, which `prune` calls under the exclusive lock; it removes
nothing by default. Two bulk primitives have defaults that call the single-object ones in a loop;
a backend that can do better overrides them: `object_types(repo, ids)`, which `put` and batches
use to check all of an object's links at once (one query instead of one per link), and
`write_objects(repo, objects)`, which writes a batch. `write_objects` receives children before the
objects that point at them and must keep that order on storage, or make all of them visible at
once (one transaction), so a crash never leaves an object without its links.
`conformance.dangling_links(store, repo)` lists stored objects whose links are missing, for a
backend's own crash tests. Run the conformance suite against the new store; it needs a `store`
fixture and an `age` fixture that moves an object's write time into the past:

```python
import pytest
from appinfra.cas.conformance import StoreConformance


class TestMyStore(StoreConformance):
    @pytest.fixture
    def store(self, tmp_path):
        return MyStore(tmp_path)

    @pytest.fixture
    def age(self, store):
        def age(
            repo, object_id, seconds
        ): ...  # move the object's stored write time back by `seconds`

        return age
```

`StoreConformance` is made of two parts that can also run on their own:
`StoreSerialConformance` calls the store from the test's thread only, and
`StoreConcurrencyConformance` calls it from several threads at once and needs only the `store`
fixture. A store tested in the unit suite subclasses the serial part there and the concurrency
part in its integration suite, since a unit test runs on one thread.

A store subclass passes the logger to `Store.__init__(lg)`.

## Logging

Stores log to a logger derived from `lg` named `cas` (e.g. `/cas` under the root logger), so its
level can be set on its own. Nothing is logged at `info`: an application running at `info` sees
only a `warning` when cleanup finds what a crashed writer left behind (temp files in `tmp/`, or a
directory a failed `delete_repo` left). Errors are raised, not logged.

| Level | Event |
|-------|-------|
| `warning` | Temp files of a writer that died removed by `prune`; a failed delete's leftover removed |
| `debug` | `prune` finished (`deleted`, `kept`, `swept`, `after`); repository deleted |
| `trace` | Ref moved or deleted; `commit()` found its ref moved; a lock relocked after its file was renamed away |

## Errors

All derive from `CasError` (an `InfraError`).

| Error | Raised when |
|-------|-------------|
| `ObjectNotFoundError` | An object an operation needs is missing |
| `ObjectTypeError` | An object has another type than required |
| `CorruptObjectError` | Stored bytes do not parse as a valid object or do not match their id; carries `repo` and `object_id` when known |
| `RefConflictError` | `commit()` found its ref moved by another writer |
| `InvalidNameError` | A repository or ref name is empty, `.`, `..`, contains NUL, is too long or not UTF-8, or an id is malformed (also a `ValueError`) |
