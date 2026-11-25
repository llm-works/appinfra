# Runtime Module

Tasks, and the runtime that runs them; channels between tasks, and pipes between processes.

## Overview

`appinfra.runtime` runs functions as tasks:
- **One entry point**: `Runtime.spawn(fn, *args)` calls a function once, as a task, from any
  thread, and returns its `Task`
- **Two kinds of task**, picked from the function: an async function runs on the runtime's
  shared event loop, any other function on a thread of its own
- **One stop signal**: each task has a `StopToken`, derived from the token of the task that
  spawned it; cancelling a task stops every task it spawned
- **Channels**: `Chan` connects tasks of either kind; `select` waits on several channel
  operations and completes one; `pipe` connects two processes

The package imports nothing from `appinfra.service`. What it exports is the whole API: `Runtime`
and `Task` are final, and the types `spawn()` and `pipe()` return cannot be constructed
directly.

## Quick Start

```python
from appinfra.log import Logger
from appinfra.runtime import Chan, Runtime


def produce(out: Chan[int]) -> None:
    for i in range(5):
        out.send(i)
    out.close()


async def double(n: int) -> int:
    return n * 2


lg = Logger(name="app")
with Runtime(lg) as rt:
    ch = Chan[int](0)  # unbuffered: a send waits for a receiver
    rt.spawn(produce, ch)  # a thread
    total = sum(ch)  # receive until closed

    t = rt.spawn(double, 21)  # on the loop
    assert t.wait(timeout=5.0) == 42
# Leaving the block stops every task's token and waits for the tasks
```

## Tasks

### Spawning

```python
t = rt.spawn(fn, *args, name=None, token=None, done=None)
```

| Function | Runs as |
|----------|---------|
| `async def` | a task on the runtime's event loop, shared by every async task |
| any other callable | a daemon thread of its own |

`spawn()` raises `RuntimeError` once the runtime is not running.

### The Task handle

| Member | Meaning |
|--------|---------|
| `t.id` | the id the runtime assigned, never reused |
| `t.name` | the name given to `spawn()`, or `None` |
| `t.wait(timeout=None)` | block until the task ends; return its result or raise its error |
| `await t` | the same in a coroutine, on any event loop |
| `t.cancel()` | stop the task's token; a loop task is also cancelled |
| `t.alive()` | `True` until the task has ended |
| `t.detach()` | give up waiting: a failure is logged instead |

The outcome stays on the handle: `wait()` and `await` can be repeated, and each raises the
task's error from the task's own traceback. The runtime drops a task as it ends.

```python
t = rt.spawn(fetch, url)
try:
    page = t.wait(timeout=5.0)
except TimeoutError:
    t.cancel()  # still running
```

How a wait ends:

| The task | `wait()` / `await` |
|----------|--------------------|
| returned | returns the result |
| raised | raises that exception |
| was stopped before it returned | raises `StoppedError` |
| is still running after `timeout` | raises `TimeoutError` (`asyncio.wait_for` bounds an `await`) |

A function that sees its stop and returns ends with its result. A `StopIteration` from a task
becomes a `RuntimeError` caused by it, as in a coroutine.

Refused with `RuntimeError`:
- `wait()` on the runtime's loop thread while the task runs: it would block every loop task
  (`await` it instead)
- a task waiting for itself, also from a worker it handed its context to
  (`asyncio.to_thread`)
- `wait()` or `await` on a detached task

### Inside a task

```python
from appinfra.runtime import stopping, task_id


def worker(jobs: Chan[int]) -> None:
    token = stopping()  # this task's StopToken
    for job in jobs:  # a stop ends the wait with StoppedError
        handle(job, task_id())
```

A task runs in a copy of its spawner's `contextvars`, as `asyncio.create_task()` and
`asyncio.to_thread()` do: it sees the spawner's values, and what it sets stays its own.

### StopToken

| Member | Meaning |
|--------|---------|
| `is_set()` | `True` once stopped |
| `stop()` | stop it and every token derived from it |
| `wait(timeout=None)` | block until stopped; `False` on timeout |
| `child()` | a token stopped with this one |
| `detach()` | leave the parent's tree |

A thread task cannot be interrupted: it checks its token or waits on it. A loop task is also
cancelled, with `CancelledError` at the `await` it is parked on. Every channel wait ends with
`StoppedError` when the waiting task's token is stopped.

### Spawn options

**`name=`** names the task: its thread or asyncio task (`appinfra-task-7-db`), the `task_name`
field of its log records, and its `TaskDone`.

**`token=`** derives the task's token from the given one instead of the spawner's. A layer that
runs its own units as tasks stops them with its own tokens; `Runtime.stop()` still stops them.

**`done=`** takes a `Chan` or a pipe's `PipeSender`. The task is detached, and its end is sent
there as a `TaskDone`, so one receiver learns of the ends of many tasks:

