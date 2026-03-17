"""Tests for Runner classes."""

import threading
import time
from unittest.mock import patch

import pytest

from appinfra.log import Logger
from appinfra.service import (
    HealthTimeoutError,
    InvalidTransitionError,
    ProcessRunner,
    RestartPolicy,
    RunError,
    ScheduledService,
    Service,
    SetupError,
    State,
    ThreadRunner,
)


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


class SimpleService(Service):
    """Simple test service."""

    def __init__(self, name: str = "test", health_delay: float = 0) -> None:
        self._name = name
        self._health_delay = health_delay
        self._stop_event = threading.Event()
        self._running = False
        self._healthy = False

    @property
    def name(self) -> str:
        return self._name

    def execute(self) -> None:
        self._running = True
        if self._health_delay:
            time.sleep(self._health_delay)
        self._healthy = True
        self._stop_event.wait()
        self._running = False
        self._healthy = False

    def teardown(self) -> None:
        self._stop_event.set()

    def is_healthy(self) -> bool:
        return self._healthy


class FailingService(Service):
    """Service that raises during execute()."""

    @property
    def name(self) -> str:
        return "failing"

    def execute(self) -> None:
        raise RuntimeError("intentional failure")


class SetupFailService(Service):
    """Service that fails during setup()."""

    @property
    def name(self) -> str:
        return "setup-fail"

    def setup(self) -> None:
        raise SetupError(self.name, "config invalid")

    def execute(self) -> None:
        pass


class FailOnFirstExecute(Service):
    """Service that fails on first execute but succeeds on retry."""

    def __init__(self) -> None:
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
        self._healthy = True
        self._stop_event.wait()
        self._healthy = False

    def teardown(self) -> None:
        self._stop_event.set()

    def is_healthy(self) -> bool:
        return self._healthy


@pytest.mark.unit
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

    def test_setup_error_transitions_to_failed(self):
        """SetupError transitions to FAILED."""
        svc = SetupFailService()
        runner = ThreadRunner(svc)

        with pytest.raises(SetupError, match="config invalid"):
            runner.start()

        assert runner.state == State.FAILED

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

    def test_invalid_transition_raises(self):
        """Invalid state transition raises error."""
        svc = SimpleService()
        runner = ThreadRunner(svc)

        with pytest.raises(InvalidTransitionError):
            runner._transition(State.RUNNING)

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

    def test_check_not_running(self):
        """check() returns False when not running."""
        svc = SimpleService()
        runner = ThreadRunner(svc)

        # Not started yet
        result = runner.check()
        assert result is False

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


