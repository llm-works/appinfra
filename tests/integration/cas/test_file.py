# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""FileStore against the store conformance suite, plus its on-disk behaviour."""

from __future__ import annotations

import multiprocessing
import os
import threading
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from unittest import mock

import pytest

from appinfra.cas import (
    Blob,
    Commit,
    CorruptObjectError,
    FileStore,
    InvalidNameError,
    Tree,
    TreeEntry,
)
from appinfra.cas import file as file_store
from appinfra.cas.conformance import Age, StoreConformance
from appinfra.log import Logger
from tests.helpers.fork import forks_in_xdist_worker

pytestmark = pytest.mark.integration

LG = Logger("test-cas")


def _object_file(root: Path, repo: str, object_id: str) -> Path:
    return root / repo / "objects" / object_id[:2] / object_id[2:]


class TestFileStore(StoreConformance):
    """FileStore passes the conformance suite."""

    @pytest.fixture
    def store(self, tmp_path: Path) -> FileStore:
        """A fresh, empty store under a temp directory."""
        return FileStore(LG, tmp_path / "store")

    @pytest.fixture
    def age(self, tmp_path: Path) -> Age:
        """Move an object file's mtime into the past."""

        def age(repo: str, object_id: str, seconds: float) -> None:
            path = _object_file(tmp_path / "store", repo, object_id)
            mtime = path.stat().st_mtime - seconds
            os.utime(path, (mtime, mtime))

        return age


