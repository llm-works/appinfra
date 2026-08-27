#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

import pathlib
import sys

# Add the project root to the path
project_root = str(pathlib.Path(__file__).resolve().parents[3])
sys.path.append(project_root) if project_root not in sys.path else None

from appinfra.app import App, AppBuilder


class HelloWorldApp(App):
    """Hello world application that derives from App."""

    def add_args(self) -> None:
        # Add default logging arguments
        super().add_args()

        # Add hello world specific arguments
        self.parser.add_argument("--silent", action="store_true", help="silent mode")

    def _run(self) -> int:
        """Run the hello world application."""
        # Since we're using with_main_cls, there are no tools registered
        # so we can directly run our logic
        silent = getattr(self.args, "silent", False)

        if silent:
            self.lg.info("Silent mode enabled")
        else:
            self.lg.info("Hello, World!")
            self.lg.info("Hello, World 2!")
        return 0


def create_application() -> App:
    """Create the application using AppBuilder with HelloWorldApp."""
    # Create the application with main class
    app = (
        AppBuilder("hello_world")
        .with_main_cls(HelloWorldApp)
        .with_description("Simple hello world application")
        .build()
    )

    return app


def main() -> int:
    """Main function."""
    app = create_application()
    return app.main()


if __name__ == "__main__":
    sys.exit(main())
