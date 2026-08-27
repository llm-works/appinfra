# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Rich terminal output module for appinfra.

Provides beautiful terminal output with tables, panels, progress bars,
enhanced help formatting, and interactive prompts. Gracefully degrades
when rich/questionary is not installed or in non-TTY environments.

Example:
    from . import console, Table, Panel, prompts

    # Print styled text
    console.print("[green]Success![/green] Operation completed.")

    # Create a table
    table = Table(title="Results")
    table.add_column("Name")
    table.add_column("Status")
    table.add_row("server-1", "[green]OK[/]")
    console.print(table)

    # Show a panel
    panel = Panel("Important message", title="Notice")
    console.print(panel)

    # Interactive prompts
    if prompts.confirm("Delete files?"):
        env = prompts.select("Environment:", ["dev", "staging", "prod"])
"""

from . import prompts
from .console import Console, get_console
from .help import RichHelpFormatter, get_help_formatter
from .progress_logger import ProgressLogger
from .prompts import (
    INQUIRER_AVAILABLE,
    TERM_MENU_AVAILABLE,
    NonInteractiveError,
    confirm,
    multiselect,
    password,
    select,
    select_scrollable,
    select_table,
    text,
)

# Re-export rich components with fallbacks
try:
    from rich.panel import Panel
    from rich.progress import Progress
    from rich.table import Table

    RICH_AVAILABLE = True
except ImportError:
    from .fallback import Panel, Progress, Table  # type: ignore[assignment]

    RICH_AVAILABLE = False

# Default console instance
console = get_console()

__all__ = [
    # Console
    "Console",
    "console",
    "get_console",
    # Rich components
    "Panel",
    "Progress",
    "ProgressLogger",
    "Table",
    "RICH_AVAILABLE",
    # Help formatter
    "RichHelpFormatter",
    "get_help_formatter",
    # Prompts
    "prompts",
    "confirm",
    "text",
    "password",
    "select",
    "select_scrollable",
    "select_table",
    "multiselect",
    "NonInteractiveError",
    "INQUIRER_AVAILABLE",
    "TERM_MENU_AVAILABLE",  # Backward compatibility alias
]
