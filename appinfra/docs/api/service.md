# Service Module

Services, and the runtime that runs them.

## Overview

The service module runs long-lived services with:
- **One entry point**: `Runtime.spawn()` takes services in any order, from any thread, and runs
  each as it needs to run
- **Dependency ordering**: a service starts as soon as the services it depends on run
- **One stop signal**: every service gets a hierarchical `StopToken` as `self.stopping`
- **State machine**: explicit states with hooks for observability
- **Restart policies**: automatic restart with configurable backoff
- **Execution kinds**: tasks on a shared event loop, threads, processes, scheduled ticks

## Architecture

| Layer | Responsibility | Examples |
|-------|---------------|----------|
| **Service** | WHAT to run (definition, config, behavior) | `Service`, `ScheduledService`, `AsyncService` |
| **Runtime** | Running them: dependency ordering, health, restarts, ordered stop | `Runtime` |
| **Runner** | A service's record in the runtime: state, policy, hooks | `Runner` |

The `Runtime` runs every step of a service (`setup()`, its run, `teardown()`, its health checks) as
a task on an [`appinfra.runtime`](runtime.md) runtime it owns. One task of its own holds the state
of every service, so a service needs no lock of its own for it.

## Quick Start

```python
from appinfra.log import Logger
from appinfra.service import Runtime, Service


class Database(Service):
    def __init__(self, lg: Logger):
        self._lg = lg

    @property
    def name(self) -> str:
        return "database"

    def run(self) -> None:
        self._lg.info("service started")
        self.stopping.wait()  # Block until stopped


class Api(Service):
    def __init__(self, lg: Logger):
        self._lg = lg

    @property
    def name(self) -> str:
        return "api"

    @property
    def depends_on(self) -> list[str]:
        return ["database"]

    def run(self) -> None:
        self.stopping.wait()


lg = Logger(name="app")
with Runtime(lg) as rt:
    api = rt.spawn(Api(lg))  # waits: "database" is not running yet
    rt.spawn(Database(lg))  # starts; api starts once it is RUNNING
    rt.ready(api)
    # ... services are running ...
# Leaving the block stops api, then database
```

## Services

Services define WHAT to run. A `Service` implements `run()`, which holds its thread until the
service is stopped. A `ScheduledService` implements `tick()` instead: its `run()` is the tick loop.
An `AsyncService`'s `run()` is a coroutine: it runs as a task on the runtime's event loop, shared
with every other async service.

```python
class Service(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        """Unique service identifier."""

    @property
    def depends_on(self) -> list[str]:
        """Names of services this depends on."""
        return []

    @abstractmethod
    def run(self) -> None:
        """Do the work, blocking until stopped. ScheduledService implements it."""

    def setup(self) -> None:
        """Initialize resources. Raise SetupError to abort."""

    def teardown(self) -> None:
        """Cleanup, once the run is told to stop. run() returns on self.stopping, not on teardown()."""

    def is_healthy(self) -> bool:
        """Check if ready. The runtime waits for this before RUNNING state."""
        return True

    @property
    def lg(self) -> Logger:
        """Logger instance."""
        return self._lg
```

| Class | Implement | Runs on |
|-------|-----------|---------|
| `Service` | `run()` | a thread of its own, or a process with `isolate=True`; held until stopped |
| `ScheduledService` | `tick()`, `interval` | as `Service`; `tick()` runs `interval` seconds after the last one returned |
| `AsyncService` | `async def run()` | a task on the runtime's event loop, shared by every async service |

`setup()` and `teardown()` run on threads of their own, before and after the run: never on the
event loop, and in a process of its own for an isolated service. `teardown()` of a scheduled
service runs once its loop has ended (stopped or failed), so it never overlaps `tick()`.

### AsyncService

```python
class Doubler(AsyncService):
    def __init__(self, lg: Logger, inbox: AsyncChannel):
        self._lg = lg
        self._inbox = inbox

    @property
    def name(self) -> str:
        return "doubler"

    async def run(self) -> None:
        while True:
            msg = await self._inbox.recv()  # parked: holds no thread
            await self._inbox.send(Message(id=msg.id, payload=msg.payload * 2))


pair = AsyncQueueChannelFactory().create_pair()
with Runtime(lg) as rt:
    rt.ready(rt.spawn(Doubler(lg, pair.child)))
    # Callers on the same loop, another AsyncService for one, await pair.parent
```

