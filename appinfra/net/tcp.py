"""
TCP server implementation for network-based applications.

This module provides a TCP server that can run in single-process or multiprocessing
mode, with support for ticker-based background processing and HTTP request handling.

The server is designed for applications that need to serve HTTP requests while
performing background tasks, such as:
- Web APIs with periodic data updates
- Monitoring services with health checks
- Data processing servers with background workers
- Real-time applications with ticker-based updates

Key Features:
- Dual execution modes (single-process and multiprocessing)
- Ticker integration for background processing
- HTTP request handling with custom handlers
- Graceful shutdown and resource cleanup
- Comprehensive logging integration

Example Usage:
    # Simple HTTP server
    class MyHandler(HTTPRequestHandler):
        def do_GET(self, instance):
            instance.send_response(200)
            instance.send_header("Content-type", "text/html")
            instance.end_headers()
            instance.wfile.write(b"Hello, World!")

    server = TCPServer(logger, 8080, MyHandler())
    server.run()

    # Server with background ticker
    class MyTickerHandler(Ticker, TickerHandler, HTTPRequestHandler):
        def __init__(self, lg):
            self._lg = lg
            super().__init__(self, secs=5)  # Tick every 5 seconds

        def ticker_tick(self):
            self._lg.info("background task executed")

        def do_GET(self, instance):
            instance.send_response(200)
            instance.send_header("Content-type", "application/json")
            instance.end_headers()
            instance.wfile.write(b'{"status": "ok"}')

    handler = MyTickerHandler(logger)
    server = TCPServer(logger, 8080, handler, handler)
    server.run()  # Runs in multiprocessing mode
"""

import multiprocessing
import socketserver
from typing import Any

from ..log import Logger
from ..time import Ticker, TickerHandler
from .errors import (
    ServerShutdownError,
    ServerStartupError,
)
from .http import RequestHandler as HTTPRequestHandler


class _Server(socketserver.TCPServer):
    """
    Internal TCP server implementation.

    Extends the standard TCPServer to integrate with the application's
    logging system and request handling framework. This class handles
    the low-level TCP server operations while delegating request
    processing to custom handlers.

    The server automatically enables address reuse to allow quick
    restarts and provides hooks for periodic service actions.
    """

    def __init__(self, lg: Logger, handler: Any, *args: Any, **kwargs: Any) -> None:
        """
        Initialize the TCP server.

        Args:
            lg: Logger instance for server operations
            handler: Request handler instance
            *args: Arguments passed to TCPServer
            **kwargs: Keyword arguments passed to TCPServer

        Raises:
            ServerStartupError: If server initialization fails
        """
        try:
            self._lg = lg
            self._handler = handler
            super().__init__(*args, **kwargs)
            self._lg.debug("TCP server initialized successfully")
        except Exception as e:
            self._lg.error("failed to initialize TCP server", extra={"exception": e})
            raise ServerStartupError(f"Server initialization failed: {e}") from e

    def allow_reuse_address(self) -> bool:  # type: ignore[override]
        """
        Allow address reuse for the server socket.

        Returns:
            bool: Always True to allow address reuse
        """
        return True

    def service_actions(self) -> None:
        """
        Perform periodic service actions.

        Currently a no-op, can be overridden for periodic maintenance tasks.
        """
        pass


# Helper functions for Server._run_multiprocessing()


def _start_ticker_process(
    handler: Any, ticker: Any, manager: Any, lg: Any
) -> multiprocessing.Process:
    """Start ticker in separate process with given manager."""
    handler.ticker_start(manager)
    proc = multiprocessing.Process(target=ticker.run_started, args=(manager,))
    proc.start()
    lg.debug("ticker process started")
    return proc


def _start_ticker_in_process(handler: Any, lg: Any) -> None:
    """Start ticker in single-process mode if handler supports it."""
    if handler is not None and isinstance(handler, Ticker):
        handler.start()
        lg.debug("ticker started in single-process mode")


def _run_http_server_with_cleanup(
    lg: Any, handler: Any, host: str, port: int, mode: str = "multiprocessing"
) -> None:
    """Run HTTP server with proper cleanup."""
    with _Server(lg, handler, (host, port), HTTPRequestHandler) as httpd:
        lg.info(
            "serving at port...",
            extra={"host": host, "port": port, "mode": mode},
        )
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            lg.info("keyboard interrupt, exiting server...")
        except Exception as e:
            lg.error("HTTP server error", extra={"exception": e})
            raise ServerShutdownError(f"HTTP server error: {e}") from e
        finally:
            try:
                httpd.shutdown()
                httpd.server_close()
                lg.info("closed server")
            except Exception as e:
                lg.error("error during server shutdown", extra={"exception": e})


def _cleanup_ticker_process(proc: multiprocessing.Process | None, lg: Any) -> None:
    """Terminate and join ticker process."""
    if not proc or not proc.is_alive():
        return

    try:
        proc.terminate()
        proc.join(timeout=5)
        if proc.is_alive():
            lg.warning("ticker process did not terminate gracefully")
            proc.kill()
    except Exception as e:
        lg.error("error terminating ticker process", extra={"exception": e})


