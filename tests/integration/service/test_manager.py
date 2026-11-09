# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for the service manager running services on threads."""

import threading
import time
from unittest.mock import MagicMock

import pytest

from appinfra.service import (
    Manager,
    Service,
    SetupError,
    ThreadRunner,
)
from tests.helpers.service.manager import SimpleService


class UnhealthyService(Service):
    """Service that never becomes healthy."""

    def __init__(self, name: str) -> None:
        self._name = name
        self._lg = MagicMock()
        self._stop = threading.Event()
        self._teardown_called = False

    @property
    def name(self) -> str:
        return self._name

    def execute(self) -> None:
        self._stop.wait()

    def teardown(self) -> None:
        self._teardown_called = True
        self._stop.set()

    def is_healthy(self) -> bool:
        return False  # Never healthy


@pytest.fixture
def lg():
    """Mock logger."""
    mock_lg = MagicMock()
    mock_lg.debug = MagicMock()
    mock_lg.info = MagicMock()
    mock_lg.warning = MagicMock()
    mock_lg.error = MagicMock()
    return mock_lg


class TestManagerLifecycle:
    """Test service lifecycle management."""

    def test_start_stop_single_service(self, lg):
        """Can start and stop a single service."""
        mgr = Manager(lg)
        svc = SimpleService("a")
        mgr.add_service(svc)

        mgr.start()
        assert svc._setup_called
        assert svc._execute_called
        assert svc.is_healthy()
        assert mgr.is_running("a")

        mgr.stop()
        assert svc._teardown_called
        assert not mgr.is_running("a")

    def test_context_manager(self, lg):
        """Can use as context manager."""
        mgr = Manager(lg)
        svc = SimpleService("a")
        mgr.add_service(svc)

        with mgr:
            assert svc.is_healthy()

        assert svc._teardown_called

    def test_dependency_order(self, lg):
        """Services start in dependency order."""
        order: list[str] = []

        class OrderTrackingService(SimpleService):
            def execute(self) -> None:
                order.append(self._name)
                super().execute()

        mgr = Manager(lg)
        svc_a = OrderTrackingService("a")
        svc_b = OrderTrackingService("b", depends_on=["a"])
        svc_c = OrderTrackingService("c", depends_on=["b"])

        mgr.add_service(svc_a).add_service(svc_b).add_service(svc_c)

        with mgr:
            assert mgr.is_running("a")
            assert mgr.is_running("b")
            assert mgr.is_running("c")

        assert order.index("a") < order.index("b")
        assert order.index("b") < order.index("c")

    def test_parallel_independent_services(self, lg):
        """Independent services can start in parallel."""
        mgr = Manager(lg)
        svc_a = SimpleService("a", health_delay=1.0)
        svc_b = SimpleService("b", health_delay=1.0)
        svc_c = SimpleService("c", depends_on=["a", "b"])

        mgr.add_service(svc_a).add_service(svc_b).add_service(svc_c)

        start = time.monotonic()
        with mgr:
            elapsed = time.monotonic() - start

        # If parallel: ~1s, if sequential: ~2s
        assert elapsed < 1.5

    def test_setup_error_stops_started_services(self, lg):
        """If setup fails, already-started services are stopped."""
        mgr = Manager(lg)
        svc_a = SimpleService("a")
        svc_b = SimpleService("b", depends_on=["a"], setup_error="fail")

        mgr.add_service(svc_a).add_service(svc_b)

        with pytest.raises(SetupError):
            mgr.start()

        assert svc_a._teardown_called

    def test_restart_after_stop(self, lg):
        """Manager can be restarted after stop."""
        mgr = Manager(lg)
        svc = SimpleService("a")
        mgr.add_service(svc)

        # First start/stop cycle
        mgr.start()
        assert mgr.is_running("a")
        mgr.stop()
        assert not mgr.is_running("a")

        # Reset service state for second cycle
        svc._stop_event.clear()
        svc._healthy = False

        # Second start/stop cycle - should re-register atexit
        mgr.start()
        assert mgr.is_running("a")
        mgr.stop()
        assert not mgr.is_running("a")

    def test_start_while_running_raises(self, lg):
        """Calling start() while running raises RuntimeError."""
        mgr = Manager(lg)
        mgr.add_service(SimpleService("a"))
        mgr.start()

        with pytest.raises(RuntimeError, match="already running"):
            mgr.start()

        mgr.stop()


class TestManagerIsRunning:
    """Test is_running method."""

    def test_running_after_start(self, lg):
        """Services running after start."""
        mgr = Manager(lg)
        mgr.add_service(SimpleService("a"))
        mgr.start()

        assert mgr.is_running("a")
        mgr.stop()

    def test_not_running_after_stop(self, lg):
        """Services not running after stop."""
        mgr = Manager(lg)
        svc = SimpleService("a")
        mgr.add_service(svc)

        with mgr:
            assert mgr.is_running("a")

        assert not mgr.is_running("a")


class TestManagerCheckAll:
    """Test check_all method."""

    def test_check_all_healthy(self, lg):
        """check_all returns False for all healthy services."""
        mgr = Manager(lg)
        mgr.add_service(SimpleService("a"))
        mgr.add_service(SimpleService("b"))

        with mgr:
            results = mgr.check_all()

        assert results == {"a": False, "b": False}


class TestManagerHealthCheckFailure:
    """Test health check failure handling."""

    def test_health_failure_stops_started_services(self, lg):
        """Health check failure still stops started services."""
        from unittest.mock import patch

        from appinfra.service import HealthTimeoutError

        mgr = Manager(lg)
        svc = UnhealthyService("unhealthy")
        mgr.add_service(svc)

        # Patch wait_healthy to use short timeout
        with (
            patch.object(
                ThreadRunner,
                "wait_healthy",
                side_effect=HealthTimeoutError("unhealthy", 0.1),
            ),
            pytest.raises(HealthTimeoutError),
        ):
            mgr.start()

        # Service should be tracked as failed and teardown called
        assert "unhealthy" in mgr._failed
        assert svc._teardown_called