```python
done = Chan[TaskDone](len(urls))
for url in urls:
    rt.spawn(fetch, url, name=url, done=done)
for _ in urls:
    end = done.recv()  # TaskDone(task_id, name, result, error)
    if end.error is not None:
        lg.warning("fetch failed", extra={"url": end.name, "exception": end.error})
```

`error` is what `wait()` would raise: the exception, or `StoppedError` for a stop. The ending
task never waits for room: an end that finds the channel full is sent from the loop once there
is room, an end on a closed channel is dropped, and one still waiting when the runtime stops is
lost. Through a pipe, an end that does not survive a pickle round trip arrives with a
`RuntimeError` naming why, in place of its result and error.

### Stopping

`Runtime.stop(timeout=5.0)` stops every task's token, cancels the loop tasks and waits for the
thread tasks, all within `timeout`. A thread task still running then is logged and left: a
thread cannot be killed. Leaving a `with Runtime(lg) as rt:` block calls it, and a runtime left
running is stopped at interpreter exit.

## Channels

`Chan[T](capacity)` is a one-way FIFO channel between tasks of either kind. A send waits while
`capacity` values are buffered; with capacity 0 a send waits for a receiver to take the value.

| Thread code | Coroutine | Meaning |
|-------------|-----------|---------|
| `ch.send(v, timeout=None)` | `await ch.asend(v, timeout=None)` | send, waiting for room |
| `ch.recv(timeout=None)` | `await ch.arecv(timeout=None)` | receive, waiting for a value |
| `for v in ch:` | `async for v in ch:` | receive until closed and drained |
| `ch.close()` | | end the channel |

- `timeout=0` means do not wait (`TimeoutError` when the call would have to wait)
- after `close()`, a receive still gets the buffered values, then raises `ChanClosedError`; a
  send raises `ChanClosedError`
- a wait ends with `StoppedError` when the waiting task's token is stopped
- on an event loop's thread, `send()` and `recv()` take only `timeout=0`: coroutines await
  `asend()` and `arecv()`

### Select

`select(*cases, timeout=None)` waits until one of several channel operations can complete,
completes exactly that one, and returns its position and the value received (`None` for a
send). Among cases ready at once, one is chosen at random. `aselect()` is the same in a
coroutine.

```python
from appinfra.runtime import ChanClosedError, ChanRecv, aselect


async def merge(a: Chan[str], b: Chan[str]) -> list[str]:
    cases, seen = [ChanRecv(a), ChanRecv(b)], []
    while cases:
        try:
            i, v = await aselect(*cases, timeout=5.0)
        except ChanClosedError as e:
            del cases[e.index]  # that input is done
            continue
        seen.append(v)
    return seen
```

With `timeout=0`, a select that cannot complete at once raises `TimeoutError`:

```python
try:
    select(ChanSend(out, v), timeout=0)
except TimeoutError:
    dropped += 1
```

A closed channel's case raises `ChanClosedError`, its `index` naming the case.

## Pipes

`pipe(capacity)` is a channel from one process to another. Each end goes to the process that
uses it, which opens it there; values are pickled.

```python
import multiprocessing as mp

from appinfra.runtime import PipeSendEnd, pipe


def child(send: PipeSendEnd[int]) -> None:
    out = send.open()  # a PipeSender: send, asend, close, aclose
    for i in range(3):
        out.send(i * i)
    out.close()  # returns once the values are on the pipe


if __name__ == "__main__":
    send, recv = pipe(4)
    proc = mp.get_context("spawn").Process(target=child, args=(send,))
    proc.start()
    send.release()  # the child has its copy
    # a PipeReceiver: recv, arecv, iteration, close
    assert list(recv.open()) == [0, 1, 4]
    proc.join()
```

- with the `spawn` start method the child imports the main module again: process creation
  goes under `if __name__ == "__main__":`, the child's function at module level
- `capacity` must be at least 1: a send cannot wait for a receiver in another process
- a close on either side, or the other process exiting, closes the channel; a close on the
  receiving side drops what is still on its way
- a process that hands an end to another `release()`s its own copy
- a value the receiving side cannot unpickle is skipped and reported through
  `threading.excepthook`
- `ChanSend(sender, v)` and `ChanRecv(receiver)` work in `select`

## API Reference

| Name | Kind |
|------|------|
| `Runtime` | runs tasks: `start`, `stop`, `spawn`, context manager |
| `Task` | the handle `spawn()` returns |
| `TaskDone` | `(task_id, name, result, error)`, sent on `done` |
| `stopping()`, `task_id()` | the current task's token and id |
| `StopToken`, `StoppedError` | the stop signal, and the error a stop ends a wait with |
| `Chan`, `ChanClosedError` | a channel, and the error a closed one raises |
| `select`, `aselect`, `ChanRecv`, `ChanSend` | select and its cases |
| `pipe`, `PipeSendEnd`, `PipeRecvEnd`, `PipeSender`, `PipeReceiver` | a channel between processes |

## See Also

- [Runtime examples](../../examples/13_runtime/) - Tasks, channels and pipes, run as scripts
- [Service](service.md) - Long-lived services with dependency ordering, restarts and state
