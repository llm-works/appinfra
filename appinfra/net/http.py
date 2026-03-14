"""
HTTP server components for web-based applications.

This module provides HTTP request handling components that integrate with
the application's logging and server framework.

The HTTP request handler is designed to work seamlessly with the TCP server,
providing custom request processing while maintaining compatibility with
standard HTTP protocols.

Key Features:
- Custom request handling with delegation to server handlers
- Integration with application's structured logging system
- Support for standard HTTP methods (GET, HEAD, POST, etc.)
- Extensible design for custom protocol handling

Example Usage:
    class MyHandler(HTTPRequestHandler):
        def do_GET(self, instance):
            # Handle GET requests
            instance.send_response(200)
            instance.send_header("Content-type", "application/json")
            instance.end_headers()
            instance.wfile.write(b'{"message": "Hello, World!"}')

        def do_POST(self, instance):
            # Handle POST requests
            content_length = int(instance.headers['Content-Length'])
            post_data = instance.rfile.read(content_length)
            # Process post_data...
            instance.send_response(200)
            instance.end_headers()
"""

import http.server
from typing import Any, Protocol, cast

from .errors import HandlerError


class ServerWithHandler(Protocol):
    """Protocol defining expected server interface with custom handler and logger."""

    _handler: Any
    _lg: Any


class RequestHandler(http.server.SimpleHTTPRequestHandler):
    """
    Custom HTTP request handler that integrates with the application framework.

    Extends the standard SimpleHTTPRequestHandler to delegate request handling
    to the application's server framework and use the application's logging system.

    Attributes:
        server: Server instance with _handler and _lg attributes (typed as ServerWithHandler)
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """
        Initialize the request handler.

        Args:
            *args: Arguments passed to the parent handler
            **kwargs: Keyword arguments passed to the parent handler
        """
        super().__init__(*args, **kwargs)

    def do_HEAD(self) -> None:
        """
        Handle HTTP HEAD requests.

        Delegates to the server's handler for custom HEAD request processing.

        Raises:
            HandlerError: If the handler fails to process the request
        """
        server = cast(ServerWithHandler, self.server)
        try:
            server._handler.do_HEAD(self)
        except Exception as e:
            server._lg.error("HEAD request handler error", extra={"exception": e})
            self.send_error(500, f"Internal server error: {e}")
            raise HandlerError(f"HEAD request handler failed: {e}") from e

    def do_GET(self) -> None:
        """
        Handle HTTP GET requests.

        Delegates to the server's handler for custom GET request processing.

        Raises:
            HandlerError: If the handler fails to process the request
        """
        server = cast(ServerWithHandler, self.server)
        try:
            server._handler.do_GET(self)
        except Exception as e:
            server._lg.error("GET request handler error", extra={"exception": e})
            self.send_error(500, f"Internal server error: {e}")
            raise HandlerError(f"GET request handler failed: {e}") from e

    def log_message(self, format: str, *args: Any, **kwargs: Any) -> None:
        """
        Log HTTP request messages using the application's logging system.

        Args:
            format: Log message format string
            *args: Format arguments
            **kwargs: Additional keyword arguments
        """
        # Use the server's logger for request logging
        server = cast(ServerWithHandler, self.server)
        server._lg.trace(format % args)
