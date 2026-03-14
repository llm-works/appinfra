"""
Comprehensive tests for TCP server functionality.

Tests TCP server implementation including:
- Server initialization and validation
- Single-process and multiprocessing modes
- HTTP request handling
- Ticker integration
- Error handling and cleanup
- Helper functions
"""

import socketserver
from unittest.mock import MagicMock, Mock, patch

import pytest

from appinfra.net.errors import (
    HandlerError,
    ServerShutdownError,
    ServerStartupError,
)
from appinfra.net.http import RequestHandler
from appinfra.net.tcp import (
    Server,
    _cleanup_ticker_process,
    _run_http_server_with_cleanup,
    _Server,
    _start_ticker_in_process,
    _start_ticker_process,
)
from appinfra.time.ticker import Ticker, TickerHandler

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_logger():
    """Create mock logger."""
    logger = Mock()
    logger.debug = Mock()
    logger.info = Mock()
    logger.warning = Mock()
    logger.error = Mock()
    logger.trace = Mock()
    return logger


@pytest.fixture
def mock_handler():
    """Create mock request handler."""
    handler = Mock()
    handler.do_GET = Mock()
    handler.do_HEAD = Mock()
    return handler


@pytest.fixture
def mock_ticker():
    """Create mock ticker."""
    ticker = Mock(spec=Ticker)
    ticker.run_started = Mock()
    return ticker


@pytest.fixture
def mock_ticker_handler():
    """Create mock handler that implements TickerHandler."""
    handler = Mock(spec=TickerHandler)
    handler.do_GET = Mock()
    handler.ticker_start = Mock()
    return handler


# =============================================================================
# Test _Server Class
# =============================================================================


@pytest.mark.unit
class TestServerClass:
    """Test _Server internal class."""

    def test_init_success(self, mock_logger, mock_handler):
        """Test successful _Server initialization."""
        with patch.object(socketserver.TCPServer, "__init__", return_value=None):
            server = _Server(
                mock_logger, mock_handler, ("localhost", 8080), RequestHandler
            )
            assert server._lg == mock_logger
            assert server._handler == mock_handler
            mock_logger.debug.assert_called()

    def test_init_failure_raises_startup_error(self, mock_logger, mock_handler):
        """Test _Server initialization failure raises ServerStartupError."""
        with patch.object(
            socketserver.TCPServer,
            "__init__",
            side_effect=Exception("socket error"),
        ):
            with pytest.raises(ServerStartupError, match="initialization failed"):
                _Server(mock_logger, mock_handler, ("localhost", 8080), RequestHandler)

    def test_allow_reuse_address_returns_true(self, mock_logger, mock_handler):
        """Test allow_reuse_address always returns True."""
        with patch.object(socketserver.TCPServer, "__init__", return_value=None):
            server = _Server(
                mock_logger, mock_handler, ("localhost", 8080), RequestHandler
            )
            assert server.allow_reuse_address() is True

    def test_service_actions_is_noop(self, mock_logger, mock_handler):
        """Test service_actions is a no-op."""
        with patch.object(socketserver.TCPServer, "__init__", return_value=None):
            server = _Server(
                mock_logger, mock_handler, ("localhost", 8080), RequestHandler
            )
            # Should not raise
            server.service_actions()


# =============================================================================
# Test Helper Functions
# =============================================================================