Every async service shares the runtime's one event loop thread: a service waiting on an `await`
costs its task, not a thread.

- `run()` runs on the loop; `setup()` and `teardown()` run on threads, off the loop. Open clients
  bound to the loop inside `run()` and close them in its `finally`.
- A stop cancels the task: `CancelledError` is raised at the `await` `run()` is parked on.
- An exception from `run()` fails that service only; the loop and its other services run on.
- `run()` must not call anything that blocks without awaiting: that stalls every service on the
  loop. Run blocking code through `asyncio.to_thread()`.
- One loop uses one core. An `AsyncService` cannot run with `isolate=True`.

### Service with run()

```python
class Database(Service):
    def __init__(self, lg: Logger):
        self._lg = lg

    @property
    def name(self) -> str:
        return "database"

    def run(self) -> None:
        self._lg.info("service started")
        self.stopping.wait()  # Block until stopped
```

The runtime gives every service a `StopToken` as `self.stopping`, set when the service is to stop.
Each service's token derives from the runtime's, so stopping the runtime reaches every service.
`self.stopping.child()` derives a token that is stopped with it, for work the service starts. The
runtime also stops the token once the run has ended, however it ended, before `teardown()`: work
derived from the token is told to stop first. Stopping a token does not wait for that work; a
service that must not release resources while its workers still use them waits for them, for
instance by joining them in `teardown()`.

- **A service with its own synchronous `run()`** blocks on `self.stopping.wait()` or checks
  `self.stopping.is_set()` instead of keeping an event of its own. In the runtime's process, a
  stop also calls `teardown()` while `run()` still runs, so a `run()` blocked on something else
  can be released there; in a process of its own, `teardown()` runs after `run()` returns.
- **An `AsyncService`** needs no token to learn of a stop: stopping cancels its task at the
  `await` it is parked on. It never calls `self.stopping.wait()`, which blocks the loop every async
  service shares. It derives tokens for work it hands to threads
  (`await asyncio.to_thread(token.wait)`), and may check `is_set()`.

## State Machine

Services transition through explicit states:

```
CREATED → INITD → STARTING → RUNNING → STOPPING → STOPPED → DONE
                     ↓           ↓          ↓
                   FAILED ←←←←←←←←←←←←←←←←←←
```

| State | Description |
|-------|-------------|
| `CREATED` | Spawned, not started: waiting for its dependencies, or in `setup()` |
| `INITD` | Setup completed successfully |
| `STARTING` | Running, not yet healthy |
| `RUNNING` | Healthy and serving |
| `IDLE` | Between scheduled executions |
| `STOPPING` | Shutdown in progress |
| `STOPPED` | Cleanly stopped |
| `FAILED` | Error occurred |
| `DONE` | Terminal state, will not run again |

### State Hooks

Register callbacks for state changes on the runner `spawn()` returns:

```python
def on_change(name: str, old: State, new: State) -> None:
    print(f"{name}: {old.value} -> {new.value}")


runner = rt.spawn(service)
runner.on_state_change(on_change)
```

`spawn()` starts the service at once, so a hook sees the transitions from the moment it is
registered. Hooks run on the runtime's own task: a hook observes, and calling the runtime from it
(`spawn()`, `ready()`, `stop_service()`, `stop()`) raises `RuntimeError`.

## Runtime

`Runtime` is the entry point for running services. `spawn()` takes a service and starts it once its
dependencies run; each step of the service is a task:

| Service | Its run |
|---------|---------|
| `AsyncService` | a task on the runtime's event loop, shared by every async service |
| `Service`, `ScheduledService` | a task on a thread of its own |
| `Service`, `ScheduledService` with `isolate=True` | a task in a process of its own |

```python
from appinfra.service import RestartPolicy, Runtime

with Runtime(lg) as rt:
    api = rt.spawn(Api(lg))
    rt.spawn(Database(lg, cfg), policy=RestartPolicy(max_retries=5))
    rt.spawn(Indexer(lg), isolate=True)
    rt.ready(api, timeout=30.0)
    run_application()
```