class Server:
    """
    TCP server with support for single-process and multiprocessing modes.

    Provides a flexible server implementation that can run with or without
    background ticker processes, supporting both HTTP and custom protocol handling.

    The server automatically chooses between single-process and multiprocessing
    modes based on whether a ticker is provided:
    - Single-process mode: Runs everything in the current process
    - Multiprocessing mode: Runs ticker in a separate process for better isolation

    Thread Safety:
        The server is designed to be thread-safe when used correctly.
        In multiprocessing mode, shared state should be managed through
        multiprocessing.Manager() objects.

    Example:
        # Single-process server
        server = Server(logger, 8080, MyHandler())
        server.run()

        # Multiprocessing server with ticker
        handler = MyTickerHandler(logger)
        server = Server(logger, 8080, handler, handler)
        server.run()
    """

    def __init__(
        self, lg: Logger, port: int, handler: Any, ticker: Any | None = None
    ) -> None:
        """
        Initialize the TCP server.

        Args:
            lg: Logger instance for server operations
            port (int): Port number to listen on
            handler: Request handler instance
            ticker: Optional ticker for background processing

        Raises:
            ServerStartupError: If server initialization fails
            ValueError: If invalid parameters are provided
        """
        if lg is None:
            raise ValueError("Logger cannot be None")
        if port is None or not isinstance(port, int) or port <= 0:
            raise ValueError(f"Port must be a positive integer, got: {port}")
        if handler is None:
            raise ValueError("Handler cannot be None")

        try:
            self._lg = lg
            self._port = port
            self._handler = handler
            self._ticker = ticker
            self._lg.debug(f"Server initialized on port {port}")
        except Exception as e:
            raise ServerStartupError(f"Server initialization failed: {e}") from e

    def run(self) -> int:
        """
        Run the TCP server.

        Chooses between single-process and multiprocessing mode based on
        whether a ticker is provided.

        Returns:
            int: Exit code (0 for success, 1 for error)

        Raises:
            ServerStartupError: If server fails to start
            ServerShutdownError: If server fails to shutdown gracefully
        """
        try:
            if self._ticker is not None:
                if not isinstance(self._handler, TickerHandler):
                    raise ServerStartupError(
                        "Handler must implement TickerHandler when ticker is provided"
                    )
                return self._run_multiprocessing()
            return self._run_in_process()
        except Exception as e:
            self._lg.error("server run failed", extra={"exception": e})
            raise ServerStartupError(f"Server run failed: {e}") from e

    def _start_multiprocessing_components(
        self, manager: Any
    ) -> multiprocessing.Process:
        """Start ticker process and HTTP server with error handling."""
        try:
            proc = _start_ticker_process(self._handler, self._ticker, manager, self._lg)
        except Exception as e:
            self._lg.error("failed to start ticker process", extra={"exception": e})
            raise ServerStartupError(f"Ticker startup failed: {e}") from e

        try:
            _run_http_server_with_cleanup(
                self._lg, self._handler, "0.0.0.0", self._port
            )
        except Exception as e:
            self._lg.error("failed to start HTTP server", extra={"exception": e})
            raise ServerStartupError(f"HTTP server startup failed: {e}") from e

        return proc

    def _run_multiprocessing(self) -> int:
        """
        Run the server in multiprocessing mode with background ticker.

        Starts a separate process for the ticker and runs the HTTP server
        in the main process, with proper cleanup on shutdown.

        Returns:
            int: Exit code (0 for success)

        Raises:
            ServerStartupError: If server fails to start
            ServerShutdownError: If server fails to shutdown gracefully
        """
        self._lg.debug(
            "running server with multiprocessing...", extra={"port": self._port}
        )
        proc = None
        try:
            with multiprocessing.Manager() as manager:
                proc = self._start_multiprocessing_components(manager)
                _cleanup_ticker_process(proc, self._lg)

        except Exception as e:
            self._lg.error("multiprocessing server run failed", extra={"exception": e})
            raise ServerStartupError(f"Multiprocessing server run failed: {e}") from e
        finally:
            _cleanup_ticker_process(proc, self._lg)

        return 0

    def _run_in_process(self) -> int:
        """
        Run the server in single-process mode.

        Runs the HTTP server in the current process, optionally starting
        a ticker if the handler supports it.

        Returns:
            int: Exit code (0 for success)

        Raises:
            ServerStartupError: If server fails to start
            ServerShutdownError: If server fails to shutdown gracefully
        """
        self._lg.debug("running server in process...", extra={"port": self._port})

        try:
            try:
                _start_ticker_in_process(self._handler, self._lg)
            except Exception as e:
                self._lg.error("failed to start ticker", extra={"exception": e})
                raise ServerStartupError(f"Ticker startup failed: {e}") from e

            try:
                _run_http_server_with_cleanup(
                    self._lg, self._handler, "0.0.0.0", self._port, mode="in_process"
                )
            except Exception as e:
                self._lg.error("failed to start HTTP server", extra={"exception": e})
                raise ServerStartupError(f"HTTP server startup failed: {e}") from e

        except Exception as e:
            self._lg.error("single-process server run failed", extra={"exception": e})
            raise ServerStartupError(f"Single-process server run failed: {e}") from e

        return 0
