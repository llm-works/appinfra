# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for runners that run a service on a thread."""

import threading
import time
from unittest.mock import MagicMock

import pytest

from appinfra.service import (
    HealthTimeoutError,
    RestartPolicy,
    RunError,
    ScheduledService,
    Service,
    State,
    ThreadRunner,
)
from tests.helpers.service.runner import SimpleService


class FailingService(Service):
    """Service that raises during execute()."""

    def __init__(self) -> None:
        self._lg = MagicMock()

    @property
    def name(self) -> str:
        return "failing"

    def execute(self) -> None:
        raise RuntimeError("intentional failure")


class FailOnFirstExecute(Service):
    """Service that fails on first execute but succeeds on retry."""

    def __init__(self) -> None:
        self._lg = MagicMock()
        self._runs = 0
        self._stop_event = threading.Event()
        self._healthy = False

    @property
    def name(self) -> str:
        return "flaky"

    def execute(self) -> None:
        self._runs += 1
        if self._runs == 1:
            raise RuntimeError("first run fails")
        # Clear stop event in case it was set during previous teardown
        self._stop_event.clear()
        self._healthy = True
        self._stop_event.wait()
        self._healthy = False

    def teardown(self) -> None:
        self._stop_event.set()

    def is_healthy(self) -> bool:
        return self._healthy


class TestThreadRunner:
    """Test ThreadRunner class."""

    def test_start_spawns_thread(self):
        """start() spawns a daemon thread."""
        svc = SimpleService()
        runner = ThreadRunner(svc)

        runner.start()
        try:
            time.sleep(0.05)
            assert runner.is_alive()
            assert runner.state == State.STARTING
        finally:
            runner.stop()

    def test_wait_healthy_transitions_to_running(self):
        """wait_healthy() transitions to RUNNING state."""
        svc = SimpleService()
        runner = ThreadRunner(svc)

        runner.start()
        runner.wait_healthy(timeout=5.0)

        assert runner.state == State.RUNNING
        assert runner.is_healthy()

        runner.stop()

    def test_stop_transitions_to_stopped(self):
        """stop() transitions to STOPPED state."""
        svc = SimpleService()
        runner = ThreadRunner(svc)

        runner.start()
        runner.wait_healthy(timeout=5.0)
        runner.stop()

        assert runner.state == State.STOPPED
        assert not runner.is_alive()

    def test_exception_captured(self):
        """Exception from execute() is captured."""
        svc = FailingService()
        runner = ThreadRunner(svc)

        runner.start()
        time.sleep(0.1)

        assert not runner.is_alive()
        assert runner.exception is not None
        assert "intentional failure" in str(runner.exception)

    def test_state_hooks_called(self):
        """State change hooks are called."""
        transitions = []

        def hook(name, old, new):
            transitions.append((name, old, new))

        svc = SimpleService()
        runner = ThreadRunner(svc)
        runner.on_state_change(hook)

        runner.start()
        runner.wait_healthy(timeout=5.0)
        runner.stop()

        assert (svc.name, State.CREATED, State.INITD) in transitions
        assert (svc.name, State.INITD, State.STARTING) in transitions
        assert (svc.name, State.STARTING, State.RUNNING) in transitions
        assert (svc.name, State.RUNNING, State.STOPPING) in transitions
        assert (svc.name, State.STOPPING, State.STOPPED) in transitions

    def test_hook_exception_ignored(self):
        """Exception in hook is ignored."""

        def bad_hook(name, old, new):
            raise RuntimeError("hook failed")

        svc = SimpleService()
        runner = ThreadRunner(svc)
        runner.on_state_change(bad_hook)

        # Should not raise despite bad hook
        runner.start()
        runner.wait_healthy(timeout=5.0)
        runner.stop()

        assert runner.state == State.STOPPED

    def test_restart_policy(self):
        """Restart policy triggers restart on failure."""
        svc = FailOnFirstExecute()
        policy = RestartPolicy(max_retries=3, backoff=0.01)
        runner = ThreadRunner(svc, policy)

        runner.start()
        with pytest.raises(RunError):
            runner.wait_healthy(timeout=0.5)

        assert runner.state == State.FAILED

        # check() should trigger restart
        result = runner.check()
        assert result is True
        assert runner.state == State.RUNNING

        runner.stop()

    def test_health_timeout_raises(self):
        """wait_healthy() raises HealthTimeoutError on timeout."""

        class NeverHealthy(Service):
            @property
            def name(self) -> str:
                return "never-healthy"

            def __init__(self) -> None:
                self._stop = threading.Event()

            def execute(self) -> None:
                self._stop.wait()

            def teardown(self) -> None:
                self._stop.set()

            def is_healthy(self) -> bool:
                return False

        svc = NeverHealthy()
        runner = ThreadRunner(svc)

        runner.start()
        with pytest.raises(HealthTimeoutError):
            runner.wait_healthy(timeout=0.1)

        assert runner.state == State.FAILED
        runner.stop()

    def test_exit_without_exception(self):
        """Service that exits cleanly without exception."""

        class QuietExit(Service):
            @property
            def name(self) -> str:
                return "quiet-exit"

            def execute(self) -> None:
                pass  # Exits immediately

        svc = QuietExit()
        runner = ThreadRunner(svc)

        runner.start()
        with pytest.raises(RunError, match="exited during startup"):
            runner.wait_healthy(timeout=0.5)

        assert runner.state == State.FAILED


