#!/usr/bin/env python3
"""
Hot-Reload Configuration Example

Demonstrates how to use ConfigWatcher for hot-reloading configuration
without restarting the application.

Features shown:
- Enabling hot-reload via AppBuilder
- Accessing watcher via app.config_watcher
- Section callbacks for arbitrary config sections
- Manual reload trigger

Usage:
    python hot_reload_example.py serve

Then edit examples/04_configuration/etc/hot_reload.yaml while running
to see changes applied automatically.

Requirements:
    pip install appinfra[hotreload]
"""

import pathlib
import sys
import time
from typing import Any

# Add the project root to the path
project_root = str(pathlib.Path(__file__).resolve().parents[3])
sys.path.insert(0, project_root)

from appinfra.app.builder import AppBuilder
from appinfra.app.tools import Tool, ToolConfig


class ServeCommand(Tool):
    """Long-running server that responds to config changes."""

    def __init__(self, parent: Tool | None = None) -> None:
        super().__init__(
            parent,
            ToolConfig(name="serve", help_text="Start server with hot-reload enabled"),
        )

    def setup(self, **kwargs: Any) -> None:
        """Register section callbacks on startup."""
        self.request_count = 0
        self.timeout = 30
        self.max_connections = 100

        # Access watcher via app
        watcher = self.app.config_watcher
        if watcher:
            # Register callback for server config section
            watcher.add_section_callback("server", self._on_server_config_changed)
            self.lg.info("registered server config callback")
        else:
            self.lg.warning("hot-reload not enabled, config changes require restart")

    def _on_server_config_changed(self, server_config: Any) -> None:
        """Called when server section in config changes."""
        old_timeout = self.timeout
        old_max = self.max_connections

        self.timeout = server_config.get("timeout", 30)
        self.max_connections = server_config.get("max_connections", 100)

        self.lg.info(
            "server config updated",
            extra={
                "timeout": f"{old_timeout} -> {self.timeout}",
                "max_connections": f"{old_max} -> {self.max_connections}",
            },
        )

    def run(self, **kwargs: Any) -> int:
        """Simulate a long-running server."""
        self.lg.info(
            "server started",
            extra={"timeout": self.timeout, "max_connections": self.max_connections},
        )
        self.lg.info("edit etc/hot_reload.yaml to see hot-reload in action")
        self.lg.info("press Ctrl+C to stop")

        try:
            while True:
                # Simulate processing requests
                self.request_count += 1
                if self.request_count % 5 == 0:
                    self.lg.debug(
                        "heartbeat",
                        extra={
                            "requests": self.request_count,
                            "timeout": self.timeout,
                        },
                    )
                time.sleep(1)
        except KeyboardInterrupt:
            self.lg.info("server stopped", extra={"total_requests": self.request_count})
            return 0


class ReloadCommand(Tool):
    """Manually trigger config reload."""

    def __init__(self, parent: Tool | None = None) -> None:
        super().__init__(
            parent,
            ToolConfig(name="reload", help_text="Manually trigger config reload"),
        )

    def run(self, **kwargs: Any) -> int:
        """Force immediate config reload."""
        watcher = self.app.config_watcher
        if watcher:
            self.lg.info("triggering manual reload...")
            watcher.reload_now()
            self.lg.info("reload complete")
            return 0
        else:
            self.lg.error("hot-reload not enabled")
            return 1


class StatusCommand(Tool):
    """Show hot-reload status."""

    def __init__(self, parent: Tool | None = None) -> None:
        super().__init__(
            parent,
            ToolConfig(name="status", help_text="Show hot-reload watcher status"),
        )

    def run(self, **kwargs: Any) -> int:
        """Display watcher status."""
        watcher = self.app.config_watcher
        if watcher:
            print("Hot-reload enabled: Yes")
            print(f"Watcher running: {watcher.is_running()}")
            print(f"Config paths: {watcher._config_paths}")
            print(f"Debounce: {watcher._debounce_ms}ms")
            return 0
        else:
            print("Hot-reload enabled: No")
            return 0


def create_app():
    """Create app with hot-reload enabled."""
    return (
        AppBuilder("hot-reload-demo")
        # Load config from relative path (not from --etc-dir)
        .with_config_file(
            "examples/04_configuration/etc/hot_reload.yaml", from_etc_dir=False
        )
        .logging.with_level("debug")
        .with_hot_reload(enabled=True, debounce_ms=500)
        .done()
        .tools.with_tools(ServeCommand(), ReloadCommand(), StatusCommand())
        .done()
        .build()
    )


if __name__ == "__main__":
    app = create_app()
    raise SystemExit(app.main())
