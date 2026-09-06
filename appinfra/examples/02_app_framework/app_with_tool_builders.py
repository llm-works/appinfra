#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

# ci-run: --help
# ci-run: status
# ci-run: info

import sys
from pathlib import Path

# Allow running from a source checkout without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from appinfra.app.builder.app import AppBuilder
from appinfra.app.builder.tool import ToolBuilder


def status_handler(tool, **kwargs):
    """Handle status command."""
    tool.lg.info("running status...")
    return 0


def first_handler(tool, **kwargs):
    """Handle first command."""
    tool.lg.info("running 1...")
    return 0


def info_handler(tool, **kwargs):
    """Handle info command."""
    tool.lg.info("running 1 info...")
    return 0


def second_handler(tool, **kwargs):
    """Handle second command."""
    tool.lg.info("running 2...")
    return 0


def _create_tool_builders():
    """Create and return all tool builders for the application."""
    first_tool = (
        ToolBuilder("first")
        .with_help("First tool")
        .with_alias("f1")
        .with_argument("-d", action="store_true", help="x switch")
        .with_run_function(first_handler)
    )
    status_tool = (
        ToolBuilder("status")
        .with_help("status tool")
        .with_alias("s")
        .with_argument("-x", action="store_true", help="x flag")
        .with_run_function(status_handler)
    )
    info_tool = (
        ToolBuilder("info")
        .with_help("info command")
        .with_alias("i")
        .with_run_function(info_handler)
    )
    second_tool = (
        ToolBuilder("second")
        .with_help("Second tool")
        .with_alias("s2")
        .with_argument("-y", action="store_true", help="y switch")
        .with_run_function(second_handler)
    )

    return [first_tool, status_tool, info_tool, second_tool]


def create_application():
    """Create the application using AppBuilder."""
    tools = _create_tool_builders()

    # Create the application with tools
    app_builder = (
        AppBuilder("main_with_group")
        .with_description("Example application with tools using AppBuilder")
        .logging.with_level("info")
        .with_location(1)
        .done()
    )

    # Add all tools
    for tool in tools:
        app_builder = app_builder.tools.with_tool_builder(tool).done()

    # Finalize and build
    app = app_builder.build()

    return app


def main():
    """Main function."""
    app = create_application()

    try:
        return app.main()
    except KeyboardInterrupt:
        print("\napp interrupted by user")
        return 1
    except Exception as e:
        print(f"application error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
