# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Service base class, and the scheduled and async services."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..log import Logger
from ..runtime import StopToken


class Service(ABC):
    """Base class for service definitions.

    A Service defines WHAT to run: configuration and behavior. The Runtime
    runs it, each step as an appinfra.runtime task, and keeps its state in a
    Runner.

    A plain Service implements run(), which holds its thread, or process, until
    the service is stopped. Two subclasses work differently:
    - ScheduledService: its run() is the tick loop, calling tick() every
      interval seconds until the service is stopped
    - AsyncService: run() is a coroutine; many of them run as tasks on one
      event loop, and one waiting on an await holds no thread

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

            @property
            def name(self) -> str:
                return "database"

            def setup(self) -> None:
                if not self._config.host:
                    raise SetupError(self.name, "host required")

            def run(self) -> None:
                self._pool = create_pool(self._config)
                self._lg.info("database pool created")
                self.stopping.wait()  # Block until stopped

            def teardown(self) -> None:
                if self._pool:
                    self._pool.close()

            def is_healthy(self) -> bool:
                return self._pool is not None and self._pool.is_connected()
    """

    _lg: Logger
    """Logger instance. Set by subclass __init__, and in a process of its own by
    the runtime."""

    stopping: StopToken
    """Set when this run of the service is to stop, and once the run has ended
    however it ended; set by the runtime before setup(), a new token for each
    start. ``stopping.child()`` derives a token stopped with it, so work the run
    starts is told to stop with it, before teardown(); stopping does not wait
    for that work.

    A synchronous run(), on its thread or in a process of its own,
    checks it (``is_set()``) or blocks on it (``wait()``) and returns once it
    is set. An AsyncService's run() never calls ``wait()``, which would block
    the loop it shares: stopping it cancels its task, and it uses the token to
    derive tokens for what it starts."""

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

        The runtime calls it once, and it returns once ``self.stopping`` is set.
        In the runtime's process, a stop also calls teardown() while run()
        still runs, so a run() blocked elsewhere can be released there; in a
        process of its own, teardown() runs there after run() returns.
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
        """Cleanup the service, once the run is told to stop.

        run() returns on ``self.stopping``; teardown() releases resources. It
        runs on a thread of its own, or in the service's process when it has
        one. For a scheduled service, it runs once the loop has ended (stopped
        or failed), so it never overlaps tick(). For an async service, it runs
        after run() has ended, off the event loop: it must not touch objects
        bound to the loop. For a service with its own run(), a stop calls it
        once the token is set, while run() may still be running, so it can also
        release a run() blocked on something other than the token; in a process
        of its own, it runs there after run() has returned. Default does
        nothing.
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

    The runtime runs it as a task on its event loop, alongside many others:
    while run() waits on an await, the service holds no thread. It stays on
    that loop for its lifetime. Stopping it cancels the task, raising
    CancelledError at the await it is parked on. A process of its own is
    refused for an AsyncService.

    run() must not call anything that blocks without awaiting: that stalls
    every service on the loop. Run blocking code through asyncio.to_thread().
    Open clients bound to the loop in run() and close them in its finally:
    setup() and teardown() run on threads, off the loop.

    Example:
        class Doubler(AsyncService):
            def __init__(self, lg: Logger, requests: Chan[tuple[int, Chan[int]]]) -> None:
                self._lg = lg
                self._requests = requests

            @property
            def name(self) -> str:
                return "doubler"

            async def run(self) -> None:
                async for value, reply in self._requests:
                    await reply.asend(value * 2)
    """

    # A coroutine, unlike Service.run(): the runtime runs it on its event loop,
    # and never in a process of its own
    @abstractmethod
    async def run(self) -> None:  # type: ignore[override]
        """Do the service's work until it returns or is cancelled."""
        ...


class ScheduledService(Service):
    """Service that runs on a schedule.

    Its run() calls tick(), then waits ``interval`` seconds, until the service
    is stopped: ticks start interval plus tick() time apart. An exception from
    tick() fails the service. A subclass implements tick() and keeps run():
    the Runtime refuses one that overrides it.

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
        """tick(), then wait ``interval`` seconds, until ``stopping`` is set; an
        exception from tick() ends the run with it."""
        while not self.stopping.is_set():
            self.tick()
            self.stopping.wait(self.interval)