class TestRunnerRestart:
    """Test restart functionality."""

    def test_max_retries_exhausted(self):
        """Restart stops after max_retries."""

        class AlwaysFails(Service):
            def __init__(self) -> None:
                self._lg = MagicMock()

            @property
            def name(self) -> str:
                return "always-fails"

            def execute(self) -> None:
                raise RuntimeError("always fails")

        policy = RestartPolicy(max_retries=2, backoff=0.01)
        service = AlwaysFails()
        runner = ThreadRunner(service, policy)

        runner.start()
        with pytest.raises(RunError):
            runner.wait_healthy(timeout=0.1)

        # First restart attempt
        runner.check()
        assert runner.retries == 1

        # Second restart attempt
        runner.check()
        assert runner.retries == 2

        # Third attempt should not restart (max reached)
        result = runner.check()
        assert result is False

        # Each failed restart is logged, not dropped
        failures = [
            c
            for c in service._lg.warning.call_args_list
            if c.args == ("restart failed",)
        ]
        assert len(failures) == 2

    def test_restart_disabled(self):
        """Restart can be disabled."""

        class FailsOnce(Service):
            @property
            def name(self) -> str:
                return "fails-once"

            def execute(self) -> None:
                raise RuntimeError("fails")

        policy = RestartPolicy(restart_on_failure=False)
        runner = ThreadRunner(FailsOnce(), policy)

        runner.start()
        with pytest.raises(RunError):
            runner.wait_healthy(timeout=0.1)

        result = runner.check()
        assert result is False


class TestScheduledService:
    """Test ScheduledService with ThreadRunner."""

    def test_tick_called_repeatedly(self):
        """tick() is called repeatedly."""
        tick_count = 0
        two_ticks = threading.Event()

        class CountingService(ScheduledService):
            interval = 0.2

            @property
            def name(self) -> str:
                return "counter"

            def tick(self) -> None:
                nonlocal tick_count
                tick_count += 1
                if tick_count == 2:
                    two_ticks.set()

            def is_healthy(self) -> bool:
                return tick_count > 0

        svc = CountingService()
        runner = ThreadRunner(svc)

        runner.start()
        runner.wait_healthy(timeout=5.0)
        assert two_ticks.wait(timeout=5.0)
        runner.stop()

        assert tick_count >= 2
