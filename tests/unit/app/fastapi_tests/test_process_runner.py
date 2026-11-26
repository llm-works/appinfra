# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Unit tests for ProcessRunner, the runner the FastAPI server runs uvicorn under."""

import itertools
import queue
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from appinfra.app.fastapi.runtime.process import ProcessRunner
from appinfra.log import Logger
from appinfra.runtime import StopToken
from appinfra.service import (
    AsyncService,
    HealthTimeoutError,
    InvalidTransitionError,
    RestartPolicy,
    RunError,
    Service,
    SetupError,
    State,
)

_PROCESS = "appinfra.app.fastapi.runtime.process"


@contextmanager
def _mock_mp_context() -> Iterator[tuple[MagicMock, MagicMock, MagicMock]]:
    """Patch ProcessRunner's multiprocessing context; yield its Process, Event, Queue.
    Its Pipe gives a pair of mock ends."""
    with patch(f"{_PROCESS}.mp.get_context") as get_context:
        ctx = get_context.return_value
        ctx.Pipe.side_effect = lambda duplex=True: (MagicMock(), MagicMock())
        yield ctx.Process, ctx.Event, ctx.Queue


# Module-level service for ProcessRunner tests (must be picklable)
class MPSimpleService(Service):
    """Simple service for multiprocessing tests."""

    def __init__(self, lg: Logger, name: str = "mp-test") -> None:
        self._lg = lg
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def run(self) -> None:
        self.stopping.wait()

    def is_healthy(self) -> bool:
        return True


class MPSetupFailService(Service):
    """Service that fails during setup. Module-level for ProcessRunner (picklable)."""

    def __init__(self, lg: Logger) -> None:
        self._lg = lg

    @property
    def name(self) -> str:
        return "fail-setup"

    def setup(self) -> None:
        raise SetupError(self.name, "setup failed")

    def run(self) -> None:
        pass


class HookedLock:
    """Stands in for a runner's lock: once armed, its next acquisition is
    preceded, or with *on_release* its next release followed, by *hook*: what
    another thread does in that window."""

    def __init__(
        self,
        runner: ProcessRunner,
        hook: Callable[[], None],
        on_release: bool = False,
    ) -> None:
        self._lock = runner._lock
        self._hook = hook
        self._on_release = on_release
        self._armed = False
        runner._lock = self  # type: ignore[assignment]

    def arm(self, *args: object) -> None:
        self._armed = True

    def _fire(self) -> None:
        if self._armed:
            self._armed = False
            self._hook()

    def __enter__(self) -> None:
        if not self._on_release:
            self._fire()
        self._lock.acquire()

    def __exit__(self, *exc: object) -> None:
        self._lock.release()
        if self._on_release:
            self._fire()

    def acquire(self, *args: Any, **kwargs: Any) -> bool:
        return self._lock.acquire(*args, **kwargs)

    def release(self) -> None:
        self._lock.release()


