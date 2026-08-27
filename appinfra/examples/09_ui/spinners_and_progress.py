#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Spinners and Progress Bars Example

Demonstrates various spinner styles and multiple concurrent progress bars:
- Different spinner animations
- Multiple progress bars running concurrently
- Custom progress bar styles
- Task-based progress tracking

Run:
    python examples/09_ui/spinners_and_progress.py              # Show help
    python examples/09_ui/spinners_and_progress.py spinners     # Spinners only
    python examples/09_ui/spinners_and_progress.py progress     # Progress bars only
    python examples/09_ui/spinners_and_progress.py all          # Run all demos
"""

import sys
import time
from pathlib import Path

# Add parent to path for development
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from appinfra.app import AppBuilder
from appinfra.app.tools import Tool, ToolConfig
from appinfra.ui import RICH_AVAILABLE, console

if RICH_AVAILABLE:
    from rich.live import Live
    from rich.progress import (
        BarColumn,
        DownloadColumn,
        FileSizeColumn,
        MofNCompleteColumn,
        Progress,
        ProgressColumn,
        SpinnerColumn,
        TaskProgressColumn,
        TextColumn,
        TimeElapsedColumn,
        TimeRemainingColumn,
        TotalFileSizeColumn,
        TransferSpeedColumn,
    )
    from rich.style import Style
    from rich.table import Table
    from rich.text import Text

    class CustomBarColumn(ProgressColumn):
        """A progress bar with customizable characters for different visual thickness."""

        # Preset character styles
        STYLES = {
            "thin": ("─", "─", " "),  # ─────────
            "medium": ("━", "━", " "),  # ━━━━━━━━━ (rich default)
            "thick": ("█", "█", "░"),  # ████████░░░
            "block": ("▓", "▓", "░"),  # ▓▓▓▓▓▓▓▓░░░
            "double": ("═", "═", " "),  # ═════════
            "dots": ("●", "●", "○"),  # ●●●●●●○○○○
            "arrows": ("▶", "▶", "▷"),  # ▶▶▶▶▶▶▷▷▷▷
            "squares": ("■", "■", "□"),  # ■■■■■■□□□□
        }

        def __init__(
            self,
            bar_width: int = 40,
            style: str = "thick",
            complete_color: str = "green",
            incomplete_color: str = "white",
        ):
            super().__init__()
            self.bar_width = bar_width
            chars = self.STYLES.get(style, self.STYLES["thick"])
            self.complete_char = chars[0]
            self.head_char = chars[1]
            self.incomplete_char = chars[2]
            self.complete_color = complete_color
            self.incomplete_color = incomplete_color

        def render(self, task) -> Text:
            """Render the progress bar."""
            if task.total is None:
                return Text("?" * self.bar_width)

            completed = int(self.bar_width * task.completed / task.total)
            remaining = self.bar_width - completed

            bar = Text()
            if completed > 0:
                bar.append(self.complete_char * completed, style=self.complete_color)
            if remaining > 0:
                bar.append(
                    self.incomplete_char * remaining,
                    style=Style(color=self.incomplete_color, dim=True),
                )
            return bar


# All available spinner styles (73 total)
ALL_SPINNERS = [
    "aesthetic",
    "arc",
    "arrow",
    "arrow2",
    "arrow3",
    "balloon",
    "balloon2",
    "betaWave",
    "bounce",
    "bouncingBall",
    "bouncingBar",
    "boxBounce",
    "boxBounce2",
    "christmas",
    "circle",
    "circleHalves",
    "circleQuarters",
    "clock",
    "dots",
    "dots10",
    "dots11",
    "dots12",
    "dots2",
    "dots3",
    "dots4",
    "dots5",
    "dots6",
    "dots7",
    "dots8",
    "dots8Bit",
    "dots9",
    "dqpb",
    "earth",
    "flip",
    "grenade",
    "growHorizontal",
    "growVertical",
    "hamburger",
    "hearts",
    "layer",
    "line",
    "line2",
    "material",
    "monkey",
    "moon",
    "noise",
    "pipe",
    "point",
    "pong",
    "runner",
    "shark",
    "simpleDots",
    "simpleDotsScrolling",
    "smiley",
    "squareCorners",
    "squish",
    "star",
    "star2",
    "toggle",
    "toggle10",
    "toggle11",
    "toggle12",
    "toggle13",
    "toggle2",
    "toggle3",
    "toggle4",
    "toggle5",
    "toggle6",
    "toggle7",
    "toggle8",
    "toggle9",
    "triangle",
    "weather",
]


def demo_spinners():
    """Show different spinner styles."""
    console.rule("Spinner Styles")

    if not RICH_AVAILABLE:
        console.print("Rich not available - spinners require rich library")
        return

    console.print(f"Showing all {len(ALL_SPINNERS)} spinner styles:\n")

    for spinner_name in ALL_SPINNERS:
        with console.status(f"[bold green]{spinner_name}...", spinner=spinner_name):
            time.sleep(2)
        console.print(f"  [cyan]{spinner_name}[/]")

    console.print()


def demo_basic_progress():
    """Show basic progress bar."""
    console.rule("Basic Progress Bar")

    if not RICH_AVAILABLE:
        console.print("Processing...")
        for i in range(10):
            time.sleep(0.2)
            console.print(f"  Step {i + 1}/10")
        return

    with Progress() as progress:
        task = progress.add_task("[green]Processing...", total=100)
        while not progress.finished:
            progress.update(task, advance=2)
            time.sleep(0.05)

    console.print()


def _run_concurrent_downloads(files: list[tuple[str, int]]) -> None:
    """Run concurrent download simulation with progress bars."""
    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.fields[filename]}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeRemainingColumn(),
    ) as progress:
        tasks = {
            fn: progress.add_task("download", total=sz, filename=fn) for fn, sz in files
        }
        while not progress.finished:
            for filename, size in files:
                task_id = tasks[filename]
                if not progress.tasks[task_id].finished:
                    progress.update(task_id, advance=size / 50)
            time.sleep(0.1)


def demo_multiple_progress_bars():
    """Show multiple concurrent progress bars."""
    console.rule("Multiple Progress Bars")
    if not RICH_AVAILABLE:
        console.print("Multiple progress bars require rich library")
        return

    files = [
        ("config.yaml", 50),
        ("database.sql", 200),
        ("assets.tar.gz", 500),
        ("dependencies.lock", 80),
    ]
    _run_concurrent_downloads(files)
    console.print_success("All downloads complete!")
    console.print()


def _demo_style_minimal():
    """Demo style 1: minimal spinner."""
    console.print("[bold]Style 1: Minimal with spinner[/]")
    with Progress(
        SpinnerColumn("dots"),
        TextColumn("[progress.description]{task.description}"),
        transient=True,
    ) as progress:
        progress.add_task("Building project...", total=None)
        time.sleep(2)
    console.print_success("Build complete")
    console.print()


def _demo_style_detailed():
    """Demo style 2: detailed progress."""
    console.print("[bold]Style 2: Detailed progress[/]")
    with Progress(
        TextColumn("[bold]{task.description}"),
        BarColumn(bar_width=40),
        TaskProgressColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
    ) as progress:
        for name, total in [("Compiling", 100), ("Testing", 50), ("Packaging", 30)]:
            task = progress.add_task(name, total=total)
            while not progress.tasks[task].finished:
                progress.update(task, advance=1)
                time.sleep(0.02)
    console.print()


def _demo_style_compact():
    """Demo style 3: compact percentage."""
    console.print("[bold]Style 3: Compact[/]")
    with Progress(
        TextColumn("{task.description}"),
        BarColumn(bar_width=20, complete_style="green", finished_style="green"),
        TextColumn("{task.percentage:>3.0f}%"),
    ) as progress:
        task = progress.add_task("Installing", total=100)
        while not progress.tasks[task].finished:
            progress.update(task, advance=1)
            time.sleep(0.02)
    console.print()


def _demo_basic_styles():
    """Demo styles 1-3: minimal, detailed, compact."""
    _demo_style_minimal()
    _demo_style_detailed()
    _demo_style_compact()


def _demo_style_download():
    """Demo style 4: download with speed."""
    console.print("[bold]Style 4: Download with speed[/]")
    with Progress(
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
    ) as progress:
        task = progress.add_task("Downloading", total=1024 * 1024 * 50)  # 50 MB
        while not progress.tasks[task].finished:
            progress.update(task, advance=1024 * 512)  # 512 KB chunks
            time.sleep(0.05)
    console.print()


def _demo_style_filesize():
    """Demo style 5: file size display."""
    console.print("[bold]Style 5: File processing with sizes[/]")
    with Progress(
        SpinnerColumn(),
        TextColumn("{task.description}"),
        BarColumn(),
        FileSizeColumn(),
        TextColumn("/"),
        TotalFileSizeColumn(),
        TimeElapsedColumn(),
    ) as progress:
        task = progress.add_task("Processing data.csv", total=1024 * 1024 * 100)
        while not progress.tasks[task].finished:
            progress.update(task, advance=1024 * 1024 * 2)  # 2 MB chunks
            time.sleep(0.05)
    console.print()


def _demo_style_indeterminate():
    """Demo style 6: indeterminate/pulsing progress."""
    console.print("[bold]Style 6: Indeterminate (pulsing)[/]")
    with Progress(
        SpinnerColumn(),
        TextColumn("[bold magenta]{task.description}"),
        BarColumn(pulse_style="magenta"),
    ) as progress:
        progress.add_task("Searching...", total=None)
        time.sleep(3)
    console.print_success("Search complete")
    console.print()


def _demo_file_styles():
    """Demo styles 4-6: download, file size, indeterminate."""
    _demo_style_download()
    _demo_style_filesize()
    _demo_style_indeterminate()


def _demo_style_colorful():
    """Demo style 7: colorful multi-column."""
    console.print("[bold]Style 7: Colorful multi-column[/]")
    with Progress(
        SpinnerColumn("dots12", style="cyan"),
        TextColumn("[bold cyan]{task.description}"),
        BarColumn(complete_style="cyan", finished_style="green"),
        TaskProgressColumn(),
        TextColumn("•"),
        TimeElapsedColumn(),
        TextColumn("•"),
        TimeRemainingColumn(),
    ) as progress:
        task = progress.add_task("Analyzing", total=100)
        while not progress.tasks[task].finished:
            progress.update(task, advance=1)
            time.sleep(0.03)
    console.print()


def _demo_style_ascii_emoji():
    """Demo styles 8-9: ASCII and emoji."""
    console.print("[bold]Style 8: ASCII style[/]")
    with Progress(
        TextColumn("{task.description}"),
        BarColumn(
            bar_width=30, style="white", complete_style="white", finished_style="white"
        ),
        TextColumn("[{task.completed}/{task.total}]"),
    ) as progress:
        task = progress.add_task("Loading", total=50)
        while not progress.tasks[task].finished:
            progress.update(task, advance=1)
            time.sleep(0.04)
    console.print()

    console.print("[bold]Style 9: With status emoji[/]")
    with Progress(
        TextColumn("🚀"),
        TextColumn("{task.description}"),
        BarColumn(bar_width=25),
        TaskProgressColumn(),
        TextColumn("⏱"),
        TimeElapsedColumn(),
    ) as progress:
        task = progress.add_task("Deploying", total=100)
        while not progress.tasks[task].finished:
            progress.update(task, advance=1)
            time.sleep(0.02)
    console.print()


def _demo_style_steps():
    """Demo style 10: step counter."""
    console.print("[bold]Style 10: Step counter[/]")
    steps = ["Initialize", "Validate", "Process", "Finalize", "Cleanup"]
    with Progress(
        TextColumn("[bold]{task.description}"),
        MofNCompleteColumn(),
        BarColumn(),
        TimeElapsedColumn(),
    ) as progress:
        task = progress.add_task("Steps", total=len(steps))
        for step in steps:
            progress.update(task, description=f"Step: {step}")
            time.sleep(0.5)
            progress.update(task, advance=1)
    console.print()


def _demo_decorative_styles():
    """Demo styles 7-10: colorful, ASCII, emoji, steps."""
    _demo_style_colorful()
    _demo_style_ascii_emoji()
    _demo_style_steps()


def _demo_width_bar(style_num: int, width: int, name: str, color: str) -> None:
    """Demo a single width style bar."""
    console.print(f"[bold]Style {style_num}: {name} bar (width={width})[/]")
    with Progress(
        TextColumn("{task.description}"),
        BarColumn(bar_width=width, complete_style=color),
        TaskProgressColumn(),
    ) as progress:
        task = progress.add_task(name, total=100)
        while not progress.tasks[task].finished:
            progress.update(task, advance=2)
            time.sleep(0.02)
    console.print()


def _demo_width_styles():
    """Demo styles 11-13: width variations."""
    _demo_width_bar(11, 15, "Narrow", "cyan")
    _demo_width_bar(12, 40, "Standard", "green")
    _demo_width_bar(13, 80, "Wide", "magenta")


def _demo_thickness_styles():
    """Demo styles 14-21: bar character thickness variations."""
    console.rule("Bar Character Styles (Thickness)")

    bar_styles = [
        ("thin", "cyan", "Thin lines"),
        ("medium", "blue", "Medium (default)"),
        ("thick", "green", "Thick blocks"),
        ("block", "yellow", "Shaded blocks"),
        ("double", "magenta", "Double lines"),
        ("dots", "red", "Dots"),
        ("arrows", "cyan", "Arrows"),
        ("squares", "white", "Squares"),
    ]

    for i, (style_name, color, description) in enumerate(bar_styles, start=14):
        console.print(f"[bold]Style {i}: {description} ({style_name})[/]")
        with Progress(
            TextColumn("{task.description}"),
            CustomBarColumn(bar_width=40, style=style_name, complete_color=color),
            TaskProgressColumn(),
        ) as progress:
            task = progress.add_task(style_name.capitalize(), total=100)
            while not progress.tasks[task].finished:
                progress.update(task, advance=2)
                time.sleep(0.02)
        console.print()


def demo_custom_progress_styles():
    """Show different progress bar styles."""
    console.rule("Progress Bar Styles")

    if not RICH_AVAILABLE:
        console.print("Custom progress styles require rich library")
        return

    _demo_basic_styles()
    _demo_file_styles()
    _demo_decorative_styles()
    _demo_width_styles()
    _demo_thickness_styles()


DEPLOYMENT_STAGES = [
    ("🔨 Building", "dots", 30),
    ("🧪 Testing", "dots2", 50),
    ("📦 Packaging", "arc", 20),
    ("🚀 Deploying", "dots12", 40),
    ("✅ Verifying", "bounce", 15),
]


def _run_deployment_stages() -> None:
    """Run deployment with progress for each stage."""
    with Progress(
        SpinnerColumn(),
        TextColumn("[bold]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
    ) as progress:
        for name, spinner, total in DEPLOYMENT_STAGES:
            task = progress.add_task(name, total=total)
            while not progress.tasks[task].finished:
                progress.update(task, advance=1)
                time.sleep(0.05)


def demo_deployment_simulation():
    """Simulate a deployment with multiple stages."""
    console.rule("Deployment Simulation")
    if not RICH_AVAILABLE:
        console.print("Deployment simulation requires rich library")
        for stage in ["Build", "Test", "Push", "Deploy", "Verify"]:
            console.print(f"  {stage}...")
            time.sleep(0.5)
    else:
        _run_deployment_stages()
    console.print()
    console.print_success("Deployment complete!")
    console.print()


def _get_service_status(started: bool, pct: int) -> tuple[str, str]:
    """Get status and progress display for a service."""
    if not started:
        return "[dim]Pending[/]", "[dim]—[/]"
    if pct >= 100:
        return "[green]✓ Ready[/]", "[green]100%[/]"
    return "[yellow]● Starting[/]", f"[yellow]{pct}%[/]"


def _generate_status_table(step: int) -> Table:
    """Generate a status table for the current step."""
    table = Table(title="Service Status", show_header=True)
    table.add_column("Service", style="cyan")
    table.add_column("Status")
    table.add_column("Progress")
    services = [
        ("web-server", step >= 2, step * 20 if step < 5 else 100),
        ("api-gateway", step >= 3, max(0, (step - 1) * 25) if step < 5 else 100),
        ("database", step >= 1, max(0, (step - 0) * 25) if step < 5 else 100),
        ("cache", step >= 4, max(0, (step - 2) * 33) if step < 5 else 100),
    ]
    for name, started, pct in services:
        status, prog = _get_service_status(started, pct)
        table.add_row(name, status, prog)
    return table


def demo_live_table():
    """Show a live-updating table (like Claude Code's display)."""
    console.rule("Live Status Table")
    if not RICH_AVAILABLE:
        console.print("Live table requires rich library")
        return

    with Live(_generate_status_table(0), refresh_per_second=4) as live:
        for step in range(6):
            time.sleep(0.8)
            live.update(_generate_status_table(step))
    console.print()


class SpinnersTool(Tool):
    """Show all 73 available spinner styles."""

    def __init__(self, parent=None):
        config = ToolConfig(
            name="spinners",
            aliases=["s"],
            help_text="Demo all 73 spinner styles (2 seconds each)",
        )
        super().__init__(parent, config)

    def run(self, **kwargs):
        console.print()
        console.print("[bold blue]Spinners Demo[/bold blue]")
        console.print(f"Rich available: {RICH_AVAILABLE}")
        console.print()
        demo_spinners()
        console.rule("Demo Complete")
        return 0


class ProgressTool(Tool):
    """Show all progress bar styles."""

    def __init__(self, parent=None):
        config = ToolConfig(
            name="progress",
            aliases=["p"],
            help_text="Demo 10 different progress bar styles",
        )
        super().__init__(parent, config)

    def run(self, **kwargs):
        console.print()
        console.print("[bold blue]Progress Bars Demo[/bold blue]")
        console.print(f"Rich available: {RICH_AVAILABLE}")
        console.print()
        demo_basic_progress()
        demo_multiple_progress_bars()
        demo_custom_progress_styles()
        demo_deployment_simulation()
        demo_live_table()
        console.rule("Demo Complete")
        return 0


class AllTool(Tool):
    """Run all demos (spinners + progress bars)."""

    def __init__(self, parent=None):
        config = ToolConfig(
            name="all",
            aliases=["a"],
            help_text="Run all demos (spinners + progress bars)",
        )
        super().__init__(parent, config)

    def run(self, **kwargs):
        console.print()
        console.print("[bold blue]Spinners and Progress Bars Demo[/bold blue]")
        console.print(f"Rich available: {RICH_AVAILABLE}")
        console.print()
        demo_spinners()
        demo_basic_progress()
        demo_multiple_progress_bars()
        demo_custom_progress_styles()
        demo_deployment_simulation()
        demo_live_table()
        console.rule("Demo Complete")
        return 0


def main():
    """Build and run the demo app."""
    app = (
        AppBuilder("ui-demo")
        .with_description("Demo spinners and progress bars from appinfra.ui")
        .logging.with_level("warning")
        .done()
        .tools.with_tool(SpinnersTool())
        .with_tool(ProgressTool())
        .with_tool(AllTool())
        .done()
        .build()
    )
    return app.main()


if __name__ == "__main__":
    sys.exit(main())
