"""Service manager with dependency-ordered execution."""

from __future__ import annotations

import atexit
import threading
from typing import TYPE_CHECKING, Self

from .errors import DependencyFailedError
from .graph import dependency_levels, validate_dependencies
from .runner import Runner, ThreadRunner
from .state import RestartPolicy, State

if TYPE_CHECKING:
    from appinfra.log import Logger

    from .base import Service


class Manager:
    """Manages service execution with dependency-ordered parallel startup.

    Services are started in dependency order: dependencies first, then dependents.
    Services at the same dependency level are started in parallel.
    Shutdown is the reverse: dependents first, then dependencies.

    Example:
        from appinfra.service import Manager, ThreadRunner, ProcessRunner

        mgr = Manager(lg)
        mgr.add(ThreadRunner(db_service))
        mgr.add(ProcessRunner(cache_service), depends_on=["database"])
        mgr.add(ThreadRunner(api_service), depends_on=["database", "cache"])

        with mgr:
            # Starts in dependency order
            run_app()
        # Stops in reverse order
    """

    def __init__(self, lg: Logger) -> None:
        """Initialize the manager.

        Args:
            lg: Logger instance.
        """
        self._lg = lg
        self._runners: dict[str, Runner] = {}
        self._depends_on: dict[str, list[str]] = {}
        self._started: list[str] = []
        self._failed: set[str] = set()
        self._lock = threading.Lock()
        self._atexit_registered = True

        atexit.register(self._atexit_stop)

    @property
    def runners(self) -> dict[str, Runner]:
        """All registered runners."""
        return dict(self._runners)

    def add(
        self,
        runner: Runner,
        depends_on: list[str] | None = None,
    ) -> Self:
        """Register a runner.

        Args:
            runner: Runner to register.
            depends_on: Service names this depends on.

        Returns:
            Self for chaining.

        Raises:
            CycleError: If adding creates a dependency cycle.
            ValueError: If name is duplicate or dependency doesn't exist.
        """
        name = runner.name
        if name in self._runners:
            raise ValueError(f"Service '{name}' already registered")

        self._runners[name] = runner
        self._depends_on[name] = depends_on or []

        # Validate graph
        try:
            self._validate_graph()
        except Exception:
            del self._runners[name]
            del self._depends_on[name]
            raise

        return self

    def add_service(
        self,
        service: Service,
        policy: RestartPolicy | None = None,
    ) -> Self:
        """Register a service with ThreadRunner.

        Convenience method that wraps a Service in a ThreadRunner.

        Args:
            service: Service to register.
            policy: Restart policy.

        Returns:
            Self for chaining.
        """
        runner = ThreadRunner(service, policy)
        return self.add(runner, depends_on=service.depends_on)

    def get(self, name: str) -> Runner:
        """Get a runner by name.

        Args:
            name: Service name.

        Returns:
            The runner instance.

        Raises:
            KeyError: If not found.
        """
        return self._runners[name]

    def _is_active(self) -> bool:
        """Check if any runners are in an active state."""
        return any(
            r.state in (State.STARTING, State.RUNNING, State.STOPPING)
            for r in self._runners.values()
        )

    def start(self) -> None:
        """Start all services in dependency order.

        Services at the same level are started in parallel.
        If a service fails, its dependents are not started.

        Raises:
            SetupError: If setup fails.
            RunError: If execution fails to start.
            HealthTimeoutError: If health check times out.
            DependencyFailedError: If a dependency failed.
            RuntimeError: If manager is already running.
        """
        if not self._runners:
            return

        if self._is_active():
            raise RuntimeError("Manager is already running")

        if not self._atexit_registered:
            atexit.register(self._atexit_stop)
            self._atexit_registered = True

        self._failed.clear()
        self._started.clear()

        levels = self._get_dependency_levels()
        self._lg.debug(
            "starting services",
            extra={"levels": [[s for s in lvl] for lvl in levels]},
        )

        try:
            for level in levels:
                self._start_level(level)
        except Exception:
            self._lg.warning("startup failed, stopping started services")
            self._stop_started()
            raise

    def stop(self) -> None:
        """Stop all services in reverse dependency order.

        Errors during shutdown are logged but don't prevent other
        services from stopping.
        """
        # Unregister atexit handler since we're stopping explicitly
        if self._atexit_registered:
            atexit.unregister(self._atexit_stop)
            self._atexit_registered = False

        if not self._started:
            return

        self._stop_started()

    def is_running(self, name: str) -> bool:
        """Check if a service is running.

        Args:
            name: Service name.

        Returns:
            True if in RUNNING state.
        """
        if name not in self._runners:
            return False
        return self._runners[name].state == State.RUNNING

    def check_all(self) -> dict[str, bool]:
        """Check health of all running services.

        Returns:
            Dict mapping service name to whether restart was triggered.
        """
        results = {}
        for name in self._started:
            runner = self._runners[name]
            results[name] = runner.check()
        return results

    def on_state_change(self, name: str, hook: object) -> None:
        """Register a state change hook for a service.

        Args:
            name: Service name.
            hook: Callable(service_name, from_state, to_state).
        """

        self._runners[name].on_state_change(hook)  # type: ignore[arg-type]

    def _validate_graph(self) -> None:
        """Validate dependency graph."""

        class _DepProxy:
            """Proxy for dependency validation."""

            def __init__(self, name: str, deps: list[str]) -> None:
                self._name = name
                self._deps = deps

            @property
            def name(self) -> str:
                return self._name

            @property
            def depends_on(self) -> list[str]:
                return self._deps

        services = {
            name: _DepProxy(name, self._depends_on[name]) for name in self._runners
        }
        validate_dependencies(services)  # type: ignore[arg-type]

    def _get_dependency_levels(self) -> list[list[str]]:
        """Get services grouped by dependency level."""

        class _DepProxy:
            def __init__(self, name: str, deps: list[str]) -> None:
                self._name = name
                self._deps = deps

            @property
            def name(self) -> str:
                return self._name

            @property
            def depends_on(self) -> list[str]:
                return self._deps

        services = {
            name: _DepProxy(name, self._depends_on[name]) for name in self._runners
        }
        return dependency_levels(services)  # type: ignore[arg-type]

    def _start_level(self, names: list[str]) -> None:
        """Start all services in a level."""
        self._check_failed_deps(names)

        # Track which services we've started in this level
        started_in_level: list[str] = []

        # Start all (non-blocking)
        for name in names:
            self._lg.info(f"starting {name}")
            self._runners[name].start()
            # Track immediately after start() so cleanup can stop it if needed
            with self._lock:
                self._started.append(name)
            started_in_level.append(name)

        # Wait for all to be healthy
        for name in started_in_level:
            runner = self._runners[name]
            try:
                runner.wait_healthy()
                self._lg.info(f"{name} is healthy")
            except Exception:
                # Keep in _started so _stop_started() can stop the running process
                self._failed.add(name)
                raise

    def _check_failed_deps(self, names: list[str]) -> None:
        """Check if any service has a failed dependency."""
        for name in names:
            for dep in self._depends_on[name]:
                if dep in self._failed:
                    self._failed.add(name)
                    raise DependencyFailedError(name, dep)

    def _stop_started(self) -> None:
        """Stop all started services in reverse order."""
        if not self._started:
            return

        levels = self._get_dependency_levels()
        started_set = set(self._started)
        reverse_levels = [
            [name for name in level if name in started_set]
            for level in reversed(levels)
        ]
        reverse_levels = [level for level in reverse_levels if level]

        for level in reverse_levels:
            self._stop_level(level)

        self._started.clear()

    def _stop_level(self, names: list[str]) -> None:
        """Stop all services in a level."""
        for name in names:
            runner = self._runners[name]
            self._lg.info(f"stopping {name}")
            try:
                runner.stop()
            except Exception as e:
                self._lg.warning(f"error stopping {name}", extra={"exception": e})

    def _atexit_stop(self) -> None:
        """Stop services on interpreter exit."""
        if self._started:
            try:
                self.stop()
            except Exception:
                pass

    def __enter__(self) -> Self:
        """Start all services."""
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        """Stop all services."""
        self.stop()
