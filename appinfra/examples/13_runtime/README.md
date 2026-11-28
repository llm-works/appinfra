# Runtime Examples

Concurrency patterns on `appinfra.runtime`: tasks on threads, on the runtime's event loop and in
processes of their own, and channels between them. Each script runs its examples in order, one
function per pattern. See the [Runtime API reference](../../docs/api/runtime.md).

## `tasks.py`

The lifecycle of tasks.

| Pattern | What it shows |
|---------|---------------|
| spawn and join | start a task, wait for its result |
| wait for all | start several tasks, await each from a coroutine |
| done channel | every task reports its end on one channel, in the order they end |
| error group | tasks under one token; the first error stops the rest |
| cancellation tree | cancelling a task stops the tasks it spawned |
| deadline | a timer task stops the work's token when time runs out |
| for-select loop | a worker selects over its jobs and a quit channel |
| heartbeat | the supervisor selects over heartbeats, the result and a timeout |

```bash
python tasks.py
```

## `channels.py`

Patterns built on `Chan` and `select`.

| Pattern | What it shows |
|---------|---------------|
| ping-pong | an unbuffered hand-over between two sides |
| queue | a buffered channel; values come out in order |
| generator | a task produces values and closes; the caller ranges over them |
| pipeline | stages joined by channels, thread and loop tasks alike |
| fan-out, fan-in | workers read one input; their outputs merge with select |
| worker pool | fixed workers, a jobs channel and a results channel |
| semaphore | a buffered channel of slots bounds concurrency |
| timeout | wait for a reply, but only so long |
| non-blocking | `timeout=0` sends and receives |
| or-done | read until the stream ends or a quit channel closes |
| rate limiting | a ticker task paces requests |

```bash
python channels.py
```

## `processes.py`

Process Chans: `Chan(n, process=True)` handed to a process task, used there as here.

| Example | What it shows |
|---------|---------------|
| from a child | a child sends, the parent receives until the child closes |
| request and reply | each request carries the Chan its reply comes back on |
| a child's task ends | a child's own tasks report their ends on the parent's Chan with `done=` |
| select in the home | a process Chan in select next to a local Chan, in its home |

```bash
python processes.py
```
