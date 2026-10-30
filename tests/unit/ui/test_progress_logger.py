# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for appinfra.ui.progress_logger module."""

from __future__ import annotations

import logging
import os
from unittest.mock import MagicMock, patch

import pytest

from appinfra.ui.progress_logger import ProgressLogger, _is_interactive


@pytest.fixture
def mock_logger():
    """Create a mock logger for testing."""
    return MagicMock()


class TestIsInteractive:
    """Tests for _is_interactive function."""

    def test_interactive_when_tty(self):
        """Test returns True when stdout and stderr are TTY."""
        with (
            patch("sys.stdout") as mock_stdout,
            patch("sys.stderr") as mock_stderr,
            patch.dict(os.environ, {}, clear=True),
        ):
            mock_stdout.isatty.return_value = True
            mock_stderr.isatty.return_value = True
            assert _is_interactive() is True

    def test_not_interactive_when_stdout_not_tty(self):
        """Test returns False when stdout is not TTY."""
        with (
            patch("sys.stdout") as mock_stdout,
            patch("sys.stderr") as mock_stderr,
            patch.dict(os.environ, {}, clear=True),
        ):
            mock_stdout.isatty.return_value = False
            mock_stderr.isatty.return_value = True
            assert _is_interactive() is False

    def test_not_interactive_when_env_set(self):
        """Test returns False when APPINFRA_NON_INTERACTIVE is set."""
        with patch.dict(os.environ, {"APPINFRA_NON_INTERACTIVE": "1"}):
            assert _is_interactive() is False

    def test_not_interactive_with_true_value(self):
        """Test returns False when APPINFRA_NON_INTERACTIVE is 'true'."""
        with patch.dict(os.environ, {"APPINFRA_NON_INTERACTIVE": "true"}):
            assert _is_interactive() is False


class TestProgressLoggerInit:
    """Tests for ProgressLogger initialization."""

    def test_init_defaults(self, mock_logger):
        """Test ProgressLogger initializes with defaults."""
        pl = ProgressLogger(mock_logger)
        assert pl._lg is mock_logger
        assert pl._message == "Working..."
        assert pl._total is None
        assert pl._spinner == "dots"
        assert pl._completed == 0

    def test_init_with_message(self, mock_logger):
        """Test ProgressLogger with custom message."""
        pl = ProgressLogger(mock_logger, message="Processing...")
        assert pl._message == "Processing..."

    def test_init_with_total(self, mock_logger):
        """Test ProgressLogger with total (progress bar mode)."""
        pl = ProgressLogger(mock_logger, total=100)
        assert pl._total == 100

    def test_init_with_spinner(self, mock_logger):
        """Test ProgressLogger with custom spinner."""
        pl = ProgressLogger(mock_logger, spinner="arc")
        assert pl._spinner == "arc"


class TestProgressLoggerNonInteractive:
    """Tests for ProgressLogger in non-interactive mode."""

    def test_log_passes_through(self, mock_logger):
        """Test log calls logger in non-interactive mode."""
        with patch("appinfra.ui.progress_logger._is_interactive", return_value=False):
            pl = ProgressLogger(mock_logger, "Working...")
            with pl:
                pl.log("Test message")

            mock_logger.log.assert_called_once_with(logging.INFO, "Test message")

    def test_log_with_level(self, mock_logger):
        """Test log with custom level."""
        with patch("appinfra.ui.progress_logger._is_interactive", return_value=False):
            pl = ProgressLogger(mock_logger)
            with pl:
                pl.log("Warning message", level=logging.WARNING)

            mock_logger.log.assert_called_with(logging.WARNING, "Warning message")

    def test_debug_helper(self, mock_logger):
        """Test debug convenience method."""
        with patch("appinfra.ui.progress_logger._is_interactive", return_value=False):
            pl = ProgressLogger(mock_logger)
            with pl:
                pl.debug("Debug message")

            mock_logger.log.assert_called_with(logging.DEBUG, "Debug message")

    def test_info_helper(self, mock_logger):
        """Test info convenience method."""
        with patch("appinfra.ui.progress_logger._is_interactive", return_value=False):
            pl = ProgressLogger(mock_logger)
            with pl:
                pl.info("Info message")

            mock_logger.log.assert_called_with(logging.INFO, "Info message")

    def test_warning_helper(self, mock_logger):
        """Test warning convenience method."""
        with patch("appinfra.ui.progress_logger._is_interactive", return_value=False):
            pl = ProgressLogger(mock_logger)
            with pl:
                pl.warning("Warning message")

            mock_logger.log.assert_called_with(logging.WARNING, "Warning message")

    def test_error_helper(self, mock_logger):
        """Test error convenience method."""
        with patch("appinfra.ui.progress_logger._is_interactive", return_value=False):
            pl = ProgressLogger(mock_logger)
            with pl:
                pl.error("Error message")

            mock_logger.log.assert_called_with(logging.ERROR, "Error message")

    def test_update_is_noop(self, mock_logger):
        """Test update is no-op in non-interactive mode."""
        with patch("appinfra.ui.progress_logger._is_interactive", return_value=False):
            pl = ProgressLogger(mock_logger)
            with pl:
                # Should not raise
                pl.update("New message", advance=1)
            assert pl._completed == 1

    def test_set_total_updates_internal_state(self, mock_logger):
        """Test set_total updates internal state in non-interactive mode."""
        with patch("appinfra.ui.progress_logger._is_interactive", return_value=False):
            pl = ProgressLogger(mock_logger)
            with pl:
                pl.set_total(50)
            assert pl._total == 50


