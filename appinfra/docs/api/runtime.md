# Runtime Module

Tasks, and the runtime that runs them; channels between tasks, in one process or across processes.

## Overview

`appinfra.runtime` runs functions as tasks:
- **One entry point**: `Runtime.spawn(fn, *args)` calls a function once, as a task, from any
  thread, and returns its `Task`
- **Two kinds of task**, picked from the function: an async function runs on the runtime's
  shared event loop, any other function on a thread of its own
- **One stop signal**: each task has a `StopToken`, derived from the token of the task that
  spawned it; cancelling a task stops every task it spawned
- **Channels**: `Chan` connects tasks of either kind; `select` waits on several channel
  operations and completes one; `Chan(n, process=True)` crosses into process tasks

The package imports nothing from `appinfra.service`. What it exports is the whole API: `Runtime`
and `Task` are final, and the handles `spawn()` returns cannot be constructed directly.

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
t = rt.spawn(fn, *args, name=None, token=None, done=None, process=False, derive_lg=None)
```

| Function | Runs as |
|----------|---------|
| `async def` | a task on the runtime's event loop, shared by every async task |
| any other callable | a daemon thread of its own |
| any other callable, `process=True` | a child process of its own |

`spawn()` raises `RuntimeError` once the runtime is not running, and `TypeError` for an `async def`
with `process=True`: a child has no event loop. `derive_lg` gives the task a logger of its own
(see [Inside a task](#inside-a-task)); a suffix that is not a string raises `TypeError`, an empty
one `ValueError`.

### Processes

`process=True` calls the function in a child process, started with the runtime's start method
(`forkserver` unless [configured](#configuration) otherwise); the returned `Task` is waited for
and cancelled like any other.

```python
from appinfra.runtime import Runtime, this_task


def index(path: str) -> int:  # module level: the child imports it
    me = this_task()
    count = 0
    for _ in walk(path):
        if me.token.is_set():
            break
        count += 1
    me.lg.info("indexed", extra={"path": path, "count": count})
    return count


if __name__ == "__main__":
    with Runtime(lg) as rt:
        t = rt.spawn(index, "/data", process=True)
        print(t.wait(timeout=60.0))
```

- the function and its arguments are pickled: the function is defined at module level, and
  process creation goes under `if __name__ == "__main__":`; the child does not see the parent's
  `contextvars`
- inside the child, `this_task()` works as in any task, with the parent's task id and name. Its
  logger has the runtime logger's name, or the derived one with `derive_lg`, and the runtime's
  handlers in the parent emit its records: every child gets a queue for them, with a listener
  thread in the parent while it runs
- the result comes back pickled; an exception is raised with the child's traceback as a note
  (`__notes__`), so it survives a `done=` process Chan too; an outcome that does not survive a
  pickle round trip, here or in the child, arrives as a `RuntimeError` naming why
- `cancel()` and the runtime's stop stop the child's token; so does the parent going away
- a child that exits without an outcome (killed, crashed, `os._exit()`) fails the task with
  `ProcessExitError`, whose `exitcode` is negative for the signal that ended it; a task stopped
  that way raises `StoppedError` instead
- `Runtime.stop()` terminates, then kills, a child still running after its timeout;
  `t.stop(timeout)` does the same for one task
- a queue, event or value shared with the child comes from `rt.process_context`, or
  `process_context()` before any runtime exists: one from the `fork` context, e.g. a default
  `mp.Queue()` on Linux before Python 3.14, fails in the child

With `forkserver`, every child is forked from one server process that imported the modules once,
so the children share those pages. What each more process task costs is its child's private
memory (Linux), not its resident set, which counts the shared pages in every child:

- before its first child, the runtime sets the server's preload to the main module and every
  `appinfra` module the process has imported by then
- the server imports the main module only when Python hands it the module's file path: 3.13.8
  and later, and 3.14.1 and later, do for a script run by path (`python app.py`); earlier
  releases, 3.12 included, do not, and no version does for `python -m pkg`. Where it does not,
  each child imports the main module itself, running its module-level code, but what it imports
  from appinfra is already shared
- the preload list is process-wide: it replaces one the application set with
  `set_forkserver_preload()`. Where the main module is not preloaded, a module it imports from
  outside appinfra, a large dependency say, is still imported by each child on its own

`t.process` is the task's child (`TaskProcess`), and `None` for a task on the loop or a thread:

| Member | Meaning |
|--------|---------|
| `t.process.detail()` | `ProcessDetail(pid, exitcode, alive)`, read anew on each call; once the child is reaped, as it ended |
| `t.process.terminate()` | SIGTERM to the child, or to it once started |
| `t.process.kill()` | SIGKILL, the same way |
| `t.process.grace` | seconds past a stop's timeout that forcing the child can take |

`detail()` reads the child at that moment: two calls can see it end in between, so keep one
snapshot for the fields read together. Before the child has started, its `pid` is `None`.

### The Task handle

| Member | Meaning |
|--------|---------|
| `t.id` | the id the runtime assigned, never reused |
| `t.name` | the name given to `spawn()`, or `None` |
| `t.wait(timeout=None)` | block until the task ends; return its result or raise its error |
| `await t` | the same in a coroutine, on any event loop |
| `t.cancel()` | stop the task's token; a loop task is also cancelled |
| `t.stop(timeout)` | `cancel()`, and a process task's child still running *timeout* seconds on gets SIGTERM, then SIGKILL; returns at once |
| `t.alive()` | `True` until the task has ended |
| `t.detach()` | give up waiting: a failure is logged instead |
| `t.kind` | what the task runs as: `TaskKind.LOOP`, `THREAD` or `PROCESS` |
| `t.process` | the child of a process task (see [Processes](#processes)), else `None` |

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
from appinfra.runtime import this_task


def worker(jobs: Chan[int]) -> None:
    me = this_task()  # TaskContext: id, name, lg, token
    me.lg.info("started", extra={"task": me.id, "name": me.name})
    for job in jobs:  # a stop ends the wait with StoppedError
        handle(job)


rt.spawn(worker, jobs)  # me.lg is the runtime's logger
rt.spawn(worker, jobs, derive_lg="worker")  # me.lg is <runtime lg>/worker
```

