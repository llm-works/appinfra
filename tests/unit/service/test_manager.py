# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for service manager."""

import threading
import time
from unittest.mock import MagicMock

import pytest

from appinfra.service import (
    CycleError,
    Manager,
    Service,
    SetupError,
    ThreadRunner,
)


class SimpleService(Service):
    """Simple test service that tracks lifecycle calls."""

    def __init__(
        self,
        name: str,
        depends_on: list[str] | None = None,
        setup_error: str | None = None,
        health_delay: float = 0,
    ) -> None:
        self._name = name
        self._depends_on = depends_on or []
        self._setup_error = setup_error
        self._health_delay = health_delay

        self._setup_called = False
        self._execute_called = False
        self._teardown_called = False
        self._healthy = False
        self._stop_event = threading.Event()

    @property
    def name(self) -> str:
        return self._name

    @property
    def depends_on(self) -> list[str]:
        return self._depends_on

    def setup(self) -> None:
        self._setup_called = True
        if self._setup_error:
            raise SetupError(self._name, self._setup_error)

    def execute(self) -> None:
        self._execute_called = True

        if self._health_delay:
            time.sleep(self._health_delay)

        self._healthy = True
        self._stop_event.wait()

    def teardown(self) -> None:
        self._teardown_called = True
        self._stop_event.set()

    def is_healthy(self) -> bool:
        return self._healthy


@pytest.fixture
def lg():
    """Mock logger."""
    mock_lg = MagicMock()
    mock_lg.debug = MagicMock()
    mock_lg.info = MagicMock()
    mock_lg.warning = MagicMock()
    mock_lg.error = MagicMock()
    return mock_lg


class TestManagerRegistration:
    """Test service registration."""

    def test_add_single_service(self, lg):
        """Can add a single service."""
        mgr = Manager(lg)
        svc = SimpleService("a")
        runner = ThreadRunner(svc)
        mgr.add(runner)

        assert "a" in mgr.runners
        assert mgr.get("a") is runner

    def test_add_service_convenience(self, lg):
        """add_service() wraps in ThreadRunner."""
        mgr = Manager(lg)
        svc = SimpleService("a")
        mgr.add_service(svc)

        assert "a" in mgr.runners
        assert isinstance(mgr.get("a"), ThreadRunner)

    def test_add_chaining(self, lg):
        """add() returns self for chaining."""
        mgr = Manager(lg)
        svc_a = SimpleService("a")
        svc_b = SimpleService("b")

        result = mgr.add_service(svc_a).add_service(svc_b)

        assert result is mgr
        assert len(mgr.runners) == 2

    def test_duplicate_name_rejected(self, lg):
        """Cannot add two services with same name."""
        mgr = Manager(lg)
        mgr.add_service(SimpleService("a"))

        with pytest.raises(ValueError, match="already registered"):
            mgr.add_service(SimpleService("a"))

    def test_missing_dependency_rejected(self, lg):
        """Cannot add service with missing dependency."""
        mgr = Manager(lg)

        with pytest.raises(ValueError, match="unknown service"):
            mgr.add_service(SimpleService("a", depends_on=["nonexistent"]))

    def test_cycle_rejected(self, lg):
        """Cycle detection works.

        Note: Tests validate_dependencies directly because Manager.add()
        rejects missing dependencies before cycles can be formed.
        """
        from appinfra.service.graph import validate_dependencies

        class _Svc:
            def __init__(self, name, deps):
                self._name = name
                self._deps = deps

            @property
            def name(self):
                return self._name

            @property
            def depends_on(self):
                return self._deps

        services = {
            "a": _Svc("a", ["c"]),
            "b": _Svc("b", ["a"]),
            "c": _Svc("c", ["b"]),
        }
        with pytest.raises(CycleError):
            validate_dependencies(services)

    def test_get_nonexistent(self, lg):
        """get() raises KeyError for unknown service."""
        mgr = Manager(lg)
        with pytest.raises(KeyError):
            mgr.get("nonexistent")


class TestManagerLifecycle:
    """Test service lifecycle management."""

    def test_setup_error_prevents_start(self, lg):
        """Setup error prevents service from starting."""
        mgr = Manager(lg)
        svc = SimpleService("a", setup_error="config invalid")
        mgr.add_service(svc)

        with pytest.raises(SetupError, match="config invalid"):
            mgr.start()

        assert svc._setup_called
        assert not svc._execute_called

    def test_dependency_failed_error(self, lg):
        """If dependency fails, dependent is not started."""
        mgr = Manager(lg)
        svc_a = SimpleService("a", setup_error="broken")
        svc_b = SimpleService("b", depends_on=["a"])

        mgr.add_service(svc_a).add_service(svc_b)

        with pytest.raises(SetupError):
            mgr.start()

        assert not svc_b._setup_called

    def test_empty_manager(self, lg):
        """Empty manager starts/stops without error."""
        mgr = Manager(lg)
        mgr.start()
        mgr.stop()

    def test_stop_without_start(self, lg):
        """Stopping without starting is safe."""
        mgr = Manager(lg)
        mgr.add_service(SimpleService("a"))
        mgr.stop()


class TestManagerIsRunning:
    """Test is_running method."""

    def test_not_running_before_start(self, lg):
        """Services not running before start."""
        mgr = Manager(lg)
        mgr.add_service(SimpleService("a"))
        assert not mgr.is_running("a")

    def test_is_running_unknown_service(self, lg):
        """is_running returns False for unknown service."""
        mgr = Manager(lg)
        assert not mgr.is_running("nonexistent")