class TestProgressLoggerProperties:
    """Tests for ProgressLogger properties."""

    def test_is_interactive_property(self, mock_logger):
        """Test is_interactive property."""
        with patch("appinfra.ui.progress_logger._is_interactive", return_value=False):
            pl = ProgressLogger(mock_logger)
            assert pl.is_interactive is False

    def test_total_property(self, mock_logger):
        """Test total property."""
        with patch("appinfra.ui.progress_logger._is_interactive", return_value=False):
            pl = ProgressLogger(mock_logger, total=100)
            assert pl.total == 100

    def test_completed_property(self, mock_logger):
        """Test completed property."""
        with patch("appinfra.ui.progress_logger._is_interactive", return_value=False):
            pl = ProgressLogger(mock_logger)
            with pl:
                pl.update(advance=5)
            assert pl.completed == 5


class TestProgressLoggerContextManager:
    """Tests for ProgressLogger context manager behavior."""

    def test_enter_returns_self(self, mock_logger):
        """Test __enter__ returns self."""
        with patch("appinfra.ui.progress_logger._is_interactive", return_value=False):
            pl = ProgressLogger(mock_logger)
            result = pl.__enter__()
            assert result is pl
            pl.__exit__(None, None, None)

    def test_exit_cleans_up(self, mock_logger):
        """Test __exit__ cleans up resources."""
        with patch("appinfra.ui.progress_logger._is_interactive", return_value=False):
            pl = ProgressLogger(mock_logger)
            pl.__enter__()
            pl.__exit__(None, None, None)
            # In non-interactive mode, nothing to clean up
            assert pl._status is None
            assert pl._progress is None


