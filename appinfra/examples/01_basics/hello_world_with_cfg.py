#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Hello World example using the appinfra.app.App class.

This example demonstrates:
- Using the App class for proper application framework integration
- Declaring the config source with the builder's config block; the file is
  loaded into ``self.config`` before ``_run``
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

import sys
from pathlib import Path

# Allow running from a source checkout without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from appinfra.app import App, AppBuilder


class HelloWorldWithConfigApp(App):
    """Hello world application using the App framework with config-based logging."""

    def _run(self) -> int:
        """Run the hello world application with config-based logging."""

        # Set up logging from the config the spec resolved to during setup
        logger, _ = self.setup_logging_from_config(self.config)

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
        .with_standard_args()
        # appinfra's packaged base is etc/infra.yaml (its one deviation from rule 2)
        .config.with_spec("llm-works", "appinfra", filename="infra.yaml")
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
