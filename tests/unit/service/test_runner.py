# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for Runner classes."""

import itertools
import time
from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from appinfra.log import Logger
from appinfra.service import (
    InvalidTransitionError,
    ProcessRunner,
    RestartPolicy,
    Service,
    SetupError,
    State,
    ThreadRunner,
)
from tests.helpers.service.runner import SimpleService


@contextmanager
def _mock_mp_context() -> Iterator[tuple[MagicMock, MagicMock, MagicMock]]:
    """Patch ProcessRunner's multiprocessing context; yield its Process, Event, Queue."""
    with patch("appinfra.service.runner.process.mp.get_context") as get_context:
        ctx = get_context.return_value
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

    def execute(self) -> None:
        # Wait for shutdown signal (injected by ProcessRunner)
        if hasattr(self, "_shutdown_event") and self._shutdown_event:
            self._shutdown_event.wait()
        else:
            time.sleep(10)

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

    def execute(self) -> None:
        pass


class SetupFailService(Service):
    """Service that fails during setup()."""

    def __init__(self) -> None:
        self._lg = MagicMock()

    @property
    def name(self) -> str:
        return "setup-fail"

    def setup(self) -> None:
        raise SetupError(self.name, "config invalid")

    def execute(self) -> None:
        pass


class TestThreadRunner:
    """Test ThreadRunner class."""

    def test_setup_error_transitions_to_failed(self):
        """SetupError transitions to FAILED."""
        svc = SetupFailService()
        runner = ThreadRunner(svc)

        with pytest.raises(SetupError, match="config invalid"):
            runner.start()

        assert runner.state == State.FAILED

    def test_invalid_transition_raises(self):
        """Invalid state transition raises error."""
        svc = SimpleService()
        runner = ThreadRunner(svc)

        with pytest.raises(InvalidTransitionError):
            runner._transition(State.RUNNING)

    def test_check_not_running(self):
        """check() returns False when not running."""
        svc = SimpleService()
        runner = ThreadRunner(svc)

        # Not started yet
        result = runner.check()
        assert result is False


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
            patch("appinfra.service.runner.process.LogQueueListener"),
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

    def test_state_hooks_called(self, lg):
        """State hooks are called on transitions."""
        with (
            _mock_mp_context(),
            patch("appinfra.service.runner.process.LogQueueListener"),
        ):
            transitions = []

            def hook(name, old, new):
                transitions.append((name, old, new))

            svc = MPSimpleService(lg, name="test")
            runner = ProcessRunner(svc)
            runner.on_state_change(hook)

            runner.start()

            assert ("test", State.CREATED, State.INITD) in transitions
            assert ("test", State.INITD, State.STARTING) in transitions

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
            patch("appinfra.service.runner.process.LogQueueListener"),
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
            patch("appinfra.service.runner.process.LogQueueListener") as mock_listener,
        ):
            child = mock_process.return_value
            child.is_alive.return_value = True  # alive until terminated
            child.terminate.side_effect = lambda: setattr(
                child.is_alive, "return_value", False
            )
            mock_listener.return_value.start.side_effect = RuntimeError("no thread")

            runner = ProcessRunner(MPSimpleService(lg))
            with pytest.raises(RuntimeError, match="no thread"):
                runner.start()

            child.terminate.assert_called_once()
            child.join.assert_called_once_with(timeout=2.0)
            child.kill.assert_not_called()
            assert runner.state == State.FAILED
            assert runner.process is None  # ended, so the handles are released

    def test_start_failure_kills_a_child_that_ignores_terminate(self, lg):
        """A child still alive after terminate() is killed."""
        with (
            _mock_mp_context() as (mock_process, _, _),
            patch("appinfra.service.runner.process.LogQueueListener") as mock_listener,
        ):
            child = mock_process.return_value
            child.is_alive.return_value = True
            mock_listener.return_value.start.side_effect = RuntimeError("no thread")

            runner = ProcessRunner(MPSimpleService(lg))
            with pytest.raises(RuntimeError):
                runner.start()

            child.kill.assert_called_once()
            assert runner.state == State.FAILED
            # Still alive: the handle stays so a later stop() can retry
            assert runner.process is child

    def test_is_alive_when_running(self, lg):
        """is_alive() returns True when process is alive."""
        with (
            _mock_mp_context() as (mock_process, _, _),
            patch("appinfra.service.runner.process.LogQueueListener"),
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
            patch("appinfra.service.runner.process.LogQueueListener"),
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
            patch("appinfra.service.runner.process.LogQueueListener"),
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
            patch("appinfra.service.runner.process.LogQueueListener"),
        ):
            mock_process.return_value.is_alive.return_value = False
            mock_process.return_value.exitcode = 0

            svc = MPSimpleService(lg)
            runner = ProcessRunner(svc)
            runner.start()

            assert runner.exit_code == 0

    def test_exception_from_queue(self, lg):
        """exception property reads from error queue."""
        from queue import Empty

        with (
            _mock_mp_context() as (_, _, mock_queue_cls),
            patch("appinfra.service.runner.process.LogQueueListener"),
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
            patch("appinfra.service.runner.process.LogQueueListener"),
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


class TestRunnerRestart:
    """Test restart functionality."""

    def test_can_restart(self):
        """can_restart holds until max_retries is reached, and never when disabled."""
        runner = ThreadRunner(SimpleService(), RestartPolicy(max_retries=2))
        assert runner.can_restart
        runner._retries = 2
        assert not runner.can_restart

        disabled = RestartPolicy(restart_on_failure=False)
        assert not ThreadRunner(SimpleService(), disabled).can_restart

    def test_restart_pending_through_the_last_attempt(self):
        """The last allowed restart counts as pending while it runs.

        _maybe_restart() counts the attempt before making it, so can_restart is
        already False during it; a waiter must not give up on that attempt.
        """
        runner = ThreadRunner(SimpleService(), RestartPolicy(max_retries=1, backoff=0))
        during: list[bool] = []
        with (
            patch.object(
                runner,
                "_stop_for_restart",
                lambda: during.append(runner.restart_pending),
            ),
            patch.object(runner, "start"),
            patch.object(runner, "wait_healthy"),
        ):
            assert runner._maybe_restart()

        assert during == [True]
        assert not runner.restart_pending  # attempt over, no retries left
