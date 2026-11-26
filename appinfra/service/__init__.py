# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Services, and the runtime that runs them.

- Service: WHAT to run (definition, config, behavior)
- Runtime: the entry point. spawn() takes services in any order and from any
  thread, runs each as appinfra.runtime tasks (a thread, the event loop, or a
  process of its own, from the service's kind), starts each once its
  ``depends_on`` run, restarts a failed one per its policy, and stops them in
  reverse start order
- Runner: a service's state in the Runtime, its restart policy and hooks

A Service implements run(), which returns once ``self.stopping`` is set. Two
subclasses work differently:
- ScheduledService: the runner calls tick() every interval seconds
- AsyncService: run() is a coroutine; it runs as a task on the runtime's event
  loop, shared by every async service

Usage:
    from appinfra.service import RestartPolicy, Runtime, Service

    class MyService(Service):
        def __init__(self, lg: Logger) -> None:
            self._lg = lg

        @property
        def name(self) -> str:
            return "myservice"

        @property
        def depends_on(self) -> list[str]:
            return ["database"]

        def run(self) -> None:
            self.stopping.wait()  # Block until stopped

    with Runtime(lg) as rt:
        svc = rt.spawn(MyService(lg))   # starts once "database" runs
        rt.spawn(Database(lg, cfg), policy=RestartPolicy(max_retries=5))
        rt.spawn(Indexer(lg), isolate=True)  # a process of its own
        rt.ready(svc)
        run_application()

spawn() returns the service's runner; ``runner.on_state_change(hook)``
observes its transitions.
"""

from ..runtime import StopToken
from .base import AsyncService, ScheduledService, Service
from .channel import (
    AsyncBufferedChannel,
    AsyncChannel,
    AsyncProcessQueueTransport,
    AsyncQueueTransport,
    AsyncTransport,
    BufferedChannel,
    Channel,
    Message,
    ProcessQueueTransport,
    QueueTransport,
    Transport,
)
from .errors import (
    ChannelClosedError,
    ChannelError,
    ChannelFullError,
    ChannelResponseError,
    ChannelTimeoutError,
    CycleError,
    DependencyFailedError,
    DependencyNotRunningError,
    Error,
    HealthTimeoutError,
    InvalidTransitionError,
    RunError,
    SetupError,
)
from .factory import (
    AsyncChannelPair,
    AsyncProcessChannelPair,
    AsyncProcessQueueChannelFactory,
    AsyncQueueChannelFactory,
    ChannelConfig,
    ChannelPair,
    ChannelPairFactory,
    ProcessQueueChannelFactory,
    QueueChannelFactory,
    ServiceFactory,
    ServiceRegistration,
)
from .runtime import Runner, Runtime
from .state import RestartPolicy, State, StateHook

__all__ = [
    # Core classes
    "Service",
    "ScheduledService",
    "AsyncService",
    "Runner",
    "Runtime",
    # Transport (wire level)
    "Transport",
    "QueueTransport",
    "ProcessQueueTransport",
    "AsyncTransport",
    "AsyncQueueTransport",
    "AsyncProcessQueueTransport",
    # Channel (protocol + concrete)
    "Channel",
    "BufferedChannel",
    "AsyncChannel",
    "AsyncBufferedChannel",
    "Message",
    # Channel errors
    "ChannelError",
    "ChannelTimeoutError",
    "ChannelClosedError",
    "ChannelFullError",
    "ChannelResponseError",
    # Factories
    "ChannelConfig",
    "ChannelPair",
    "ChannelPairFactory",
    "QueueChannelFactory",
    "ProcessQueueChannelFactory",
    "AsyncChannelPair",
    "AsyncProcessChannelPair",
    "AsyncQueueChannelFactory",
    "AsyncProcessQueueChannelFactory",
    "ServiceFactory",
    "ServiceRegistration",
    # State management
    "State",
    "RestartPolicy",
    "StateHook",
    "StopToken",
    # Errors
    "Error",
    "CycleError",
    "SetupError",
    "RunError",
    "HealthTimeoutError",
    "DependencyFailedError",
    "DependencyNotRunningError",
    "InvalidTransitionError",
]
