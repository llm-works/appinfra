"""Factory for creating runners with optional channels."""

from __future__ import annotations

from dataclasses import dataclass

from ...log import Logger
from ..base import Service
from ..channel.sync import Channel
from ..runner import ProcessRunner, Runner, ThreadRunner
from ..state import RestartPolicy
from .channel import (
    ChannelConfig,
    ChannelPair,
    ChannelPairFactory,
    ProcessQueueChannelFactory,
    QueueChannelFactory,
)


@dataclass
class RunnerWithChannel:
    """Runner with an associated channel for communication.

    Attributes:
        runner: The runner instance
        channel: Parent-side channel for communicating with the service
        service_channel: Service-side channel (pass to service)
    """

    runner: Runner
    channel: Channel
    service_channel: Channel


class RunnerFactory:
    """
    Factory for creating runners with consistent configuration.

    Simplifies runner creation by:
    - Applying default restart policies
    - Optionally creating channels for communication
    - Ensuring consistent configuration

    Example:
        factory = RunnerFactory(
            lg=lg,
            default_policy=RestartPolicy(max_retries=3),
        )

        # Simple runner
        runner = factory.create_thread_runner(my_service)

        # Runner with channel for request/response
        result = factory.create_thread_runner_with_channel(my_service)
        runner = result.runner
        channel = result.channel  # Use to communicate with service
    """

    def __init__(
        self,
        lg: Logger,
        default_policy: RestartPolicy | None = None,
        channel_config: ChannelConfig | None = None,
        channel_factory: ChannelPairFactory | None = None,
        stop_timeout: float = 5.0,
    ) -> None:
        """
        Initialize factory.

        Args:
            lg: Logger for factory operations
            default_policy: Default restart policy for runners
            channel_config: Configuration for built-in channels (ignored if
                channel_factory is provided)
            channel_factory: Custom transport factory. When provided, all
                channel creation uses this instead of the built-in factories.
            stop_timeout: Default stop timeout for ProcessRunner
        """
        self._lg = lg
        self._default_policy = default_policy
        self._custom_channel_factory = channel_factory
        self._channel_config = channel_config
        self._stop_timeout = stop_timeout

    def create_thread_runner(
        self,
        service: Service,
        policy: RestartPolicy | None = None,
    ) -> ThreadRunner:
        """
        Create a ThreadRunner for the service.

        Args:
            service: Service to run
            policy: Restart policy (uses default if not provided)

        Returns:
            Configured ThreadRunner
        """
        effective_policy = policy if policy is not None else self._default_policy
        return ThreadRunner(service, policy=effective_policy)

    def create_thread_runner_with_channel(
        self,
        service: Service,
        policy: RestartPolicy | None = None,
        channel_pair: ChannelPair | None = None,
    ) -> RunnerWithChannel:
        """
        Create a ThreadRunner with a channel pair for communication.

        Args:
            service: Service to run
            policy: Restart policy (uses default if not provided)
            channel_pair: Pre-built channel pair (overrides factory).

        Returns:
            RunnerWithChannel containing runner and both channels
        """
        runner = self.create_thread_runner(service, policy)
        pair = channel_pair or self._create_thread_pair()

        return RunnerWithChannel(
            runner=runner,
            channel=pair.parent,
            service_channel=pair.child,
        )

    def create_process_runner(
        self,
        service: Service,
        policy: RestartPolicy | None = None,
        stop_timeout: float | None = None,
    ) -> ProcessRunner:
        """
        Create a ProcessRunner for the service.

        Args:
            service: Service to run (must be picklable)
            policy: Restart policy (uses default if not provided)
            stop_timeout: Stop timeout (uses factory default if not provided)

        Returns:
            Configured ProcessRunner
        """
        effective_policy = policy if policy is not None else self._default_policy
        effective_timeout = (
            stop_timeout if stop_timeout is not None else self._stop_timeout
        )
        return ProcessRunner(
            service, policy=effective_policy, stop_timeout=effective_timeout
        )

    def create_process_runner_with_channel(
        self,
        service: Service,
        policy: RestartPolicy | None = None,
        stop_timeout: float | None = None,
        channel_pair: ChannelPair | None = None,
    ) -> RunnerWithChannel:
        """
        Create a ProcessRunner with a channel pair for communication.

        IMPORTANT: Create this BEFORE starting the runner.

        Args:
            service: Service to run (must be picklable)
            policy: Restart policy (uses default if not provided)
            stop_timeout: Stop timeout (uses factory default if not provided)
            channel_pair: Pre-built channel pair (overrides factory).

        Returns:
            RunnerWithChannel containing runner and both channels
        """
        runner = self.create_process_runner(service, policy, stop_timeout)
        pair = channel_pair or self._create_process_pair()

        return RunnerWithChannel(
            runner=runner,
            channel=pair.parent,
            service_channel=pair.child,
        )

    def _create_thread_pair(self) -> ChannelPair:
        """Create a channel pair for thread runners."""
        if self._custom_channel_factory is not None:
            return self._custom_channel_factory.create_pair()
        return QueueChannelFactory(self._channel_config).create_pair()

    def _create_process_pair(self) -> ChannelPair:
        """Create a channel pair for process runners.

        When using a custom factory, the caller is responsible for ensuring the
        transport is process-safe (picklable queues or shared-memory).
        """
        if self._custom_channel_factory is not None:
            self._lg.info(
                "custom channel factory used with ProcessRunner — "
                "ensure transport is process-safe (picklable)",
            )
            return self._custom_channel_factory.create_pair()
        return ProcessQueueChannelFactory(self._channel_config).create_pair()