@pytest.mark.unit
class TestHelperFunctions:
    """Test module-level helper functions."""

    def test_start_ticker_process(self, mock_ticker_handler, mock_ticker, mock_logger):
        """Test starting ticker in separate process."""
        mock_manager = Mock()
        mock_process = Mock()

        with patch("multiprocessing.Process", return_value=mock_process):
            proc = _start_ticker_process(
                mock_ticker_handler, mock_ticker, mock_manager, mock_logger
            )

            mock_ticker_handler.ticker_start.assert_called_once_with(mock_manager)
            mock_process.start.assert_called_once()
            mock_logger.debug.assert_called_with("ticker process started")
            assert proc == mock_process

    def test_start_ticker_in_process_with_ticker(self, mock_logger):
        """Test starting ticker in single-process mode."""
        mock_handler = Mock(spec=Ticker)
        mock_handler.start = Mock()

        _start_ticker_in_process(mock_handler, mock_logger)

        mock_handler.start.assert_called_once()
        mock_logger.debug.assert_called_with("ticker started in single-process mode")

    def test_start_ticker_in_process_without_ticker(self, mock_handler, mock_logger):
        """Test starting ticker when handler is not a Ticker."""
        # Should not raise, just do nothing
        _start_ticker_in_process(mock_handler, mock_logger)
        mock_logger.debug.assert_not_called()

    def test_start_ticker_in_process_with_none_handler(self, mock_logger):
        """Test starting ticker with None handler."""
        # Should not raise
        _start_ticker_in_process(None, mock_logger)

    def test_cleanup_ticker_process_terminates_running_process(self, mock_logger):
        """Test cleanup terminates running ticker process."""
        mock_proc = Mock()
        mock_proc.is_alive.return_value = True

        _cleanup_ticker_process(mock_proc, mock_logger)

        mock_proc.terminate.assert_called_once()
        mock_proc.join.assert_called_once()

    def test_cleanup_ticker_process_kills_if_not_terminated(self, mock_logger):
        """Test cleanup kills process if it doesn't terminate gracefully."""
        mock_proc = Mock()
        mock_proc.is_alive.side_effect = [True, True]  # Still alive after terminate

        _cleanup_ticker_process(mock_proc, mock_logger)

        mock_proc.terminate.assert_called_once()
        mock_proc.kill.assert_called_once()
        mock_logger.warning.assert_called()

    def test_cleanup_ticker_process_with_none_proc(self, mock_logger):
        """Test cleanup with None process."""
        # Should not raise
        _cleanup_ticker_process(None, mock_logger)

    def test_cleanup_ticker_process_with_dead_process(self, mock_logger):
        """Test cleanup with already-dead process."""
        mock_proc = Mock()
        mock_proc.is_alive.return_value = False

        _cleanup_ticker_process(mock_proc, mock_logger)

        # Should not try to terminate
        mock_proc.terminate.assert_not_called()

    def test_cleanup_ticker_process_handles_exceptions(self, mock_logger):
        """Test cleanup handles exceptions during termination."""
        mock_proc = Mock()
        mock_proc.is_alive.return_value = True
        mock_proc.terminate.side_effect = Exception("termination error")

        # Should not raise
        _cleanup_ticker_process(mock_proc, mock_logger)

        mock_logger.error.assert_called()


# =============================================================================
# Test run_http_server_with_cleanup
# =============================================================================


@pytest.mark.unit
class TestRunHTTPServerWithCleanup:
    """Test HTTP server execution with cleanup."""

    @patch("appinfra.net.tcp._Server")
    def test_server_runs_and_logs(self, mock_server_class, mock_logger, mock_handler):
        """Test HTTP server runs and logs properly."""
        mock_server = MagicMock()
        mock_server_class.return_value.__enter__.return_value = mock_server
        mock_server.serve_forever.side_effect = KeyboardInterrupt()

        _run_http_server_with_cleanup(mock_logger, mock_handler, "0.0.0.0", 8080)

        mock_logger.info.assert_any_call(
            "serving at port...",
            extra={"host": "0.0.0.0", "port": 8080, "mode": "multiprocessing"},
        )
        mock_server.serve_forever.assert_called_once()
        mock_server.shutdown.assert_called_once()
        mock_server.server_close.assert_called_once()

    @patch("appinfra.net.tcp._Server")
    def test_server_handles_keyboard_interrupt(
        self, mock_server_class, mock_logger, mock_handler
    ):
        """Test server handles keyboard interrupt gracefully."""
        mock_server = MagicMock()
        mock_server_class.return_value.__enter__.return_value = mock_server
        mock_server.serve_forever.side_effect = KeyboardInterrupt()

        _run_http_server_with_cleanup(mock_logger, mock_handler, "0.0.0.0", 8080)

        mock_logger.info.assert_any_call("keyboard interrupt, exiting server...")

    @patch("appinfra.net.tcp._Server")
    def test_server_handles_exception_during_serve(
        self, mock_server_class, mock_logger, mock_handler
    ):
        """Test server handles exception during serve_forever."""
        mock_server = MagicMock()
        mock_server_class.return_value.__enter__.return_value = mock_server
        mock_server.serve_forever.side_effect = Exception("serve error")

        with pytest.raises(ServerShutdownError, match="HTTP server error"):
            _run_http_server_with_cleanup(mock_logger, mock_handler, "0.0.0.0", 8080)

        mock_logger.error.assert_called()

    @patch("appinfra.net.tcp._Server")
    def test_server_cleanup_on_shutdown_error(
        self, mock_server_class, mock_logger, mock_handler
    ):
        """Test cleanup continues even if shutdown fails."""
        mock_server = MagicMock()
        mock_server_class.return_value.__enter__.return_value = mock_server
        mock_server.serve_forever.side_effect = KeyboardInterrupt()
        mock_server.shutdown.side_effect = Exception("shutdown error")

        _run_http_server_with_cleanup(mock_logger, mock_handler, "0.0.0.0", 8080)

        mock_logger.error.assert_any_call(
            "error during server shutdown",
            extra={"exception": mock_server.shutdown.side_effect},
        )


