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
    def __init__(self, lg: Logger, requests: Chan[tuple[int, Chan[int]]]):
        self._lg = lg
        self._requests = requests

    @property
    def name(self) -> str:
        return "doubler"

    async def run(self) -> None:
        async for value, reply in self._requests:  # parked: holds no thread
            await reply.asend(value * 2)


requests: Chan[tuple[int, Chan[int]]] = Chan(16)
with Runtime(lg) as rt:
    rt.ready(rt.spawn(Doubler(lg, requests)))
    reply: Chan[int] = Chan(1)
    requests.send((21, reply))
    assert reply.recv(timeout=5.0) == 42
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
| `IDLE` | Allowed after `RUNNING`; the Runtime does not enter it, and a `ScheduledService` ticks while `RUNNING` |
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
`retries`, `exception`, `on_state_change()`, and `task`, the runtime `Task` of its current step
(its `setup()` or its run; `None` between steps). A restart replaces the task, so read it when
needed. `rt.services` maps the names of the services in the runtime to their runners.
`stop_service(runner, timeout=5.0)` stops one service and waits until it has ended and been torn
down; it then leaves the runtime.

### Isolated services

`isolate=True` runs the service in a child process started with the `spawn` method: `setup()`,
`run()` and `teardown()` all run there. The service must be picklable; its logger is not pickled,
the child makes one that forwards its records to the service's logger in the parent. The child
reports health to the parent, and its `self.stopping` is stopped when the parent stops the service.

- While it runs, `runner.task.kind` is `TaskKind.PROCESS` and `runner.task.process` gives the
  child: `detail()` (pid, exit code, liveness), `terminate()`, `kill()` (see
  [runtime](runtime.md#processes)).
- A queue, event or value the service shares with its child is made from `rt.process_context`
  before `spawn()` and handed to the service, e.g. in its constructor.
- A child that has not ended when a stop's timeout runs out is terminated, then killed: see
  [Restarts and stop](#restarts-and-stop).

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
- An isolated service's process still running when its stop's *timeout* runs out gets SIGTERM,
  then SIGKILL `task.process.grace` seconds later: `stop_service()` and `stop()` give the timeout
  they were called with and wait through the forcing; a stop the runtime makes on its own (a
  failed health check, a `ready()` given up on) gives the policy's `stop_timeout`. A second stop
  of a service already stopping forces it within its own, shorter timeout.
- A negative timeout is refused with `ValueError`, before anything is stopped.

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
    stop_timeout=5.0,  # Seconds an isolated run gets when the runtime stops it on its own
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

## Talking to a Service

Services and their callers talk over [`appinfra.runtime`](runtime.md#channels) Chans. A request
carries the Chan its reply comes back on, so replies need no ids:

```python
from appinfra.runtime import Chan

requests: Chan[tuple[str, Chan[str]]] = Chan(
    16
)  # Chan(16, process=True) for an isolated service
rt.spawn(WorkerService(lg, requests=requests))

reply: Chan[str] = Chan(1)
requests.send(("work", reply))
result = reply.recv(
    timeout=5.0
)  # TimeoutError if no reply came; ClosedError if it was refused
```

A streaming reply is any number of values on the reply Chan, ended by the replier closing it; the
caller iterates the reply Chan. An isolated service takes a process Chan
(`Chan(n, process=True)`) homed in the parent: it crosses into the service's process with the
service, and a restarted process reaches the same Chan.

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
