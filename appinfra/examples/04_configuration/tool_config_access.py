#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

# ci-run: --help
# ci-run: status
# ci-run: serve

"""
Accessing YAML Config from Tools Example

This example demonstrates how to access the application's YAML configuration
from within a Tool subclass using the `self.app.config` property.

What This Example Demonstrates:
- Accessing YAML config via `self.app.config`
- Using dot notation: `self.app.config.server.host`
- Using dict-style access: `self.app.config.get("server", {})`
- The distinction between Tool config and App config

Running the Example:
    # From the infra project root
    ~/.venv/bin/python examples/04_configuration/tool_config_access.py serve

Key Concepts:
- `self.config` on a Tool is the ToolConfig (name, aliases, help)
- `self.app.config` is the YAML config loaded by the App
- `self.app` traverses the parent chain to find the root App instance
- This works regardless of intermediate parents (e.g., ToolGroups)
"""

# Add the project root to the path
from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from appinfra.dot_dict import DotDict

# Allow running from a source checkout without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from appinfra.app.builder import AppBuilder
from appinfra.app.tools.base import Tool, ToolConfig

if TYPE_CHECKING:
    from appinfra.dot_dict import DotDict


class ServeTool(Tool):
    """Example tool that accesses the App's YAML configuration."""

    def _create_config(self) -> ToolConfig:
        return ToolConfig(
            name="serve",
            aliases=["s"],
            help_text="Start the server",
            description="Demonstrates accessing YAML config from a Tool",
        )

    def add_args(self, parser: Any) -> None:
        """Add tool-specific arguments."""
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print config without starting server",
        )

    def configure(self) -> None:
        """
        Configure the tool using YAML config.

        This method demonstrates accessing the App's YAML configuration
        via self.app.config. This is the recommended way to access
        application configuration from within a Tool.
        """
        # Access YAML config via self.app.config
        # Use dict-style access with fallbacks for safety
        self.server_cfg = self.app.config.get("server", {})
        self.engine_cfg = self.app.config.get("engine", {})

        # Extract specific values with defaults
        self.host = self.server_cfg.get("host", "127.0.0.1")
        self.port = self.server_cfg.get("port", 8080)
        self.workers = self.engine_cfg.get("workers", 4)

        self.lg.debug(f"Configured server: {self.host}:{self.port}")

    def _print_tool_config(self) -> None:
        """Print Tool config (metadata about the tool)."""
        print("1. Tool config (self.config) - metadata about the tool:")
        print(f"   name: {self.config.name}")
        print(f"   aliases: {self.config.aliases}")
        print(f"   help: {self.config.help_text}")

    def _print_app_config(self) -> None:
        """Print App config (YAML configuration values)."""
        print("\n2. App config (self.app.config) - YAML configuration:")
        print(f"   server.host: {self.host}")
        print(f"   server.port: {self.port}")
        print(f"   engine.workers: {self.workers}")

    def _print_access_patterns(self) -> None:
        """Demonstrate alternative access patterns."""
        print("\n3. Alternative access patterns:")
        if hasattr(self.app.config, "server"):
            print(f"   Dot notation: self.app.config.server = {self.app.config.server}")
        logging_cfg = self.app.config.get("logging", {})
        print(f"   Dict-style: self.app.config.get('logging', {{}}) = {logging_cfg}")
        log_level = self.app.config.get("logging", {}).get("level", "info")
        print(
            f"   Nested: config.get('logging', {{}}).get('level', 'info') = {log_level}"
        )

    def run(self, **kwargs: Any) -> int:
        """Run the tool."""
        self.lg.info("ServeTool running")
        print("\n=== Accessing Config from Tool ===\n")
        self._print_tool_config()
        self._print_app_config()
        self._print_access_patterns()
        if not self.args.dry_run:
            print(
                f"\n[Would start server on {self.host}:{self.port} with {self.workers} workers]"
            )
        return 0


class StatusTool(Tool):
    """Another tool demonstrating config access in a multi-tool app."""

    def _create_config(self) -> ToolConfig:
        return ToolConfig(
            name="status",
            aliases=["st"],
            help_text="Show server status",
        )

    def configure(self) -> None:
        """Access shared config."""
        # Same pattern - access via self.app.config
        self.server_cfg = self.app.config.get("server", {})

    def run(self, **kwargs: Any) -> int:
        """Show status using config values."""
        host = self.server_cfg.get("host", "127.0.0.1")
        port = self.server_cfg.get("port", 8080)
        print(f"\nServer configured at: {host}:{port}")
        print("Status: Not running (this is a demo)")
        return 0


def _create_sample_config() -> DotDict:
    """Create sample YAML config (normally loaded from etc/infra.yaml)."""
    from appinfra.dot_dict import DotDict

    return DotDict(
        server={"host": "0.0.0.0", "port": 8080},
        engine={"workers": 4, "timeout": 30},
        logging={"level": "info"},
    )


def main() -> int:
    """Build and run the example application."""
    app = (
        AppBuilder("config-demo")
        .with_description("Demonstrates accessing YAML config from Tools")
        .with_config(_create_sample_config())
        .tools.with_tool(ServeTool())
        .with_tool(StatusTool())
        .done()
        .logging.with_level("info")
        .done()
        .build()
    )
    return app.main()


if __name__ == "__main__":
    sys.exit(main())
