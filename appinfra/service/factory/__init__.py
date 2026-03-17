"""Factories for service, runner, and channel creation.

Provides centralized creation of service components with:
- Consistent configuration
- Dependency injection
- Optional channel wiring

Example:
    from appinfra.service.factory import (
        ChannelFactory,
        RunnerFactory,
        ServiceFactory,
    )

    # Channel factory for direct channel creation
    ch_factory = ChannelFactory(ChannelConfig(response_timeout=60.0))
    pair = ch_factory.create_thread_pair()

    # Runner factory for runner + channel creation
    runner_factory = RunnerFactory(lg, default_policy=RestartPolicy(max_retries=3))
    result = runner_factory.create_thread_runner_with_channel(service)

    # Service factory for registry-based service creation
    svc_factory = ServiceFactory(lg)
    svc_factory.register("worker", WorkerService, with_channel=True)
    worker = svc_factory.create("worker")
"""

from .channel import (
    AsyncChannelPair,
    AsyncProcessChannelPair,
    ChannelConfig,
    ChannelFactory,
    ChannelPair,
)
from .runner import RunnerFactory, RunnerWithChannel
from .service import ServiceFactory, ServiceRegistration

__all__ = [
    # Channel factory
    "ChannelFactory",
    "ChannelConfig",
    "ChannelPair",
    "AsyncChannelPair",
    "AsyncProcessChannelPair",
    # Runner factory
    "RunnerFactory",
    "RunnerWithChannel",
    # Service factory
    "ServiceFactory",
    "ServiceRegistration",
]
