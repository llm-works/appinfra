# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Console wrapper with auto-detection and graceful degradation.

Provides a unified interface for terminal output that automatically
detects terminal capabilities and falls back gracefully when rich
is not available or in non-TTY environments.
"""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from rich.console import Console as RichConsole

# Check for rich availability
try:
    from rich.console import Console as RichConsole
    from rich.theme import Theme

    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False
    RichConsole = None  # type: ignore[assignment, misc]
    Theme = None  # type: ignore[assignment, misc]


def _is_interactive() -> bool:
    """Check if we're in an interactive terminal."""
    return sys.stdout.isatty() and sys.stderr.isatty()


def _should_use_color() -> bool:
    """Determine if color output should be used."""
    # Respect NO_COLOR environment variable (https://no-color.org/)
    if os.environ.get("NO_COLOR"):
        return False

    # Respect FORCE_COLOR for CI environments that support color
    if os.environ.get("FORCE_COLOR"):
        return True

    # Check if stdout is a TTY
    return _is_interactive()


# Default theme for appinfra
APPINFRA_THEME = {
    "info": "cyan",
    "warning": "yellow",
    "error": "red bold",
    "success": "green",
    "muted": "dim",
    "highlight": "bold magenta",
    "key": "bold blue",
    "value": "white",
}


class Console:
    """
    Console wrapper with auto-detection and graceful degradation.

    Provides rich terminal output when available, falls back to plain
    text when rich is not installed or in non-TTY environments.

    Example:
        console = Console()
        console.print("[green]Success![/green]")
        console.print_error("Something went wrong")

        # With table
        table = Table(title="Results")
        table.add_column("Name")
        table.add_row("test")
        console.print(table)
    """

    def __init__(
        self,
        *,
        force_terminal: bool | None = None,
        no_color: bool | None = None,
        quiet: bool = False,
        file: Any = None,
    ):
        """
        Initialize the console.

        Args:
            force_terminal: Force terminal mode (True/False) or auto-detect (None)
            no_color: Disable color output (True/False) or auto-detect (None)
            quiet: Suppress non-essential output
            file: Output file (default: sys.stdout)
        """
        self._quiet = quiet
        self._file = file or sys.stdout
        self._rich_console: RichConsole | None = None

        # Determine color mode
        if no_color is None:
            no_color = not _should_use_color()

        # Determine terminal mode
        if force_terminal is None:
            force_terminal = _is_interactive()

        self._no_color = no_color
        self._force_terminal = force_terminal

        # Initialize rich console if available and appropriate
        if RICH_AVAILABLE and not no_color:
            theme = Theme(APPINFRA_THEME) if Theme is not None else None
            self._rich_console = RichConsole(
                force_terminal=force_terminal,
                no_color=no_color,
                theme=theme,
                file=self._file,
            )

    @property
    def is_rich(self) -> bool:
        """Check if rich output is enabled."""
        return self._rich_console is not None

    @property
    def is_interactive(self) -> bool:
        """Check if running in interactive mode."""
        return self._force_terminal

    @property
    def quiet(self) -> bool:
        """Check if quiet mode is enabled."""
        return self._quiet

    def print(self, *args: Any, **kwargs: Any) -> None:
        """
        Print to the console.

        Supports rich markup when rich is available.

        Args:
            *args: Objects to print
            **kwargs: Additional arguments passed to rich.console.print() or print()
        """
        if self._quiet:
            return

        if self._rich_console:
            self._rich_console.print(*args, **kwargs)
        else:
            # Strip rich markup for plain output
            text = " ".join(self._strip_markup(str(arg)) for arg in args)
            print(text, file=self._file)

    def print_info(self, message: str) -> None:
        """Print an info message."""
        if self._quiet:
            return
        self.print(f"[info]{message}[/info]")

    def print_success(self, message: str) -> None:
        """Print a success message."""
        if self._quiet:
            return
        self.print(f"[success]{message}[/success]")

    def print_warning(self, message: str) -> None:
        """Print a warning message."""
        self.print(f"[warning]Warning:[/warning] {message}")

    def print_error(self, message: str) -> None:
        """Print an error message."""
        self.print(f"[error]Error:[/error] {message}")

    def rule(self, title: str = "") -> None:
        """Print a horizontal rule."""
        if self._quiet:
            return

        if self._rich_console:
            self._rich_console.rule(title)
        else:
            if title:
                width = 60
                title_part = f" {title} "
                padding = width - len(title_part)
                left = padding // 2
                right = padding - left
                print("-" * left + title_part + "-" * right, file=self._file)
            else:
                print("-" * 60, file=self._file)

    def status(self, message: str, *, spinner: str = "dots") -> Any:
        """
        Create a status context manager for showing progress.

        Args:
            message: Status message to display
            spinner: Spinner style (e.g., "dots", "dots2", "line", "arc", "moon")

        Returns:
            Context manager (rich.status.Status or no-op)

        Example:
            with console.status("Processing..."):
                do_work()

            with console.status("Deploying...", spinner="arc"):
                deploy()
        """
        if self._rich_console:
            return self._rich_console.status(message, spinner=spinner)
        else:
            # Return a no-op context manager
            return _NoOpContextManager(message, self._file, self._quiet)

    @staticmethod
    def _strip_markup(text: str) -> str:
        """Remove rich markup tags from text."""
        import re

        # Remove [tag] and [/tag] patterns
        return re.sub(r"\[/?[^\]]+\]", "", text)


class _NoOpContextManager:
    """No-op context manager for when rich is not available."""

    def __init__(self, message: str, file: Any, quiet: bool):
        self._message = message
        self._file = file
        self._quiet = quiet

    def __enter__(self) -> _NoOpContextManager:
        if not self._quiet:
            print(f"{self._message}...", file=self._file)
        return self

    def __exit__(self, *args: Any) -> None:
        pass

    def update(self, message: str) -> None:
        """Update status message (no-op in plain mode)."""
        pass


# Global console instance
_global_console: Console | None = None


def get_console(
    *,
    force_terminal: bool | None = None,
    no_color: bool | None = None,
    quiet: bool = False,
) -> Console:
    """
    Get or create the global console instance.

    Args:
        force_terminal: Force terminal mode
        no_color: Disable color output
        quiet: Suppress non-essential output

    Returns:
        Console instance
    """
    global _global_console

    # If arguments are provided, create a new console
    if force_terminal is not None or no_color is not None or quiet:
        return Console(
            force_terminal=force_terminal,
            no_color=no_color,
            quiet=quiet,
        )

    # Return or create the global console
    if _global_console is None:
        _global_console = Console()

    return _global_console


def reset_console() -> None:
    """Reset the global console instance."""
    global _global_console
    _global_console = None
