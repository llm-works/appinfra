"""
Request handlers and middleware for server applications.

This module provides request handling functionality and middleware support.
"""

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any


class Middleware(ABC):
    """Base class for server middleware."""

    @abstractmethod
    async def process_request(self, request: Any) -> Any:
        """
        Process an incoming request.

        Args:
            request: HTTP request object

        Returns:
            Modified request object
        """
        pass

    @abstractmethod
    async def process_response(self, response: Any) -> Any:
        """
        Process an outgoing response.

        Args:
            response: HTTP response object

        Returns:
            Modified response object
        """
        pass


class RequestHandler:
    """Base class for request handlers."""

    def __init__(self, server: Any = None) -> None:
        """
        Initialize the request handler.

        Args:
            server: Server instance (optional)
        """
        self.server = server

    async def handle(self, request: Any) -> Any:
        """
        Handle a request.

        Args:
            request: HTTP request object

        Returns:
            Response object
        """
        method = getattr(request, "method", "GET")
        handler_name = f"handle_{method.lower()}"

        if hasattr(self, handler_name):
            handler = getattr(self, handler_name)
            return await handler(request)

        return await self.handle_default(request)

    async def handle_default(self, request: Any) -> Any:
        """
        Handle requests with no specific method handler.

        Args:
            request: HTTP request object

        Returns:
            Response object
        """
        return {"status": 405, "message": "Method Not Allowed"}

    async def handle_get(self, request: Any) -> Any:
        """Handle GET requests."""
        return await self.handle_default(request)

    async def handle_post(self, request: Any) -> Any:
        """Handle POST requests."""
        return await self.handle_default(request)

    async def handle_put(self, request: Any) -> Any:
        """Handle PUT requests."""
        return await self.handle_default(request)

    async def handle_delete(self, request: Any) -> Any:
        """Handle DELETE requests."""
        return await self.handle_default(request)


class LoggingMiddleware(Middleware):
    """Middleware for request/response logging."""

    def __init__(self, logger: Any) -> None:
        """
        Initialize logging middleware.

        Args:
            logger: Logger instance
        """
        self.logger = logger

    async def process_request(self, request: Any) -> Any:
        """Log incoming request."""
        path = getattr(request, "path", "/")
        method = getattr(request, "method", "GET")
        self.logger.info("incoming request", extra={"method": method, "path": path})
        return request

    async def process_response(self, response: Any) -> Any:
        """Log outgoing response."""
        status = getattr(response, "status", 200)
        self.logger.info("outgoing response", extra={"status": status})
        return response


class AuthMiddleware(Middleware):
    """Middleware for authentication."""

    def __init__(self, auth_checker: Callable[[Any], bool]):
        """
        Initialize auth middleware.

        Args:
            auth_checker: Function to check if request is authenticated
        """
        self.auth_checker = auth_checker

    async def process_request(self, request: Any) -> Any:
        """Check authentication."""
        if not self.auth_checker(request):
            return self._create_unauthorized_response()
        return request

    async def process_response(self, response: Any) -> Any:
        """Process response (no changes needed for auth)."""
        return response

    def _create_unauthorized_response(self) -> Any:
        """Create an unauthorized response."""
        return {"status": 401, "message": "Unauthorized"}
