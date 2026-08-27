# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Configuration builders for the AppBuilder framework.

This module provides builders for creating various types of configuration
objects with a fluent API.
"""

from dataclasses import dataclass, field
from typing import Any, Self

from ...config import Config
from ...dot_dict import DotDict
from ..core.config import create_config


@dataclass
class ServerConfig:
    """Configuration for server components."""

    port: int = 8080
    host: str = "localhost"
    ssl_enabled: bool = False
    cors_origins: list[str] = field(default_factory=list)
    timeout: int = 30
    max_connections: int = 100
    keep_alive: bool = True
    compression: bool = True


@dataclass
class LoggingConfig:
    """Configuration for logging."""

    level: str = "info"
    location: int = 0
    micros: bool = False
    format_string: str | None = None
    file_path: str | None = None
    max_file_size: int = 10 * 1024 * 1024  # 10MB
    backup_count: int = 5


class ConfigBuilder:
    """Builder for application configuration."""

    def __init__(self) -> None:
        self._log_level = "info"
        self._log_location = 0
        self._log_micros = False
        self._quiet_mode = False
        self._debug_mode = False
        self._verbose_mode = False
        self._config_file: str | None = None
        self._environment: str = "production"
        self._custom_config: dict[str, Any] = {}

    def with_log_level(self, level: str) -> Self:
        """Set the log level."""
        self._log_level = level
        return self

    def with_log_location(self, depth: int) -> Self:
        """Set the log location depth."""
        self._log_location = depth
        return self

    def with_log_micros(self, enabled: bool = True) -> Self:
        """Enable/disable microsecond timestamps in logs."""
        self._log_micros = enabled
        return self

    def with_quiet_mode(self, enabled: bool = True) -> Self:
        """Enable/disable quiet mode."""
        self._quiet_mode = enabled
        return self

    def with_debug_mode(self, enabled: bool = True) -> Self:
        """Enable/disable debug mode."""
        self._debug_mode = enabled
        return self

    def with_verbose_mode(self, enabled: bool = True) -> Self:
        """Enable/disable verbose mode."""
        self._verbose_mode = enabled
        return self

    def with_config_file(self, file_path: str) -> Self:
        """Set the configuration file path."""
        self._config_file = file_path
        return self

    def with_environment(self, env: str) -> Self:
        """Set the environment (development, staging, production)."""
        self._environment = env
        return self

    def with_custom_config(self, key: str, value: Any) -> Self:
        """Add custom configuration value."""
        self._custom_config[key] = value
        return self

    def _apply_logging_settings(self, config: DotDict) -> None:
        """Apply logging settings to config."""
        if self._log_level:
            config.logging.level = self._log_level  # type: ignore[attr-defined]
        if self._log_location is not None:
            config.logging.location = self._log_location  # type: ignore[attr-defined]
        if self._log_micros is not None:
            config.logging.micros = self._log_micros  # type: ignore[attr-defined]

    def _apply_mode_flags(self, config: DotDict) -> None:
        """Apply mode flags to config."""
        if self._quiet_mode:
            config.quiet = self._quiet_mode  # type: ignore[attr-defined]
        if self._debug_mode:
            config.debug = self._debug_mode  # type: ignore[attr-defined]
        if self._verbose_mode:
            config.verbose = self._verbose_mode  # type: ignore[attr-defined]

    def build(self) -> Config | DotDict:
        """Build the application configuration."""
        # Load config from file if specified, otherwise create empty
        config = (
            create_config(file_path=self._config_file)
            if self._config_file
            else DotDict()
        )

        # Ensure logging section exists
        if not hasattr(config, "logging"):
            config.logging = DotDict()  # type: ignore[attr-defined]

        # Apply builder settings
        self._apply_logging_settings(config)
        self._apply_mode_flags(config)

        # Set environment (top-level)
        if self._environment:
            config.environment = self._environment  # type: ignore[attr-defined]

        # Set custom configuration
        for key, value in self._custom_config.items():
            setattr(config, key, value)

        return config


class ServerConfigBuilder:
    """Builder for server configuration."""

    def __init__(self) -> None:
        self._port = 8080
        self._host = "localhost"
        self._ssl_enabled = False
        self._cors_origins: list[str] = []
        self._timeout = 30
        self._max_connections = 100
        self._keep_alive = True
        self._compression = True

    def with_port(self, port: int) -> Self:
        """Set the server port."""
        self._port = port
        return self

    def with_host(self, host: str) -> Self:
        """Set the server host."""
        self._host = host
        return self

    def with_ssl(self, enabled: bool = True) -> Self:
        """Enable/disable SSL."""
        self._ssl_enabled = enabled
        return self

    def with_cors(self, origins: list[str]) -> Self:
        """Set CORS origins."""
        self._cors_origins = origins
        return self

    def add_cors_origin(self, origin: str) -> Self:
        """Add a CORS origin."""
        self._cors_origins.append(origin)
        return self

    def with_timeout(self, timeout: int) -> Self:
        """Set the request timeout."""
        self._timeout = timeout
        return self

    def with_max_connections(self, max_conn: int) -> Self:
        """Set the maximum number of connections."""
        self._max_connections = max_conn
        return self

    def with_keep_alive(self, enabled: bool = True) -> Self:
        """Enable/disable keep-alive."""
        self._keep_alive = enabled
        return self

    def with_compression(self, enabled: bool = True) -> Self:
        """Enable/disable compression."""
        self._compression = enabled
        return self

    def build(self) -> ServerConfig:
        """Build the server configuration."""
        return ServerConfig(
            port=self._port,
            host=self._host,
            ssl_enabled=self._ssl_enabled,
            cors_origins=self._cors_origins,
            timeout=self._timeout,
            max_connections=self._max_connections,
            keep_alive=self._keep_alive,
            compression=self._compression,
        )


class LoggingConfigBuilder:
    """Builder for logging configuration."""

    def __init__(self) -> None:
        self._level = "info"
        self._location = 0
        self._micros = False
        self._format_string: str | None = None
        self._file_path: str | None = None
        self._max_file_size = 10 * 1024 * 1024  # 10MB
        self._backup_count = 5

    def with_level(self, level: str) -> Self:
        """Set the log level."""
        self._level = level
        return self

    def with_location(self, depth: int) -> Self:
        """Set the log location depth."""
        self._location = depth
        return self

    def with_micros(self, enabled: bool = True) -> Self:
        """Enable/disable microsecond timestamps."""
        self._micros = enabled
        return self

    def with_format(self, format_string: str) -> Self:
        """Set the log format string."""
        self._format_string = format_string
        return self

    def with_file_output(self, file_path: str) -> Self:
        """Enable file output for logs."""
        self._file_path = file_path
        return self

    def with_file_rotation(self, max_size: int, backup_count: int = 5) -> Self:
        """Configure file rotation."""
        self._max_file_size = max_size
        self._backup_count = backup_count
        return self

    def build(self) -> LoggingConfig:
        """Build the logging configuration."""
        return LoggingConfig(
            level=self._level,
            location=self._location,
            micros=self._micros,
            format_string=self._format_string,
            file_path=self._file_path,
            max_file_size=self._max_file_size,
            backup_count=self._backup_count,
        )


def create_config_builder() -> ConfigBuilder:
    """
    Create a new configuration builder.

    Returns:
        ConfigBuilder instance

    Example:
        config = create_config_builder().with_log_level("debug").build()
    """
    return ConfigBuilder()


def create_server_config_builder() -> ServerConfigBuilder:
    """
    Create a new server configuration builder.

    Returns:
        ServerConfigBuilder instance

    Example:
        server = create_server_config_builder().with_host("0.0.0.0").build()
    """
    return ServerConfigBuilder()


def create_logging_config_builder() -> LoggingConfigBuilder:
    """
    Create a new logging configuration builder.

    Returns:
        LoggingConfigBuilder instance

    Example:
        logging = create_logging_config_builder().with_level("info").build()
    """
    return LoggingConfigBuilder()
