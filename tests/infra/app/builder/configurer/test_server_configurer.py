# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for app/builder/configurer/server.py.

Tests key functionality including:
- ServerConfigurer initialization
- Server configuration options (port, host, ssl, cors, timeout)
- Middleware configuration
- Method chaining (fluent API)
"""

from unittest.mock import Mock, patch

import pytest

from appinfra.app.builder.configurer.server import ServerConfigurer

# =============================================================================
# Test ServerConfigurer Initialization
# =============================================================================


@pytest.mark.unit
class TestServerConfigurerInit:
    """Test ServerConfigurer initialization."""

    def test_stores_app_builder_reference(self):
        """Test stores reference to parent AppBuilder."""
        app_builder = Mock()

        configurer = ServerConfigurer(app_builder)

        assert configurer._app_builder is app_builder


# =============================================================================
# Test with_config
# =============================================================================


@pytest.mark.unit
class TestWithConfig:
    """Test ServerConfigurer.with_config method."""

    def test_sets_server_config(self):
        """Test sets _server_config on AppBuilder."""
        app_builder = Mock()
        configurer = ServerConfigurer(app_builder)
        server_config = Mock(name="ServerConfig")

        result = configurer.with_config(server_config)

        assert app_builder._server_config is server_config
        assert result is configurer  # Returns self for chaining


# =============================================================================
# Test with_port
# =============================================================================


@pytest.mark.unit
class TestWithPort:
    """Test ServerConfigurer.with_port method."""

    def test_creates_server_config_if_none(self):
        """Test creates ServerConfig if not set."""
        app_builder = Mock()
        app_builder._server_config = None
        configurer = ServerConfigurer(app_builder)

        with patch("appinfra.app.builder.app.ServerConfig") as MockServerConfig:
            mock_config = Mock()
            MockServerConfig.return_value = mock_config

            configurer.with_port(8080)

            MockServerConfig.assert_called_once()
            assert mock_config.port == 8080

    def test_updates_existing_server_config(self):
        """Test updates existing ServerConfig."""
        app_builder = Mock()
        existing_config = Mock()
        app_builder._server_config = existing_config
        configurer = ServerConfigurer(app_builder)

        result = configurer.with_port(9000)

        assert existing_config.port == 9000
        assert result is configurer

    def test_returns_self_for_chaining(self):
        """Test returns self for method chaining."""
        app_builder = Mock()
        app_builder._server_config = Mock()
        configurer = ServerConfigurer(app_builder)

        result = configurer.with_port(8080)

        assert result is configurer


# =============================================================================
# Test with_host
# =============================================================================


@pytest.mark.unit
class TestWithHost:
    """Test ServerConfigurer.with_host method."""

    def test_creates_server_config_if_none(self):
        """Test creates ServerConfig if not set."""
        app_builder = Mock()
        app_builder._server_config = None
        configurer = ServerConfigurer(app_builder)

        with patch("appinfra.app.builder.app.ServerConfig") as MockServerConfig:
            mock_config = Mock()
            MockServerConfig.return_value = mock_config

            configurer.with_host("0.0.0.0")

            assert mock_config.host == "0.0.0.0"

    def test_updates_existing_server_config(self):
        """Test updates existing ServerConfig."""
        app_builder = Mock()
        existing_config = Mock()
        app_builder._server_config = existing_config
        configurer = ServerConfigurer(app_builder)

        result = configurer.with_host("localhost")

        assert existing_config.host == "localhost"
        assert result is configurer


# =============================================================================
# Test with_ssl
# =============================================================================


@pytest.mark.unit
class TestWithSsl:
    """Test ServerConfigurer.with_ssl method."""

    def test_enables_ssl_by_default(self):
        """Test enables SSL when called without argument."""
        app_builder = Mock()
        app_builder._server_config = Mock()
        configurer = ServerConfigurer(app_builder)

        configurer.with_ssl()

        assert app_builder._server_config.ssl_enabled is True

    def test_can_disable_ssl(self):
        """Test can explicitly disable SSL."""
        app_builder = Mock()
        app_builder._server_config = Mock()
        configurer = ServerConfigurer(app_builder)

        configurer.with_ssl(enabled=False)

        assert app_builder._server_config.ssl_enabled is False

    def test_creates_server_config_if_none(self):
        """Test creates ServerConfig if not set."""
        app_builder = Mock()
        app_builder._server_config = None
        configurer = ServerConfigurer(app_builder)

        with patch("appinfra.app.builder.app.ServerConfig") as MockServerConfig:
            mock_config = Mock()
            MockServerConfig.return_value = mock_config

            configurer.with_ssl(True)

            assert mock_config.ssl_enabled is True


# =============================================================================
# Test with_cors_origins
# =============================================================================


@pytest.mark.unit
class TestWithCorsOrigins:
    """Test ServerConfigurer.with_cors_origins method."""

    def test_sets_cors_origins(self):
        """Test sets CORS origins list."""
        app_builder = Mock()
        app_builder._server_config = Mock()
        configurer = ServerConfigurer(app_builder)

        result = configurer.with_cors_origins(
            "http://localhost:3000", "https://example.com"
        )

        assert app_builder._server_config.cors_origins == [
            "http://localhost:3000",
            "https://example.com",
        ]
        assert result is configurer

    def test_creates_server_config_if_none(self):
        """Test creates ServerConfig if not set."""
        app_builder = Mock()
        app_builder._server_config = None
        configurer = ServerConfigurer(app_builder)

        with patch("appinfra.app.builder.app.ServerConfig") as MockServerConfig:
            mock_config = Mock()
            MockServerConfig.return_value = mock_config

            configurer.with_cors_origins("http://localhost")

            assert mock_config.cors_origins == ["http://localhost"]


# =============================================================================
# Test with_timeout
# =============================================================================


@pytest.mark.unit
class TestWithTimeout:
    """Test ServerConfigurer.with_timeout method."""

    def test_sets_timeout(self):
        """Test sets request timeout."""
        app_builder = Mock()
        app_builder._server_config = Mock()
        configurer = ServerConfigurer(app_builder)

        result = configurer.with_timeout(30)

        assert app_builder._server_config.timeout == 30
        assert result is configurer

    def test_creates_server_config_if_none(self):
        """Test creates ServerConfig if not set."""
        app_builder = Mock()
        app_builder._server_config = None
        configurer = ServerConfigurer(app_builder)

        with patch("appinfra.app.builder.app.ServerConfig") as MockServerConfig:
            mock_config = Mock()
            MockServerConfig.return_value = mock_config

            configurer.with_timeout(60)

            assert mock_config.timeout == 60


# =============================================================================
# Test with_middleware
# =============================================================================


@pytest.mark.unit
class TestWithMiddleware:
    """Test ServerConfigurer.with_middleware method."""

    def test_adds_middleware_to_list(self):
        """Test adds middleware to AppBuilder's middleware list."""
        app_builder = Mock()
        app_builder._middleware = []
        configurer = ServerConfigurer(app_builder)
        middleware = Mock(name="TestMiddleware")

        result = configurer.with_middleware(middleware)

        assert middleware in app_builder._middleware
        assert result is configurer

    def test_appends_multiple_middleware(self):
        """Test can add multiple middleware."""
        app_builder = Mock()
        app_builder._middleware = []
        configurer = ServerConfigurer(app_builder)
        mw1 = Mock(name="Middleware1")
        mw2 = Mock(name="Middleware2")

        configurer.with_middleware(mw1).with_middleware(mw2)

        assert mw1 in app_builder._middleware
        assert mw2 in app_builder._middleware
        assert len(app_builder._middleware) == 2


