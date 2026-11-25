# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for runners that run a service on a thread."""

import threading
import time
from unittest.mock import MagicMock

import pytest

from appinfra.service import (
    HealthTimeoutError,
    InvalidTransitionError,
    RestartPolicy,
    RunError,
    ScheduledService,
    Service,
    State,
    StopToken,
    ThreadRunner,
)
from tests.helpers.service.runner import SimpleService


class FailingService(Service):
    """Service that raises during run()."""

    def __init__(self) -> None:
        self._lg = MagicMock()

    @property
    def name(self) -> str:
        return "failing"

    def run(self) -> None:
        raise RuntimeError("intentional failure")


class FailOnFirstRun(Service):
    """Service that fails on first run but succeeds on retry."""

    def __init__(self) -> None:
        self._lg = MagicMock()
        self._runs = 0
        self._stop_event = threading.Event()
        self._healthy = False

    @property
    def name(self) -> str:
        return "flaky"

    def run(self) -> None:
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


class SlowSetup(SimpleService):
    """Counts setup() calls; each blocks until released."""

    def __init__(self) -> None:
        super().__init__("slow-setup")
        self.setups = 0
        self.in_setup = threading.Event()
        self.release = threading.Event()

    def setup(self) -> None:
        self.setups += 1
        self.in_setup.set()
        self.release.wait(5.0)


class FailsFirstRun(SlowSetup):
    """Its first run() fails; later runs park like SimpleService. Counts
    teardown() calls."""

    def __init__(self) -> None:
        super().__init__()
        self.runs = 0
        self.teardowns = 0

    def run(self) -> None:
        self.runs += 1
        if self.runs == 1:
            raise RuntimeError("first run fails")
        super().run()

    def teardown(self) -> None:
        self.teardowns += 1
        super().teardown()


class OutlivesStop(Service):
    """run() ignores teardown() and returns only once released."""

    def __init__(self) -> None:
        self._lg = MagicMock()
        self.release = threading.Event()

    @property
    def name(self) -> str:
        return "outlives-stop"

    def run(self) -> None:
        self.release.wait(5.0)


class DerivesThenFails(Service):
    """run() derives a token for its work from its own, then fails."""

    def __init__(self) -> None:
        self._lg = MagicMock()
        self.work: StopToken | None = None
        self.derived = threading.Event()

    @property
    def name(self) -> str:
        return "derives-then-fails"

    def run(self) -> None:
        self.work = self.stopping.child()
        self.derived.set()
        raise RuntimeError("run() fails")


