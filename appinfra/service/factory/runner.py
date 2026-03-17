"""Factory for creating runners with optional channels."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ...log import Logger
from ..base import Service
from ..channel import ProcessChannel, ThreadChannel
from ..runner import ProcessRunner, Runner, ThreadRunner
from ..state import RestartPolicy
from .channel import ChannelConfig, ChannelFactory


@dataclass
class RunnerWithChannel:
    """Runner with an associated channel for communication.

    Attributes:
        runner: The runner instance
        channel: Parent-side channel for communicating with the service
        service_channel: Service-side channel (pass to service)
    """

    runner: Runner
    channel: ThreadChannel[Any, Any] | ProcessChannel[Any, Any]
    service_channel: ThreadChannel[Any, Any] | ProcessChannel[Any, Any]


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
        stop_timeout: float = 5.0,
    ) -> None:
        """
        Initialize factory.

        Args:
            lg: Logger for factory operations
            default_policy: Default restart policy for runners
            channel_config: Configuration for channels
            stop_timeout: Default stop timeout for ProcessRunner
        """
        self._lg = lg
        self._default_policy = default_policy
        self._channel_factory = ChannelFactory(channel_config)
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
    ) -> RunnerWithChannel:
        """
        Create a ThreadRunner with a channel pair for communication.

        The service should accept the service_channel and use it to
        receive requests and send responses.

        Args:
            service: Service to run
            policy: Restart policy (uses default if not provided)

        Returns:
            RunnerWithChannel containing runner and both channels
        """
        runner = self.create_thread_runner(service, policy)
        pair = self._channel_factory.create_thread_pair()

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
    ) -> RunnerWithChannel:
        """
        Create a ProcessRunner with a channel pair for communication.

        The service should accept the service_channel and use it to
        receive requests and send responses.

        IMPORTANT: Create this BEFORE starting the runner. Pass the
        service_channel to the service before it's pickled.

        Args:
            service: Service to run (must be picklable)
            policy: Restart policy (uses default if not provided)
            stop_timeout: Stop timeout (uses factory default if not provided)

        Returns:
            RunnerWithChannel containing runner and both channels
        """
        runner = self.create_process_runner(service, policy, stop_timeout)
        pair = self._channel_factory.create_process_pair()

        return RunnerWithChannel(
            runner=runner,
            channel=pair.parent,
            service_channel=pair.child,
        )