class TestProgressLoggerWithMockedRich:
    """Tests for ProgressLogger with mocked Rich components."""

    def test_spinner_mode_starts_status(self, mock_logger):
        """Test spinner mode starts Rich Status."""
        mock_console = MagicMock()
        mock_status = MagicMock()
        mock_console.status.return_value = mock_status

        with (
            patch("appinfra.ui.progress_logger._is_interactive", return_value=True),
            patch("appinfra.ui.progress_logger.RICH_AVAILABLE", True),
            patch("appinfra.ui.progress_logger.RichConsole", return_value=mock_console),
        ):
            pl = ProgressLogger(mock_logger, message="Working...")
            pl.__enter__()

            mock_console.status.assert_called_once_with("Working...", spinner="dots")
            mock_status.start.assert_called_once()

            pl.__exit__(None, None, None)
            mock_status.stop.assert_called()

    def test_progress_bar_mode_starts_progress(self, mock_logger):
        """Test progress bar mode starts Rich Progress."""
        mock_console = MagicMock()
        mock_progress = MagicMock()
        mock_progress.add_task.return_value = 0

        with (
            patch("appinfra.ui.progress_logger._is_interactive", return_value=True),
            patch("appinfra.ui.progress_logger.RICH_AVAILABLE", True),
            patch("appinfra.ui.progress_logger.RichConsole", return_value=mock_console),
            patch(
                "appinfra.ui.progress_logger.RichProgress", return_value=mock_progress
            ),
        ):
            pl = ProgressLogger(mock_logger, message="Downloading...", total=100)
            pl.__enter__()

            mock_progress.start.assert_called_once()
            mock_progress.add_task.assert_called_once_with("Downloading...", total=100)

            pl.__exit__(None, None, None)
            mock_progress.stop.assert_called()

    def test_log_pauses_and_resumes_spinner(self, mock_logger):
        """Test log pauses spinner, logs, then resumes."""
        mock_console = MagicMock()
        mock_status = MagicMock()
        mock_console.status.return_value = mock_status

        with (
            patch("appinfra.ui.progress_logger._is_interactive", return_value=True),
            patch("appinfra.ui.progress_logger.RICH_AVAILABLE", True),
            patch("appinfra.ui.progress_logger.RichConsole", return_value=mock_console),
        ):
            pl = ProgressLogger(mock_logger)
            with pl:
                # Reset mock to track calls during log
                mock_status.reset_mock()
                pl.log("Test message")

            # Should have stopped, then started again
            mock_status.stop.assert_called()
            mock_status.start.assert_called()
            mock_logger.log.assert_called_with(logging.INFO, "Test message")

    def test_log_pauses_and_resumes_progress(self, mock_logger):
        """Test log pauses progress bar, logs, then resumes."""
        mock_console = MagicMock()
        mock_progress = MagicMock()
        mock_progress.add_task.return_value = 0

        with (
            patch("appinfra.ui.progress_logger._is_interactive", return_value=True),
            patch("appinfra.ui.progress_logger.RICH_AVAILABLE", True),
            patch("appinfra.ui.progress_logger.RichConsole", return_value=mock_console),
            patch(
                "appinfra.ui.progress_logger.RichProgress", return_value=mock_progress
            ),
        ):
            pl = ProgressLogger(mock_logger, total=100)
            with pl:
                # Reset mock to track calls during log
                mock_progress.reset_mock()
                pl.log("Test message")

            # Should have stopped, then started again
            mock_progress.stop.assert_called()
            mock_progress.start.assert_called()

    def test_update_advances_progress(self, mock_logger):
        """Test update advances progress bar."""
        mock_console = MagicMock()
        mock_progress = MagicMock()
        mock_progress.add_task.return_value = 0

        with (
            patch("appinfra.ui.progress_logger._is_interactive", return_value=True),
            patch("appinfra.ui.progress_logger.RICH_AVAILABLE", True),
            patch("appinfra.ui.progress_logger.RichConsole", return_value=mock_console),
            patch(
                "appinfra.ui.progress_logger.RichProgress", return_value=mock_progress
            ),
        ):
            pl = ProgressLogger(mock_logger, total=100)
            with pl:
                pl.update(advance=5)

            mock_progress.update.assert_called_with(0, advance=5)

    def test_update_sets_completed(self, mock_logger):
        """Test update with completed parameter."""
        mock_console = MagicMock()
        mock_progress = MagicMock()
        mock_progress.add_task.return_value = 0

        with (
            patch("appinfra.ui.progress_logger._is_interactive", return_value=True),
            patch("appinfra.ui.progress_logger.RICH_AVAILABLE", True),
            patch("appinfra.ui.progress_logger.RichConsole", return_value=mock_console),
            patch(
                "appinfra.ui.progress_logger.RichProgress", return_value=mock_progress
            ),
        ):
            pl = ProgressLogger(mock_logger, total=100)
            with pl:
                pl.update(completed=50)

            mock_progress.update.assert_called_with(0, completed=50)
            assert pl._completed == 50

    def test_update_spinner_message(self, mock_logger):
        """Test update message in spinner mode."""
        mock_console = MagicMock()
        mock_status = MagicMock()
        mock_console.status.return_value = mock_status

        with (
            patch("appinfra.ui.progress_logger._is_interactive", return_value=True),
            patch("appinfra.ui.progress_logger.RICH_AVAILABLE", True),
            patch("appinfra.ui.progress_logger.RichConsole", return_value=mock_console),
        ):
            pl = ProgressLogger(mock_logger)
            with pl:
                pl.update(message="New status")

            mock_status.update.assert_called_with("New status")

    def test_set_total_switches_to_progress_bar(self, mock_logger):
        """Test set_total switches from spinner to progress bar."""
        mock_console = MagicMock()
        mock_status = MagicMock()
        mock_progress = MagicMock()
        mock_progress.add_task.return_value = 0
        mock_console.status.return_value = mock_status

        with (
            patch("appinfra.ui.progress_logger._is_interactive", return_value=True),
            patch("appinfra.ui.progress_logger.RICH_AVAILABLE", True),
            patch("appinfra.ui.progress_logger.RichConsole", return_value=mock_console),
            patch(
                "appinfra.ui.progress_logger.RichProgress", return_value=mock_progress
            ),
        ):
            pl = ProgressLogger(mock_logger, message="Scanning...")
            with pl:
                # Initially in spinner mode
                assert pl._status is not None
                assert pl._progress is None

                # Switch to progress bar mode
                pl.set_total(50)

                # Spinner should be stopped
                mock_status.stop.assert_called()
                # Progress should be started
                mock_progress.start.assert_called()
                mock_progress.add_task.assert_called_with(
                    "Scanning...", total=50, completed=0
                )