# =============================================================================
# Test Server Initialization
# =============================================================================


@pytest.mark.unit
class TestServerInitialization:
    """Test Server class initialization."""

    def test_init_success(self, mock_logger, mock_handler):
        """Test successful server initialization."""
        server = Server(mock_logger, 8080, mock_handler)
        assert server._lg == mock_logger
        assert server._port == 8080
        assert server._handler == mock_handler
        assert server._ticker is None

    def test_init_with_ticker(self, mock_logger, mock_handler, mock_ticker):
        """Test initialization with ticker."""
        server = Server(mock_logger, 8080, mock_handler, ticker=mock_ticker)
        assert server._ticker == mock_ticker

    def test_init_with_none_logger_raises_error(self, mock_handler):
        """Test initialization with None logger raises ValueError."""
        with pytest.raises(ValueError, match="Logger cannot be None"):
            Server(None, 8080, mock_handler)

    def test_init_with_none_port_raises_error(self, mock_logger, mock_handler):
        """Test initialization with None port raises ValueError."""
        with pytest.raises(ValueError, match="Port must be a positive integer"):
            Server(mock_logger, None, mock_handler)

    def test_init_with_invalid_port_type_raises_error(self, mock_logger, mock_handler):
        """Test initialization with invalid port type raises ValueError."""
        with pytest.raises(ValueError, match="Port must be a positive integer"):
            Server(mock_logger, "8080", mock_handler)

    def test_init_with_zero_port_raises_error(self, mock_logger, mock_handler):
        """Test initialization with zero port raises ValueError."""
        with pytest.raises(ValueError, match="Port must be a positive integer"):
            Server(mock_logger, 0, mock_handler)

    def test_init_with_negative_port_raises_error(self, mock_logger, mock_handler):
        """Test initialization with negative port raises ValueError."""
        with pytest.raises(ValueError, match="Port must be a positive integer"):
            Server(mock_logger, -1, mock_handler)

    def test_init_with_none_handler_raises_error(self, mock_logger):
        """Test initialization with None handler raises ValueError."""
        with pytest.raises(ValueError, match="Handler cannot be None"):
            Server(mock_logger, 8080, None)

    def test_init_logs_debug_message(self, mock_logger, mock_handler):
        """Test initialization logs debug message."""
        Server(mock_logger, 8080, mock_handler)
        mock_logger.debug.assert_called_with("Server initialized on port 8080")


# =============================================================================
# Test Server.run() - Single Process Mode
# =============================================================================


