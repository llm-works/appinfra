# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Server configuration builder for AppBuilder.

This module provides focused builder for configuring server and middleware.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from ...server.handlers import Middleware
from ..middleware import MiddlewareBuilder

if TYPE_CHECKING:
    from ..app import AppBuilder, ServerConfig


class ServerConfigurer:
    """
    Focused builder for server and middleware configuration.

    This class extracts server-related configuration from AppBuilder,
    following the Single Responsibility Principle.
    """

    def __init__(self, app_builder: AppBuilder):
        """
        Initialize the server configurer.

        Args:
            app_builder: Parent AppBuilder instance
        """
        self._app_builder = app_builder

    def with_config(self, config: ServerConfig) -> Self:
        """
        Set the server configuration.

        Args:
            config: ServerConfig instance

        Returns:
            Self for method chaining
        """
        self._app_builder._server_config = config
        return self

    def with_port(self, port: int) -> Self:
        """
        Set the server port.

        Args:
            port: Port number

        Returns:
            Self for method chaining
        """
        from ..app import ServerConfig

        if self._app_builder._server_config is None:
            self._app_builder._server_config = ServerConfig()
        self._app_builder._server_config.port = port
        return self

    def with_host(self, host: str) -> Self:
        """
        Set the server host.

        Args:
            host: Host address

        Returns:
            Self for method chaining
        """
        from ..app import ServerConfig

        if self._app_builder._server_config is None:
            self._app_builder._server_config = ServerConfig()
        self._app_builder._server_config.host = host
        return self

    def with_ssl(self, enabled: bool = True) -> Self:
        """
        Enable or disable SSL.

        Args:
            enabled: Whether to enable SSL

        Returns:
            Self for method chaining
        """
        from ..app import ServerConfig

        if self._app_builder._server_config is None:
            self._app_builder._server_config = ServerConfig()
        self._app_builder._server_config.ssl_enabled = enabled
        return self

    def with_cors_origins(self, *origins: str) -> Self:
        """
        Set CORS allowed origins.

        Args:
            *origins: Origin URLs to allow

        Returns:
            Self for method chaining
        """
        from ..app import ServerConfig

        if self._app_builder._server_config is None:
            self._app_builder._server_config = ServerConfig()
        self._app_builder._server_config.cors_origins = list(origins)
        return self

    def with_timeout(self, timeout: int) -> Self:
        """
        Set request timeout.

        Args:
            timeout: Timeout in seconds

        Returns:
            Self for method chaining
        """
        from ..app import ServerConfig

        if self._app_builder._server_config is None:
            self._app_builder._server_config = ServerConfig()
        self._app_builder._server_config.timeout = timeout
        return self

    def with_middleware(self, middleware: Middleware) -> Self:
        """
        Add middleware to the application.

        Args:
            middleware: Middleware instance

        Returns:
            Self for method chaining
        """
        self._app_builder._middleware.append(middleware)
        return self

    def with_middleware_builder(self, builder: MiddlewareBuilder) -> Self:
        """
        Add middleware using a middleware builder.

        Args:
            builder: MiddlewareBuilder instance

        Returns:
            Self for method chaining
        """
        self._app_builder._middleware.append(builder.build())
        return self

    def done(self) -> AppBuilder:
        """
        Finish server configuration and return to main builder.

        Returns:
            Parent AppBuilder instance for continued chaining
        """
        return self._app_builder