`Runtime(lg)` is started by `start()` or by entering the `with` block, once; `stop()` or leaving
the block stops it. `spawn()` returns the service's `Runner`, its record in the runtime: `state`,
`retries`, `exception`, `on_state_change()`. `rt.services` maps the names of the services in the
runtime to their runners. `stop_service(runner, timeout=5.0)` stops one service and waits until it
has ended and been torn down; it then leaves the runtime.

### Isolated services

`isolate=True` runs the service in a child process started with the `spawn` method: `setup()`,
`run()` and `teardown()` all run there. The service must be picklable; its logger is not pickled,
the child makes one that forwards its records to the service's logger in the parent. The child
reports health to the parent, and its `self.stopping` is stopped when the parent stops the service.

### Dependencies

A service names the services it needs in `depends_on`:

```python
class Api(Service):
    @property
    def depends_on(self) -> list[str]:
        return ["database", "cache"]
```

- **Any order.** `spawn()` takes services in any order, from any thread, before or after others
  start. A service whose dependencies are all `RUNNING` starts at once; any other waits, its
  runner `CREATED`, and starts as soon as the last of them reaches `RUNNING`. The runtime checks
  the health of a service others wait on, so a chain moves on without `ready()`.
- **`ready(*runners, timeout=30.0)`** waits until each is healthy, *timeout* in all, and raises how
  a start failed: `SetupError` if `setup()` failed, `RunError` if the run ended or was stopped
  while starting, `HealthTimeoutError` if it is not healthy in time (its run is then ended). A
  service still waiting for a dependency raises `DependencyNotRunningError`, which names it.
- **Health is checked while something waits.** Only `ready()`, a service waiting on it, or a
  restart under way moves a service from `STARTING` to `RUNNING`.
- **Cycles.** A `spawn()` whose dependencies would lead back to the service raises `CycleError`.
- **A dependency that leaves.** A service waiting on one that leaves the runtime (it failed with
  no restart left, ended or was stopped) fails with `DependencyFailedError`, and so does what
  waits on it in turn.

### Restarts and stop

- A service that fails while `RUNNING` is restarted per its `RestartPolicy`, after the policy's
  backoff: `setup()` and the run again, in a new process for an isolated service. A failure while
  starting is not restarted. A service that ends, is stopped, or fails with no restart left
  leaves the runtime.
- `stop(timeout=5.0)` ends the backoffs under way, then stops the started services in reverse
  start order, each within *timeout*: dependents before what they depend on. A service that does
  not end in time is logged and the rest stop regardless. A service still waiting for its
  dependencies never starts; `ready()` on it raises `RunError`.

## Scheduled Services

For periodic execution, extend `ScheduledService`. Its `run()` calls `tick()`, then waits
`interval` seconds, until the service is stopped; ticks start `interval` plus the time `tick()`
took apart. An exception from `tick()` ends the run with it:

```python
class MetricsCollector(ScheduledService):
    interval = 60.0  # Seconds from one tick() returning to the next

    def __init__(self, lg: Logger):
        self._lg = lg

    @property
    def name(self) -> str:
        return "metrics"

    def tick(self) -> None:
        """Called repeatedly at interval."""
        metrics = collect_metrics()
        send_to_server(metrics)

    def is_healthy(self) -> bool:
        return True
```

## Restart Policy

Configure automatic restart on failure:

```python
from appinfra.service import RestartPolicy

policy = RestartPolicy(
    max_retries=5,  # Restart attempts since the service was last healthy
    backoff=1.0,  # Initial backoff in seconds
    backoff_multiplier=2.0,  # Exponential backoff
    max_backoff=60.0,  # Maximum backoff cap
    restart_on_failure=True,
)

rt.spawn(service, policy=policy)
```

`RestartPolicy` is frozen; derive a variant with `dataclasses.replace()`.

## Error Handling

| Error | When Raised |
|-------|-------------|
| `SetupError` | `setup()` failed; from `ready()`. Any other exception from `setup()` becomes one, caused by it |
| `RunError` | The run ended or was stopped while starting, or the runtime stopped before the service started |
| `HealthTimeoutError` | Service doesn't become healthy |
| `InvalidTransitionError` | Invalid state transition attempted |
| `CycleError` | A `spawn()` whose dependencies lead back to the service |
| `DependencyFailedError` | A dependency left the runtime before the waiting service started |
| `DependencyNotRunningError` | `ready()` timed out on a service still waiting for a dependency; also a `TimeoutError` |

