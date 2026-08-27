# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Progress logger with spinner/progress bar and logging coordination.

Provides a context manager that displays a spinner or progress bar while
coordinating with logging output - pausing the visual display when logs
are written, then resuming.

Only shows visual elements on TTY; falls back to plain logging otherwise.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import TYPE_CHECKING, Any

from ..log import Logger

if TYPE_CHECKING:
    from rich.console import Console as RichConsole
    from rich.progress import Progress as RichProgress
    from rich.progress import TaskID
    from rich.status import Status as RichStatus

# Check for rich availability
try:
    from rich.console import Console as RichConsole
    from rich.progress import (
        BarColumn,
        SpinnerColumn,
        TaskID,
        TaskProgressColumn,
        TextColumn,
        TimeElapsedColumn,
        TimeRemainingColumn,
    )
    from rich.progress import (
        Progress as RichProgress,
    )
    from rich.table import Column

    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False
    TaskID = int  # type: ignore[misc, assignment]


def _is_interactive() -> bool:
    """Check if we're in an interactive terminal."""
    # Respect APPINFRA_NON_INTERACTIVE environment variable
    if os.environ.get("APPINFRA_NON_INTERACTIVE", "").lower() in ("1", "true", "yes"):
        return False
    return sys.stdout.isatty() and sys.stderr.isatty()