class TestFileStoreWithoutFsync(TestFileStore):
    """With fsync=False the store behaves the same, and never flushes."""

    @pytest.fixture
    def store(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FileStore:
        """A store that must not call fsync at all."""

        def no_fsync(fd: int) -> None:
            raise AssertionError("fsync called with fsync=False")

        monkeypatch.setattr(file_store.os, "fsync", no_fsync)
        return FileStore(LG, tmp_path / "store", fsync=False)


def _set_ref(root: str, head: str, base: str) -> bool:
    """Move ref main from base to head in a separate process."""
    return FileStore(LG, root).repo("r").set_ref("main", head, base)


def _put_blob(root: str) -> str:
    """Put a blob from a separate process."""
    return FileStore(LG, root).repo("r").put(Blob(b"from another process"))


def _commit_then_die(root: str, tree_id: str, parent: str) -> None:
    """Store a commit, then end the process before moving any ref."""
    FileStore(LG, root).repo("r").put(Commit(tree_id, (parent,), b"lost"))
    os._exit(17)


class TestFileLayout:
    """Where FileStore puts things and how it reads them back."""

    def test_object_file_has_header_and_data(self, tmp_path: Path) -> None:
        """An object is '<type> <length>\\0' plus its bytes, under a fan-out dir."""
        blob_id = FileStore(LG, tmp_path).repo("r").put(Blob(b"hello"))
        assert _object_file(tmp_path, "r", blob_id).read_bytes() == b"blob 5\0hello"

    def test_ref_name_with_slash_is_one_file(self, tmp_path: Path) -> None:
        """Ref names are quoted into a single path segment."""
        repo = FileStore(LG, tmp_path).repo("r")
        commit_id = repo.commit("branches/a b", repo.put(Tree()))
        assert (tmp_path / "r" / "refs" / "branches%2Fa%20b").read_text() == commit_id
        assert repo.refs() == {"branches/a b": commit_id}

    def test_repo_name_is_quoted(self, tmp_path: Path) -> None:
        """A slash in a repository name cannot escape the root."""
        store = FileStore(LG, tmp_path)
        store.repo("a/../b").put(Blob(b"x"))
        assert [p.name for p in tmp_path.iterdir()] == ["a%2F..%2Fb"]
        assert store.list_repos() == ["a/../b"]

    def test_temp_files_are_not_listed(self, tmp_path: Path) -> None:
        """Files still being written live in tmp/, outside objects/ and refs/."""
        store = FileStore(LG, tmp_path)
        repo = store.repo("r")
        repo.commit("main", repo.put(Tree()))
        (tmp_path / "r" / "tmp" / "leftover").write_bytes(b"partial")
        assert len(store.list_objects("r")) == 2
        assert list(repo.refs()) == ["main"]

    def test_rewrite_refreshes_mtime(self, tmp_path: Path) -> None:
        """Putting an existing object again protects it from prune."""
        store = FileStore(LG, tmp_path)
        repo = store.repo("r")
        blob_id = repo.put(Blob(b"x"))
        path = _object_file(tmp_path, "r", blob_id)
        old = time.time() - 7200
        os.utime(path, (old, old))
        assert repo.prune(expire=3600) == 1
        blob_id = repo.put(Blob(b"x"))
        os.utime(path, (old, old))
        repo.put(Blob(b"x"))
        assert repo.prune(expire=3600) == 0
        assert blob_id in repo

    def test_bad_header_is_corrupt(self, tmp_path: Path) -> None:
        """A damaged header raises instead of returning garbage."""
        repo = FileStore(LG, tmp_path).repo("r")
        blob_id = repo.put(Blob(b"x"))
        _object_file(tmp_path, "r", blob_id).write_bytes(b"junk")
        with pytest.raises(CorruptObjectError):
            repo.get(blob_id)
        with pytest.raises(CorruptObjectError):
            _ = blob_id in repo

    def test_truncated_object_is_corrupt(self, tmp_path: Path) -> None:
        """A length that does not match the header raises."""
        repo = FileStore(LG, tmp_path).repo("r")
        blob_id = repo.put(Blob(b"hello"))
        _object_file(tmp_path, "r", blob_id).write_bytes(b"blob 5\0hel")
        with pytest.raises(CorruptObjectError):
            repo.get(blob_id)

    def test_deleted_repo_leftover_is_hidden_then_removed(self, tmp_path: Path) -> None:
        """A crashed delete's leftover is not listed; the next delete of the name removes it."""
        store = FileStore(LG, tmp_path)
        store.repo("a").put(Blob(b"x"))
        store.repo("ab").put(Blob(b"x"))
        (tmp_path / "a%deleted-0123").mkdir()
        assert store.list_repos() == ["a", "ab"]
        with mock.patch.object(store._lg, "warning") as warning:
            store.delete_repo("a")
        assert sorted(p.name for p in tmp_path.iterdir()) == ["ab"]
        warning.assert_called_once()  # the old leftover, not this delete's own rename
        assert warning.call_args.kwargs["extra"]["path"].endswith("a%deleted-0123")

    def test_failed_delete_is_finished_by_a_retry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A delete that fails while removing files is already invisible; a retry cleans up."""
        store = FileStore(LG, tmp_path)
        repo = store.repo("r")
        repo.commit("main", repo.put(Tree()))

        def failing_rmtree(path: object, *args: object, **kwargs: object) -> None:
            raise OSError("disk went away")

        monkeypatch.setattr(file_store.shutil, "rmtree", failing_rmtree)
        with pytest.raises(OSError):
            store.delete_repo("r")
        assert store.list_repos() == []
        assert repo.get_ref("main") is None
        monkeypatch.undo()
        store.delete_repo("r")
        assert list(tmp_path.iterdir()) == []

    def test_prune_sweeps_stale_temp_files(self, tmp_path: Path) -> None:
        """Temp files of a writer that died go once older than expire; fresh ones stay."""
        store = FileStore(LG, tmp_path)
        repo = store.repo("r")
        repo.commit("main", repo.put(Tree()))
        stale, fresh = (
            tmp_path / "r" / "tmp" / "stale",
            tmp_path / "r" / "tmp" / "fresh",
        )
        stale.write_bytes(b"partial")
        fresh.write_bytes(b"partial")
        old = time.time() - 7200
        os.utime(stale, (old, old))
        with (
            mock.patch.object(store._lg, "warning") as warning,
            mock.patch.object(store._lg, "debug") as debug,
        ):
            repo.prune(expire=3600)
        assert not stale.exists() and fresh.exists()
        warning.assert_called_once()
        assert warning.call_args.kwargs["extra"] == {"repo": "r", "count": 1}
        summary = debug.call_args.kwargs["extra"]
        assert (summary["deleted"], summary["swept"]) == (0, 1)
        assert summary["after"] >= 0

    def test_store_logs_under_cas(self, tmp_path: Path) -> None:
        """The store's logger is derived from the one passed in, named cas."""
        assert FileStore(LG, tmp_path)._lg.name.endswith("/cas")

    @forks_in_xdist_worker
    def test_death_between_commit_and_ref_move(self, tmp_path: Path) -> None:
        """A process killed after storing a commit but before moving the ref changes no ref."""
        store = FileStore(LG, tmp_path)
        repo = store.repo("r")
        tree_id = repo.put(Tree())
        base = repo.commit("main", tree_id)
        child = multiprocessing.Process(
            target=_commit_then_die, args=(str(tmp_path), tree_id, base)
        )
        child.start()
        child.join(10.0)
        assert child.exitcode == 17
        lost = Commit(tree_id, (base,), b"lost").id
        assert lost in repo
        assert repo.get_ref("main") == base
        assert [c.id for c in repo.ancestors(base)] == [base]
        assert repo.prune(expire=0) == 1
        assert lost not in repo

    def test_quoted_names_must_fit_a_path_segment(self, tmp_path: Path) -> None:
        """Names too long once quoted raise InvalidNameError, not an OSError."""
        store = FileStore(LG, tmp_path)
        repo = store.repo("a" * 214)
        commit_id = repo.commit("x" * 255, repo.put(Tree()))
        store.delete_repo("a" * 214)
        assert store.list_repos() == []
        with pytest.raises(InvalidNameError):
            store.repo("a" * 215).put(Blob(b"x"))
        with pytest.raises(InvalidNameError):
            store.repo("r").get_ref("/" * 86)  # 86 bytes, 258 quoted
        assert commit_id not in store.repo("a" * 214)

    def test_waiting_writer_relocks_after_the_repo_is_renamed(
        self, tmp_path: Path
    ) -> None:
        """A writer that waited on a lock file delete_repo renamed away locks the live one."""
        store = FileStore(LG, tmp_path)
        repo = store.repo("r")
        repo.put(Blob(b"x"))
        stale = store.lock("r", exclusive=True)
        stale.__enter__()
        writer = threading.Thread(target=lambda: repo.put(Blob(b"w")))
        writer.start()
        writer.join(0.3)
        assert writer.is_alive()
        (tmp_path / "r").rename(tmp_path / "r%deleted-test")  # what delete_repo does
        live = store.lock("r", exclusive=True)
        live.__enter__()
        stale.__exit__(None, None, None)
        writer.join(0.5)
        assert writer.is_alive(), "writer ran under the renamed-away lock"
        live.__exit__(None, None, None)
        writer.join(5.0)
        assert not writer.is_alive()
        assert Blob(b"w").id in repo

    def test_list_on_missing_root(self, tmp_path: Path) -> None:
        """A store whose root does not exist yet is empty."""
        store = FileStore(LG, tmp_path / "absent")
        assert store.list_repos() == []
        assert store.list_objects("r") == {}
        assert store.list_refs("r") == {}

    @forks_in_xdist_worker
    def test_concurrent_moves_across_processes(self, tmp_path: Path) -> None:
        """The ref lock holds across processes: one writer wins."""
        repo = FileStore(LG, tmp_path).repo("r")
        tree_id = repo.put(Tree((TreeEntry("f", "blob", repo.put(Blob(b"x"))),)))
        base = repo.commit("main", tree_id)
        heads = [repo.put(Commit(tree_id, (base,), str(i).encode())) for i in range(8)]
        with ProcessPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(_set_ref, [str(tmp_path)] * 8, heads, [base] * 8))
        assert results.count(True) == 1
        assert repo.get_ref("main") == heads[results.index(True)]

    @forks_in_xdist_worker
    def test_exclusive_lock_holds_across_processes(self, tmp_path: Path) -> None:
        """A put in another process waits for the exclusive lock."""
        store = FileStore(LG, tmp_path)
        store.repo("r").put(Blob(b"x"))
        with ProcessPoolExecutor(max_workers=1) as pool:
            pool.submit(time.sleep, 0).result()  # start the worker before locking
            with store.lock("r", exclusive=True):
                future = pool.submit(_put_blob, str(tmp_path))
                time.sleep(0.5)
                assert not future.done()
            assert future.result(timeout=5.0) == Blob(b"from another process").id
