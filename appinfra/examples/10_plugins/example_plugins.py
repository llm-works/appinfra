# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Example plugin implementations for the AppBuilder framework.

This module demonstrates how to create custom plugins for database,
authentication, logging, and metrics functionality.
"""

import sys
from pathlib import Path

# Allow running from a source checkout without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from appinfra.app.builder.app import AppBuilder
from appinfra.app.builder.hook import HookBuilder
from appinfra.app.builder.middleware import MiddlewareBuilder
from appinfra.app.builder.plugin import Plugin
from appinfra.app.builder.tool import ToolBuilder
from appinfra.app.core.app import App


class DatabasePlugin(Plugin):
    """Plugin for database functionality."""

    def __init__(self, connection_string: str | None = None):
        super().__init__("database")
        self.connection_string = connection_string
        self._connection = None

    def configure(self, builder: AppBuilder) -> None:
        """Configure database tools and hooks."""
        # Add database tools
        builder.tools.with_tool_builder(
            ToolBuilder("migrate")
            .with_help("Run database migrations")
            .with_run_function(self._migrate)
        )

        builder.tools.with_tool_builder(
            ToolBuilder("db-status")
            .with_help("Check database status")
            .with_run_function(self._check_status)
        )

        # Add database hooks
        builder.advanced.with_hook_builder(
            HookBuilder().on_startup(self._connect_db).on_shutdown(self._disconnect_db)
        )

    def initialize(self, application: App) -> None:
        """Initialize database connection."""
        if self.connection_string:
            # Initialize database connection
            pass

    def cleanup(self, application: App) -> None:
        """Clean up database connection."""
        if self._connection:
            # Close database connection
            pass

    def _migrate(self, tool, **kwargs):
        """Run database migrations."""
        tool.lg.info("running database migrations...")
        # Implementation would go here
        return 0

    def _check_status(self, tool, **kwargs):
        """Check database status."""
        tool.lg.info("checking database status...")
        # Implementation would go here
        return 0

    def _connect_db(self, context):
        """Connect to database on startup."""
        if self.connection_string:
            # Connect to database
            pass

    def _disconnect_db(self, context):
        """Disconnect from database on shutdown."""
        if self._connection:
            # Disconnect from database
            pass


class AuthPlugin(Plugin):
    """Plugin for authentication functionality."""

    def __init__(self, auth_type: str = "jwt"):
        super().__init__("auth")
        self.auth_type = auth_type

    def configure(self, builder: AppBuilder) -> None:
        """Configure authentication tools and middleware."""
        # Add auth tools
        builder.tools.with_tool_builder(
            ToolBuilder("login")
            .with_help("Authenticate user")
            .with_run_function(self._login)
        )

        builder.tools.with_tool_builder(
            ToolBuilder("logout")
            .with_help("Logout user")
            .with_run_function(self._logout)
        )

        # Add auth middleware
        builder.server.with_middleware_builder(
            MiddlewareBuilder("auth")
            .process_request(self._auth_middleware)
            .when(lambda req: hasattr(req, "path") and req.path.startswith("/api"))
        )

    def _login(self, tool, **kwargs):
        """Handle user login."""
        tool.lg.info("handling user login...")
        # Implementation would go here
        return 0

    def _logout(self, tool, **kwargs):
        """Handle user logout."""
        tool.lg.info("handling user logout...")
        # Implementation would go here
        return 0

    def _auth_middleware(self, request):
        """Authentication middleware."""
        # Implementation would go here
        return request


class LoggingPlugin(Plugin):
    """Plugin for enhanced logging functionality."""

    def __init__(self, log_file: str | None = None):
        super().__init__("logging")
        self.log_file = log_file

    def configure(self, builder: AppBuilder) -> None:
        """Configure logging tools and hooks."""
        # Add logging tools
        builder.tools.with_tool_builder(
            ToolBuilder("log-level")
            .with_help("Set log level")
            .with_run_function(self._set_log_level)
        )

        # Add logging hooks
        builder.advanced.with_hook_builder(
            HookBuilder().on_startup(self._setup_logging).on_error(self._log_error)
        )

    def _set_log_level(self, tool, **kwargs):
        """Set log level."""
        tool.lg.info("setting log level...")
        # Implementation would go here
        return 0

    def _setup_logging(self, context):
        """Setup enhanced logging on startup."""
        if self.log_file:
            # Setup file logging
            pass

    def _log_error(self, context):
        """Log errors with enhanced formatting."""
        if context.error:
            # Enhanced error logging
            pass


class MetricsPlugin(Plugin):
    """Plugin for metrics and monitoring functionality."""

    def __init__(self, metrics_endpoint: str | None = None):
        super().__init__("metrics")
        self.metrics_endpoint = metrics_endpoint

    def configure(self, builder: AppBuilder) -> None:
        """Configure metrics tools and middleware."""
        # Add metrics tools
        builder.tools.with_tool_builder(
            ToolBuilder("metrics")
            .with_help("Show application metrics")
            .with_run_function(self._show_metrics)
        )

        # Add metrics middleware
        builder.server.with_middleware_builder(
            MiddlewareBuilder("metrics")
            .process_request(self._record_request)
            .process_response(self._record_response)
        )

    def _show_metrics(self, tool, **kwargs):
        """Show application metrics."""
        tool.lg.info("showing application metrics...")
        # Implementation would go here
        return 0

    def _record_request(self, request):
        """Record request metrics."""
        # Implementation would go here
        return request

    def _record_response(self, response):
        """Record response metrics."""
        # Implementation would go here
        return response
