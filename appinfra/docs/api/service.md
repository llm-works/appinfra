# Service Module

Service execution framework for managing service lifecycles with dependency ordering.

## Overview

The service module provides a framework for managing long-running services with:
- **Dependency ordering**: Services start after their dependencies
- **Parallel execution**: Independent services start/stop in parallel
- **State machine**: Explicit states with hooks for observability
- **Restart policies**: Automatic restart with configurable backoff
- **Multiple execution modes**: Threads, processes, scheduled

## Architecture

Three-layer architecture separates concerns:

| Layer | Responsibility | Examples |
|-------|---------------|----------|
| **Service** | WHAT to run (definition, config, behavior) | `Service`, `ScheduledService` |
| **Runner** | HOW to run it (execution + state management) | `ThreadRunner`, `ProcessRunner` |
| **Manager** | Orchestration (dependency ordering, parallel start/stop) | `Manager` |

## Quick Start

```python
from appinfra.log import Logger
from appinfra.service import Service, ThreadRunner, Manager

class MyService(Service):
    def __init__(self, lg: Logger):
        self._lg = lg
        self._stop = threading.Event()

    @property
    def name(self) -> str:
        return "myservice"

    def execute(self) -> None:
        self._lg.info("service started")
        self._stop.wait()  # Block until teardown

    def teardown(self) -> None:
        self._stop.set()

    def is_healthy(self) -> bool:
        return True

# Run with ThreadRunner
lg = Logger(name="app")
runner = ThreadRunner(MyService(lg))
runner.start()
runner.wait_healthy(timeout=30.0)
# ... service is running ...
runner.stop()
```

## Service Base Class

Services define WHAT to run. Implement these methods:

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

    def setup(self) -> None:
        """Initialize resources. Raise SetupError to abort."""

    @abstractmethod
    def execute(self) -> None:
        """Main work. Block until teardown for long-running services."""

    def teardown(self) -> None:
        """Cleanup. Should cause execute() to return."""

    def is_healthy(self) -> bool:
        """Check if ready. Runner waits for this before RUNNING state."""
        return True

    @property
    def lg(self) -> Logger:
        """Logger instance."""
        return self._lg
```

## State Machine

Services transition through explicit states:

```
CREATED → INITD → STARTING → RUNNING → STOPPING → STOPPED → DONE
                     ↓           ↓          ↓
                   FAILED ←←←←←←←←←←←←←←←←←←
```

| State | Description |
|-------|-------------|
| `CREATED` | Service created but never started |
| `INITD` | Setup completed successfully |
| `STARTING` | Execution beginning |
| `RUNNING` | Healthy and serving |
| `IDLE` | Between scheduled executions |
| `STOPPING` | Shutdown in progress |
| `STOPPED` | Cleanly stopped |
| `FAILED` | Error occurred |
| `DONE` | Terminal state, will not run again |

### State Hooks

Register callbacks for state changes:

```python
def on_change(name: str, old: State, new: State) -> None:
    print(f"{name}: {old.value} -> {new.value}")

runner.on_state_change(on_change)
```

## Runners

### ThreadRunner

Runs `service.execute()` in a daemon thread:

```python
runner = ThreadRunner(service)
runner.start()
runner.wait_healthy(timeout=30.0)
# ... service running ...
runner.stop()
```

### ProcessRunner

Runs `service.execute()` in a subprocess for isolation:

```python
runner = ProcessRunner(service)
runner.start()
runner.wait_healthy(timeout=30.0)
# ... service running in subprocess ...
runner.stop()
```

ProcessRunner features:
- Uses `multiprocessing.Process` for subprocess isolation
- Queue-based logging forwarded to parent process
- IPC for shutdown signaling and health status
- Service must be picklable

## Scheduled Services

For periodic execution, extend `ScheduledService`:

```python
class MetricsCollector(ScheduledService):
    interval = 60.0  # Seconds between tick() calls

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
from appinfra.service import RestartPolicy, ThreadRunner

policy = RestartPolicy(
    max_retries=5,       # Max restart attempts
    backoff=1.0,         # Initial backoff in seconds
    backoff_multiplier=2.0,  # Exponential backoff
    max_backoff=60.0,    # Maximum backoff cap
    restart_on_failure=True,
)

runner = ThreadRunner(service, policy=policy)
```

Call `runner.check()` periodically to detect failures and trigger restarts.

## Manager

Orchestrate multiple services with dependency ordering:

```python
from appinfra.service import Manager, ThreadRunner

lg = Logger(name="app")
mgr = Manager(lg)

# Add services (dependencies are resolved automatically)
mgr.add_service(database_service)
mgr.add_service(cache_service)
mgr.add_service(api_service)  # Depends on database and cache

# Context manager starts all services and stops on exit
with mgr:
    run_application()
