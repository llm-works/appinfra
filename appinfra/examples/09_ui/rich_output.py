#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Rich Terminal Output Example

Demonstrates beautiful terminal output using the appinfra.ui module:
- Styled text with colors and formatting
- Tables for structured data
- Panels for highlighted content
- Progress bars for long operations

Run: python examples/09_ui/rich_output.py
"""

import sys
import time
from pathlib import Path

# Allow running from a source checkout without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from appinfra.ui import RICH_AVAILABLE, Panel, Progress, Table, console


def demo_styled_text():
    """Demonstrate styled text output."""
    console.rule("Styled Text")

    console.print("Basic text output")
    console.print("[bold]Bold text[/bold]")
    console.print("[italic]Italic text[/italic]")
    console.print("[red]Red text[/red]")
    console.print("[green]Green text[/green]")
    console.print("[bold magenta]Bold magenta text[/bold magenta]")
    console.print()

    # Convenience methods
    console.print_info("This is an info message")
    console.print_success("This is a success message")
    console.print_warning("This is a warning message")
    console.print_error("This is an error message")
    console.print()


def demo_tables():
    """Demonstrate table output."""
    console.rule("Tables")

    # Basic table
    table = Table(title="Server Status")
    table.add_column("Server", style="cyan")
    table.add_column("Status", style="green")
    table.add_column("CPU", style="yellow")
    table.add_column("Memory", style="magenta")

    table.add_row("web-01", "[green]Online[/green]", "45%", "2.1 GB")
    table.add_row("web-02", "[green]Online[/green]", "62%", "3.4 GB")
    table.add_row("db-01", "[yellow]Degraded[/yellow]", "89%", "7.2 GB")
    table.add_row("cache-01", "[red]Offline[/red]", "0%", "0 GB")

    console.print(table)
    console.print()


def demo_panels():
    """Demonstrate panel output."""
    console.rule("Panels")

    # Info panel
    panel = Panel(
        "This is important information that should stand out.\n"
        "Panels are great for highlighting key messages.",
        title="Notice",
    )
    console.print(panel)
    console.print()

    # Warning panel
    warning = Panel(
        "[yellow]Database connection pool is at 90% capacity.\n"
        "Consider scaling up or optimizing queries.[/yellow]",
        title="Warning",
    )
    console.print(warning)
    console.print()


def demo_progress():
    """Demonstrate progress bar."""
    console.rule("Progress Bars")

    # Simulate processing files
    files = ["config.yaml", "data.json", "users.csv", "logs.txt", "cache.db"]

    with Progress() as progress:
        task = progress.add_task("Processing files...", total=len(files))

        for filename in files:
            time.sleep(0.3)  # Simulate work
            progress.update(task, advance=1)

    console.print_success("All files processed!")
    console.print()


def demo_status():
    """Demonstrate status spinner."""
    console.rule("Status Spinner")

    with console.status("Connecting to server..."):
        time.sleep(1)

    console.print_success("Connected!")

    with console.status("Fetching data..."):
        time.sleep(0.5)

    console.print_success("Data fetched!")
    console.print()


def main():
    """Run all demos."""
    console.print()
    console.print("[bold blue]Rich Terminal Output Demo[/bold blue]")
    console.print(f"Rich available: {RICH_AVAILABLE}")
    console.print()

    demo_styled_text()
    demo_tables()
    demo_panels()
    demo_progress()
    demo_status()

    console.rule("Demo Complete")


if __name__ == "__main__":
    main()
