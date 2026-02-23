"""Tests for SubprocessManager."""

import time
from unittest.mock import MagicMock, patch

import pytest

from appinfra.app.fastapi.runtime.subprocess import SubprocessManager, SubprocessState


@pytest.mark.unit
class TestSubprocessState:
    """Tests for SubprocessState dataclass."""

    def test_default_values(self):
        """Test default state values."""
        state = SubprocessState()
        assert state.process is None
        assert state.restart_count == 0
        assert state.last_restart == 0.0
        assert state.stop_requested is False


@pytest.mark.unit
class TestSubprocessManager:
    """Tests for SubprocessManager."""

    def test_initialization(self):
        """Test manager initialization."""

        def target():
            pass

        manager = SubprocessManager(
            target=target,
            args=(1, 2),
            kwargs={"key": "value"},
            shutdown_timeout=10.0,
            auto_restart=False,
            restart_delay=2.0,
            max_restarts=3,
        )

        assert manager._target is target
        assert manager._args == (1, 2)
        assert manager._kwargs == {"key": "value"}
        assert manager._shutdown_timeout == 10.0
        assert manager._auto_restart is False
        assert manager._restart_delay == 2.0
        assert manager._max_restarts == 3

    def test_default_initialization(self):
        """Test manager with default values."""

        def target():
            pass

        manager = SubprocessManager(target=target)

        assert manager._args == ()
        assert manager._kwargs == {}
        assert manager._shutdown_timeout == 5.0
        assert manager._auto_restart is True
        assert manager._restart_delay == 1.0
        assert manager._max_restarts == 5

    def test_is_alive_no_process(self):
        """Test is_alive when no process started."""
        manager = SubprocessManager(target=lambda: None)
        assert manager.is_alive() is False

    def test_pid_no_process(self):
        """Test pid when no process started."""
        manager = SubprocessManager(target=lambda: None)
        assert manager.pid is None

    def test_restart_count_initial(self):
        """Test restart_count is initially zero."""
        manager = SubprocessManager(target=lambda: None)
        assert manager.restart_count == 0

    def test_process_property(self):
        """Test process property returns state's process."""
        manager = SubprocessManager(target=lambda: None)
        assert manager.process is None

    def test_start_raises_if_already_running(self):
        """Test start raises if process already running."""
        manager = SubprocessManager(target=lambda: None)

        # Mock is_alive to return True
        with patch.object(manager, "is_alive", return_value=True):
            with pytest.raises(RuntimeError, match="already running"):
                manager.start()

    def test_should_restart_unlimited(self):
        """Test _should_restart with max_restarts=0 (unlimited)."""
        manager = SubprocessManager(target=lambda: None, max_restarts=0)
        manager._state.restart_count = 100
        assert manager._should_restart() is True

    def test_should_restart_within_limit(self):
        """Test _should_restart within limit."""
        manager = SubprocessManager(target=lambda: None, max_restarts=5)
        manager._state.restart_count = 3
        assert manager._should_restart() is True

    def test_should_restart_at_limit(self):
        """Test _should_restart at limit."""
        manager = SubprocessManager(target=lambda: None, max_restarts=5)
        manager._state.restart_count = 5
        assert manager._should_restart() is False

    def test_handle_process_exit_clean_shutdown(self):
        """Test _handle_process_exit with exit code 0 (clean shutdown)."""
        manager = SubprocessManager(target=lambda: None)
        result = manager._handle_process_exit(exit_code=0)
        assert result is False  # Don't restart on clean exit

    def test_handle_process_exit_crash_with_restart(self):
        """Test _handle_process_exit with crash and restart available."""
        manager = SubprocessManager(
            target=lambda: None,
            max_restarts=5,
            restart_delay=0.01,
        )
        manager._state.restart_count = 0

        with patch.object(manager, "_do_restart") as mock_restart:
            result = manager._handle_process_exit(exit_code=1)

        assert result is True  # Continue monitoring after restart
        mock_restart.assert_called_once()

    def test_handle_process_exit_crash_max_restarts_exceeded(self):
        """Test _handle_process_exit when max restarts exceeded."""
        manager = SubprocessManager(target=lambda: None, max_restarts=3)
        manager._state.restart_count = 3  # Already at limit

        result = manager._handle_process_exit(exit_code=1)
        assert result is False  # Stop monitoring, max restarts exceeded


