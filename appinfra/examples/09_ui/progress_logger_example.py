#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

# ci-run: --help
# ci-run: all
# ci-timeout: 25

"""
Progress Logger Example

Demonstrates ProgressLogger for coordinating spinners/progress bars with logging:
- Spinner mode for unknown duration tasks
- Progress bar mode for known total tasks (with elapsed time and ETA)
- Right-justified mode for stable progress bar with variable-length messages
- Switching from spinner to progress bar mid-operation
- Automatic pause/resume when logging

Run:
    python examples/09_ui/progress_logger_example.py              # Show help
    python examples/09_ui/progress_logger_example.py spinner      # Spinner demo
    python examples/09_ui/progress_logger_example.py progress     # Progress bar demo (shows ETA)
    python examples/09_ui/progress_logger_example.py justified    # Right-justified demo
    python examples/09_ui/progress_logger_example.py switch       # Mode switching demo
    python examples/09_ui/progress_logger_example.py all          # Run all demos
"""

import sys
import time
from pathlib import Path

# Allow running from a source checkout without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from appinfra.app import AppBuilder
from appinfra.app.tools import Tool, ToolConfig
from appinfra.ui import ProgressLogger


class SpinnerDemo(Tool):
    """Demonstrate spinner mode with periodic logging."""

    def _create_config(self) -> ToolConfig:
        return ToolConfig(
            name="spinner",
            help_text="Spinner mode demo - unknown duration with periodic logs",
        )

    def run(self, **kwargs) -> int:
        self.lg.info("Starting spinner demo...")

        # Spinner mode - no total specified
        with ProgressLogger(self.lg, "Processing items...") as pl:
            for i in range(10):
                time.sleep(0.3)
                # Log every 3 items - spinner pauses, logs, resumes
                if (i + 1) % 3 == 0:
                    pl.info(f"Processed {i + 1} items so far")

        self.lg.info("Spinner demo complete!")
        return 0


class ProgressDemo(Tool):
    """Demonstrate progress bar mode with periodic logging."""

    def _create_config(self) -> ToolConfig:
        return ToolConfig(
            name="progress",
            help_text="Progress bar mode demo - known total with periodic logs",
        )

    def run(self, **kwargs) -> int:
        self.lg.info("Starting progress bar demo...")

        total_items = 20

        # Progress bar mode - shows: spinner, message, bar, count, elapsed, ETA
        with ProgressLogger(self.lg, "Downloading files...", total=total_items) as pl:
            for i in range(total_items):
                time.sleep(0.15)
                pl.update(advance=1)
                # Log every 5 items
                if (i + 1) % 5 == 0:
                    pl.info(f"Downloaded {i + 1}/{total_items} files")

        self.lg.info("Progress bar demo complete!")
        return 0


class SwitchDemo(Tool):
    """Demonstrate switching from spinner to progress bar."""

    def _create_config(self) -> ToolConfig:
        return ToolConfig(
            name="switch",
            help_text="Mode switching demo - spinner to progress bar",
        )

    def run(self, **kwargs) -> int:
        self.lg.info("Starting mode switch demo...")

        with ProgressLogger(self.lg, "Scanning directory...") as pl:
            # Phase 1: Spinner while "scanning"
            pl.info("Phase 1: Scanning (spinner mode)")
            for _ in range(5):
                time.sleep(0.2)

            # "Found" some items - switch to progress bar
            found_items = 15
            pl.info(f"Found {found_items} items, switching to progress bar")
            pl.set_total(found_items)

            # Phase 2: Progress bar while "processing"
            pl.update(message="Processing items...")
            for i in range(found_items):
                time.sleep(0.1)
                pl.update(advance=1)
                if (i + 1) % 5 == 0:
                    pl.info(f"Processed {i + 1}/{found_items} items")

        self.lg.info("Mode switch demo complete!")
        return 0


class JustifiedDemo(Tool):
    """Demonstrate right-justified progress bar for variable-length messages."""

    def _create_config(self) -> ToolConfig:
        return ToolConfig(
            name="justified",
            help_text="Right-justified progress bar demo - stable bar position",
        )

    def run(self, **kwargs) -> int:
        self.lg.info("Starting right-justified demo...")
        self.lg.info("Notice how the progress bar stays anchored to the right edge:\n")

        # Packages with varying name lengths
        packages = [
            "cli",
            "core_utils",
            "submodules/infer",
            "submodules/models/large",
            "api",
        ]

        # Right-justified: bar stays fixed as message length changes
        with ProgressLogger(
            self.lg, "Syncing...", total=len(packages), justify="right"
        ) as pl:
            for i, pkg in enumerate(packages):
                pl.update(message=f"Syncing {pkg}...")
                time.sleep(1.0)

        self.lg.info("\nRight-justified demo complete!")
        return 0


class AllDemo(Tool):
    """Run all demos sequentially."""

    def _create_config(self) -> ToolConfig:
        return ToolConfig(
            name="all",
            help_text="Run all demos sequentially",
        )

    def run(self, **kwargs) -> int:
        self.lg.info("Running all demos...\n")

        # Get other tools from registry
        app = self.app
        tools = ["spinner", "progress", "justified", "switch"]

        for tool_name in tools:
            self.lg.info(f"\n{'=' * 50}")
            self.lg.info(f"Running {tool_name} demo")
            self.lg.info(f"{'=' * 50}\n")
            tool = app.registry.get_tool(tool_name)
            if tool:
                # Sibling tools were never selected, so the lifecycle has not
                # set them up; do it here before running them.
                app.lifecycle.setup_tool(tool)
                tool.run()
            time.sleep(0.5)

        self.lg.info("\nAll demos complete!")
        return 0


# Build and run the app
app = (
    AppBuilder("progress-logger-demo")
    .with_description(
        "Demonstrates ProgressLogger for coordinated logging with spinners/progress"
    )
    .tools.with_tool(SpinnerDemo())
    .with_tool(ProgressDemo())
    .with_tool(JustifiedDemo())
    .with_tool(SwitchDemo())
    .with_tool(AllDemo())
    .done()
    .build()
)

if __name__ == "__main__":
    sys.exit(app.main())
