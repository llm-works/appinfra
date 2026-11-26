# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Unit tests for ProcessRunner, the runner the FastAPI server runs uvicorn under."""

import itertools
import queue
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager, nullcontext
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from appinfra.app.fastapi.runtime.process import ProcessRunner, _RunErrors
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
    Its Pipe gives a pair of mock ends; its queues are empty, as a real one
    raises queue.Empty once drained. No fork happens, so no SIGINT is held
    around it: the hold installs a real handler, which integration tests cover."""
    with (
        patch(f"{_PROCESS}.mp.get_context") as get_context,
        patch(f"{_PROCESS}._interrupt_held", nullcontext),
    ):
        ctx = get_context.return_value
        ctx.Pipe.side_effect = lambda duplex=True: (MagicMock(), MagicMock())
        ctx.Queue.return_value.get_nowait.side_effect = queue.Empty
        ctx.Process.return_value.exitcode = None  # running, as a real one starts
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


class _ClosableQueue:
    """An error queue holding *items* that, like a multiprocessing queue,
    raises ValueError once closed."""

    def __init__(self, *items: BaseException) -> None:
        self._items = list(items)
        self.closed = False

    def get_nowait(self) -> BaseException:
        if self.closed:
            raise ValueError("Queue is closed")
        if not self._items:
            raise queue.Empty()
        return self._items.pop(0)

    def cancel_join_thread(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True


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

    def test_an_interrupted_launch_ends_the_child_and_raises_unchanged(self, lg):
        """A KeyboardInterrupt after the fork gets the cleanup a failure gets:
        the child ended, the work setup() started stopped, the run FAILED; the
        interrupt itself reaches the caller as it is, not as a RunError."""
        derived: list[StopToken] = []

        class DerivesInSetup(MPSimpleService):
            def setup(self) -> None:
                derived.append(self.stopping.child())

        with (
            _mock_mp_context() as (mock_process, _, _),
            patch(f"{_PROCESS}.LogQueueListener") as mock_listener,
        ):
            child = mock_process.return_value
            child.is_alive.return_value = True  # alive until terminated
            child.terminate.side_effect = lambda: setattr(
                child.is_alive, "return_value", False
            )
            mock_listener.return_value.start.side_effect = KeyboardInterrupt

            runner = ProcessRunner(DerivesInSetup(lg))
            with pytest.raises(KeyboardInterrupt):
                runner.start()

            child.terminate.assert_called_once()
            assert derived[0].is_set()
            assert runner.state == State.FAILED
            assert runner.process is None

    @pytest.mark.parametrize(
        ("exitcode", "read"), [(-15, False), (3, True)], ids=["killed", "exited"]
    )
    def test_stop_reads_no_error_queue_of_a_killed_child(self, lg, exitcode, read):
        """A child ended by a signal can leave a partial frame in its error
        queue, which a read would wait on forever: its queue is closed
        unread. A child that exited on its own flushed its queue: it is read."""
        with (
            _mock_mp_context() as (mock_process, _, mock_queue),
            patch(f"{_PROCESS}.LogQueueListener"),
        ):
            errors = MagicMock()
            errors.get_nowait.side_effect = queue.Empty
            mock_queue.side_effect = [MagicMock(), errors]  # the log queue first
            child = mock_process.return_value
            child.is_alive.return_value = True
            runner = ProcessRunner(MPSimpleService(lg))
            runner.start()

            child.is_alive.return_value = False
            child.exitcode = exitcode
            runner.stop()

        assert errors.get_nowait.called is read
        errors.close.assert_called_once()

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
        next run's: a run's claim gives it a record of its own."""
        runner = ProcessRunner(MPSimpleService(lg))
        runner._errors.first = RuntimeError("first run")
        with runner._lock:
            runner._claim_locked()
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

    def test_a_start_failing_in_setup_reports_no_error_of_the_run_before(self, lg):
        """Run 1 failed with an error the runner read and kept; a retry start()
        fails in setup(), before its process exists: the runner reports no
        error of run 1's for it."""
        runner = ProcessRunner(MPSetupFailService(lg))
        ctx = MagicMock()
        first = RuntimeError("run 1")
        queued: list[BaseException] = [first]

        def get_nowait() -> BaseException:
            if not queued:
                raise queue.Empty()
            return queued.pop()

        ctx.Queue.return_value.get_nowait.side_effect = get_nowait
        ctx.Pipe.return_value = (MagicMock(), MagicMock())
        runner._create_ipc_primitives(ctx)
        assert runner.exception is first  # read and kept
        runner._state = State.FAILED
        runner._process = MagicMock()
        runner._process.is_alive.return_value = False  # run 1's child, dead

        with pytest.raises(SetupError):
            runner.start()

        assert runner.exception is None

    def test_an_old_runs_exception_is_not_published_into_a_new_run(self, lg):
        """A reader drains run A's queue; as it takes A's exception, run B
        starts with a record of its own. B reports no exception of A's; A's
        record keeps it."""
        runner = ProcessRunner(MPSimpleService(lg))
        first = RuntimeError("run A")
        drained: list[BaseException] = [first]
        a_errors = runner._errors

        def get_nowait() -> BaseException:
            if not drained:
                raise queue.Empty()
            runner._errors = _RunErrors()  # run B's, from its claim
            return drained.pop()

        a_errors.queue = MagicMock()
        a_errors.queue.get_nowait.side_effect = get_nowait

        assert runner.exception is first  # the read began on run A's record
        assert runner.exception is None  # run B's
        assert a_errors.first is first

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
        old_errors = runner._errors.queue = MagicMock()
        old_errors.get_nowait.side_effect = queue.Empty

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

    def test_a_waiter_blocked_on_a_start_does_not_take_the_next_run(self, lg):
        """The waiter blocks on another thread's start of run 1. Before it
        wakes, that start returns, a stop() ends run 1, and a start of run 3
        completes, healthy: the waiter learns its run was stopped instead of
        reporting run 3 ready."""
        runner = ProcessRunner(MPSimpleService(lg))
        runner._state = State.STARTING
        runner._run = 1
        runner._start_thread = -1  # another thread's start, in progress

        class Replaced:
            def wait_for(self, predicate: Callable[[], bool], timeout: float) -> bool:
                runner._start_thread = None  # run 1's start returned
                runner._run = 3  # a stop() ended it, a start() claimed run 3
                return predicate()

        runner._start_done = Replaced()  # type: ignore[assignment]
        with (
            patch.object(runner, "is_alive", return_value=True),
            patch.object(runner, "is_healthy", return_value=True),
            pytest.raises(RunError, match="stopped during startup"),
        ):
            runner.wait_healthy(timeout=5.0)

        assert runner.state == State.STARTING  # run 3 is not this waiter's

    def test_a_waiter_woken_after_the_next_start_claimed_learns_it_was_stopped(
        self, lg
    ):
        """The waiter blocks on another thread's start of run 1. Before it
        wakes, a stop() ends run 1 and a start of run 2 claims it, still in
        setup: the waiter learns its run was stopped instead of waiting on
        run 2's start until it times out."""
        runner = ProcessRunner(MPSimpleService(lg))
        runner._state = State.STARTING
        runner._run = 1
        runner._start_thread = -1  # another thread's start, in progress

        class Claimed:
            def wait_for(self, predicate: Callable[[], bool], timeout: float) -> bool:
                runner._run = 2  # a stop() ended run 1, a start() claimed run 2
                runner._start_thread = -2  # run 2's start, in setup
                return predicate()

        runner._start_done = Claimed()  # type: ignore[assignment]
        with pytest.raises(RunError, match="stopped during startup"):
            runner.wait_healthy(timeout=5.0)

    def test_a_stop_wakes_the_waiters_of_the_start_it_ends(self, lg):
        """stop() during another thread's start notifies that start's waiters,
        so they learn at once that their run was stopped."""
        runner = ProcessRunner(MPSimpleService(lg))
        runner._state = State.STARTING
        runner._start_thread = -1  # another thread's start, in progress
        done = runner._start_done = MagicMock()
        with patch.object(runner, "_await_start", return_value=False):
            runner.stop(timeout=0)

        done.notify_all.assert_called_once()

    def test_a_waiter_reports_its_own_run_s_exception(self, lg):
        """The waiter fails run 1, which exited; before it reads the cause, run
        1 is stopped and run 2 starts, with an error of its own queued: run 1's
        RunError is caused by run 1's exception."""
        runner = ProcessRunner(MPSimpleService(lg))
        runner._state = State.FAILED
        runner._run = 1
        a_error, b_error = RuntimeError("a"), RuntimeError("b")
        a_queue: queue.Queue[BaseException] = queue.Queue()
        a_queue.put(a_error)
        runner._errors.queue = a_queue  # type: ignore[assignment]

        def b_started() -> None:
            with runner._lock:
                runner._claim_locked()  # run 2's claim: a record of its own
            b_queue: queue.Queue[BaseException] = queue.Queue()
            b_queue.put(b_error)
            runner._state = State.STARTING
            runner._errors.queue = b_queue  # type: ignore[assignment]

        hook = HookedLock(runner, b_started, on_release=True)
        fail = runner._fail_run

        def fail_then_arm(run: int) -> Any:
            hook.arm()  # fires as _fail_run() releases the lock
            return fail(run)

        with (
            patch.object(runner, "_fail_run", side_effect=fail_then_arm),
            pytest.raises(RunError, match="exited during startup") as e,
        ):
            runner.wait_healthy(timeout=5.0)

        assert e.value.__cause__ is a_error

    def test_a_waiter_keeps_its_run_s_cause_once_its_queue_is_closed(self, lg):
        """The waiter fails run 1, whose error no one has read yet; before it
        reads the cause, run 2's claim closes run 1's queue, which can no
        longer be read, as a multiprocessing queue cannot: run 1's RunError is
        still caused by run 1's exception."""
        runner = ProcessRunner(MPSimpleService(lg))
        runner._state = State.FAILED
        runner._run = 1
        a_error = RuntimeError("a")
        a_queue = _ClosableQueue(a_error)
        runner._errors.queue = a_queue  # type: ignore[assignment]

        def b_started() -> None:
            with runner._lock:
                runner._claim_locked()  # closes run 1's queue
            runner._state = State.STARTING

        hook = HookedLock(runner, b_started, on_release=True)
        fail = runner._fail_run

        def fail_then_arm(run: int) -> Any:
            hook.arm()  # fires as _fail_run() releases the lock
            return fail(run)

        with (
            patch.object(runner, "_fail_run", side_effect=fail_then_arm),
            pytest.raises(RunError, match="exited during startup") as e,
        ):
            runner.wait_healthy(timeout=5.0)

        assert a_queue.closed
        assert e.value.__cause__ is a_error

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
            assert runner._maybe_restart(runner._run) is False
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
            assert runner._maybe_restart(runner._run) is True
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
            runner._monitor_loop(0, threading.Event())

        assert runner.state == state

    def test_a_clean_exit_observed_for_a_replaced_run_cleans_nothing(self, lg):
        """check() sees run 1's process exit 0; before it ends the run, run 2
        is RUNNING with process B: B's IPC stays, and the runner stays
        RUNNING."""
        runner = ProcessRunner(MPSimpleService(lg))
        runner._state = State.RUNNING
        runner._run = 1
        b, b_listener = MagicMock(), MagicMock()

        def replaced() -> int:
            runner._run, runner._process = 2, b
            runner._log_listener = b_listener
            return 0  # run 1's exit code, read as run 2 starts

        a = MagicMock()
        type(a).exitcode = property(lambda _: replaced())
        runner._process = a

        with patch.object(runner, "is_alive", return_value=False):
            assert runner.check() is False

        assert runner.state == State.RUNNING
        assert runner.process is b
        b_listener.stop.assert_not_called()

    def test_a_clean_exit_the_monitor_records_during_stop_ends_it(self, lg):
        """stop() finds the run RUNNING; while it joins the monitor, the
        monitor records the child's clean exit: stop() returns, the runner
        DONE, instead of refusing the stop of a run that ended."""
        runner = ProcessRunner(MPSimpleService(lg))
        runner._state = State.RUNNING
        runner._process = MagicMock(exitcode=0)

        def monitor_finishes(*args: object) -> None:
            runner._monitor_loop(0, threading.Event())  # past its stop check

        with (
            patch.object(runner, "is_alive", return_value=False),
            patch.object(runner, "_end_monitor", side_effect=monitor_finishes),
        ):
            runner.stop()

        assert runner.state == State.DONE

    def test_a_stop_releases_its_claim_as_it_publishes_stopped(self, lg):
        """Once another thread can see STOPPED, it can start a run and stop it:
        that stop's claim is not refused by the stop that just finished."""
        runner = ProcessRunner(MPSimpleService(lg))
        runner._state = State.RUNNING
        runner._process = MagicMock(exitcode=-15)
        runner._process.is_alive.return_value = False
        claims: list[bool] = []

        def started_and_stopped() -> None:
            assert runner.state == State.STOPPED
            runner._state = State.RUNNING  # a start() on another thread
            runner._run += 1
            with runner._lock:
                claims.append(runner._claim_stop_locked())  # and its stop()

        hook = HookedLock(runner, started_and_stopped, on_release=True)
        cleanup = runner._cleanup_ipc

        def cleanup_then_arm() -> None:
            cleanup()
            hook.arm()  # the next release publishes STOPPED

        with patch.object(runner, "_cleanup_ipc", side_effect=cleanup_then_arm):
            runner.stop()

        assert claims == [True]

    def test_a_stopped_monitor_pass_does_not_fail_a_later_run(self, lg):
        """A monitor pass is between its stop check and its check() when a
        stop() signals it and a start() makes run 3 current, unhealthy: the
        pass fails nothing and restarts nothing."""
        runner = ProcessRunner(MPSimpleService(lg))
        runner._state = State.RUNNING
        runner._run = 1
        stopped = threading.Event()

        def stopped_then_started() -> None:
            stopped.set()  # a stop() signalled this monitor
            runner._run = 3  # and a start() made run 3 current
            runner._state = State.RUNNING

        hook = HookedLock(runner, stopped_then_started)
        hook.arm()
        with (
            patch.object(runner, "is_alive", return_value=False),
            patch.object(runner, "is_healthy", return_value=False),
            patch.object(runner, "_maybe_restart") as restart,
        ):
            runner._monitor_loop(0, stopped)

        assert runner.state == State.RUNNING
        restart.assert_not_called()

    def test_one_monitor_runs_when_two_callers_start_one(self, lg):
        """A second start_monitor() right after the first released the lock
        finds the first monitor running and starts none of its own."""
        runner = ProcessRunner(MPSimpleService(lg))
        threads: list[MagicMock] = []

        def new_thread(*args: Any, **kwargs: Any) -> MagicMock:
            thread = MagicMock()
            thread.is_alive.return_value = False  # until started
            thread.start.side_effect = lambda: setattr(
                thread.is_alive, "return_value", True
            )
            threads.append(thread)
            return thread

        hook = HookedLock(
            runner, lambda: runner.start_monitor(interval=0), on_release=True
        )
        hook.arm()
        with patch(f"{_PROCESS}.threading.Thread", side_effect=new_thread):
            runner.start_monitor(interval=0)

        assert len(threads) == 1
        threads[0].start.assert_called_once()

    def test_a_failed_monitor_start_leaves_none_registered(self, lg):
        """A monitor thread that fails to start is not left registered: a
        later start_monitor() starts one."""
        runner = ProcessRunner(MPSimpleService(lg))
        failing = MagicMock()
        failing.is_alive.return_value = False
        failing.start.side_effect = RuntimeError("can't start new thread")
        with (
            patch(f"{_PROCESS}.threading.Thread", return_value=failing),
            pytest.raises(RuntimeError),
        ):
            runner.start_monitor(interval=0)

        assert runner._monitor is None

    def test_a_stop_does_not_end_a_monitor_started_after_it(self, lg):
        """stop() is waiting for a start in progress when another stop() ends
        the run and a start() begins the next, with a monitor of its own: the
        first stop leaves that monitor running."""
        runner = ProcessRunner(MPSimpleService(lg))
        runner._state = State.RUNNING
        new_thread = MagicMock()
        new_thread.is_alive.return_value = True

        def stopped_and_restarted(timeout: float) -> bool:
            runner._run += 2  # another stop()'s, then the start()'s
            runner._state = State.RUNNING
            with patch(f"{_PROCESS}.threading.Thread", return_value=new_thread):
                runner.start_monitor(interval=0)
            return True

        with (
            patch.object(runner, "_await_start", side_effect=stopped_and_restarted),
            patch.object(runner, "_end_process"),
        ):
            runner.stop()

        new_thread.join.assert_not_called()
        assert runner.monitoring

    def test_a_stop_does_not_stop_a_run_started_after_it(self, lg):
        """stop() is joining the monitor when another stop() ends the run and a
        start() begins the next: the first stop leaves the new run alone."""
        runner = ProcessRunner(MPSimpleService(lg))
        runner._state = State.RUNNING

        def stopped_and_started(*args: object) -> None:
            runner._run += 2  # another stop()'s, then the start()'s
            runner._state = State.RUNNING

        with (
            patch.object(runner, "_end_monitor", side_effect=stopped_and_started),
            patch.object(runner, "_end_process") as end_process,
        ):
            runner.stop()

        end_process.assert_not_called()
        assert runner.state == State.RUNNING

    def test_check_ends_a_clean_exit_done_without_a_restart(self, lg):
        """The child exited with code 0 after the monitor last looked: check()
        ends the run DONE, as the monitor would, and restarts nothing."""
        runner = ProcessRunner(MPSimpleService(lg))
        runner._state = State.RUNNING
        runner._process = MagicMock(exitcode=0)
        with (
            patch.object(runner, "is_alive", return_value=False),
            patch.object(runner, "_maybe_restart") as restart,
        ):
            assert runner.check() is False

        assert runner.state == State.DONE
        restart.assert_not_called()

    def test_check_ends_a_child_exiting_cleanly_during_it_done(self, lg):
        """check() finds the child alive but unhealthy; by its second look the
        child has exited with code 0: the run ends DONE, not restarted."""
        runner = ProcessRunner(MPSimpleService(lg))
        runner._state = State.RUNNING
        runner._process = MagicMock(exitcode=0)
        alive = itertools.chain([True, True], itertools.repeat(False))
        with (
            patch.object(runner, "is_alive", side_effect=lambda: next(alive)),
            patch.object(runner, "is_healthy", return_value=False),
            patch.object(runner, "_maybe_restart") as restart,
        ):
            assert runner.check() is False

        assert runner.state == State.DONE
        restart.assert_not_called()

    @pytest.mark.parametrize(
        ("process", "restarts"),
        [(MagicMock(exitcode=0), False), (MagicMock(exitcode=3), True), (None, True)],
        ids=["clean-exit", "failed-exit", "setup-failed"],
    )
    def test_check_restarts_a_failed_run_unless_it_exited_cleanly(
        self, lg, process, restarts
    ):
        """A FAILED run is restarted, unless its child has since exited with
        code 0, which ends it DONE: a nonzero exit, or a setup() that failed
        before any child, still restarts."""
        runner = ProcessRunner(MPSimpleService(lg))
        runner._state = State.FAILED
        runner._process = process
        with (
            patch.object(runner, "is_alive", return_value=False),
            patch.object(runner, "_maybe_restart", return_value=True) as restart,
        ):
            assert runner.check() is restarts

        assert restart.called is restarts
        assert (runner.state == State.DONE) is not restarts

    def test_a_clean_exit_stops_the_work_setup_started(self, lg):
        """setup() derived a token for its work; the child then exits cleanly:
        that work is told to stop, as on every other end of a run."""
        runner = ProcessRunner(MPSimpleService(lg))
        runner._state = State.RUNNING
        runner._process = MagicMock(exitcode=0)
        work = runner.service.stopping.child()  # as setup() derives it
        with patch.object(runner, "is_alive", return_value=False):
            runner._monitor_loop(0, threading.Event())

        assert runner.state == State.DONE
        assert work.is_set()

    def test_a_clean_exit_releases_the_log_listener_and_queues(self, lg):
        """A process that exits cleanly under the monitor leaves no log listener
        thread or queues behind: DONE is final, so no stop() will release them.
        The exit code stays readable."""
        runner = ProcessRunner(MPSimpleService(lg))
        runner._state = State.RUNNING
        runner._process = MagicMock(exitcode=0)
        listener = runner._log_listener = MagicMock()
        errors = runner._errors.queue = MagicMock()
        errors.get_nowait.side_effect = queue.Empty
        logs = runner._log_queue = MagicMock()
        with patch.object(runner, "is_alive", return_value=False):
            runner._monitor_loop(0, threading.Event())

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

    def test_a_failed_health_check_does_not_fail_a_run_started_since(self, lg):
        """check() finds run 1 unhealthy; before it fails the run, a restart on
        another thread ends run 1 and run 2 is RUNNING: run 2 stays RUNNING and
        no restart is attempted for it."""
        runner = ProcessRunner(MPSimpleService(lg))
        runner._state = State.RUNNING
        runner._run = 1

        def unhealthy_then_replaced() -> bool:
            runner._run = 2  # run 2 started and healthy, state RUNNING again
            return False

        with (
            patch.object(runner, "is_alive", return_value=True),
            patch.object(runner, "is_healthy", side_effect=unhealthy_then_replaced),
            patch.object(runner, "_maybe_restart") as restart,
        ):
            assert runner.check() is False

        assert runner.state == State.RUNNING
        restart.assert_not_called()

    def test_a_restart_reserves_only_the_failed_run_check_saw(self, lg):
        """check() finds run 1 FAILED; before it reserves the restart, another
        caller's restart has started run 2, which has failed too, with retries
        left: the stale check reserves nothing for run 2 and spends none of its
        retries. Run 2 FAILED leaves the run check alone to refuse."""
        runner = ProcessRunner(MPSimpleService(lg), RestartPolicy(backoff=0.0))
        runner._state = State.FAILED
        runner._run = 1
        reserve = runner._maybe_restart

        def replaced_then_reserve(*args: int) -> bool:
            runner._run = 2  # restarted meanwhile, and failed again
            assert runner._retry_left()
            return reserve(*args)

        with (
            patch.object(runner, "_maybe_restart", replaced_then_reserve),
            patch.object(runner, "_attempt_restart") as attempt,
        ):
            assert runner.check() is False

        attempt.assert_not_called()
        assert runner._retries == 0
        assert not runner._restarting

    @pytest.mark.parametrize("retries", [1, 2], ids=["last-retry", "two-left"])
    def test_one_restart_runs_at_a_time(self, retries):
        """A second caller (check() on another thread) finding the run FAILED
        while a restart of it is under way reserves nothing: the restart in
        progress is the run's, and the retry is spent once, the last one too."""
        runner = ProcessRunner(
            MPSimpleService(MagicMock()), RestartPolicy(max_retries=retries, backoff=0)
        )
        runner._state = State.FAILED
        second: list[bool] = []

        def attempt(run: int) -> bool:
            second.append(runner._maybe_restart(run))  # the other caller, meanwhile
            return True

        with patch.object(runner, "_attempt_restart", side_effect=attempt) as attempts:
            assert runner._maybe_restart(runner._run) is True

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
        runner._state = State.FAILED
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
            assert runner._maybe_restart(runner._run)

        assert during == [True]
        assert not runner.restart_pending  # attempt over, no retries left