class TestProcessRunner:
    """Unit tests for ProcessRunner with mocks."""

    @pytest.fixture
    def lg(self):
        """Create a logger for tests."""
        return Logger(name="test")

    def test_start_transitions_states(self, lg):
        """start() transitions through INITD -> STARTING."""
        with (
            _mock_mp_context() as (mock_process, _, _),
            patch(f"{_PROCESS}.LogQueueListener"),
        ):
            mock_process.return_value.is_alive.return_value = True
            mock_process.return_value.pid = 12345

            svc = MPSimpleService(lg)
            runner = ProcessRunner(svc)

            runner.start()

            assert runner.state == State.STARTING
            mock_process.assert_called_once()
            mock_process.return_value.start.assert_called_once()

    def test_stop_not_started(self, lg):
        """stop() on unstarted runner is no-op."""
        svc = MPSimpleService(lg)
        runner = ProcessRunner(svc)

        runner.stop()  # Should not raise
        assert runner.state == State.CREATED

    def test_stop_idempotent(self, lg):
        """stop() is idempotent."""
        svc = MPSimpleService(lg)
        runner = ProcessRunner(svc)
        runner.stop()
        runner.stop()  # Still OK

    def test_is_alive_not_started(self, lg):
        """is_alive() returns False when not started."""
        svc = MPSimpleService(lg)
        runner = ProcessRunner(svc)
        assert not runner.is_alive()

    def test_is_healthy_not_started(self, lg):
        """is_healthy() returns False when not started."""
        svc = MPSimpleService(lg)
        runner = ProcessRunner(svc)
        assert not runner.is_healthy()

    def test_pid_not_started(self, lg):
        """pid is None when not started."""
        svc = MPSimpleService(lg)
        runner = ProcessRunner(svc)
        assert runner.pid is None

    def test_setup_error_transitions_to_failed(self, lg):
        """Setup error transitions to FAILED."""
        svc = MPSetupFailService(lg)
        runner = ProcessRunner(svc)

        with pytest.raises(SetupError):
            runner.start()

        assert runner.state == State.FAILED

    def test_stop_running_process(self, lg):
        """stop() terminates a running process."""
        with (
            _mock_mp_context() as (mock_process, mock_event, _),
            patch(f"{_PROCESS}.LogQueueListener"),
        ):
            mock_process.return_value.is_alive.return_value = False
            mock_event.return_value.set = lambda: None

            svc = MPSimpleService(lg)
            runner = ProcessRunner(svc)
            runner.start()
            runner._transition(State.RUNNING)  # Simulate healthy

            runner.stop()

            assert runner.state == State.STOPPED
            mock_process.return_value.join.assert_called()

    def test_start_failure_after_fork_ends_the_child(self, lg):
        """A failure after the fork terminates the forked child before start() raises."""
        with (
            _mock_mp_context() as (mock_process, _, _),
            patch(f"{_PROCESS}.LogQueueListener") as mock_listener,
        ):
            child = mock_process.return_value
            child.is_alive.return_value = True  # alive until terminated
            child.terminate.side_effect = lambda: setattr(
                child.is_alive, "return_value", False
            )
            mock_listener.return_value.start.side_effect = RuntimeError("no thread")

            runner = ProcessRunner(MPSimpleService(lg))
            with pytest.raises(RunError, match="failed to start: no thread") as e:
                runner.start()
            assert isinstance(e.value.__cause__, RuntimeError)

            child.terminate.assert_called_once()
            child.join.assert_called_once_with(timeout=2.0)
            child.kill.assert_not_called()
            assert runner.state == State.FAILED
            assert runner.process is None  # ended, so the handles are released

    def test_start_failure_kills_a_child_that_ignores_terminate(self, lg):
        """A child still alive after terminate() is killed."""
        with (
            _mock_mp_context() as (mock_process, _, _),
            patch(f"{_PROCESS}.LogQueueListener") as mock_listener,
        ):
            child = mock_process.return_value
            child.is_alive.return_value = True
            mock_listener.return_value.start.side_effect = RuntimeError("no thread")

            runner = ProcessRunner(MPSimpleService(lg))
            with pytest.raises(RunError):
                runner.start()

            child.kill.assert_called_once()
            assert runner.state == State.FAILED
            # Still alive: the handle stays so a later stop() can retry
            assert runner.process is child

    def test_is_alive_when_running(self, lg):
        """is_alive() returns True when process is alive."""
        with (
            _mock_mp_context() as (mock_process, _, _),
            patch(f"{_PROCESS}.LogQueueListener"),
        ):
            mock_process.return_value.is_alive.return_value = True

            svc = MPSimpleService(lg)
            runner = ProcessRunner(svc)
            runner.start()

            assert runner.is_alive()

    def test_is_healthy_when_running(self, lg):
        """is_healthy() returns True when process alive and healthy event set."""
        with (
            _mock_mp_context() as (mock_process, mock_event, _),
            patch(f"{_PROCESS}.LogQueueListener"),
        ):
            mock_process.return_value.is_alive.return_value = True
            mock_event.return_value.is_set.return_value = True

            svc = MPSimpleService(lg)
            runner = ProcessRunner(svc)
            runner.start()

            assert runner.is_healthy()

    def test_pid_when_running(self, lg):
        """pid returns process ID when running."""
        with (
            _mock_mp_context() as (mock_process, _, _),
            patch(f"{_PROCESS}.LogQueueListener"),
        ):
            mock_process.return_value.is_alive.return_value = True
            mock_process.return_value.pid = 12345

            svc = MPSimpleService(lg)
            runner = ProcessRunner(svc)
            runner.start()

            assert runner.pid == 12345

    def test_exit_code_when_stopped(self, lg):
        """exit_code returns code when process stopped."""
        with (
            _mock_mp_context() as (mock_process, _, _),
            patch(f"{_PROCESS}.LogQueueListener"),
        ):
            mock_process.return_value.is_alive.return_value = False
            mock_process.return_value.exitcode = 0

            svc = MPSimpleService(lg)
            runner = ProcessRunner(svc)
            runner.start()

            assert runner.exit_code == 0

    def test_a_new_run_reports_its_own_exception(self, lg):
        """The first run's exception, read and kept, does not stand for the
        next run's: a run's primitives start it afresh."""
        runner = ProcessRunner(MPSimpleService(lg))
        runner._exception = RuntimeError("first run")
        ctx = MagicMock()
        second = RuntimeError("second run")
        queued: list[BaseException] = [second]  # returned, not raised, by get_nowait

        def get_nowait() -> BaseException:
            if not queued:
                raise queue.Empty()
            return queued.pop()

        ctx.Queue.return_value.get_nowait.side_effect = get_nowait
        ctx.Pipe.return_value = (MagicMock(), MagicMock())

        runner._create_ipc_primitives(ctx)

        assert runner.exception is second

    def test_an_old_runs_exception_is_not_published_into_a_new_run(self, lg):
        """A reader drains run A's queue; as it takes A's exception, run B
        starts with a queue of its own. B reports no exception of A's."""
        runner = ProcessRunner(MPSimpleService(lg))
        first = RuntimeError("run A")
        drained: list[BaseException] = [first]

        def get_nowait() -> BaseException:
            if not drained:
                raise queue.Empty()
            exc = drained.pop()
            runner._error_queue = MagicMock()  # run B's, empty, from its start
            runner._error_queue.get_nowait.side_effect = queue.Empty()
            runner._exception = None
            return exc

        runner._error_queue = MagicMock()
        runner._error_queue.get_nowait.side_effect = get_nowait

        assert runner.exception is None

    def test_exception_from_queue(self, lg):
        """exception property reads from error queue."""
        from queue import Empty

        with (
            _mock_mp_context() as (_, _, mock_queue_cls),
            patch(f"{_PROCESS}.LogQueueListener"),
        ):
            # Create separate mocks for log queue and error queue
            log_queue_mock = MagicMock()
            error_queue_mock = MagicMock()
            mock_queue_cls.side_effect = [log_queue_mock, error_queue_mock]

            # Setup error queue: return exception first, then raise Empty
            # (side_effect with exception instances raises them, so use a list
            # with the value to return, then a callable that raises)
            test_error = RuntimeError("test error")
            call_count = 0

            def get_nowait_effect():
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return test_error  # Return the exception object
                raise Empty()  # Then raise Empty

            error_queue_mock.get_nowait.side_effect = get_nowait_effect

            svc = MPSimpleService(lg)
            runner = ProcessRunner(svc)
            runner.start()

            exc = runner.exception
            assert exc is test_error

    def test_stop_with_stubborn_process(self, lg):
        """stop() kills a process that won't terminate."""
        with (
            _mock_mp_context() as (mock_process, mock_event, _),
            patch(f"{_PROCESS}.LogQueueListener"),
        ):
            # Process stays alive through terminate, dies on kill()
            # Calls: 1) after join (alive->terminate), 2) after terminate (alive->kill), 3) final check (dead)
            mock_process.return_value.is_alive.side_effect = [True, True, False]
            mock_event.return_value.set = lambda: None

            svc = MPSimpleService(lg)
            runner = ProcessRunner(svc)
            runner.start()
            runner._transition(State.RUNNING)

            runner.stop()

            assert runner.state == State.STOPPED
            mock_process.return_value.terminate.assert_called()
            mock_process.return_value.kill.assert_called()

    def test_a_later_stop_finishes_a_stop_the_child_outlived(self, lg):
        """A child alive even after kill() leaves the runner STOPPING with its
        handles; once it has died, the next stop() reaps it and ends STOPPED."""
        with (
            _mock_mp_context() as (mock_process, _, _),
            patch(f"{_PROCESS}.LogQueueListener"),
        ):
            # Alive through the first stop's join, terminate and kill; dead after
            alive = itertools.chain([True, True, True], itertools.repeat(False))
            mock_process.return_value.is_alive.side_effect = lambda: next(alive)
            runner = ProcessRunner(MPSimpleService(lg))
            runner.start()
            runner._transition(State.RUNNING)

            runner.stop()
            assert runner.state == State.STOPPING
            runner.stop()

            assert runner.state == State.STOPPED
            assert runner._process is None

    def test_a_failed_setup_stops_the_work_it_started(self, lg):
        """setup() derives a token for its work, then raises: that work is told
        to stop, and a retry gets a token of its own."""
        derived: list[StopToken] = []

        class FailsAfterDeriving(MPSimpleService):
            def setup(self) -> None:
                derived.append(self.stopping.child())
                raise RuntimeError("no database")

        runner = ProcessRunner(FailsAfterDeriving(lg))
        first = runner.service.stopping
        with pytest.raises(SetupError):
            runner.start()

        assert derived[0].is_set()
        with pytest.raises(SetupError):
            runner.start()
        assert runner.service.stopping is not first

    def test_a_stop_landing_as_the_start_releases_its_claim_is_not_lost(self, lg):
        """A stop(timeout=0) from another thread lands after the launch, as the
        start releases its claim: the start either sees it and stops its child,
        or a later stop() finds no start in progress. It is never lost."""
        runner = ProcessRunner(MPSimpleService(lg))

        def stopped() -> None:
            runner._run += 1  # a stop(timeout=0)'s effect

        hook = HookedLock(runner, stopped)
        with (
            patch.object(runner, "_launch", side_effect=hook.arm),
            patch.object(runner, "_stop_process") as stop_process,
            pytest.raises(RunError, match="stopped during startup"),
        ):
            runner.start()
        stop_process.assert_called_once()

    def test_a_retry_releases_the_failed_runs_handles(self, lg):
        """A wait_healthy() that timed out leaves the run FAILED with its
        handles; its child has died since. A start() releases those handles
        before the new run takes its own: no listener thread is left behind."""
        runner = ProcessRunner(MPSimpleService(lg))
        runner._state = State.FAILED
        runner._process = MagicMock()
        runner._process.is_alive.return_value = False
        old_listener = runner._log_listener = MagicMock()
        old_errors = runner._error_queue = MagicMock()

        with (
            _mock_mp_context() as (mock_process, _, _),
            patch(f"{_PROCESS}.LogQueueListener"),
        ):
            mock_process.return_value.is_alive.return_value = True
            runner.start()

        old_listener.stop.assert_called_once()
        old_errors.close.assert_called_once()

    def test_a_failed_launch_stops_the_work_setup_started(self, lg):
        """setup() succeeded and derived a token for its work; the launch then
        fails: that work is told to stop, as after a failed setup()."""
        derived: list[StopToken] = []

        class DerivesInSetup(MPSimpleService):
            def setup(self) -> None:
                derived.append(self.stopping.child())

        with (
            _mock_mp_context() as (mock_process, _, _),
            patch(f"{_PROCESS}.LogQueueListener") as mock_listener,
        ):
            mock_process.return_value.is_alive.return_value = False
            mock_listener.return_value.start.side_effect = RuntimeError("no thread")
            runner = ProcessRunner(DerivesInSetup(lg))
            with pytest.raises(RunError, match="failed to start"):
                runner.start()

        assert derived[0].is_set()

    def test_a_stop_from_setup_does_not_wait_for_its_own_start(self):
        """setup() stops its runner: the start in progress is its own thread's,
        so the stop takes effect without waiting for it, and start() raises
        once its child is spawned."""

        class StopsInSetup(MPSimpleService):
            def setup(self) -> None:
                runner.stop(timeout=5.0)

        lg = MagicMock()
        with (
            _mock_mp_context() as (mock_process, _, _),
            patch(f"{_PROCESS}.LogQueueListener"),
        ):
            mock_process.return_value.is_alive.return_value = False
            runner = ProcessRunner(StopsInSetup(lg))
            with pytest.raises(RunError, match="stopped during startup"):
                runner.start()

        waited = [c for c in lg.warning.call_args_list if "waited" in c.args[0]]
        assert waited == []

    def test_an_async_service_is_refused(self, lg):
        """Its run() would return an unawaited coroutine in the subprocess."""

        class Parked(AsyncService):
            def __init__(self) -> None:
                self._lg = lg

            @property
            def name(self) -> str:
                return "parked"

            async def run(self) -> None:
                raise AssertionError("never run")

        with pytest.raises(TypeError, match="cannot run in a process"):
            ProcessRunner(Parked())

    def test_a_failed_runner_with_a_live_child_does_not_start_again(self, lg):
        """A FAILED runner whose child still runs, as after a wait_healthy() that
        timed out, needs stop() first: a start() would replace the handles of a
        child nothing could stop then."""
        runner = ProcessRunner(MPSimpleService(lg))
        runner._state = State.FAILED
        runner._process = MagicMock()
        runner._process.is_alive.return_value = True

        with pytest.raises(InvalidTransitionError):
            runner.start()
        assert runner._start_thread is None

    def test_a_failed_runner_whose_child_ended_starts_again(self, lg):
        runner = ProcessRunner(MPSimpleService(lg))
        runner._state = State.FAILED
        runner._process = MagicMock()
        runner._process.is_alive.return_value = False

        runner._claim_start()  # no InvalidTransitionError
        assert runner._start_thread is not None

    def test_a_healthy_run_is_running_for_its_waiter(self, lg):
        runner = ProcessRunner(MPSimpleService(lg))
        runner._state = State.STARTING
        with (
            patch.object(runner, "is_alive", return_value=True),
            patch.object(runner, "is_healthy", return_value=True),
        ):
            runner.wait_healthy(timeout=5.0)
        assert runner.state == State.RUNNING

    def test_a_waiter_does_not_mark_a_later_run_running(self, lg):
        """The run waited for was stopped and another started between its
        health check and the transition: the new run, not yet healthy, stays
        STARTING and the waiter learns its run is gone."""
        runner = ProcessRunner(MPSimpleService(lg))
        runner._state = State.STARTING

        def healthy_then_replaced() -> bool:
            runner._run += 1  # stop() and start() of another run, on another thread
            return True

        with (
            patch.object(runner, "is_alive", return_value=True),
            patch.object(runner, "is_healthy", side_effect=healthy_then_replaced),
            pytest.raises(RunError, match="stopped during startup"),
        ):
            runner.wait_healthy(timeout=5.0)
        assert runner.state == State.STARTING

    def test_a_waiter_seeing_its_run_exit_does_not_fail_a_later_run(self, lg):
        """The waiter sees its run's child gone; before it settles that exit,
        the run is stopped and another started. The new run stays STARTING,
        and the waiter learns its run was stopped."""
        runner = ProcessRunner(MPSimpleService(lg))
        runner._state = State.STARTING

        def gone_then_replaced() -> bool:
            runner._run += 1  # stop() and start() on another thread
            return False

        with (
            patch.object(runner, "is_alive", side_effect=gone_then_replaced),
            pytest.raises(RunError, match="stopped during startup"),
        ):
            runner.wait_healthy(timeout=5.0)
        assert runner.state == State.STARTING

    def test_a_waiter_takes_its_run_with_the_start_it_waited_for(self, lg):
        """Right after the waiter sees no start in progress, a stop() ends the
        run and a start() claims another: the waiter's run is the one it saw,
        so it learns its run was stopped instead of waiting on the new one."""
        runner = ProcessRunner(MPSimpleService(lg))
        runner._state = State.STARTING

        def stopped_and_started() -> None:
            runner._run += 1

        hook = HookedLock(runner, stopped_and_started, on_release=True)
        hook.arm()
        with (
            patch.object(runner, "is_alive", return_value=True),
            patch.object(runner, "is_healthy", return_value=True),
            pytest.raises(RunError, match="stopped during startup"),
        ):
            runner.wait_healthy(timeout=5.0)

    def test_a_waiter_timing_out_does_not_fail_a_run_another_saw_healthy(self, lg):
        """Two waiters on one run: the one with the shorter timeout sees it
        unhealthy, and before its deadline expires the other marks it RUNNING.
        The first raises its timeout; the run stays RUNNING."""
        runner = ProcessRunner(MPSimpleService(lg))
        runner._state = State.STARTING

        def healthy_for_the_other_waiter() -> bool:
            runner._state = State.RUNNING  # the other waiter's promotion
            return False

        clock = itertools.chain([0.0, 0.0], itertools.repeat(10.0))
        with (
            patch(f"{_PROCESS}.time.monotonic", side_effect=lambda: next(clock)),
            patch(f"{_PROCESS}.time.sleep"),
            patch.object(runner, "is_alive", return_value=True),
            patch.object(
                runner, "is_healthy", side_effect=healthy_for_the_other_waiter
            ),
            pytest.raises(HealthTimeoutError),
        ):
            runner.wait_healthy(timeout=5.0)
        assert runner.state == State.RUNNING

    def test_a_waiter_timing_out_does_not_fail_a_later_run(self, lg):
        runner = ProcessRunner(MPSimpleService(lg))
        runner._state = State.STARTING

        def replaced() -> bool:
            runner._run += 1
            return False

        # A fake clock: one check within the timeout, then past it
        clock = itertools.chain([0.0, 0.0], itertools.repeat(10.0))
        with (
            patch(f"{_PROCESS}.time.monotonic", side_effect=lambda: next(clock)),
            patch(f"{_PROCESS}.time.sleep"),
            patch.object(runner, "is_alive", return_value=True),
            patch.object(runner, "is_healthy", side_effect=replaced),
            pytest.raises(RunError, match="stopped during startup"),
        ):
            runner.wait_healthy(timeout=5.0)
        assert runner.state == State.STARTING

    def test_a_stop_between_the_restart_cleanup_and_its_start_cancels_it(self, lg):
        """stop() lands after the restart stopped the failed child, which leaves
        the runner STOPPED, and before the restart's start(): the restart
        launches nothing once stop() has returned."""
        runner = ProcessRunner(MPSimpleService(lg), RestartPolicy(backoff=0.0))
        runner._state = State.FAILED

        def cleaned_up_then_stopped(run: int) -> None:
            runner._state = State.STOPPED
            runner.stop()

        with (
            patch.object(runner, "_stop_for_restart", cleaned_up_then_stopped),
            patch.object(runner, "_launch") as launch,
        ):
            assert runner._maybe_restart() is False
        launch.assert_not_called()
        assert runner.state == State.STOPPED

    def test_a_restart_no_stop_interrupts_starts_again(self, lg):
        runner = ProcessRunner(MPSimpleService(lg), RestartPolicy(backoff=0.0))
        runner._state = State.FAILED

        def cleaned_up(run: int) -> None:
            runner._state = State.STOPPED

        with (
            patch.object(runner, "_stop_for_restart", cleaned_up),
            patch.object(runner, "_launch") as launch,
            patch.object(runner, "wait_healthy"),
        ):
            assert runner._maybe_restart() is True
        launch.assert_called_once()

    def test_exit_code_not_started(self, lg):
        """exit_code returns None when not started."""
        svc = MPSimpleService(lg)
        runner = ProcessRunner(svc)
        assert runner.exit_code is None

    @pytest.mark.parametrize(
        ("exitcode", "state"), [(3, State.FAILED), (0, State.DONE)]
    )
    def test_monitor_records_an_exit_right_after_check(self, lg, exitcode, state):
        """A process that dies after check() saw it healthy ends the monitor in its
        end state, not RUNNING, when no restart can follow."""
        runner = ProcessRunner(
            MPSimpleService(lg), RestartPolicy(restart_on_failure=False)
        )
        runner._state = State.RUNNING
        runner._process = MagicMock(exitcode=exitcode)
        # Alive for the clean-exit test and inside check(), dead from then on
        alive = itertools.chain([True, True], itertools.repeat(False))
        with (
            patch.object(runner, "is_alive", side_effect=lambda: next(alive)),
            patch.object(runner, "is_healthy", return_value=True),
        ):
            runner._monitor_loop(interval=0)

        assert runner.state == state

    def test_a_clean_exit_releases_the_log_listener_and_queues(self, lg):
        """A process that exits cleanly under the monitor leaves no log listener
        thread or queues behind: DONE is final, so no stop() will release them.
        The exit code stays readable."""
        runner = ProcessRunner(MPSimpleService(lg))
        runner._state = State.RUNNING
        runner._process = MagicMock(exitcode=0)
        listener = runner._log_listener = MagicMock()
        errors = runner._error_queue = MagicMock()
        logs = runner._log_queue = MagicMock()
        with patch.object(runner, "is_alive", return_value=False):
            runner._monitor_loop(interval=0)

        assert runner.state == State.DONE
        listener.stop.assert_called_once()
        errors.close.assert_called_once()
        logs.close.assert_called_once()
        assert runner.exit_code == 0

    def test_a_restart_cleanup_does_not_stop_a_run_started_since(self, lg):
        """The monitor's restart of run 1 is about to stop it when an explicit
        stop() ends run 1 and a start() begins run 2: the restart's cleanup
        leaves run 2 alone and gives up."""
        runner = ProcessRunner(MPSimpleService(lg))
        runner._state = State.FAILED
        runner._run = 1

        def stopped_and_started() -> None:
            runner._run = 2
            runner._state = State.STARTING

        hook = HookedLock(runner, stopped_and_started)
        hook.arm()
        with patch.object(runner, "_end_process") as end_process:
            assert runner._attempt_restart(1) is False

        end_process.assert_not_called()
        assert runner.state == State.STARTING

    @pytest.mark.parametrize("retries", [1, 2], ids=["last-retry", "two-left"])
    def test_one_restart_runs_at_a_time(self, retries):
        """A second caller (check() on another thread) finding the run FAILED
        while a restart of it is under way reserves nothing: the restart in
        progress is the run's, and the retry is spent once, the last one too."""
        runner = ProcessRunner(
            MPSimpleService(MagicMock()), RestartPolicy(max_retries=retries, backoff=0)
        )
        second: list[bool] = []

        def attempt(run: int) -> bool:
            second.append(runner._maybe_restart())  # the other caller, meanwhile
            return True

        with patch.object(runner, "_attempt_restart", side_effect=attempt) as attempts:
            assert runner._maybe_restart() is True

        assert second == [False]  # it reached the reservation, and was refused
        assert attempts.call_count == 1
        assert runner._retries == 1
        assert not runner._restarting

    def test_restart_pending_through_the_last_attempt(self):
        """The last allowed restart counts as pending while it runs.

        _maybe_restart() counts the attempt before making it, so can_restart is
        already False during it; a waiter must not give up on that attempt.
        """
        runner = ProcessRunner(
            MPSimpleService(MagicMock()), RestartPolicy(max_retries=1, backoff=0)
        )
        during: list[bool] = []
        with (
            patch.object(
                runner,
                "_stop_for_restart",
                lambda run: during.append(runner.restart_pending),
            ),
            patch.object(runner, "_start"),  # a restart's start
            patch.object(runner, "wait_healthy"),
        ):
            assert runner._maybe_restart()

        assert during == [True]
        assert not runner.restart_pending  # attempt over, no retries left
