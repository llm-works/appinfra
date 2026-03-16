"""Base service class."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..log import Logger


class Service(ABC):
    """Base class for service definitions.

    A Service defines WHAT to run - configuration and behavior.
    The Runner handles HOW to run it and manages state.

    Lifecycle methods:
    - setup(): Initialize resources, validate config
    - execute(): The main work (blocking for threads, one-shot for scheduled)
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

            def execute(self) -> None:
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

    def setup(self) -> None:
        """Initialize the service.

        Called before execute(). Use for:
        - Validating configuration
        - Allocating resources
        - Checking prerequisites

        Raise SetupError to abort startup.
        """

    @abstractmethod
    def execute(self) -> None:
        """Execute the service work.

        For long-running services (ThreadRunner): block until teardown.
        For scheduled services: do one iteration of work.
        For process services: not used (ProcessRunner runs external command).
        """
        ...

    def teardown(self) -> None:
        """Cleanup the service.

        Called to stop the service. Should cause execute() to return
        for blocking services. Default does nothing.
        """

    def is_healthy(self) -> bool:
        """Check if service is ready.

        Called after execute() begins to determine when the service
        is ready. Runner waits for this before reporting RUNNING state.

        Returns:
            True if service is ready, False otherwise.
        """
        return True


class ScheduledService(Service):
    """Service that runs on a schedule.

    Instead of blocking execute(), scheduled services implement tick()
    which is called repeatedly. The interval property controls frequency.

    If used with ThreadRunner, the default execute() loops calling tick().

    Example:
        class MetricsCollector(ScheduledService):
            name = "metrics"
            interval = 60.0  # Collect every minute

            def tick(self) -> None:
                metrics = collect_metrics()
                send_to_server(metrics)
    """

    interval: float = 1.0
    """Seconds between tick() calls."""

    @abstractmethod
    def tick(self) -> None:
        """Execute one iteration of work.

        Should complete quickly and not block.
        """
        ...

    def execute(self) -> None:
        """Default execute() that loops calling tick()."""
        import time

        self._stop_flag = False
        while not getattr(self, "_stop_flag", False):
            self.tick()
            time.sleep(self.interval)

    def teardown(self) -> None:
        """Signal the service to stop."""
        self._stop_flag = True