class ProgressLogger:
    """
    Context manager for spinner/progress bar with logging coordination.

    Shows a spinner (unknown duration) or progress bar (known total) while
    allowing log messages to be written cleanly by pausing the visual display.

    Only shows visual elements on TTY; in non-interactive mode, just passes
    through to the logger.

    Example - Spinner mode (unknown duration):
        with ProgressLogger(lg, "Processing...") as pl:
            for item in items:
                process(item)
                pl.log("Processed item")

    Example - Progress bar mode (known total):
        with ProgressLogger(lg, "Downloading...", total=100) as pl:
            for chunk in chunks:
                download(chunk)
                pl.update(advance=1)

    Example - Switch mid-operation:
        with ProgressLogger(lg, "Scanning...") as pl:
            items = scan_directory()  # Spinner while scanning
            pl.set_total(len(items))  # Switch to progress bar
            for item in items:
                process(item)
                pl.update()
    """

    def __init__(
        self,
        lg: Logger,
        message: str = "Working...",
        total: int | None = None,
        spinner: str = "dots",
        justify: str = "left",
        expand: bool = False,
        bar_style: str = "bar.complete",
    ):
        """
        Initialize the progress logger.

        Args:
            lg: Logger instance to use for log messages
            message: Status/progress message to display
            total: Total items for progress bar (None = spinner mode)
            spinner: Spinner style for spinner mode (e.g., "dots", "arc", "moon")
            justify: Progress bar justification ("left" or "right"). Use "right"
                     to anchor progress bar to right edge, preventing jumping
                     when message text has variable length.
            expand: When True, progress bar fills terminal width (omits text column).
                    Useful when message is empty and you want full-width display.
            bar_style: Style for completed portion of bar (e.g., "green", "blue",
                       "bar.complete"). Default is Rich's "bar.complete" (Monokai pink).
        """
        self._lg = lg
        self._message = message
        self._total = total
        self._spinner = spinner
        self._justify = justify
        self._expand = expand
        self._bar_style = bar_style
        self._completed = 0

        # Determine if we should show visual elements
        self._interactive = _is_interactive() and RICH_AVAILABLE

        # Rich objects (created on __enter__)
        self._console: RichConsole | None = None
        self._status: RichStatus | None = None  # Spinner mode
        self._progress: RichProgress | None = None  # Progress bar mode
        self._task_id: TaskID | None = None

    def __enter__(self) -> ProgressLogger:
        """Start the spinner or progress bar."""
        if not self._interactive:
            return self

        self._console = RichConsole(file=sys.stdout)
        self._start_display()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Stop the spinner or progress bar."""
        self._stop_display()

    def _create_progress_bar(self) -> RichProgress:
        """Create a Rich Progress bar with appropriate justification."""
        # Right-justify: TextColumn with ratio=1 pushes bar to right edge
        if self._justify == "right":
            text_col = TextColumn(
                "[progress.description]{task.description}",
                table_column=Column(ratio=1),
            )
            bar_col, expand = BarColumn(complete_style=self._bar_style), True
        else:
            text_col = TextColumn("[progress.description]{task.description}")
            # bar_width=None allows bar to expand when expand=True
            bar_col = BarColumn(
                bar_width=None if self._expand else 40,
                complete_style=self._bar_style,
            )
            expand = self._expand

        return RichProgress(
            SpinnerColumn(),
            text_col,
            bar_col,
            TaskProgressColumn(),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            console=self._console,
            transient=True,
            expand=expand,
        )

    def _start_display(self) -> None:
        """Start the appropriate display mode."""
        if not self._interactive or not self._console:
            return

        if self._total is None:
            # Spinner mode
            self._status = self._console.status(self._message, spinner=self._spinner)
            self._status.start()
        else:
            # Progress bar mode
            self._progress = self._create_progress_bar()
            self._progress.start()
            self._task_id = self._progress.add_task(self._message, total=self._total)

    def _stop_display(self) -> None:
        """Stop the current display."""
        if self._status:
            self._status.stop()
            self._status = None
        if self._progress:
            self._progress.stop()
            self._progress = None
        self._task_id = None

    def _pause(self) -> None:
        """Pause the display for logging."""
        if self._status:
            self._status.stop()
        if self._progress:
            self._progress.stop()

    def _resume(self) -> None:
        """Resume the display after logging."""
        if self._status:
            self._status.start()
        if self._progress:
            self._progress.start()

    def log(
        self,
        msg: str,
        level: int = logging.INFO,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """
        Log a message, pausing the spinner/progress bar if active.

        Args:
            msg: Log message
            level: Log level (default: INFO)
            *args: Additional positional args for logger
            **kwargs: Additional keyword args for logger (e.g., extra={})
        """
        self._pause()
        self._lg.log(level, msg, *args, **kwargs)
        self._resume()

    def debug(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Log a debug message."""
        self.log(msg, logging.DEBUG, *args, **kwargs)

    def info(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Log an info message."""
        self.log(msg, logging.INFO, *args, **kwargs)

    def warning(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Log a warning message."""
        self.log(msg, logging.WARNING, *args, **kwargs)

    def error(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Log an error message."""
        self.log(msg, logging.ERROR, *args, **kwargs)

    def update(
        self,
        message: str | None = None,
        advance: int = 1,
        completed: int | None = None,
    ) -> None:
        """
        Update the display message and/or progress.

        Args:
            message: New message to display (optional)
            advance: Amount to advance progress (progress bar mode)
            completed: Set absolute completion value (progress bar mode)
        """
        if message:
            self._message = message

        # Always track completed count (even in non-interactive mode)
        if completed is not None:
            self._completed = completed
        else:
            self._completed += advance

        if self._progress and self._task_id is not None:
            # Progress bar mode - update progress display
            update_kwargs: dict[str, Any] = {}
            if message:
                update_kwargs["description"] = message
            if completed is not None:
                update_kwargs["completed"] = completed
            else:
                update_kwargs["advance"] = advance
            self._progress.update(self._task_id, **update_kwargs)
        elif self._status and message:
            # Spinner mode - just update message
            self._status.update(message)

    def set_total(self, total: int) -> None:
        """
        Switch from spinner mode to progress bar mode.

        Args:
            total: Total number of items for progress tracking
        """
        if not self._interactive:
            self._total = total
            return

        # Stop spinner if active
        if self._status:
            self._status.stop()
            self._status = None

        # Start progress bar
        self._total = total
        if self._console:
            self._progress = self._create_progress_bar()
            self._progress.start()
            self._task_id = self._progress.add_task(
                self._message, total=total, completed=self._completed
            )

    @property
    def is_interactive(self) -> bool:
        """Check if running in interactive mode with visual display."""
        return self._interactive

    @property
    def total(self) -> int | None:
        """Get the total for progress bar mode (None if spinner mode)."""
        return self._total

    @property
    def completed(self) -> int:
        """Get the current completion count."""
        return self._completed