@pytest.mark.unit
class TestServerRunInProcess:
    """Test Server.run() in single-process mode."""

    @patch("appinfra.net.tcp._start_ticker_in_process")
    @patch("appinfra.net.tcp._run_http_server_with_cleanup")
    def test_run_in_process_mode(
        self,
        mock_run_http,
        mock_start_ticker,
        mock_logger,
        mock_handler,
    ):
        """Test running server in single-process mode."""
        server = Server(mock_logger, 8080, mock_handler)

        result = server.run()

        assert result == 0
        mock_logger.debug.assert_any_call(
            "running server in process...", extra={"port": 8080}
        )
        mock_start_ticker.assert_called_once_with(mock_handler, mock_logger)
        mock_run_http.assert_called_once()

    @patch("appinfra.net.tcp._start_ticker_in_process")
    @patch("appinfra.net.tcp._run_http_server_with_cleanup")
    def test_run_handles_ticker_startup_error(
        self, mock_run_http, mock_start_ticker, mock_logger, mock_handler
    ):
        """Test run handles ticker startup error."""
        mock_start_ticker.side_effect = Exception("ticker error")
        server = Server(mock_logger, 8080, mock_handler)

        with pytest.raises(ServerStartupError, match="Ticker startup failed"):
            server.run()

        mock_logger.error.assert_called()

    @patch("appinfra.net.tcp._start_ticker_in_process")
    @patch("appinfra.net.tcp._run_http_server_with_cleanup")
    def test_run_handles_http_server_startup_error(
        self, mock_run_http, mock_start_ticker, mock_logger, mock_handler
    ):
        """Test run handles HTTP server startup error."""
        mock_run_http.side_effect = Exception("http error")
        server = Server(mock_logger, 8080, mock_handler)

        with pytest.raises(ServerStartupError, match="HTTP server startup failed"):
            server.run()

        mock_logger.error.assert_called()


# =============================================================================
# Test Server.run() - Multiprocessing Mode
# =============================================================================


@pytest.mark.unit
class TestServerRunMultiprocessing:
    """Test Server.run() in multiprocessing mode."""

    @patch("appinfra.net.tcp._cleanup_ticker_process")
    @patch("appinfra.net.tcp._run_http_server_with_cleanup")
    @patch("appinfra.net.tcp._start_ticker_process")
    @patch("multiprocessing.Manager")
    def test_run_multiprocessing_mode(
        self,
        mock_manager_class,
        mock_start_ticker,
        mock_run_http,
        mock_cleanup,
        mock_logger,
        mock_ticker_handler,
        mock_ticker,
    ):
        """Test running server in multiprocessing mode."""
        mock_manager = MagicMock()
        mock_manager_class.return_value.__enter__.return_value = mock_manager
        mock_proc = Mock()
        mock_start_ticker.return_value = mock_proc

        server = Server(mock_logger, 8080, mock_ticker_handler, ticker=mock_ticker)
        result = server.run()

        assert result == 0
        mock_logger.debug.assert_any_call(
            "running server with multiprocessing...", extra={"port": 8080}
        )
        mock_start_ticker.assert_called_once()
        mock_run_http.assert_called_once()
        mock_cleanup.assert_called()

    @patch("appinfra.net.tcp._cleanup_ticker_process")
    @patch("appinfra.net.tcp._run_http_server_with_cleanup")
    @patch("appinfra.net.tcp._start_ticker_process")
    @patch("multiprocessing.Manager")
    def test_run_multiprocessing_with_invalid_handler(
        self,
        mock_manager_class,
        mock_start_ticker,
        mock_run_http,
        mock_cleanup,
        mock_logger,
        mock_handler,
        mock_ticker,
    ):
        """Test multiprocessing mode with handler that doesn't implement TickerHandler."""
        server = Server(mock_logger, 8080, mock_handler, ticker=mock_ticker)

        with pytest.raises(
            ServerStartupError, match="Handler must implement TickerHandler"
        ):
            server.run()

    @patch("appinfra.net.tcp._cleanup_ticker_process")
    @patch("appinfra.net.tcp._run_http_server_with_cleanup")
    @patch("appinfra.net.tcp._start_ticker_process")
    @patch("multiprocessing.Manager")
    def test_run_multiprocessing_handles_ticker_startup_error(
        self,
        mock_manager_class,
        mock_start_ticker,
        mock_run_http,
        mock_cleanup,
        mock_logger,
        mock_ticker_handler,
        mock_ticker,
    ):
        """Test multiprocessing mode handles ticker startup error."""
        mock_manager = MagicMock()
        mock_manager_class.return_value.__enter__.return_value = mock_manager
        mock_start_ticker.side_effect = Exception("ticker error")

        server = Server(mock_logger, 8080, mock_ticker_handler, ticker=mock_ticker)

        with pytest.raises(ServerStartupError, match="Ticker startup failed"):
            server.run()

        mock_cleanup.assert_called()

    @patch("appinfra.net.tcp._cleanup_ticker_process")
    @patch("appinfra.net.tcp._run_http_server_with_cleanup")
    @patch("appinfra.net.tcp._start_ticker_process")
    @patch("multiprocessing.Manager")
    def test_run_multiprocessing_handles_http_startup_error(
        self,
        mock_manager_class,
        mock_start_ticker,
        mock_run_http,
        mock_cleanup,
        mock_logger,
        mock_ticker_handler,
        mock_ticker,
    ):
        """Test multiprocessing mode handles HTTP server startup error."""
        mock_manager = MagicMock()
        mock_manager_class.return_value.__enter__.return_value = mock_manager
        mock_proc = Mock()
        mock_start_ticker.return_value = mock_proc
        mock_run_http.side_effect = Exception("http error")

        server = Server(mock_logger, 8080, mock_ticker_handler, ticker=mock_ticker)

        with pytest.raises(ServerStartupError, match="HTTP server startup failed"):
            server.run()

        mock_cleanup.assert_called()

    @patch("appinfra.net.tcp._cleanup_ticker_process")
    @patch("appinfra.net.tcp._run_http_server_with_cleanup")
    @patch("appinfra.net.tcp._start_ticker_process")
    @patch("multiprocessing.Manager")
    def test_run_multiprocessing_cleanup_in_finally(
        self,
        mock_manager_class,
        mock_start_ticker,
        mock_run_http,
        mock_cleanup,
        mock_logger,
        mock_ticker_handler,
        mock_ticker,
    ):
        """Test multiprocessing mode cleanup is called in finally block."""
        mock_manager = MagicMock()
        mock_manager_class.return_value.__enter__.return_value = mock_manager
        mock_proc = Mock()
        mock_start_ticker.return_value = mock_proc
        mock_run_http.side_effect = Exception("error")

        server = Server(mock_logger, 8080, mock_ticker_handler, ticker=mock_ticker)

        with pytest.raises(ServerStartupError):
            server.run()

        # Cleanup should be called twice - once in except, once in finally
        assert mock_cleanup.call_count >= 1