`this_task()` returns the `TaskContext` of the task the caller runs in, wherever below the task's
function the call is made; outside a task it raises `RuntimeError`.

| `TaskContext` | Meaning |
|---------------|---------|
| `id` | the id the runtime assigned, as on the `Task` handle |
| `name` | the name given to `spawn()`, or `None` |
| `lg` | the task's logger: the runtime's own, shared by every task, or one derived with `derive_lg` |
| `token` | the task's `StopToken` |

`spawn(..., derive_lg="worker")` derives a logger named `<runtime lg>/worker` for the task. The
logger factory keeps every derived logger: a suffix tasks share is one logger however many use it,
a suffix of each task's own (its id, say) adds one per task. The caller picks the suffix, and owns
a clash with another logger's name. A process task derives it in its child.

A task on a thread or the loop runs in a copy of its spawner's `contextvars`, as
`asyncio.create_task()` and `asyncio.to_thread()` do: it sees the spawner's values, and what it
sets stays its own. A process task's child starts with a fresh context (see Processes).

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

**`done=`** takes a `Chan`, local or process. The task is detached, and its end is sent there as
a `TaskDone`, so one receiver learns of the ends of many tasks:

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
lost. A process Chan, or a child's proxy of one, gets the end as it was when the task ended; an
end that does not survive a pickle round trip arrives with a `RuntimeError` naming why, in place
of its result and error. A child's own runtime can report its tasks' ends this way on a Chan of
the parent.

### Stopping

`Runtime.stop(timeout=None)` stops every task's token, cancels the loop tasks and waits for the
thread and process tasks, all within `timeout`, the config's `stop_timeout` (5 seconds) when
`None`. A thread task still running then is logged and left: a thread cannot be killed. Process
tasks still running then are ended by force, on top of `timeout`: every such child is sent SIGTERM
and given the config's `process.grace` (2 seconds), then every survivor SIGKILL and the grace
again, so a stop with late children takes up to `timeout` plus twice the grace. Leaving a
`with Runtime(lg) as rt:` block calls it, and a runtime left running is stopped at interpreter
exit.

### Configuration

Every setting has a default; `Runtime(lg)` takes them all. `Config` overrides them in code, and
`Factory` builds a runtime by name from a config's `runtime` section:

```python
from appinfra.runtime import Config, Factory, ProcessConfig, Runtime

rt = Runtime(lg)  # forkserver, a 2 s grace, a 5 s stop
rt = Runtime(lg, Config(process=ProcessConfig(method="spawn"), stop_timeout=10.0))
rt = Factory(lg, config).create("compute")  # config's runtime.compute
```

