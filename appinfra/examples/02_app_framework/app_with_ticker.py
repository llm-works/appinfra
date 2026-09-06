#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

# ci-run: --interval 0.5
# ci-stop: 4

import sys
import time
from pathlib import Path

# Allow running from a source checkout without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import appinfra
from appinfra.app import App, AppBuilder


class TickerApp(App, appinfra.time.TickerHandler):
    """Ticker tool implementation that combines Tool and TickerHandler."""

    def add_args(self):
        # Add default logging arguments
        super().add_args()

        # Add ticker-specific arguments
        self.parser.add_argument(
            "--interval",
            type=float,
            default=1.0,
            help="ticker interval in seconds (default: 1.0)",
        )
        self.parser.add_argument(
            "--cont",
            action="store_true",
            help="run in continuous mode (no scheduling)",
        )

    def _run(self) -> int:
        """Run the ticker tool."""
        args = self.args
        assert args is not None  # parsed before _run() is called
        interval = args.interval
        continuous = args.cont

        self.lg.info(
            "starting ticker", extra={"interval": interval, "continuous": continuous}
        )
        self._last_t = time.monotonic()

        # Create ticker instance
        ticker = appinfra.time.Ticker(
            self.lg, self, secs=None if continuous else interval
        )

        # Run the ticker
        ticker.run()

        return 0

    def ticker_start(self):
        """Called when the ticker starts."""
        self.lg.info(
            "ticker started",
            extra={"after": appinfra.time.since_str(self._last_t, precise=True)},
        )
        self._last_t = time.monotonic()

    def ticker_tick(self):
        """Called on each tick execution."""
        self.lg.info(
            "tick", extra={"after": appinfra.time.since_str(self._last_t, precise=True)}
        )
        self._last_t = time.monotonic()


def create_application():
    """Create the application using AppBuilder with TickerTool."""

    # Create the application with ticker tool
    app = (
        AppBuilder("main_with_ticker")
        .with_main_cls(TickerApp)
        .with_description("Example application with ticker tool using AppBuilder")
        .build()
    )

    return app


def main():
    """Main function."""
    app = create_application()
    return app.main()


if __name__ == "__main__":
    sys.exit(main())