@pytest.mark.unit
class TestProcessRunner:
    """Unit tests for ProcessRunner with mocks."""

    @pytest.fixture
    def lg(self):
        """Create a logger for tests."""
        return Logger(name="test")

    def test_start_transitions_states(self, lg):
        """start() transitions through INITD -> STARTING."""
        with (
            patch("appinfra.service.runner.mp.Process") as mock_process,
            patch("appinfra.service.runner.mp.Event"),
            patch("appinfra.service.runner.mp.Queue"),
            patch("appinfra.service.runner.LogQueueListener"),
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
            patch("appinfra.service.runner.mp.Process"),
            patch("appinfra.service.runner.mp.Event"),
            patch("appinfra.service.runner.mp.Queue"),
            patch("appinfra.service.runner.LogQueueListener"),
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

        class FailSetup(Service):
            def __init__(self, lg: Logger):
                self._lg = lg

            @property
            def name(self) -> str:
                return "fail-setup"

            def setup(self) -> None:
                raise SetupError(self.name, "setup failed")

            def execute(self) -> None:
                pass

        svc = FailSetup(lg)
        runner = ProcessRunner(svc)

        with pytest.raises(SetupError):
            runner.start()

        assert runner.state == State.FAILED

    def test_stop_running_process(self, lg):
        """stop() terminates a running process."""
        with (
            patch("appinfra.service.runner.mp.Process") as mock_process,
            patch("appinfra.service.runner.mp.Event") as mock_event,
            patch("appinfra.service.runner.mp.Queue"),
            patch("appinfra.service.runner.LogQueueListener"),
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

    def test_is_alive_when_running(self, lg):
        """is_alive() returns True when process is alive."""
        with (
            patch("appinfra.service.runner.mp.Process") as mock_process,
            patch("appinfra.service.runner.mp.Event"),
            patch("appinfra.service.runner.mp.Queue"),
            patch("appinfra.service.runner.LogQueueListener"),
        ):
            mock_process.return_value.is_alive.return_value = True

            svc = MPSimpleService(lg)
            runner = ProcessRunner(svc)
            runner.start()

            assert runner.is_alive()

    def test_is_healthy_when_running(self, lg):
        """is_healthy() returns True when process alive and healthy event set."""
        with (
            patch("appinfra.service.runner.mp.Process") as mock_process,
            patch("appinfra.service.runner.mp.Event") as mock_event,
            patch("appinfra.service.runner.mp.Queue"),
            patch("appinfra.service.runner.LogQueueListener"),
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
            patch("appinfra.service.runner.mp.Process") as mock_process,
            patch("appinfra.service.runner.mp.Event"),
            patch("appinfra.service.runner.mp.Queue"),
            patch("appinfra.service.runner.LogQueueListener"),
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
            patch("appinfra.service.runner.mp.Process") as mock_process,
            patch("appinfra.service.runner.mp.Event"),
            patch("appinfra.service.runner.mp.Queue"),
            patch("appinfra.service.runner.LogQueueListener"),
        ):
            mock_process.return_value.is_alive.return_value = False
            mock_process.return_value.exitcode = 0

            svc = MPSimpleService(lg)
            runner = ProcessRunner(svc)
            runner.start()

            assert runner.exit_code == 0

    def test_exception_from_queue(self, lg):
        """exception property reads from error queue."""
        with (
            patch("appinfra.service.runner.mp.Process"),
            patch("appinfra.service.runner.mp.Event"),
            patch("appinfra.service.runner.mp.Queue") as mock_queue,
            patch("appinfra.service.runner.LogQueueListener"),
        ):
            # Setup queue to return an exception
            mock_queue.return_value.empty.side_effect = [False, True]
            mock_queue.return_value.get_nowait.return_value = RuntimeError("test error")

            svc = MPSimpleService(lg)
            runner = ProcessRunner(svc)
            runner.start()

            exc = runner.exception
            assert isinstance(exc, RuntimeError)
            assert str(exc) == "test error"

    def test_stop_with_stubborn_process(self, lg):
        """stop() kills a process that won't terminate."""
        with (
            patch("appinfra.service.runner.mp.Process") as mock_process,
            patch("appinfra.service.runner.mp.Event") as mock_event,
            patch("appinfra.service.runner.mp.Queue"),
            patch("appinfra.service.runner.LogQueueListener"),
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


@pytest.mark.unit
class TestRunnerRestart:
    """Test restart functionality."""

    def test_max_retries_exhausted(self):
        """Restart stops after max_retries."""

        class AlwaysFails(Service):
            @property
            def name(self) -> str:
                return "always-fails"

            def execute(self) -> None:
                raise RuntimeError("always fails")

        policy = RestartPolicy(max_retries=2, backoff=0.01)
        runner = ThreadRunner(AlwaysFails(), policy)

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


@pytest.mark.unit
class TestScheduledService:
    """Test ScheduledService with ThreadRunner."""

    def test_tick_called_repeatedly(self):
        """tick() is called repeatedly."""
        tick_count = 0

        class CountingService(ScheduledService):
            interval = 0.05

            @property
            def name(self) -> str:
                return "counter"

            def tick(self) -> None:
                nonlocal tick_count
                tick_count += 1

            def is_healthy(self) -> bool:
                return tick_count > 0

        svc = CountingService()
        runner = ThreadRunner(svc)

        runner.start()
        runner.wait_healthy(timeout=5.0)
        time.sleep(0.2)
        runner.stop()

        assert tick_count >= 3
