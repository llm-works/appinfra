"""ServerPlugin for AppBuilder integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from ..builder.plugin import Plugin
from ..tools.base import Tool, ToolConfig
from .runtime.server import Server

if TYPE_CHECKING:
    from ..builder.app import AppBuilder
    from ..core.app import App

logger = logging.getLogger("fastapi.plugin")


class ServeTool(Tool):
    """
    Tool that starts the HTTP server.

    Registered by ServerPlugin to add a "serve" command to CLI apps.
    """

    def __init__(
        self,
        server: Server,
        name: str = "serve",
        help_text: str = "Start the HTTP server",
    ) -> None:
        """
        Initialize serve tool.

        Args:
            server: Server instance to start
            name: Tool name (default: "serve")
            help_text: Help text for CLI
        """
        config = ToolConfig(
            name=name,
            aliases=[],
            help_text=help_text,
            description=f"Start the {server.name} HTTP server",
        )
        super().__init__(parent=None, config=config)
        self._server = server

    def _create_config(self) -> ToolConfig:
        """Create default config (called if config not provided)."""
        return ToolConfig(
            name="serve",
            aliases=[],
            help_text="Start the HTTP server",
        )

    def run(self, **kwargs: Any) -> int:
        """
        Run the HTTP server.

        Returns:
            Exit code (0 for success, non-zero for error)
        """
        self.lg.info(
            "starting server...",
            extra={"host": self._server.config.host, "port": self._server.config.port},
        )

        try:
            self._server.start()
            return 0
        except KeyboardInterrupt:
            self.lg.info("server interrupted by user")
            self._server.stop()
            return 130  # Standard exit code for SIGINT
        except Exception as e:
            self.lg.error("server error", extra={"exception": e})
            self._server.stop()
            return 1


class ServerPlugin(Plugin):
    """
    Plugin to integrate FastAPI server with AppBuilder CLI apps.

    Allows CLI applications to also serve HTTP by adding a "serve" tool
    that starts the configured server.

    Example:
        server = (ServerBuilder("myapi")
            .with_port(8000)
            .routes.with_route("/health", health).done()
            .build())

        app = (AppBuilder("myapp")
            .tools.with_plugin(ServerPlugin(server)).done()
            .build())

        # CLI: myapp serve
    """

    def __init__(
        self,
        server: Server,
        tool_name: str = "serve",
        tool_help: str = "Start the HTTP server",
    ) -> None:
        """
        Initialize plugin.

        Args:
            server: Configured Server instance
            tool_name: Name for the serve command (default: "serve")
            tool_help: Help text for the serve command
        """
        super().__init__(name="ServerPlugin")
        self._server = server
        self._tool_name = tool_name
        self._tool_help = tool_help
        self._tool: ServeTool | None = None

    def configure(self, builder: AppBuilder) -> None:
        """
        Register serve tool with AppBuilder.

        Called during AppBuilder.build() phase.
        """
        self._tool = ServeTool(
            server=self._server,
            name=self._tool_name,
            help_text=self._tool_help,
        )
        # Add tool to builder's tool list
        builder._tools.append(self._tool)

    def initialize(self, application: App) -> None:
        """
        Initialize plugin with the application.

        Called after App is fully constructed.
        """
        # Set the tool's parent to the app for proper logging chain
        if self._tool is not None:
            self._tool.set_parent(application)

    def cleanup(self, application: App) -> None:
        """
        Stop server on app shutdown.

        Called during app shutdown phase.
        """
        if self._server.is_running:
            logger.info("stopping server...")
            self._server.stop()
