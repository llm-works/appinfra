# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Service base class, and the services whose loop the runner runs."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ..log import Logger


class Service(ABC):
    """Base class for service definitions.

    A Service defines WHAT to run - configuration and behavior.
    The Runner handles HOW to run it and manages state.

    A plain Service implements run(), which holds its thread, or process, until
    the service is stopped. Two subclasses hand their loop to the runner
    instead, which lets a runner host many of them without a thread each:
    - StepService: step(msg) for each message on its inbox channel
    - ScheduledService: tick() every interval seconds

    Lifecycle methods, common to all services:
    - setup(): Initialize resources, validate config
    - teardown(): Cleanup resources
    - is_healthy(): Check if ready to serve

    Example:
        class Database(Service):
            def __init__(self, lg: Logger, config: DBConfig) -> None:
                self._lg = lg
                self._config = config
                self._pool: Pool | None = None
                self._stop = threading.Event()

            @property
            def name(self) -> str:
                return "database"

            def setup(self) -> None:
                if not self._config.host:
                    raise SetupError(self.name, "host required")

            def run(self) -> None:
                self._pool = create_pool(self._config)
                self._lg.info("database pool created")
                self._stop.wait()  # Block until teardown

            def teardown(self) -> None:
                self._stop.set()
                if self._pool:
                    self._pool.close()

            def is_healthy(self) -> bool:
                return self._pool is not None and self._pool.is_connected()
    """

    _lg: Logger
    """Logger instance. Set by subclass __init__ or by ProcessRunner."""

    @property
    def lg(self) -> Logger:
        """Logger instance."""
        return self._lg

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique service identifier."""
        ...

    @property
    def depends_on(self) -> list[str]:
        """Names of services this depends on.

        Override to declare dependencies. Dependencies are started first
        and guaranteed to be healthy before this service starts.
        """
        return []

    @abstractmethod
    def run(self) -> None:
        """Do the service's work, blocking until it is stopped.

        The runner calls it once. Under ThreadRunner, teardown() must make it
        return; under ProcessRunner, the injected ``_shutdown_event`` is set
        (teardown() runs in the subprocess after run() returns). ProcessRunner
        injects it only into an attribute the service declares, e.g.
        ``self._shutdown_event = None`` in ``__init__``.
        """
        ...

    def setup(self) -> None:
        """Initialize the service.

        Called before the runner starts the service's work. Use for:
        - Validating configuration
        - Allocating resources
        - Checking prerequisites

        Raise SetupError to abort startup.
        """

    def teardown(self) -> None:
        """Cleanup the service.

        For a step or scheduled service, the runner calls it once the loop has
        ended (stopped, failed, or inbox closed), on the thread or in the
        process that ran the loop, so it never overlaps step() or tick().
        For a service with its own run(), it must make run() return: under
        ThreadRunner, stop() calls it while run() is still running. Default
        does nothing.
        """

    def is_healthy(self) -> bool:
        """Check if service is ready.

        Called after the service's work begins to determine when it is
        ready. Runner waits for this before reporting RUNNING state.

        Returns:
            True if service is ready, False otherwise.
        """
        return True


class StepService(Service):
    """Service that handles one message per step.

    The runner that hosts it owns its inbox channel: it receives each message
    and calls step() with it, one at a time and in order, until the service is
    stopped or the inbox closes. What step() returns, unless None, the runner
    sends back on the inbox, so a caller holding the other end (see
    RunnerFactory's create_*_runner_with_channel) can submit() a request and
    get the reply. While the inbox has no room for a reply, the runner waits for
    room before the next step(); a reply still waiting when the service stops
    is dropped.

    step() must not block. It may send(..., timeout=0) on other channels it
    holds, but never recv() or submit(), which wait.
    """

    @abstractmethod
    def step(self, msg: Any) -> Any:
        """Handle one message from the inbox. Must not block.

        Returns:
            A reply for the runner to send back on the inbox, or None. A reply
            to a submit() carries the request's id.
        """
        ...

    def run(self) -> None:
        """Not used: the runner drives a step service through step()."""
        raise TypeError(
            f"step service '{self.name}' is driven through step(), not run()"
        )


class ScheduledService(Service):
    """Service that runs on a schedule.

    The runner calls tick(), then waits ``interval`` seconds, until the service
    is stopped: ticks start interval plus tick() time apart. An exception from
    tick() fails the service.

    Example:
        class MetricsCollector(ScheduledService):
            interval = 60.0  # Collect every minute

            def __init__(self, lg: Logger) -> None:
                self._lg = lg

            @property
            def name(self) -> str:
                return "metrics"

            def tick(self) -> None:
                metrics = collect_metrics()
                send_to_server(metrics)
    """

    interval: float = 1.0
    """Seconds from the end of one tick() to the start of the next."""

    @abstractmethod
    def tick(self) -> None:
        """Execute one iteration of work.

        Should complete quickly and not block.
        """
        ...

    def run(self) -> None:
        """Not used: the runner drives a scheduled service through tick()."""
        raise TypeError(
            f"scheduled service '{self.name}' is driven through tick(), not run()"
        )
