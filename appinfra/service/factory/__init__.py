# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Factories for service, runner, and channel creation.

Provides centralized creation of service components with:
- Consistent configuration
- Dependency injection
- Optional channel wiring

Example:
    from appinfra.service.factory import (
        QueueChannelFactory,
        RunnerFactory,
        ServiceFactory,
    )

    # Channel factory for direct channel creation
    ch_factory = QueueChannelFactory(ChannelConfig(response_timeout=60.0))
    pair = ch_factory.create_pair()

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
    AsyncProcessQueueChannelFactory,
    AsyncQueueChannelFactory,
    ChannelConfig,
    ChannelPair,
    ChannelPairFactory,
    ProcessQueueChannelFactory,
    QueueChannelFactory,
)
from .runner import RunnerFactory, RunnerWithChannel
from .service import ServiceFactory, ServiceRegistration

__all__ = [
    # Channel factories
    "ChannelConfig",
    "ChannelPair",
    "ChannelPairFactory",
    "QueueChannelFactory",
    "ProcessQueueChannelFactory",
    "AsyncChannelPair",
    "AsyncProcessChannelPair",
    "AsyncQueueChannelFactory",
    "AsyncProcessQueueChannelFactory",
    # Runner factory
    "RunnerFactory",
    "RunnerWithChannel",
    # Service factory
    "ServiceFactory",
    "ServiceRegistration",
]
