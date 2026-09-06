#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

# ci-run: --help
# ci-run: first
# ci-run: second

import sys
from pathlib import Path

# Allow running from a source checkout without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from appinfra.app.builder.app import AppBuilder
from appinfra.app.tools.base import Tool, ToolConfig


class StatusTool(Tool):
    """Status tool implementation."""

    def __init__(self, parent=None):
        config = ToolConfig(name="status", aliases=["s"], help_text="status tool")
        super().__init__(parent, config)

    def add_args(self, parser):
        parser.add_argument("-x", action="store_true", help="x flag")

    def run(self, **kwargs):
        self.lg.info("running status...")
        return 0


class FirstTool(Tool):
    """First tool with subcommands."""

    def __init__(self, parent=None):
        config = ToolConfig(
            name="first", aliases=["f1"], help_text="First tool with subcommands"
        )
        super().__init__(parent, config)
        # Use framework's add_tool method with default subcommand
        self._status = self.add_tool(StatusTool(self), default="status")
        # Add info command in constructor
        self.add_cmd("info", aliases=["i"], run_func=self._run_info)

    def add_args(self, parser):
        parser.add_argument("-d", action="store_true", help="x switch")

    def setup(self, **kwargs):
        """Set up FirstTool-specific configuration."""
        super().setup(**kwargs)
        # FirstTool-specific setup logic here
        # Note: Framework automatically handles group/subtool setup
        self.lg.debug("firstTool setup complete")

    def run(self, **kwargs):
        self.lg.info("running 1...")
        return self.group.run(**kwargs)

    def _run_info(self):
        self.lg.info("running 1 info...")


class SecondTool(Tool):
    """Second tool implementation."""

    def __init__(self, parent=None):
        config = ToolConfig(name="second", aliases=["s2"], help_text="Second tool")
        super().__init__(parent, config)

    def add_args(self, parser):
        parser.add_argument("-y", action="store_true", help="y switch")

    def run(self, **kwargs):
        self.lg.info("running 2...")
        return 0


def create_application():
    """Create the application using AppBuilder with Tool classes."""

    # Create tool instances
    first_tool = FirstTool()
    second_tool = SecondTool()

    # Create the application with tools
    app = (
        AppBuilder("main_with_group")
        .with_description("Example application with tool classes using AppBuilder")
        # Configure logging
        .logging.with_level("info")
        .with_location(1)
        .done()
        # Add tools directly (StatusTool is now a subtool of FirstTool)
        .tools.with_tool(first_tool)
        .done()
        .tools.with_tool(second_tool)
        .done()
        .build()
    )

    return app


def main():
    """Main function."""
    app = create_application()
    return app.main()


if __name__ == "__main__":
    sys.exit(main())
