# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Rich help formatter for argparse.

Provides beautiful --help output using rich when available,
with graceful degradation to standard argparse formatting.
"""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

# Check for rich availability
try:
    from rich.console import Console
    from rich.table import Table
    from rich.text import Text

    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False


class RichHelpFormatter(argparse.HelpFormatter):
    """
    Argparse help formatter that uses rich for beautiful output.

    Falls back to standard formatting when rich is not available.

    Example:
        parser = argparse.ArgumentParser(
            formatter_class=RichHelpFormatter
        )
    """

    def __init__(
        self,
        prog: str,
        indent_increment: int = 2,
        max_help_position: int = 30,
        width: int | None = None,
    ):
        """Initialize the formatter."""
        super().__init__(prog, indent_increment, max_help_position, width)
        self._rich_output: list[Any] = []

    def _build_rich_help(self, console: Any) -> None:
        """Build rich help output to console."""
        usage = self._format_usage_rich()
        if usage:
            console.print(usage)
            console.print()
        if self._root_section._group_actions:  # type: ignore[attr-defined]
            description = self._format_description_rich()
            if description:
                console.print(description)
                console.print()
        self._format_actions_rich(console)
        epilog = self._format_epilog_rich()
        if epilog:
            console.print()
            console.print(epilog)

    def format_help(self) -> str:
        """Format the help message."""
        if not RICH_AVAILABLE:
            return super().format_help()
        from io import StringIO

        console = Console(file=StringIO(), force_terminal=True)
        self._build_rich_help(console)
        output: str = console.file.getvalue()  # type: ignore[attr-defined]
        return output

    def _format_usage_rich(self) -> Any:
        """Format usage line with rich."""
        if not RICH_AVAILABLE:
            return None

        usage = Text()
        usage.append("Usage: ", style="bold yellow")
        usage.append(self._prog, style="bold")

        # Add usage pattern
        if self._actions:  # type: ignore[attr-defined]
            usage.append(" ")
            usage.append(self._format_usage_args(), style="dim")

        return usage

    def _format_usage_args(self) -> str:
        """Format the usage arguments."""
        parts = []

        for action in self._actions:  # type: ignore[attr-defined]
            if action.option_strings:
                # Optional argument
                if action.required:
                    parts.append(
                        f"{action.option_strings[0]} {action.metavar or 'VALUE'}"
                    )
                else:
                    parts.append(f"[{action.option_strings[0]}]")
            elif action.dest != "help":
                # Positional argument
                if action.nargs in ("?", "*"):
                    parts.append(f"[{action.dest.upper()}]")
                elif action.nargs == "+":
                    parts.append(f"{action.dest.upper()} [...]")
                else:
                    parts.append(action.dest.upper())

        return " ".join(parts)

    def _format_description_rich(self) -> Any:
        """Format description with rich."""
        if not RICH_AVAILABLE or not self._prog:
            return None

        # Get description from parser if available
        # This is a simplified version - full implementation would
        # access the parser's description
        return None

    def _format_actions_rich(self, console: Any) -> None:
        """Format actions (arguments/options) as a rich table."""
        if not RICH_AVAILABLE:
            return

        positionals, optionals = self._split_actions()
        self._print_positionals(console, positionals)
        self._print_optionals(console, optionals)

    def _split_actions(self) -> tuple[list, list]:
        """Separate positional and optional arguments."""
        positionals = []
        optionals = []
        for action in self._actions:  # type: ignore[attr-defined]
            if action.option_strings:
                optionals.append(action)
            else:
                positionals.append(action)
        return positionals, optionals

    def _print_positionals(self, console: Any, positionals: list) -> None:
        """Print positional arguments table."""
        if not positionals:
            return
        console.print("[bold]Arguments:[/bold]")
        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column(style="green")
        table.add_column()
        for action in positionals:
            if action.dest == "help":
                continue
            table.add_row(action.dest.upper(), action.help or "")
        console.print(table)
        console.print()

    def _print_optionals(self, console: Any, optionals: list) -> None:
        """Print optional arguments table."""
        if not optionals:
            return
        console.print("[bold]Options:[/bold]")
        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column(style="cyan")
        table.add_column()
        for action in optionals:
            opts = ", ".join(action.option_strings)
            if action.metavar:
                opts += f" {action.metavar}"
            elif action.type and action.type is not bool:
                opts += f" {getattr(action.type, '__name__', 'VALUE').upper()}"
            help_text = action.help or ""
            if action.default and action.default != argparse.SUPPRESS:
                if action.default is not None:
                    help_text += f" [dim](default: {action.default})[/dim]"
            table.add_row(opts, help_text)
        console.print(table)

    def _format_epilog_rich(self) -> Any:
        """Format epilog with rich."""
        # Would access parser's epilog if available
        return None


def get_help_formatter() -> type[argparse.HelpFormatter]:
    """
    Get the appropriate help formatter.

    Returns RichHelpFormatter if rich is available,
    otherwise returns the standard argparse formatter.

    Returns:
        Help formatter class
    """
    if RICH_AVAILABLE:
        return RichHelpFormatter
    return argparse.HelpFormatter