class TestThreadRunner:
    """Test ThreadRunner class."""

    def test_wait_healthy_waits_for_a_start_in_progress(self):
        """Between setup() and launching its thread, a runner is STARTING but
        not alive yet: a wait_healthy() on another thread then waits for the
        start() to return instead of taking the service for one that exited."""
        runner = ThreadRunner(SimpleService())
        at_starting, release = threading.Event(), threading.Event()

        def hold(name: str, old: State, new: State) -> None:
            if new == State.STARTING:  # on the starting thread, before the launch
                at_starting.set()
                release.wait(5.0)

        runner.on_state_change(hold)
        starter = threading.Thread(target=runner.start)
        starter.start()
        assert at_starting.wait(5.0)
        errors: list[BaseException] = []

        def wait() -> None:
            try:
                runner.wait_healthy(timeout=5.0)
            except Exception as e:
                errors.append(e)

        waiter = threading.Thread(target=wait)
        waiter.start()
        # Until it waits for the start() or has given up; the deadline is the
        # failure path. Private: the condition a wait for start() creates
        deadline = time.monotonic() + 5.0
        while waiter.is_alive() and runner._start_done is None:
            assert time.monotonic() < deadline
            time.sleep(0.01)
        release.set()
        starter.join(5.0)
        waiter.join(5.0)

        assert errors == []
        assert runner.state == State.RUNNING
        runner.stop()

    def test_a_run_that_ends_stops_its_token(self):
        """A run that ends without a stop(), here by failing, stops its token,
        so work derived from it ends with the run instead of outliving it."""
        svc = DerivesThenFails()
        ThreadRunner(svc).start()
        assert svc.derived.wait(timeout=5.0)
        assert svc.work is not None
        assert svc.work.wait(timeout=5.0)  # the deadline is the failure path

    def test_stop_during_a_start_from_failed_leaves_the_start_alone(self):
        """A stop() that lands while a start() from FAILED is in setup() does
        not tear the service down under it; with no time to wait it returns,
        and the start completes."""
        svc = FailsFirstRun()
        runner = ThreadRunner(svc)
        failed = threading.Event()
        runner.on_state_change(
            lambda _name, _old, new: failed.set() if new == State.FAILED else None
        )
        svc.release.set()
        runner.start()
        assert failed.wait(5.0)
        svc.in_setup.clear()
        svc.release.clear()
        errors: list[BaseException] = []

        def start() -> None:
            try:
                runner.start()
            except BaseException as e:
                errors.append(e)

        first = threading.Thread(target=start)
        first.start()
        assert svc.in_setup.wait(5.0)

        runner.stop(timeout=0)  # the start is in progress: no time to wait for it

        assert svc.teardowns == 0
        assert runner.state == State.FAILED
        svc.release.set()
        first.join(5.0)
        assert errors == []
        runner.wait_healthy(timeout=5.0)
        runner.stop()
        assert runner.state == State.STOPPED

    def test_thread_ending_after_stop_gave_up_stops_the_runner(self):
        """A thread that outlives stop()'s join still moves the runner to
        STOPPED when it ends, so the runner can start again."""
        svc = OutlivesStop()
        runner = ThreadRunner(svc)
        stopped = threading.Event()
        runner.on_state_change(
            lambda _name, _old, new: stopped.set() if new == State.STOPPED else None
        )
        runner.start()
        runner.stop(timeout=0)
        assert runner.state == State.STOPPING

        svc.release.set()

        assert stopped.wait(5.0)
        runner.start()
        runner.stop()
        assert runner.state == State.STOPPED

    def test_start_and_stop_from_a_state_hook_are_refused(self):
        """A state hook, on the caller's thread or the service thread, cannot
        start or stop its own runner; the transitions go on as without it."""
        runner = ThreadRunner(SimpleService())
        refused: list[tuple[State, str]] = []

        def drives(_name: str, _old: State, new: State) -> None:
            for call in (runner.start, runner.stop):
                try:
                    call()
                except RuntimeError:
                    refused.append((new, call.__name__))

        runner.on_state_change(drives)
        runner.start()
        runner.wait_healthy(timeout=5.0)
        runner.stop()

        steps = [
            State.INITD,
            State.STARTING,
            State.RUNNING,
            State.STOPPING,
            State.STOPPED,  # on the service thread or in stop(), whichever is first
        ]
        assert refused == [
            (state, call) for state in steps for call in ("start", "stop")
        ]
        assert runner.state == State.STOPPED
        assert not runner.is_alive()

    def test_start_while_another_start_runs_setup_is_refused(self):
        """A start() that lands while another start() is in setup() fails
        before calling setup() again."""
        svc = SlowSetup()
        runner = ThreadRunner(svc)
        first = threading.Thread(target=runner.start)
        first.start()
        try:
            assert svc.in_setup.wait(5.0)

            with pytest.raises(InvalidTransitionError):
                runner.start()
        finally:
            svc.release.set()
            first.join(5.0)
            runner.stop()

        assert svc.setups == 1

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
        """Exception from run() is captured."""
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
        svc = FailOnFirstRun()
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

            def run(self) -> None:
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

            def run(self) -> None:
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

            def run(self) -> None:
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

            def run(self) -> None:
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
        # The runner ends the loop: the service has no teardown() of its own
        assert runner.state == State.STOPPED

    def test_teardown_runs_on_the_service_thread_after_the_last_tick(self):
        """stop() ends the loop, then teardown() runs on the thread that ticked."""
        ticked = threading.Event()
        threads: dict[str, str] = {}

        class Ticker(ScheduledService):
            interval = 5.0

            @property
            def name(self) -> str:
                return "ticker"

            def tick(self) -> None:
                threads["tick"] = threading.current_thread().name
                ticked.set()

            def teardown(self) -> None:
                threads["teardown"] = threading.current_thread().name

        runner = ThreadRunner(Ticker())
        runner.start()
        runner.wait_healthy(timeout=5.0)
        assert ticked.wait(timeout=5.0)

        runner.stop()

        assert threads == {"tick": "svc-ticker", "teardown": "svc-ticker"}
        assert runner.state == State.STOPPED

    def test_teardown_runs_after_tick_fails(self):
        """A failing tick() ends the loop; teardown() still runs on its thread."""
        torn_down = threading.Event()

        class Boom(ScheduledService):
            @property
            def name(self) -> str:
                return "boom"

            def tick(self) -> None:
                raise RuntimeError("tick failed")

            def teardown(self) -> None:
                torn_down.set()

        runner = ThreadRunner(Boom())
        runner.start()

        assert torn_down.wait(timeout=5.0)
        assert "tick failed" in str(runner.exception)
