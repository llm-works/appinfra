# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Integration tests for ProcessRunner with real subprocesses."""

import multiprocessing as mp
import threading
import time

import pytest

from appinfra.app.fastapi.runtime.process import ProcessRunner
from appinfra.log import Logger
from appinfra.service import (
    InvalidTransitionError,
    RunError,
    Service,
    State,
    StopToken,
)
from tests.helpers.fork import forks_in_xdist_worker


class SimpleProcessService(Service):
    """Simple service for multiprocessing tests."""

    def __init__(self, lg: Logger, name: str = "mp-test") -> None:
        self._lg = lg
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def run(self) -> None:
        self._lg.info("service started")
        self.stopping.wait()
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


class WaitsOnTokenFromSetup(SimpleProcessService):
    """run() waits on a token setup() took from self.stopping, the token itself
    or a child of it; setup() runs in the parent, before the subprocess starts.
    Module level so the spawn start method can pickle it."""

    def __init__(self, lg: Logger, derive: bool) -> None:
        super().__init__(lg, name="token-from-setup")
        self.derive = derive
        self.work: StopToken | None = None

    def setup(self) -> None:
        self.work = self.stopping.child() if self.derive else self.stopping

    def run(self) -> None:
        assert self.work is not None
        self.work.wait()


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

    @pytest.mark.skipif(
        "fork" not in mp.get_all_start_methods(), reason="needs the fork start method"
    )
    def test_forked_child_stops_once_the_parent_writer_closes(self, lg):
        """The stop pipe reaches EOF when the parent's writer closes, as when the
        parent dies: a forked child closes the copy of the writer it inherits,
        so nothing else holds the pipe open and its token stops."""
        runner = ProcessRunner(SimpleProcessService(lg), start_method="fork")
        runner.start()
        runner.wait_healthy(timeout=5.0)
        process = runner.process
        assert process is not None
        try:
            runner._stop_writer.close()
            process.join(timeout=10.0)  # the deadline is the failure path
            assert not process.is_alive()
            assert process.exitcode == 0
        finally:
            runner.stop()

    @pytest.mark.parametrize("method", [None, "spawn"], ids=["default", "spawn"])
    @pytest.mark.parametrize("derive", [False, True], ids=["alias", "child"])
    def test_stop_reaches_a_token_setup_took(self, lg, derive, method):
        """stop() ends a run() that waits on a token setup() kept, gracefully:
        exit code 0, not the terminate() that follows a stop_timeout. Under
        spawn the token reaches the child pickled, not copied by a fork."""
        runner = ProcessRunner(
            WaitsOnTokenFromSetup(lg, derive), stop_timeout=5.0, start_method=method
        )
        runner.start()
        runner.wait_healthy(timeout=10.0)
        process = runner.process
        assert process is not None
        runner.stop()
        assert process.exitcode == 0

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
        STOPPED for a child start() is about to spawn; with no time to wait it
        returns, and the start, once it has spawned the child, stops it and
        raises: the stop is not lost."""
        runner = ProcessRunner(SimpleProcessService(lg, name="held-start"))
        starting, release = threading.Event(), threading.Event()
        launch = runner._launch
        errors: list[Exception] = []

        def held_launch() -> None:
            starting.set()
            release.wait()  # holds start() STARTING until the driver's finally
            launch()

        def start() -> None:
            try:
                runner.start()
            except RunError as e:
                errors.append(e)

        runner._launch = held_launch  # type: ignore[method-assign]
        first = threading.Thread(target=start)
        first.start()
        try:
            assert starting.wait(5.0)
            runner.stop(timeout=0)  # the start is in progress: no time to wait
            assert runner.state == State.STARTING
        finally:
            release.set()
            first.join(10.0)

        assert [str(e) for e in errors] == ["held-start: stopped during startup"], (
            errors
        )
        assert runner.state == State.STOPPED
        assert not runner.is_alive()

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