## Channels

For bidirectional communication between services and the code that calls them.

Architecture: Transport handles wire-level send/recv, Channel wraps a Transport with correlation
logic (request/response matching), and ChannelPairFactory creates connected pairs.

### Sync Channels

For threaded code with blocking calls:

```python
from appinfra.service import QueueChannelFactory, Message

# Create paired channels
factory = QueueChannelFactory()
pair = factory.create_pair()

# Fire-and-forget
pair.parent.send(Message(payload="hello"))

# Request/response (blocking)
response = pair.parent.submit(Request(id="1", data="work"), timeout=5.0)

# Streaming response: chunks carrying the request's id, up to the one with is_final=True;
# the timeout applies to each chunk
for chunk in pair.parent.stream(Request(id="2", data="stream"), timeout=5.0):
    print(chunk.payload)

# Receive messages
msg = pair.child.recv(timeout=1.0)
pair.child.send(Response(id=msg.id, result="done"))
```

### Async Channels

For asyncio code with async/await:

```python
from appinfra.service import AsyncQueueChannelFactory

# Async channels for coroutine communication
factory = AsyncQueueChannelFactory()
pair = factory.create_pair()

# Fire-and-forget (async)
await pair.parent.send(Message(payload="hello"))

# Request/response (async)
response = await pair.parent.submit(Request(id="1", data="work"), timeout=5.0)

# Streaming response (async)
async for chunk in pair.parent.stream(Request(id="2", data="stream")):
    print(chunk.data)
    if chunk.is_final:
        break  # Automatically stops when is_final=True

# For subprocess communication (async parent, sync child)
from appinfra.service import AsyncProcessQueueChannelFactory

pair = AsyncProcessQueueChannelFactory().create_pair()
await pair.parent.send(request)  # Parent uses async
pair.child.recv()  # Child uses sync in subprocess
```

### Error Responses

A response whose `error` field is set makes `submit()` and `stream()` raise
`ChannelResponseError`, a `ChannelError` subclass. Its `response` attribute holds the message as
received, so fields beyond the error text stay readable:

```python
try:
    response = await pair.parent.submit(request, timeout=5.0)
except ChannelResponseError as e:
    status = e.response.status  # e.g. tell a rejection from a failure
```

### Custom Channels and Transports

Smart transports (ZMQ, gRPC) that handle their own correlation can implement
the `Channel` protocol directly:

```python
from appinfra.service import Channel


class ZMQChannel:
    """Implements Channel protocol directly — no BufferedChannel needed."""

    def send(self, message, timeout=None): ...
    def recv(self, timeout=None): ...
    def submit(self, request, timeout=None): ...
    def stream(self, request, timeout=None): ...
    def close(self): ...
    @property
    def is_closed(self) -> bool: ...
```

For dumb transports that only provide raw send/recv, wrap in `BufferedChannel`
to get request/response correlation and redelivery:

```python
from appinfra.service import BufferedChannel, Transport


class SharedMemTransport:
    """Any object satisfying the Transport protocol."""

    def send(self, message, timeout=None): ...
    def recv(self, timeout=None): ...
    def close(self): ...
    @property
    def is_closed(self) -> bool: ...


channel = BufferedChannel(SharedMemTransport(shm_region))
```

A transport's `send()` and `recv()` must return or raise within *timeout*: `send()` raises
`ChannelFullError` when there is no room, `recv()` raises `ChannelTimeoutError` when nothing
arrives. `BufferedChannel` calls both in short slices so that `close()` interrupts a wait.

`send(message, timeout=None)` on a channel waits while a bounded queue is full. It raises
`ChannelClosedError` if the channel closes meanwhile and `ChannelFullError` once *timeout* passes;
`timeout=0` tries once without waiting. `submit()` counts that wait against its own timeout.

### Transports and Channel Types