```yaml
runtime:
  default:            # what Factory.create() with no name builds
    process:
      method: forkserver
  compute:
    process:
      method: spawn   # forkserver or spawn
      grace: 5s       # seconds, or a duration: 500ms, 2s, 1m30s
    stop_timeout: 30s
```

| Key | Default | Meaning |
|-----|---------|---------|
| `process.method` | `forkserver` | how a process task's child starts: `forkserver` forks it from a server that imported the runtime once; `spawn` starts a fresh interpreter. `fork` is refused: a running runtime has threads |
| `process.grace` | `2s` | a child outliving its stop: SIGTERM, then SIGKILL, this far apart |
| `stop_timeout` | `5s` | how long `stop()` waits when given no timeout |

- a key left out keeps its default; an unknown key raises `ValueError`, so a misspelt one is not
  silently ignored; an unknown runtime name raises `KeyError` naming the known ones
- `INFRA_RUNTIME_<NAME>_<KEY>` overrides a key the config declares, e.g.
  `INFRA_RUNTIME_COMPUTE_PROCESS_METHOD=forkserver`, when the config given to `Factory` is loaded
  through `appinfra.config.Config` (an App's, `Config.from_path()`, `Config.from_spec()`), which
  applies the overrides as it loads; a plain mapping gets none. appinfra's own `etc/infra.yaml`
  declares a `default` runtime with every key, so `INFRA_RUNTIME_DEFAULT_...` works there out of
  the box
- `rt.config` is what a runtime was configured with; a service `Runtime` takes the same `Config`
  for the task runtime its services run on (`config=`), as an application that also uses
  `appinfra.config.Config` imports it under another name: `from appinfra.runtime import Config as
  RuntimeConfig`

## Channels

`Chan[T](capacity)` is a one-way FIFO channel between tasks of either kind. A send waits while
`capacity` values are buffered; with capacity 0 a send waits for a receiver to take the value.
With capacity `None` the buffer has no bound and a send never waits: for senders that must not,
such as a callback or sync code on the event loop. Nothing then slows a fast sender down; its
values pile up until received. `len(ch)` tells the receiver how many wait, so it can decide what
a depth means: log it, alert, or slow its senders.

| Thread code | Coroutine | Meaning |
|-------------|-----------|---------|
| `ch.send(v, timeout=None)` | `await ch.asend(v, timeout=None)` | send, waiting for room |
| `ch.recv(timeout=None)` | `await ch.arecv(timeout=None)` | receive, waiting for a value |
| `for v in ch:` | `async for v in ch:` | receive until closed and drained |
| `ch.close()` | | end the channel |
| `len(ch)` | | values waiting to be received |

- `timeout=0` means do not wait (`TimeoutError` when the call would have to wait)
- after `close()`, a receive still gets the buffered values, then raises `ChanClosedError`; a
  send raises `ChanClosedError`
- a wait ends with `StoppedError` when the waiting task's token is stopped
- on an event loop's thread, `send()` and `recv()` take only `timeout=0`: coroutines await
  `asend()` and `arecv()`. A `send()` on an unbounded channel is allowed there with any timeout,
  as it never waits

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

## Process channels

`Chan(capacity, process=True)` is a channel a process task can use. It lives in the process that
made it, its home. Handed to a process task, in its arguments or inside a value sent on another
process Chan, it arrives in the child as a proxy of the same channel, used there as here: `send`,
`recv`, iteration, `close`, and the coroutine forms.

```python
from appinfra.runtime import Chan, Runtime


def squares(out: Chan[int], n: int) -> None:  # module level: the child imports it
    for i in range(n):
        out.send(i * i, timeout=10.0)
    out.close()


if __name__ == "__main__":
    with Runtime(lg) as rt:
        out: Chan[int] = Chan(4, process=True)
        child = rt.spawn(squares, out, 3, process=True)
        assert list(out) == [0, 1, 4]
        child.wait(timeout=10.0)
```

Request and reply needs no ids: each request carries the Chan its reply comes back on, a process
Chan too.

```python
requests: Chan[tuple[int, Chan[int]]] = Chan(16, process=True)
rt.spawn(
    serve, requests, process=True
)  # def serve(requests): for n, reply in requests: ...
reply: Chan[int] = Chan(1, process=True)
requests.send((21, reply), timeout=5.0)
result = reply.recv(timeout=5.0)
```

- the channel's semantics are the same in every process: capacity, including 0, many senders
  and receivers, close; the buffer and the waits are in the home, a proxy's calls go there
- every send stores a pickled copy of its value, local senders too: a value that cannot be
  pickled fails at the sender, and every receiver gets a copy of its own
- a local `Chan(n)` cannot cross, with a `TypeError` naming `process=True`: in a process task's
  arguments the task fails with it, inside a value sent on a process Chan the send raises it
- a close on any side closes the channel for all of them; the home exiting fails the calls of
  every proxy with `ChanClosedError`; a proxy's process exiting drops its waiting calls, and the
  values it already sent stay
- on an event loop's thread a proxy takes no sync call: coroutines `await asend()` and
  `arecv()`
- `select` works on a process Chan in its home; on a proxy, in another process, it raises
  `TypeError`: a select must complete exactly one case, and a proxy's are decided in its home

## Correlator

A reply Chan in the request is the reply's return address, and it works wherever both ends can
hold Chans. Over a transport that carries something else, a socket to a peer written in any
language, the reply is found by a key it shares with its request instead: a correlation
identifier. `Correlator` does that matching over a message stream the caller owns.

```python
from appinfra.runtime import Correlator

c: Correlator[Envelope] = Correlator(
    transport.send,  # send(message, timeout)
    key=lambda m: m.id,
    failed=lambda m: m.error is not None,
    final=lambda m: m.is_final,
)
# the thread that reads the transport hands each arrival over:
#     c.deliver(message)
reply = c.submit(Envelope(id=new_id(), body=...), timeout=5.0)
for chunk in c.stream(Envelope(id=new_id(), body=...), timeout=5.0):
    ...
request = c.recv(timeout=1.0)  # a message no call waits on: the peer's own request
c.send(answer_to(request))
```

- a message whose key a `submit()` or `stream()` waits on goes to that call; any other, and a
  reply arriving after its call timed out, goes to the inbox `recv()` reads
- the call's route exists before the request is sent, so a reply arriving during the send finds
  it; two calls cannot wait on one key (`ValueError`)
- `deliver()` never waits, so the reading thread never stalls; the inbox has no bound
- `submit()`'s timeout bounds the send and the wait together, `stream()`'s each chunk; a reply
  for which `failed` is true raises `ChanResponseError`, its `response` the reply
- `stream()` sends when its first chunk is asked for; leaving early ends the call when the
  iterator closes: at once for a loop over `stream()` itself, at `close()` for one kept in a
  variable
- `close()` fails the waiting calls and any after with `ChanClosedError`, drops later arrivals,
  and lets `recv()` drain the inbox first; the transport stays the caller's
- the waits are Chan waits: they end with `StoppedError` when the task's token stops

## API Reference

| Name | Kind |
|------|------|
| `Runtime` | runs tasks: `start`, `stop`, `spawn`, `config`, `process_context`, context manager |
| `Config`, `ProcessConfig` | what a runtime is configured with: start method, grace, stop timeout |
| `Factory` | runtimes by name from a config's `runtime` section: `create(name)`, `config(name)` |
| `Task` | the handle `spawn()` returns |
| `TaskKind` | what a task runs as: `LOOP`, `THREAD`, `PROCESS` |
| `TaskProcess`, `ProcessDetail` | a process task's child, and its `pid`, `exitcode`, `alive` |
| `process_context()` | a multiprocessing context for what is shared with a child before any runtime exists |
| `TaskDone` | `(task_id, name, result, error)`, sent on `done` |
| `this_task()`, `TaskContext` | the current task: its `id`, `name`, `lg` and `token` |
| `StopToken`, `StoppedError` | the stop signal, and the error a stop ends a wait with |
| `ProcessExitError` | a process task's child exited without an outcome; `exitcode` |
| `Chan`, `ChanClosedError` | a channel, local or `process=True`, and the error a closed one raises |
| `select`, `aselect`, `ChanRecv`, `ChanSend` | select and its cases |
| `Correlator`, `ChanResponseError` | request and reply by key over a caller's message stream, and a failed reply's error |

## See Also

- [Runtime examples](../../examples/13_runtime/) - Tasks and channels, in one process and across
  processes, run as scripts
- [Service](service.md) - Long-lived services with dependency ordering, restarts and state
