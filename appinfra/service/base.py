# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Service base class, and the scheduled and async services."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..log import Logger


class Service(ABC):
    """Base class for service definitions.

    A Service defines WHAT to run - configuration and behavior.
    The Runner handles HOW to run it and manages state.

    A plain Service implements run(), which holds its thread, or process, until
    the service is stopped. Two subclasses work differently:
    - ScheduledService: the runner calls tick() every interval seconds
    - AsyncService: run() is a coroutine; a LoopHost runs many of them as tasks
      on one event loop, and one waiting on an await holds no thread

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

        For a scheduled service, the runner calls it once the loop has ended
        (stopped or failed), on the thread or in the process that ran the loop,
        so it never overlaps tick(). For an async service, it runs on the
        LoopHost's thread after run() has ended, so it must not block. For a
        service with its own run(), it must make run() return: under
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


class AsyncService(Service):
    """Service whose run() is a coroutine.

    A LoopHost runs it as a task on its event loop, alongside many others
    (``host.runner(service)``): while run() waits on an await, the service
    holds no thread. It stays on that loop for its lifetime. Stopping it
    cancels the task, raising CancelledError at the await it is parked on.
    ThreadRunner and ProcessRunner refuse an AsyncService.

    run() must not call anything that blocks without awaiting: that stalls
    every service on the loop. Run blocking code through asyncio.to_thread().
    Open clients bound to the loop in run() and close them in its finally:
    setup() runs on the caller's thread, before the task starts.

    Example:
        class Doubler(AsyncService):
            def __init__(self, lg: Logger, inbox: AsyncChannel) -> None:
                self._lg = lg
                self._inbox = inbox

            @property
            def name(self) -> str:
                return "doubler"

            async def run(self) -> None:
                while True:
                    msg = await self._inbox.recv()
                    await self._inbox.send(Message(id=msg.id, payload=msg.payload * 2))
    """

    # A coroutine, unlike Service.run(): only a LoopHost runs it, and ThreadRunner
    # and ProcessRunner refuse an AsyncService
    @abstractmethod
    async def run(self) -> None:  # type: ignore[override]
        """Do the service's work until it returns or is cancelled."""
        ...


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