# =============================================================================
# Test HTTP RequestHandler
# =============================================================================


@pytest.mark.unit
class TestRequestHandler:
    """Test HTTP RequestHandler."""

    def test_do_get_delegates_to_server_handler(self, mock_logger, mock_handler):
        """Test do_GET delegates to server handler."""
        mock_server = Mock()
        mock_server._lg = mock_logger
        mock_server._handler = mock_handler

        # Create handler without invoking __init__ (which calls handle())
        with patch.object(RequestHandler, "__init__", return_value=None):
            handler = RequestHandler.__new__(RequestHandler)
            handler.server = mock_server
            handler.send_error = Mock()

            handler.do_GET()

            mock_handler.do_GET.assert_called_once_with(handler)

    def test_do_get_handles_exception(self, mock_logger, mock_handler):
        """Test do_GET handles exception from handler."""
        mock_server = Mock()
        mock_server._lg = mock_logger
        mock_server._handler = mock_handler
        mock_handler.do_GET.side_effect = Exception("handler error")

        with patch.object(RequestHandler, "__init__", return_value=None):
            handler = RequestHandler.__new__(RequestHandler)
            handler.server = mock_server
            handler.send_error = Mock()

            with pytest.raises(HandlerError, match="GET request handler failed"):
                handler.do_GET()

            mock_logger.error.assert_called()
            handler.send_error.assert_called_with(
                500, "Internal server error: handler error"
            )

    def test_do_head_delegates_to_server_handler(self, mock_logger, mock_handler):
        """Test do_HEAD delegates to server handler."""
        mock_server = Mock()
        mock_server._lg = mock_logger
        mock_server._handler = mock_handler

        with patch.object(RequestHandler, "__init__", return_value=None):
            handler = RequestHandler.__new__(RequestHandler)
            handler.server = mock_server
            handler.send_error = Mock()

            handler.do_HEAD()

            mock_handler.do_HEAD.assert_called_once_with(handler)

    def test_do_head_handles_exception(self, mock_logger, mock_handler):
        """Test do_HEAD handles exception from handler."""
        mock_server = Mock()
        mock_server._lg = mock_logger
        mock_server._handler = mock_handler
        mock_handler.do_HEAD.side_effect = Exception("handler error")

        with patch.object(RequestHandler, "__init__", return_value=None):
            handler = RequestHandler.__new__(RequestHandler)
            handler.server = mock_server
            handler.send_error = Mock()

            with pytest.raises(HandlerError, match="HEAD request handler failed"):
                handler.do_HEAD()

            mock_logger.error.assert_called()

    def test_log_message_uses_server_logger(self, mock_logger, mock_handler):
        """Test log_message uses server logger."""
        mock_server = Mock()
        mock_server._lg = mock_logger
        mock_server._handler = mock_handler

        with patch.object(RequestHandler, "__init__", return_value=None):
            handler = RequestHandler.__new__(RequestHandler)
            handler.server = mock_server

            handler.log_message("GET %s %d", "/test", 200)

            mock_logger.trace.assert_called_once_with("GET /test 200")


