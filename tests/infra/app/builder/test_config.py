# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for app/builder/config.py.

Tests key functionality including:
- ServerConfig and LoggingConfig dataclasses
- ConfigBuilder fluent API
- ServerConfigBuilder fluent API
- LoggingConfigBuilder fluent API
"""

import pytest

from appinfra.app.builder.config import (
    ConfigBuilder,
    LoggingConfig,
    LoggingConfigBuilder,
    ServerConfig,
    ServerConfigBuilder,
)

# =============================================================================
# Test ServerConfig
# =============================================================================


@pytest.mark.unit
class TestServerConfig:
    """Test ServerConfig dataclass (lines 15-27)."""

    def test_default_values(self):
        """Test default values (lines 19-27)."""
        config = ServerConfig()

        assert config.port == 8080
        assert config.host == "localhost"
        assert config.ssl_enabled is False
        assert config.cors_origins == []
        assert config.timeout == 30
        assert config.max_connections == 100
        assert config.keep_alive is True
        assert config.compression is True

    def test_custom_values(self):
        """Test custom values."""
        config = ServerConfig(
            port=3000,
            host="0.0.0.0",
            ssl_enabled=True,
            cors_origins=["http://example.com"],
            timeout=60,
            max_connections=500,
            keep_alive=False,
            compression=False,
        )

        assert config.port == 3000
        assert config.host == "0.0.0.0"
        assert config.ssl_enabled is True
        assert config.cors_origins == ["http://example.com"]
        assert config.timeout == 60
        assert config.max_connections == 500
        assert config.keep_alive is False
        assert config.compression is False


# =============================================================================
# Test LoggingConfig
# =============================================================================


@pytest.mark.unit
class TestLoggingConfig:
    """Test LoggingConfig dataclass (lines 29-39)."""

    def test_default_values(self):
        """Test default values (lines 33-39)."""
        config = LoggingConfig()

        assert config.level == "info"
        assert config.location == 0
        assert config.micros is False
        assert config.format_string is None
        assert config.file_path is None
        assert config.max_file_size == 10 * 1024 * 1024
        assert config.backup_count == 5

    def test_custom_values(self):
        """Test custom values."""
        config = LoggingConfig(
            level="debug",
            location=3,
            micros=True,
            format_string="%(message)s",
            file_path="/var/log/app.log",
            max_file_size=5 * 1024 * 1024,
            backup_count=10,
        )

        assert config.level == "debug"
        assert config.location == 3
        assert config.micros is True
        assert config.format_string == "%(message)s"
        assert config.file_path == "/var/log/app.log"
        assert config.max_file_size == 5 * 1024 * 1024
        assert config.backup_count == 10


# =============================================================================
# Test ConfigBuilder Initialization
# =============================================================================


@pytest.mark.unit
class TestConfigBuilderInit:
    """Test ConfigBuilder initialization (lines 45-54)."""

    def test_default_values(self):
        """Test default initialization (lines 46-54)."""
        builder = ConfigBuilder()

        assert builder._log_level == "info"
        assert builder._log_location == 0
        assert builder._log_micros is False
        assert builder._quiet_mode is False
        assert builder._debug_mode is False
        assert builder._verbose_mode is False
        assert builder._config_file is None
        assert builder._environment == "production"
        assert builder._custom_config == {}


# =============================================================================
# Test ConfigBuilder Methods
# =============================================================================


@pytest.mark.unit
class TestConfigBuilderMethods:
    """Test ConfigBuilder fluent methods."""

    def test_with_log_level(self):
        """Test with_log_level method (lines 56-59)."""
        builder = ConfigBuilder()

        result = builder.with_log_level("debug")

        assert builder._log_level == "debug"
        assert result is builder

    def test_with_log_location(self):
        """Test with_log_location method (lines 61-64)."""
        builder = ConfigBuilder()

        result = builder.with_log_location(3)

        assert builder._log_location == 3
        assert result is builder

    def test_with_log_micros(self):
        """Test with_log_micros method (lines 66-69)."""
        builder = ConfigBuilder()

        result = builder.with_log_micros(True)

        assert builder._log_micros is True
        assert result is builder

    def test_with_quiet_mode(self):
        """Test with_quiet_mode method (lines 71-74)."""
        builder = ConfigBuilder()

        result = builder.with_quiet_mode(True)

        assert builder._quiet_mode is True
        assert result is builder

    def test_with_debug_mode(self):
        """Test with_debug_mode method (lines 76-79)."""
        builder = ConfigBuilder()

        result = builder.with_debug_mode(True)

        assert builder._debug_mode is True
        assert result is builder

    def test_with_verbose_mode(self):
        """Test with_verbose_mode method (lines 81-84)."""
        builder = ConfigBuilder()

        result = builder.with_verbose_mode(True)

        assert builder._verbose_mode is True
        assert result is builder

    def test_with_config_file(self):
        """Test with_config_file method (lines 86-89)."""
        builder = ConfigBuilder()

        result = builder.with_config_file("/path/to/config.yaml")

        assert builder._config_file == "/path/to/config.yaml"
        assert result is builder

    def test_with_environment(self):
        """Test with_environment method (lines 91-94)."""
        builder = ConfigBuilder()

        result = builder.with_environment("development")

        assert builder._environment == "development"
        assert result is builder

    def test_with_custom_config(self):
        """Test with_custom_config method (lines 96-99)."""
        builder = ConfigBuilder()

        result = builder.with_custom_config("database_url", "postgres://...")

        assert builder._custom_config["database_url"] == "postgres://..."
        assert result is builder


# =============================================================================
# Test ConfigBuilder build
# =============================================================================


@pytest.mark.unit
class TestConfigBuilderBuild:
    """Test ConfigBuilder build method (lines 101-137)."""

    def test_build_without_config_file(self):
        """Test build without config file (lines 106-107)."""
        builder = ConfigBuilder()

        config = builder.build()

        assert hasattr(config, "logging")

    def test_build_sets_logging(self):
        """Test build sets logging section (lines 114-119)."""
        builder = (
            ConfigBuilder()
            .with_log_level("warning")
            .with_log_location(2)
            .with_log_micros(True)
        )

        config = builder.build()

        assert config.logging.level == "warning"
        assert config.logging.location == 2
        assert config.logging.micros is True

    def test_build_sets_mode_flags(self):
        """Test build sets mode flags (lines 122-127)."""
        builder = (
            ConfigBuilder()
            .with_quiet_mode(True)
            .with_debug_mode(True)
            .with_verbose_mode(True)
        )

        config = builder.build()

        assert config.quiet is True
        assert config.debug is True
        assert config.verbose is True

    def test_build_sets_environment(self):
        """Test build sets environment (lines 130-131)."""
        builder = ConfigBuilder().with_environment("staging")

        config = builder.build()

        assert config.environment == "staging"

    def test_build_sets_custom_config(self):
        """Test build sets custom config (lines 134-135)."""
        builder = (
            ConfigBuilder()
            .with_custom_config("api_key", "secret123")
            .with_custom_config("max_retries", 3)
        )

        config = builder.build()

        assert config.api_key == "secret123"
        assert config.max_retries == 3


# =============================================================================
# Test ServerConfigBuilder
# =============================================================================


@pytest.mark.unit
class TestServerConfigBuilder:
    """Test ServerConfigBuilder class (lines 140-209)."""

    def test_initialization(self):
        """Test initialization (lines 143-151)."""
        builder = ServerConfigBuilder()

        assert builder._port == 8080
        assert builder._host == "localhost"
        assert builder._ssl_enabled is False
        assert builder._cors_origins == []
        assert builder._timeout == 30
        assert builder._max_connections == 100
        assert builder._keep_alive is True
        assert builder._compression is True

    def test_with_port(self):
        """Test with_port method (lines 153-156)."""
        builder = ServerConfigBuilder()

        result = builder.with_port(3000)

        assert builder._port == 3000
        assert result is builder

    def test_with_host(self):
        """Test with_host method (lines 158-161)."""
        builder = ServerConfigBuilder()

        result = builder.with_host("0.0.0.0")

        assert builder._host == "0.0.0.0"
        assert result is builder

    def test_with_ssl(self):
        """Test with_ssl method (lines 163-166)."""
        builder = ServerConfigBuilder()

        result = builder.with_ssl(True)

        assert builder._ssl_enabled is True
        assert result is builder

    def test_with_cors(self):
        """Test with_cors method (lines 168-171)."""
        builder = ServerConfigBuilder()

        result = builder.with_cors(["http://example.com"])

        assert builder._cors_origins == ["http://example.com"]
        assert result is builder

    def test_add_cors_origin(self):
        """Test add_cors_origin method (lines 173-176)."""
        builder = ServerConfigBuilder()

        result = builder.add_cors_origin("http://example.com")
        builder.add_cors_origin("http://other.com")

        assert "http://example.com" in builder._cors_origins
        assert "http://other.com" in builder._cors_origins
        assert result is builder

    def test_with_timeout(self):
        """Test with_timeout method (lines 178-181)."""
        builder = ServerConfigBuilder()

        result = builder.with_timeout(60)

        assert builder._timeout == 60
        assert result is builder

    def test_with_max_connections(self):
        """Test with_max_connections method (lines 183-186)."""
        builder = ServerConfigBuilder()

        result = builder.with_max_connections(500)

        assert builder._max_connections == 500
        assert result is builder

    def test_with_keep_alive(self):
        """Test with_keep_alive method (lines 188-191)."""
        builder = ServerConfigBuilder()

        result = builder.with_keep_alive(False)

        assert builder._keep_alive is False
        assert result is builder

    def test_with_compression(self):
        """Test with_compression method (lines 193-196)."""
        builder = ServerConfigBuilder()

        result = builder.with_compression(False)

        assert builder._compression is False
        assert result is builder

    def test_build(self):
        """Test build method (lines 198-209)."""
        builder = (
            ServerConfigBuilder()
            .with_port(3000)
            .with_host("0.0.0.0")
            .with_ssl(True)
            .with_cors(["http://example.com"])
            .with_timeout(60)
            .with_max_connections(500)
            .with_keep_alive(False)
            .with_compression(False)
        )

        config = builder.build()

        assert isinstance(config, ServerConfig)
        assert config.port == 3000
        assert config.host == "0.0.0.0"
        assert config.ssl_enabled is True
        assert config.cors_origins == ["http://example.com"]
        assert config.timeout == 60
        assert config.max_connections == 500
        assert config.keep_alive is False
        assert config.compression is False


# =============================================================================
# Test LoggingConfigBuilder
# =============================================================================


@pytest.mark.unit
class TestLoggingConfigBuilder:
    """Test LoggingConfigBuilder class (lines 212-267)."""

    def test_initialization(self):
        """Test initialization (lines 215-222)."""
        builder = LoggingConfigBuilder()

        assert builder._level == "info"
        assert builder._location == 0
        assert builder._micros is False
        assert builder._format_string is None
        assert builder._file_path is None
        assert builder._max_file_size == 10 * 1024 * 1024
        assert builder._backup_count == 5

    def test_with_level(self):
        """Test with_level method (lines 224-227)."""
        builder = LoggingConfigBuilder()

        result = builder.with_level("debug")

        assert builder._level == "debug"
        assert result is builder

    def test_with_location(self):
        """Test with_location method (lines 229-232)."""
        builder = LoggingConfigBuilder()

        result = builder.with_location(3)

        assert builder._location == 3
        assert result is builder

    def test_with_micros(self):
        """Test with_micros method (lines 234-237)."""
        builder = LoggingConfigBuilder()

        result = builder.with_micros(True)

        assert builder._micros is True
        assert result is builder

    def test_with_format(self):
        """Test with_format method (lines 239-242)."""
        builder = LoggingConfigBuilder()

        result = builder.with_format("%(message)s")

        assert builder._format_string == "%(message)s"
        assert result is builder

    def test_with_file_output(self):
        """Test with_file_output method (lines 244-247)."""
        builder = LoggingConfigBuilder()

        result = builder.with_file_output("/var/log/app.log")

        assert builder._file_path == "/var/log/app.log"
        assert result is builder

    def test_with_file_rotation(self):
        """Test with_file_rotation method (lines 249-255)."""
        builder = LoggingConfigBuilder()

        result = builder.with_file_rotation(5 * 1024 * 1024, backup_count=10)

        assert builder._max_file_size == 5 * 1024 * 1024
        assert builder._backup_count == 10
        assert result is builder

    def test_build(self):
        """Test build method (lines 257-267)."""
        builder = (
            LoggingConfigBuilder()
            .with_level("warning")
            .with_location(2)
            .with_micros(True)
            .with_format("%(name)s: %(message)s")
            .with_file_output("/var/log/app.log")
            .with_file_rotation(5 * 1024 * 1024, backup_count=3)
        )

        config = builder.build()

        assert isinstance(config, LoggingConfig)
        assert config.level == "warning"
        assert config.location == 2
        assert config.micros is True
        assert config.format_string == "%(name)s: %(message)s"
        assert config.file_path == "/var/log/app.log"
        assert config.max_file_size == 5 * 1024 * 1024
        assert config.backup_count == 3


# =============================================================================
# Integration Tests
# =============================================================================


@pytest.mark.integration
class TestConfigBuildersIntegration:
    """Test config builders integration."""

    def test_full_config_builder_workflow(self):
        """Test complete ConfigBuilder workflow."""
        config = (
            ConfigBuilder()
            .with_log_level("debug")
            .with_log_location(2)
            .with_log_micros(True)
            .with_debug_mode(True)
            .with_environment("development")
            .with_custom_config("api_version", "v2")
            .with_custom_config("feature_flags", {"new_ui": True})
            .build()
        )

        assert config.logging.level == "debug"
        assert config.logging.location == 2
        assert config.logging.micros is True
        assert config.debug is True
        assert config.environment == "development"
        assert config.api_version == "v2"
        assert config.feature_flags == {"new_ui": True}

    def test_server_config_full_chain(self):
        """Test complete ServerConfigBuilder chain."""
        config = (
            ServerConfigBuilder()
            .with_port(443)
            .with_host("0.0.0.0")
            .with_ssl(True)
            .with_cors(["https://example.com"])
            .add_cors_origin("https://api.example.com")
            .with_timeout(120)
            .with_max_connections(1000)
            .with_keep_alive(True)
            .with_compression(True)
            .build()
        )

        assert config.port == 443
        assert config.ssl_enabled is True
        assert len(config.cors_origins) == 2
        assert config.timeout == 120

    def test_logging_config_full_chain(self):
        """Test complete LoggingConfigBuilder chain."""
        config = (
            LoggingConfigBuilder()
            .with_level("error")
            .with_location(1)
            .with_micros(False)
            .with_format("%(asctime)s - %(message)s")
            .with_file_output("/var/log/errors.log")
            .with_file_rotation(20 * 1024 * 1024, backup_count=10)
            .build()
        )

        assert config.level == "error"
        assert config.location == 1
        assert config.micros is False
        assert config.file_path == "/var/log/errors.log"
        assert config.max_file_size == 20 * 1024 * 1024
        assert config.backup_count == 10
