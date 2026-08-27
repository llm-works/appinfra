#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Graceful Shutdown Demonstration

This example demonstrates the graceful shutdown functionality including:
- SIGTERM/SIGINT signal handling
- Plugin cleanup (LIFO order)
- Shutdown hooks
- Database connection closing
- Log buffer flushing
- Ticker shutdown

Usage:
    # Run the demo
    python examples/06_advanced/graceful_shutdown_demo.py

    # Test graceful shutdown by pressing Ctrl+C or:
    kill -SIGTERM <pid>

Expected behavior:
    - All shutdown hooks trigger
    - Plugins clean up in reverse order
    - Database connections close
    - Buffered logs flush
    - Ticker stops gracefully
"""

import pathlib
import sys
import time

# Add the project root to the path
project_root = str(pathlib.Path(__file__).resolve().parents[3])
sys.path.append(project_root) if project_root not in sys.path else None

import appinfra.time
from appinfra.app import App, AppBuilder
from appinfra.app.builder.hook import HookBuilder, HookContext
from appinfra.app.builder.plugin import Plugin


class TickerPlugin(Plugin):
    """Plugin that manages ticker lifecycle."""

    def __init__(self):
        super().__init__("TickerPlugin")
        self.ticker = None

    def configure(self, builder) -> None:
        """Configure the plugin."""
        pass

    def initialize(self, application: App) -> None:
        """Initialize plugin and store ticker reference."""
        # Ticker will be set by the tool
        pass

    def set_ticker(self, ticker):
        """Set the ticker instance to manage."""
        self.ticker = ticker

    def cleanup(self, application: App) -> None:
        """Clean up ticker during shutdown."""
        if self.ticker is not None:
            application.lg.debug(f"[{self.name}] stopping ticker...")
            self.ticker.stop()
            application.lg.debug(f"[{self.name}] ticker stopped")


class ShutdownDemoPlugin(Plugin):
    """Demo plugin that shows cleanup during shutdown."""

    def __init__(self, name: str):
        super().__init__(name)
        self.resources_allocated = False

    def configure(self, builder) -> None:
        """Configure the plugin."""
        # Add a startup hook to simulate resource allocation
        builder.advanced.with_hook_builder(
            HookBuilder().on_startup(self._allocate_resources)
        )

    def initialize(self, application: App) -> None:
        """Initialize plugin resources."""
        application.lg.info(f"[{self.name}] plugin initialized")
        self.resources_allocated = True

    def cleanup(self, application: App) -> None:
        """Clean up plugin resources (called during shutdown)."""
        if self.resources_allocated:
            application.lg.info(f"[{self.name}] plugin cleanup - releasing resources")
            time.sleep(0.5)  # Simulate cleanup work
            self.resources_allocated = False
        else:
            application.lg.info(
                f"[{self.name}] plugin cleanup - no resources to release"
            )

    def _allocate_resources(self, context: HookContext):
        """Allocate resources on startup."""
        if context.application:
            context.application.lg.info(
                f"[{self.name}] startup hook - allocating resources"
            )


class TickerApp(App, appinfra.time.TickerHandler):
    """Application with ticker that demonstrates graceful shutdown."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._tick_count = 0
        self._last_t = None

    def _run(self) -> int:
        """Override _run to run ticker directly."""
        self.lg.info("=== Starting Graceful Shutdown Demo ===")
        self.lg.info("Press Ctrl+C (SIGINT) or send SIGTERM to test graceful shutdown")
        self.lg.info("Watch for shutdown hooks, plugin cleanup, and ticker shutdown")
        self.lg.info("")

        self._last_t = time.monotonic()

        # Create ticker that runs every second
        ticker = appinfra.time.Ticker(self.lg, self, secs=1.0)

        # Get the TickerPlugin and give it the ticker instance to manage

        plugin_manager = self.lifecycle._plugin_manager
        if plugin_manager:
            for plugin_name in plugin_manager._initialized_plugins:
                plugin = plugin_manager._plugins.get(plugin_name)
                if isinstance(plugin, TickerPlugin):
                    plugin.set_ticker(ticker)
                    break

        try:
            # Run the ticker (will be interrupted by signal)
            ticker.run()
        except KeyboardInterrupt:
            # This will be caught by the signal handler in most cases
            # but we keep it as a fallback
            self.lg.info("KeyboardInterrupt caught in ticker")

        return 0

    def ticker_start(self):
        """Called when the ticker starts."""
        self.lg.info(
            "ticker started",
            extra={"after": appinfra.time.since_str(self._last_t)},
        )
        self._last_t = time.monotonic()

    def ticker_tick(self):
        """Called on each tick execution."""
        self._tick_count += 1
        self.lg.info(
            f"tick #{self._tick_count}",
            extra={"after": appinfra.time.since_str(self._last_t)},
        )
        self._last_t = time.monotonic()

    def ticker_stop(self):
        """Called when the ticker stops."""
        self.lg.info(
            f"ticker stopped after {self._tick_count} ticks",
            extra={"after": appinfra.time.since_str(self._last_t)},
        )


def create_shutdown_hook(hook_name: str):
    """Create a shutdown hook with the given name."""

    def shutdown_hook(context: HookContext):
        if context.application:
            context.application.lg.info(
                f"[{hook_name}] shutdown hook triggered - performing cleanup"
            )
            time.sleep(0.3)  # Simulate cleanup work

    return shutdown_hook


def create_application():
    """Create the application with plugins and hooks to demonstrate shutdown."""

    # Configuration will be auto-loaded from etc directory during app.setup()
    # This includes logging settings like location_color from etc/infra.yaml

    app = (
        AppBuilder("shutdown_demo")
        .with_main_cls(TickerApp)
        .with_description(
            "Graceful shutdown demonstration with plugins, hooks, and ticker"
        )
        # Add multiple plugins to demonstrate LIFO cleanup order
        # TickerPlugin first (cleaned up last due to LIFO order)
        .tools.with_plugin(TickerPlugin())
        .with_plugin(ShutdownDemoPlugin("DatabasePlugin"))
        .with_plugin(ShutdownDemoPlugin("CachePlugin"))
        .with_plugin(ShutdownDemoPlugin("MetricsPlugin"))
        .done()
        # Add shutdown hooks
        .advanced.with_hook_builder(
            HookBuilder()
            .on_shutdown(create_shutdown_hook("PrimaryShutdown"), priority=10)
            .on_shutdown(create_shutdown_hook("SecondaryShutdown"), priority=5)
        )
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