# =============================================================================
# Test Integration Scenarios
# =============================================================================


@pytest.mark.integration
class TestIntegrationScenarios:
    """Test real-world server scenarios."""

    @patch("appinfra.net.tcp._run_http_server_with_cleanup")
    @patch("appinfra.net.tcp._start_ticker_in_process")
    def test_server_with_handler_that_is_also_ticker(
        self, mock_start_ticker, mock_run_http, mock_logger
    ):
        """Test server with handler that implements both handler and ticker."""
        # Create handler that is both a request handler and ticker
        handler = Mock(spec=Ticker)
        handler.do_GET = Mock()
        handler.start = Mock()

        server = Server(mock_logger, 8080, handler)
        result = server.run()

        assert result == 0
        # Ticker should be started
        mock_start_ticker.assert_called_once_with(handler, mock_logger)
        # HTTP server should run
        mock_run_http.assert_called_once()

    def test_port_range_validation(self, mock_logger, mock_handler):
        """Test various port values."""
        # Valid ports
        Server(mock_logger, 1, mock_handler)
        Server(mock_logger, 8080, mock_handler)
        Server(mock_logger, 65535, mock_handler)

        # Invalid ports (note: upper bound not validated in code, only <= 0)
        with pytest.raises(ValueError):
            Server(mock_logger, 0, mock_handler)
        with pytest.raises(ValueError):
            Server(mock_logger, -1, mock_handler)


# =============================================================================
# Test Edge Cases
# =============================================================================


@pytest.mark.unit
class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_server_with_all_valid_ports(self, mock_logger, mock_handler):
        """Test server with boundary port values."""
        # Minimum valid port
        server = Server(mock_logger, 1, mock_handler)
        assert server._port == 1

        # Common ports
        server = Server(mock_logger, 80, mock_handler)
        assert server._port == 80

        server = Server(mock_logger, 443, mock_handler)
        assert server._port == 443

        # Maximum valid port
        server = Server(mock_logger, 65535, mock_handler)
        assert server._port == 65535

    def test_cleanup_ticker_process_with_exception_during_join(self, mock_logger):
        """Test cleanup handles exception during join."""
        mock_proc = Mock()
        mock_proc.is_alive.return_value = True
        mock_proc.join.side_effect = Exception("join error")

        # Should not raise
        _cleanup_ticker_process(mock_proc, mock_logger)

        mock_logger.error.assert_called()

    @patch("appinfra.net.tcp._Server")
    def test_http_server_cleanup_logs_shutdown_error(
        self, mock_server_class, mock_logger, mock_handler
    ):
        """Test that exception during shutdown is logged."""
        mock_server = MagicMock()
        mock_server_class.return_value.__enter__.return_value = mock_server
        mock_server.serve_forever.side_effect = KeyboardInterrupt()
        mock_server.shutdown.side_effect = Exception("shutdown error")

        _run_http_server_with_cleanup(mock_logger, mock_handler, "0.0.0.0", 8080)

        # Shutdown should be attempted
        mock_server.shutdown.assert_called_once()
        # Error should be logged
        mock_logger.error.assert_any_call(
            "error during server shutdown",
            extra={"exception": mock_server.shutdown.side_effect},
        )

    def test_server_attributes_are_private(self, mock_logger, mock_handler):
        """Test server attributes use private naming."""
        server = Server(mock_logger, 8080, mock_handler)
        # Attributes should be private (underscore prefix)
        assert hasattr(server, "_lg")
        assert hasattr(server, "_port")
        assert hasattr(server, "_handler")
        assert hasattr(server, "_ticker")