```

### Dependency Declaration

Services declare dependencies via `depends_on`:

```python
class APIService(Service):
    @property
    def name(self) -> str:
        return "api"

    @property
    def depends_on(self) -> list[str]:
        return ["database", "cache"]
```

Or specify when adding:

```python
mgr.add(runner, depends_on=["database", "cache"])
```

## Error Handling

| Error | When Raised |
|-------|-------------|
| `SetupError` | Service setup fails |
| `RunError` | Execution fails to start |
| `HealthTimeoutError` | Service doesn't become healthy |
| `InvalidTransitionError` | Invalid state transition attempted |
| `CycleError` | Circular dependency detected |
| `DependencyFailedError` | Dependency failed to start |

## Channels

For bidirectional communication between services and their runners.

### Sync Channels

For threaded code with blocking calls:

```python
from appinfra.service import ChannelFactory, Message

# Create paired channels
factory = ChannelFactory()
pair = factory.create_thread_pair()

# Fire-and-forget
pair.parent.send(Message(payload="hello"))

# Request/response (blocking)
response = pair.parent.submit(Request(id="1", data="work"), timeout=5.0)

# Receive messages
msg = pair.child.recv(timeout=1.0)
pair.child.send(Response(id=msg.id, result="done"))
```

### Async Channels

For asyncio code with async/await:

```python
from appinfra.service import ChannelFactory

# Async channels for coroutine communication
factory = ChannelFactory()
pair = factory.create_async_thread_pair()

# Fire-and-forget (async)
await pair.parent.send(Message(payload="hello"))

# Request/response (async)
response = await pair.parent.submit(Request(id="1", data="work"), timeout=5.0)

# Streaming response (async)
async for chunk in pair.parent.submit_stream(Request(id="2", data="stream")):
    print(chunk.data)
    if chunk.is_final:
        break  # Automatically stops when is_final=True

# For subprocess communication (async parent, sync child)
pair = factory.create_async_process_pair()
await pair.parent.send(request)  # Parent uses async
pair.child.recv()                 # Child uses sync in subprocess
```

### Channel Types

| Channel | Queue Type | Use Case |
|---------|-----------|----------|
| `ThreadChannel` | `queue.Queue` | Sync thread communication |
| `ProcessChannel` | `mp.Queue` | Sync cross-process IPC |
| `AsyncThreadChannel` | `asyncio.Queue` | Async coroutine communication |
| `AsyncProcessChannel` | `mp.Queue` (async wrapped) | Async parent, sync child subprocess |

## Factories

Centralized creation of service components:

```python
from appinfra.service import (
    ChannelFactory, ChannelConfig,
    RunnerFactory,
    ServiceFactory,
)

# Channel factory
ch_factory = ChannelFactory(ChannelConfig(response_timeout=60.0))
pair = ch_factory.create_thread_pair()

# Runner factory with channels
runner_factory = RunnerFactory(lg, default_policy=RestartPolicy(max_retries=3))
result = runner_factory.create_thread_runner_with_channel(service)
# result.runner, result.channel, result.service_channel

# Service factory with registry
svc_factory = ServiceFactory(lg)
svc_factory.register("worker", WorkerService, with_channel=True)
worker = svc_factory.create("worker")
```

## API Reference

### Classes

- `Service` - Base class for service definitions
- `ScheduledService` - Service with periodic tick() execution
- `Runner` - Abstract base for execution
- `ThreadRunner` - Thread-based execution
- `ProcessRunner` - Subprocess-based execution
- `Manager` - Service orchestration
- `RestartPolicy` - Restart configuration
- `State` - State enum

### Channel Classes (Sync)

- `Channel` - Abstract base for sync bidirectional communication
- `ThreadChannel` - Thread-safe queue-based channel
- `ProcessChannel` - Multiprocessing queue-based channel
- `Message` - Generic message with id for correlation

### Channel Classes (Async)

- `AsyncChannel` - Abstract base for async bidirectional communication
- `AsyncThreadChannel` - Async queue-based channel for coroutines
- `AsyncProcessChannel` - Async wrapper around mp.Queue

### Factories

- `ChannelFactory` - Creates channel pairs with configuration
  - `create_thread_pair()` - Create sync ThreadChannel pair
  - `create_process_pair()` - Create sync ProcessChannel pair
  - `create_async_thread_pair()` - Create async AsyncThreadChannel pair
  - `create_async_process_pair()` - Create async parent + sync child pair
- `ChannelConfig` - Channel configuration (timeout, queue size)
- `ChannelPair` - Sync channel pair (parent, child)
- `AsyncChannelPair` - Async channel pair (parent, child)
- `AsyncProcessChannelPair` - Mixed async parent + sync child pair
- `RunnerFactory` - Creates runners with optional channels
- `ServiceFactory` - Registry-based service creation

### Functions

- `validate_dependencies()` - Check for missing deps and cycles
- `dependency_levels()` - Get parallel execution groups