@pytest.mark.unit
class TestSubprocessManagerGracefulShutdown:
    """Tests for graceful shutdown behavior."""

    def test_graceful_shutdown_terminates_process(self):
        """Test graceful shutdown calls terminate."""
        manager = SubprocessManager(target=lambda: None)

        mock_proc = MagicMock()
        mock_proc.is_alive.return_value = False

        manager._graceful_shutdown(mock_proc)

        mock_proc.terminate.assert_called_once()
        mock_proc.join.assert_called()

    def test_graceful_shutdown_kills_if_needed(self):
        """Test graceful shutdown kills if process doesn't terminate."""
        manager = SubprocessManager(target=lambda: None, shutdown_timeout=0.1)

        mock_proc = MagicMock()
        # Process stays alive after terminate
        mock_proc.is_alive.return_value = True

        manager._graceful_shutdown(mock_proc)

        mock_proc.terminate.assert_called_once()
        mock_proc.kill.assert_called_once()

    def test_stop_clears_manager(self):
        """Test stop clears subprocess manager state."""
        manager = SubprocessManager(target=lambda: None)

        # Mock having a subprocess manager
        mock_proc = MagicMock()
        mock_proc.is_alive.return_value = False
        manager._state.process = mock_proc

        manager.stop()

        assert manager._state.stop_requested is True


@pytest.mark.integration
class TestSubprocessManagerIntegration:
    """Integration tests for SubprocessManager."""

    def test_start_and_stop(self):
        """Test starting and stopping a real subprocess."""

        def worker():
            time.sleep(10)

        manager = SubprocessManager(target=worker, auto_restart=False)

        proc = manager.start()
        assert proc is not None
        assert manager.is_alive() is True
        assert manager.pid is not None

        manager.stop()
        assert manager.is_alive() is False

    def test_process_exits_normally(self):
        """Test process that exits normally."""

        def worker():
            return

        manager = SubprocessManager(target=worker, auto_restart=False)

        proc = manager.start()
        proc.join(timeout=1.0)

        assert proc.exitcode == 0

    def test_spawn_process_with_monitor_thread(self):
        """Test that auto_restart spawns monitor thread."""

        def worker():
            time.sleep(10)

        manager = SubprocessManager(target=worker, auto_restart=True)

        proc = manager.start()
        try:
            assert manager._monitor_thread is not None
            assert manager._monitor_thread.is_alive()
        finally:
            manager.stop()

    def test_stop_joins_monitor_thread(self):
        """Test stop joins the monitor thread."""

        def worker():
            time.sleep(10)

        manager = SubprocessManager(target=worker, auto_restart=True)

        manager.start()
        assert manager._monitor_thread is not None

        manager.stop()
        assert manager._monitor_thread is None

    def test_auto_restart_on_crash(self):
        """Test auto-restart when process crashes."""
        import sys

        def crasher():
            sys.exit(1)

        manager = SubprocessManager(
            target=crasher,
            auto_restart=True,
            restart_delay=0.1,
            max_restarts=2,
        )

        manager.start()
        # Wait for restarts to happen
        time.sleep(1.0)

        # Should have restarted at least once
        assert manager.restart_count >= 1

        manager.stop()

    def test_do_restart_increments_count(self):
        """Test _do_restart increments restart count."""

        def worker():
            time.sleep(10)

        manager = SubprocessManager(
            target=worker,
            auto_restart=False,
            restart_delay=0.01,
        )

        # Set up initial state
        manager._state.restart_count = 2

        # Call _do_restart directly
        manager._do_restart()

        assert manager._state.restart_count == 3

        # Clean up
        manager.stop()