| Factory | Transport | Use Case |
|---------|-----------|----------|
| `QueueChannelFactory` | `QueueTransport` (`queue.Queue`) | Sync thread communication |
| `ProcessQueueChannelFactory` | `ProcessQueueTransport` (`mp.Queue`) | Sync cross-process IPC |
| `AsyncQueueChannelFactory` | `AsyncQueueTransport` (`asyncio.Queue`) | Async coroutine communication |
| `AsyncProcessQueueChannelFactory` | `AsyncProcessQueueTransport` (`mp.Queue`) | Async parent, sync child subprocess |

### Process Channels and Exit

The process transports use `multiprocessing.Queue`, so its rule applies ([Joining processes that
use queues](https://docs.python.org/3/library/multiprocessing.html#programming-guidelines)): at
exit, a process waits until its queue's feeder thread has written every message it sent into the
pipe. Unread messages that fit in the pipe do not delay exit, but once the pipe is full the
feeder blocks until a reader takes from it, so messages nobody reads can keep the sender alive.
Pipe capacity varies by system and can be as small as one page, so code must not rely on it.

- Consume every message sent, or call `allow_exit_without_flush()` on the sending
  `ProcessQueueTransport` where unread messages may be dropped at exit.
- A channel an isolated service holds is pickled with the service when its process starts, under
  the `spawn` method; this works only while the child starts. The child's copy starts with an
  empty redelivery buffer. Queues and events passed to a child must come from the same start
  method: multiprocessing refuses them in the child otherwise.

## Factories

Centralized creation of service components:

```python
from appinfra.service import ChannelConfig, QueueChannelFactory, ServiceFactory

# Channel factory
ch_factory = QueueChannelFactory(ChannelConfig(response_timeout=60.0))
pair = ch_factory.create_pair()

# Service factory with registry; a service registered with_channel gets its end of a pair
svc_factory = ServiceFactory(lg)
svc_factory.register(
    "worker", WorkerService, policy=RestartPolicy(max_retries=3), with_channel=True
)
worker = svc_factory.create("worker", channel=pair.child)
rt.spawn(worker, policy=svc_factory.get_policy("worker"))
```

## API Reference

### Classes

- `Service` - Base class for service definitions; its run() holds its thread until stopped
- `ScheduledService` - Service whose run() calls tick() every interval seconds
- `AsyncService` - Service whose run() is a coroutine, run as a task on the runtime's event loop
- `Runtime` - The entry point: spawns services in dependency order, restarts and stops them
- `Runner` - A service's record in the runtime: state, restart policy, hooks
- `StopToken` - Hierarchical, one-way stop signal; every service's `self.stopping`
- `RestartPolicy` - Restart configuration
- `State` - State enum

### Transport Protocols

- `Transport` - Sync wire-level protocol (send, recv, close, is_closed)
- `AsyncTransport` - Async wire-level protocol

### Built-in Transports

- `QueueTransport` - Wraps `queue.Queue` for in-process sync communication
- `ProcessQueueTransport` - Wraps `mp.Queue` for cross-process sync communication
- `AsyncQueueTransport` - Wraps `asyncio.Queue` for async coroutine communication
- `AsyncProcessQueueTransport` - Wraps `mp.Queue` with async interface

### Channel Protocols

- `Channel` - Sync channel protocol (implement directly for smart transports)
- `AsyncChannel` - Async channel protocol (implement directly for smart transports)

### Built-in Channels

- `BufferedChannel` - Wraps a `Transport` with correlation, streaming, and redelivery
- `AsyncBufferedChannel` - Wraps an `AsyncTransport` with correlation, streaming, and redelivery
- `Message` - Generic message with id for correlation

### Factories

- `ChannelPairFactory` - Protocol for pluggable channel pair creation (`create_pair()`)
- `QueueChannelFactory` - Creates sync `Channel` pairs over `QueueTransport`
- `ProcessQueueChannelFactory` - Creates sync `Channel` pairs over `ProcessQueueTransport`
- `AsyncQueueChannelFactory` - Creates async `AsyncChannel` pairs over `AsyncQueueTransport`
- `AsyncProcessQueueChannelFactory` - Creates mixed async parent + sync child pairs
- `ChannelConfig` - Channel configuration (timeout, queue size)
- `ChannelPair` - Sync channel pair (parent, child)
- `AsyncChannelPair` - Async channel pair (parent, child)
- `AsyncProcessChannelPair` - Mixed async parent + sync child pair
- `ServiceFactory` - Registry-based service creation
