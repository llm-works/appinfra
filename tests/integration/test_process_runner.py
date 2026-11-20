# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Integration tests for ProcessRunner with real subprocesses."""

import threading
import time
from multiprocessing.synchronize import Event as MPEvent

import pytest

from appinfra.log import Logger
from appinfra.service import InvalidTransitionError, ProcessRunner, Service, State
from tests.helpers.fork import forks_in_xdist_worker


class SimpleProcessService(Service):
    """Simple service for multiprocessing tests."""

    def __init__(self, lg: Logger, name: str = "mp-test") -> None:
        self._lg = lg
        self._name = name
        self._shutdown_event: MPEvent | None = None  # injected by ProcessRunner

    @property
    def name(self) -> str:
        return self._name

    def run(self) -> None:
        self._lg.info("service started")
        assert self._shutdown_event is not None
        self._shutdown_event.wait()
        self._lg.info("service stopping")

    def is_healthy(self) -> bool:
        return True


class CountsSetup(SimpleProcessService):
    """Counts setup() calls; setup() runs in the parent, in start(). Module
    level so the spawn start method can pickle it."""

    def __init__(self, lg: Logger) -> None:
        super().__init__(lg, name="counts-setup")
        self.setups = 0

    def setup(self) -> None:
        self.setups += 1


@forks_in_xdist_worker
class TestProcessRunnerIntegration:
    """Integration tests for ProcessRunner with real subprocesses."""

    @pytest.fixture
    def lg(self):
        """Create a logger for tests."""
        return Logger(name="test")

    def test_full_lifecycle(self, lg):
        """Test full start -> healthy -> stop lifecycle."""
        svc = SimpleProcessService(lg)
        runner = ProcessRunner(svc)

        runner.start()
        runner.wait_healthy(timeout=5.0)

        assert runner.state == State.RUNNING
        assert runner.is_alive()
        assert runner.pid is not None

        runner.stop()

        assert runner.state == State.STOPPED
        assert not runner.is_alive()

    def test_start_while_running_is_refused_before_setup(self, lg):
        """A second start() fails on the state check, without running setup()."""
        svc = CountsSetup(lg)
        runner = ProcessRunner(svc)
        runner.start()
        try:
            runner.wait_healthy(timeout=5.0)

            with pytest.raises(InvalidTransitionError):
                runner.start()
        finally:
            runner.stop()

        assert svc.setups == 1

    def test_stop_during_start_leaves_no_child_behind(self, lg):
        """A stop() that lands between STARTING and the spawn does not report
        STOPPED for a child start() is about to spawn; with no time to wait
        it returns, and a later stop() ends the child."""
        runner = ProcessRunner(SimpleProcessService(lg, name="held-start"))
        starting, release = threading.Event(), threading.Event()

        def hold(_name: str, _old: State, new: State) -> None:
            if new == State.STARTING and not starting.is_set():
                starting.set()
                release.wait(5.0)  # holds start() before it spawns

        runner.on_state_change(hold)
        first = threading.Thread(target=runner.start)
        first.start()
        try:
            assert starting.wait(5.0)
            runner.stop(timeout=0)  # the start is in progress: no time to wait
            assert runner.state == State.STARTING
        finally:
            release.set()
            first.join(5.0)

        runner.wait_healthy(timeout=5.0)
        runner.stop()
        assert runner.state == State.STOPPED
        assert not runner.is_alive()

    def test_stop_from_a_starting_hook_is_refused(self, lg):
        """A stop() from a STARTING hook, on the thread running start(), raises
        in the hook; the start goes on and spawns the child."""
        runner = ProcessRunner(SimpleProcessService(lg, name="hook-stop"))
        refused: list[RuntimeError] = []

        def stops(_name: str, _old: State, new: State) -> None:
            if new == State.STARTING:
                try:
                    runner.stop()
                except RuntimeError as e:
                    refused.append(e)

        runner.on_state_change(stops)
        runner.start()
        try:
            assert len(refused) == 1
            assert runner.state == State.STARTING
            assert runner.is_alive()
        finally:
            runner.stop()
        assert runner.state == State.STOPPED

    def test_subprocess_logging(self, lg):
        """Test that subprocess logs are captured via queue."""
        import logging

        # Use a custom handler to capture logs (LogQueueListener dispatches to handlers,
        # not to logger methods, so spying on lg.info() won't work)
        logged_messages: list[str] = []

        class CaptureHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                logged_messages.append(record.getMessage())

        handler = CaptureHandler()
        lg.addHandler(handler)

        try:
            svc = SimpleProcessService(lg, name="log-test")
            runner = ProcessRunner(svc)

            runner.start()
            runner.wait_healthy(timeout=5.0)

            # Give subprocess time to log
            time.sleep(0.2)

            runner.stop()

            # Verify log forwarding worked - subprocess should have logged "service started"
            assert runner.state == State.STOPPED
            assert any("started" in msg for msg in logged_messages), (
                f"Expected 'service started' log, got: {logged_messages}"
            )
        finally:
            lg.removeHandler(handler)
