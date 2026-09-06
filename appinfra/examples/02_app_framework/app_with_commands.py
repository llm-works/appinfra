#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

# ci-run: --help
# ci-run: hello
# ci-run: args

import sys
from pathlib import Path

# Allow running from a source checkout without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from appinfra.app.builder.app import AppBuilder


def hello_world(**kwargs):
    """Simple hello world command function."""
    print("hello, world!")
    return 0


def show_args(**kwargs):
    """Command that shows the parsed arguments."""
    print("arguments received:")
    for key, value in kwargs.items():
        print(f"  {key}: {value}")
    return 0


def create_application():
    """Create the application using AppBuilder with commands."""

    # Create the application with commands
    app = (
        AppBuilder("main_with_cmd")
        .with_description("Example application with commands using AppBuilder")
        # Configure logging
        .logging.with_level("info")
        .with_location(1)
        .done()
        # Add commands using with_cmd
        .tools.with_cmd(
            "hello", hello_world, aliases=["h"], help_text="Say hello to the world"
        )
        .done()
        .tools.with_cmd("args", show_args, help_text="Show parsed arguments")
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
