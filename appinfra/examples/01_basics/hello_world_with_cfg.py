#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Hello World example using the appinfra.app.App class.

This example demonstrates:
- Using the App class for proper application framework integration
- Automatic logging argument parsing with add_log_default_args()
- Command-line overrides for all config options (level, location, colors, micros)
- Proper handler level adjustment - handlers use global level when it's more restrictive
- Multiple console handlers producing structured log output
- Clean, minimal output with no print statements

Usage:
    python hello_world_with_cfg.py -l info           # Uses infra.yaml levels
    python hello_world_with_cfg.py -l trace          # Overrides to trace - shows all levels
    python hello_world_with_cfg.py --log-location 2  # Override location depth
    python hello_world_with_cfg.py --log-micros      # Enable microseconds
    python hello_world_with_cfg.py -q                # Quiet mode - minimal output

Expected output:
- Text format on stdout (colored, human-readable)
- JSON format on stderr (structured data)
- Command-line arguments override infra.yaml configuration
- Integrated with the app framework lifecycle
- No print statements - all output through proper logging
"""

import pathlib
import sys

# Add the project root to the path
project_root = str(pathlib.Path(__file__).resolve().parents[3])
sys.path.append(project_root) if project_root not in sys.path else None

from appinfra.app import App, AppBuilder


class HelloWorldWithConfigApp(App):
    """Hello world application using the App framework with config-based logging."""

    def _run(self) -> int:
        """Run the hello world application with config-based logging."""

        cfg = self.setup_config(load_all=True)

        # Set up logging using the App framework method
        logger, _ = self.setup_logging_from_config(cfg)

        # Log the greeting to demonstrate multiple handlers
        logger.info("Hello, World!")

        # Test different log levels to demonstrate level filtering
        logger.trace("This is a trace message (TRACE level)")  # type: ignore[attr-defined]
        logger.debug("This is a debug message (DEBUG level)")
        logger.info("This is an info message (INFO level)")
        logger.warning("This is a warning message (WARNING level)")
        logger.error("This is an error message (ERROR level)")

        if self.args and self.args.quiet:
            logger.info("Quiet mode enabled - minimal output")

        return 0


def create_application() -> App:
    """Create the application using AppBuilder."""
    app = (
        AppBuilder("hello_world_with_cfg")
        .with_main_cls(HelloWorldWithConfigApp)
        .with_description(
            "Hello World example using appinfra.app.App class with config-based logging"
        )
        .build()
    )
    return app


def main() -> int:
    """Main function."""
    app = create_application()
    return app.main()


if __name__ == "__main__":
    sys.exit(main())
