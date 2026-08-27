#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

import pathlib
import sys

# Add the project root to the path
project_root = str(pathlib.Path(__file__).resolve().parents[3])
sys.path.append(project_root) if project_root not in sys.path else None

from argparse import ArgumentParser
from typing import Any

from appinfra.app import App
from appinfra.app.builder.app import AppBuilder
from appinfra.app.tools.base import Tool, ToolConfig


class DemoTool(Tool):
    """Demo tool implementation."""

    def __init__(self, parent: Tool | None = None) -> None:
        config = ToolConfig(name="demo", aliases=["d"], help_text="Demo tool")
        super().__init__(parent, config)

    def add_args(self, parser: ArgumentParser) -> None:
        parser.add_argument("-d", action="store_true", help="demo")

    def run(self, **kwargs: Any) -> int:
        self.lg.info("running demo...")
        return 0


def create_application() -> App:
    """Create the application using AppBuilder."""

    # Create tool instance
    demo_tool = DemoTool()

    # Create the application with tools
    app = (
        AppBuilder("main")
        .with_description("Simple demo application using AppBuilder")
        # Configure logging
        .logging.with_level("info")
        .with_location(1)
        .done()
        # Add tool
        .tools.with_tool(demo_tool)
        .done()
        .build()
    )

    return app


def main() -> int:
    """Main function."""
    app = create_application()
    return app.main()


if __name__ == "__main__":
    sys.exit(main())