class TestProgressLoggerRichNotAvailable:
    """Tests for ProgressLogger when Rich is not available."""

    def test_fallback_to_non_interactive(self, mock_logger):
        """Test falls back to non-interactive when Rich not available."""
        with (
            patch("appinfra.ui.progress_logger._is_interactive", return_value=True),
            patch("appinfra.ui.progress_logger.RICH_AVAILABLE", False),
        ):
            pl = ProgressLogger(mock_logger)
            # Should be non-interactive due to Rich not available
            assert pl._interactive is False

            with pl:
                pl.log("Test message")

            mock_logger.log.assert_called_once()


@pytest.mark.unit
class TestProgressLoggerJustification:
    """Tests for ProgressLogger progress bar justification."""

    def test_justify_right_creates_expanded_progress(self, mock_logger):
        """Test justify='right' creates progress bar with expanded text column."""
        mock_console = MagicMock()
        mock_progress = MagicMock()
        mock_progress.add_task.return_value = 0

        with (
            patch("appinfra.ui.progress_logger._is_interactive", return_value=True),
            patch("appinfra.ui.progress_logger.RICH_AVAILABLE", True),
            patch("appinfra.ui.progress_logger.RichConsole", return_value=mock_console),
            patch(
                "appinfra.ui.progress_logger.RichProgress", return_value=mock_progress
            ) as mock_progress_class,
        ):
            pl = ProgressLogger(mock_logger, total=100, justify="right")
            pl.__enter__()

            # Verify RichProgress was called with expand=True
            call_kwargs = mock_progress_class.call_args.kwargs
            assert call_kwargs.get("expand") is True

            pl.__exit__(None, None, None)


@pytest.mark.unit
class TestProgressLoggerUpdateWithMessage:
    """Tests for ProgressLogger update with message in progress bar mode."""

    def test_update_with_message_in_progress_mode(self, mock_logger):
        """Test update with message updates description in progress bar mode."""
        mock_console = MagicMock()
        mock_progress = MagicMock()
        mock_progress.add_task.return_value = 0

        with (
            patch("appinfra.ui.progress_logger._is_interactive", return_value=True),
            patch("appinfra.ui.progress_logger.RICH_AVAILABLE", True),
            patch("appinfra.ui.progress_logger.RichConsole", return_value=mock_console),
            patch(
                "appinfra.ui.progress_logger.RichProgress", return_value=mock_progress
            ),
        ):
            pl = ProgressLogger(mock_logger, total=100)
            with pl:
                pl.update(message="New message", advance=1)

            # Should update with both description and advance
            mock_progress.update.assert_called_with(
                0, description="New message", advance=1
            )


@pytest.mark.unit
class TestProgressLoggerStartDisplayEdgeCases:
    """Tests for _start_display edge cases."""

    def test_start_display_noop_when_not_interactive(self, mock_logger):
        """Test _start_display returns early when not interactive."""
        with patch("appinfra.ui.progress_logger._is_interactive", return_value=False):
            pl = ProgressLogger(mock_logger)
            # Call _start_display directly - should be no-op
            pl._start_display()
            assert pl._status is None
            assert pl._progress is None

    def test_start_display_noop_when_no_console(self, mock_logger):
        """Test _start_display returns early when console not set."""
        with (
            patch("appinfra.ui.progress_logger._is_interactive", return_value=True),
            patch("appinfra.ui.progress_logger.RICH_AVAILABLE", True),
        ):
            pl = ProgressLogger(mock_logger)
            # Force interactive but no console
            pl._interactive = True
            pl._console = None
            # Call _start_display directly - should be no-op
            pl._start_display()
            assert pl._status is None
            assert pl._progress is None
