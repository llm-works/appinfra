"""Tests for ServerPlugin and ServeTool."""

from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.unit
class TestServeTool:
    """Tests for ServeTool."""

    @pytest.fixture
    def mock_dependencies(self):
        """Mock FastAPI dependencies."""
        with (
            patch("appinfra.app.fastapi.runtime.server.FASTAPI_AVAILABLE", True),
            patch("appinfra.app.fastapi.runtime.server.FastAPI"),
        ):
            yield

    def test_initialization(self, mock_dependencies):
        """Test tool initialization."""
        from appinfra.app.fastapi.plugin import ServeTool

        server = MagicMock()
        server.name = "test-server"

        tool = ServeTool(server, name="serve", help_text="Start server")

        assert tool._server is server
        assert tool.config.name == "serve"
        assert tool.config.help_text == "Start server"

    def test_run_starts_server(self, mock_dependencies):
        """Test run method starts server."""
        from appinfra.app.fastapi.plugin import ServeTool

        server = MagicMock()
        server.name = "test-server"
        server.config.host = "localhost"
        server.config.port = 8000

        tool = ServeTool(server)
        tool._logger = MagicMock()

        result = tool.run()

        server.start.assert_called_once()
        assert result == 0

    def test_run_handles_keyboard_interrupt(self, mock_dependencies):
        """Test run handles KeyboardInterrupt gracefully."""
        from appinfra.app.fastapi.plugin import ServeTool

        server = MagicMock()
        server.name = "test-server"
        server.config.host = "localhost"
        server.config.port = 8000
        server.start.side_effect = KeyboardInterrupt()

        tool = ServeTool(server)
        tool._logger = MagicMock()

        result = tool.run()

        server.stop.assert_called_once()
        assert result == 130  # SIGINT exit code

    def test_run_handles_exception(self, mock_dependencies):
        """Test run handles exceptions."""
        from appinfra.app.fastapi.plugin import ServeTool

        server = MagicMock()
        server.name = "test-server"
        server.config.host = "localhost"
        server.config.port = 8000
        server.start.side_effect = RuntimeError("Server error")

        tool = ServeTool(server)
        tool._logger = MagicMock()

        result = tool.run()

        server.stop.assert_called_once()
        assert result == 1


@pytest.mark.unit
class TestServerPlugin:
    """Tests for ServerPlugin."""

    @pytest.fixture
    def mock_dependencies(self):
        """Mock FastAPI dependencies."""
        with (
            patch("appinfra.app.fastapi.runtime.server.FASTAPI_AVAILABLE", True),
            patch("appinfra.app.fastapi.runtime.server.FastAPI"),
        ):
            yield

    def test_initialization(self, mock_dependencies):
        """Test plugin initialization."""
        from appinfra.app.fastapi.plugin import ServerPlugin

        server = MagicMock()

        plugin = ServerPlugin(server, tool_name="custom-serve", tool_help="Custom help")

        assert plugin._server is server
        assert plugin._tool_name == "custom-serve"
        assert plugin._tool_help == "Custom help"
        assert plugin._tool is None

    def test_default_initialization(self, mock_dependencies):
        """Test plugin initialization with defaults."""
        from appinfra.app.fastapi.plugin import ServerPlugin

        server = MagicMock()

        plugin = ServerPlugin(server)

        assert plugin._tool_name == "serve"
        assert plugin._tool_help == "Start the HTTP server"

    def test_configure_creates_tool(self, mock_dependencies):
        """Test configure creates ServeTool."""
        from appinfra.app.fastapi.plugin import ServerPlugin

        server = MagicMock()
        plugin = ServerPlugin(server)

        mock_builder = MagicMock()
        mock_builder._tools = []

        plugin.configure(mock_builder)

        assert plugin._tool is not None
        assert len(mock_builder._tools) == 1
        assert mock_builder._tools[0] is plugin._tool

    def test_initialize_sets_parent(self, mock_dependencies):
        """Test initialize sets tool parent."""
        from appinfra.app.fastapi.plugin import ServerPlugin
        from appinfra.app.tracing.traceable import Traceable

        server = MagicMock()
        plugin = ServerPlugin(server)

        # First configure
        mock_builder = MagicMock()
        mock_builder._tools = []
        plugin.configure(mock_builder)

        # Then initialize - need a Traceable-compatible mock
        mock_app = MagicMock(spec=Traceable)
        plugin.initialize(mock_app)

        # Verify parent is set (tool is real ServeTool, not mock)
        assert plugin._tool.parent is mock_app

    def test_initialize_without_configure(self, mock_dependencies):
        """Test initialize does nothing if not configured."""
        from appinfra.app.fastapi.plugin import ServerPlugin

        server = MagicMock()
        plugin = ServerPlugin(server)

        mock_app = MagicMock()

        # Should not raise
        plugin.initialize(mock_app)

    def test_cleanup_stops_server(self, mock_dependencies):
        """Test cleanup stops running server."""
        from appinfra.app.fastapi.plugin import ServerPlugin

        server = MagicMock()
        server.is_running = True

        plugin = ServerPlugin(server)

        mock_app = MagicMock()
        plugin.cleanup(mock_app)

        server.stop.assert_called_once()

    def test_cleanup_does_nothing_if_not_running(self, mock_dependencies):
        """Test cleanup does nothing if server not running."""
        from appinfra.app.fastapi.plugin import ServerPlugin

        server = MagicMock()
        server.is_running = False

        plugin = ServerPlugin(server)

        mock_app = MagicMock()
        plugin.cleanup(mock_app)

        server.stop.assert_not_called()