# =============================================================================
# Test with_middleware_builder
# =============================================================================


@pytest.mark.unit
class TestWithMiddlewareBuilder:
    """Test ServerConfigurer.with_middleware_builder method."""

    def test_builds_and_adds_middleware(self):
        """Test builds middleware from builder and adds it."""
        app_builder = Mock()
        app_builder._middleware = []
        configurer = ServerConfigurer(app_builder)

        builder = Mock()
        built_middleware = Mock(name="BuiltMiddleware")
        builder.build.return_value = built_middleware

        result = configurer.with_middleware_builder(builder)

        builder.build.assert_called_once()
        assert built_middleware in app_builder._middleware
        assert result is configurer


# =============================================================================
# Test done
# =============================================================================


@pytest.mark.unit
class TestDone:
    """Test ServerConfigurer.done method."""

    def test_returns_app_builder(self):
        """Test returns parent AppBuilder for continued chaining."""
        app_builder = Mock()
        configurer = ServerConfigurer(app_builder)

        result = configurer.done()

        assert result is app_builder


# =============================================================================
# Integration Tests
# =============================================================================


@pytest.mark.integration
class TestServerConfigurerIntegration:
    """Integration tests for ServerConfigurer."""

    def test_full_configuration_chain(self):
        """Test complete fluent configuration chain."""
        app_builder = Mock()
        app_builder._server_config = None
        app_builder._middleware = []

        with patch("appinfra.app.builder.app.ServerConfig") as MockServerConfig:
            mock_config = Mock()
            MockServerConfig.return_value = mock_config

            configurer = ServerConfigurer(app_builder)
            middleware = Mock()

            result = (
                configurer.with_port(8080)
                .with_host("0.0.0.0")
                .with_ssl(True)
                .with_cors_origins("http://localhost:3000")
                .with_timeout(30)
                .with_middleware(middleware)
                .done()
            )

            assert result is app_builder
            assert mock_config.port == 8080
            assert mock_config.host == "0.0.0.0"
            assert mock_config.ssl_enabled is True
            assert mock_config.cors_origins == ["http://localhost:3000"]
            assert mock_config.timeout == 30
            assert middleware in app_builder._middleware

    def test_partial_configuration(self):
        """Test partial configuration (only some options)."""
        app_builder = Mock()
        existing_config = Mock()
        app_builder._server_config = existing_config
        app_builder._middleware = []

        configurer = ServerConfigurer(app_builder)

        result = configurer.with_port(9000).done()

        assert result is app_builder
        assert existing_config.port == 9000
        # Other attributes not modified
