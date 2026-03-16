"""Service execution with dependency ordering.

This module provides a framework for managing service execution with:
- Dependency ordering: services start after their dependencies
- Parallel execution: independent services start/stop in parallel
- State machine: explicit states with hooks
- Restart policies: automatic restart with configurable backoff
- Multiple execution modes: threads, processes, scheduled

Three-layer architecture:
- Service: WHAT to run (definition, config, behavior)
- Runner: HOW to run it (execution + state management)
- Manager: Orchestration (dependency ordering, parallel start/stop)

Basic usage with ThreadRunner:
    from appinfra.service import Manager, ThreadRunner

    class MyService(Service):
        name = "myservice"
        depends_on = ["database"]

        def execute(self) -> None:
            # Main work - blocks until teardown
            self._stop.wait()

        def teardown(self) -> None:
            self._stop.set()

    mgr = Manager(lg)
    mgr.add_service(db_service)
    mgr.add_service(MyService())

    with mgr:
        run_application()

With ProcessRunner for subprocess isolation:
    from appinfra.service import ProcessRunner

    # Service runs in a separate process
    runner = ProcessRunner(my_service)
    runner.start()
    runner.wait_healthy(timeout=30.0)

With restart policy:
    from appinfra.service import ThreadRunner, RestartPolicy

    runner = ThreadRunner(
        my_service,
        policy=RestartPolicy(max_retries=5, backoff=2.0),
    )
    mgr.add(runner)

State change hooks:
    def on_change(name: str, old: State, new: State) -> None:
        print(f"{name}: {old.value} -> {new.value}")

    mgr.add(runner)
    mgr.on_state_change("myservice", on_change)

Scheduled services:
    class MetricsCollector(ScheduledService):
        name = "metrics"
        interval = 60.0

        def tick(self) -> None:
            collect_and_send_metrics()

    mgr.add_service(MetricsCollector())
"""

from .base import ScheduledService, Service
from .channel import (
    Channel,
    Message,
    ProcessChannel,
    ThreadChannel,
    create_process_channel_pair,
    create_thread_channel_pair,
)
from .errors import (
    ChannelClosedError,
    ChannelError,
    ChannelTimeoutError,
    CycleError,
    DependencyFailedError,
    Error,
    HealthTimeoutError,
    InvalidTransitionError,
    RunError,
    SetupError,
)
from .factory import (
    ChannelConfig,
    ChannelFactory,
    ChannelPair,
    RunnerFactory,
    RunnerWithChannel,
    ServiceFactory,
    ServiceRegistration,
)
from .manager import Manager
from .runner import ProcessRunner, Runner, ThreadRunner
from .state import RestartPolicy, State, StateHook

__all__ = [
    # Core classes
    "Service",
    "ScheduledService",
    "Runner",
    "ThreadRunner",
    "ProcessRunner",
    "Manager",
    # Channel communication
    "Channel",
    "ThreadChannel",
    "ProcessChannel",
    "Message",
    "create_thread_channel_pair",
    "create_process_channel_pair",
    "ChannelError",
    "ChannelTimeoutError",
    "ChannelClosedError",
    # Factories
    "ChannelFactory",
    "ChannelConfig",
    "ChannelPair",
    "RunnerFactory",
    "RunnerWithChannel",
    "ServiceFactory",
    "ServiceRegistration",
    # State management
    "State",
    "RestartPolicy",
    "StateHook",
    # Errors
    "Error",
    "CycleError",
    "SetupError",
    "RunError",
    "HealthTimeoutError",
    "DependencyFailedError",
    "InvalidTransitionError",
]
