# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Base server class for HTTP-based applications.

This module provides the enhanced server base class.
"""

import contextlib
import logging
import threading
from collections.abc import Callable, Generator
from typing import Any

from ... import time
from ..tracing.traceable import Traceable
from .handlers import Middleware
from .routes import RouteManager


class Server(Traceable):
    """
    Enhanced server base class for HTTP-based applications.

    Provides a framework for building servers with:
    - Route management and handling
    - Request processing lifecycle
    - Server startup and tick management
    - HTTP method handling (GET, HEAD, etc.)
    - Middleware support
    """

    def __init__(self, parent: Traceable | None = None):
        """
        Initialize the server instance.

        Args:
            parent: Parent traceable object (optional)
        """
        super().__init__(parent)
        self.routes = RouteManager()
        self.middleware: list[Middleware] = []

    @property
    def server_routes(self) -> RouteManager:
        """
        Get the server's route configuration.

        Returns:
            RouteManager: Route configuration for the server
        """
        return self.routes

    def add_route(
        self, path: str, handler: Callable, methods: list[str] | None = None
    ) -> None:
        """
        Add a route to the server.

        Args:
            path: URL path pattern
            handler: Function to handle requests
            methods: HTTP methods to handle (default: ['GET'])
        """
        if methods is None:
            methods = ["GET"]
        self.routes.add_route(path, handler, methods)

    def add_middleware(self, middleware: Middleware) -> None:
        """
        Add middleware to the request pipeline.

        Args:
            middleware: Middleware instance to add
        """
        self.middleware.append(middleware)

    def server_start(self, manager: Any) -> None:
        """
        Handle server startup.

        Args:
            manager: Server manager instance
        """
        pass

    def server_tick(self) -> None:
        """
        Handle server tick/periodic processing.

        Called periodically to perform maintenance tasks or background processing.
        """
        pass

    def server_do_GET(self, req: Any, **kwargs: Any) -> Any:
        """
        Handle GET requests.

        Args:
            req: HTTP request object
            **kwargs: Additional request parameters

        Returns:
            Response data
        """
        pass

    def server_do_POST(self, req: Any, **kwargs: Any) -> Any:
        """
        Handle POST requests.

        Args:
            req: HTTP request object
            **kwargs: Additional request parameters

        Returns:
            Response data
        """
        pass

    def server_do_PUT(self, req: Any, **kwargs: Any) -> Any:
        """
        Handle PUT requests.

        Args:
            req: HTTP request object
            **kwargs: Additional request parameters

        Returns:
            Response data
        """
        pass

    def server_do_DELETE(self, req: Any, **kwargs: Any) -> Any:
        """
        Handle DELETE requests.

        Args:
            req: HTTP request object
            **kwargs: Additional request parameters

        Returns:
            Response data
        """
        pass

    async def handle_request(self, request: Any) -> Any:
        """
        Handle an incoming request.

        Args:
            request: HTTP request object

        Returns:
            Response object
        """
        # Apply middleware
        for middleware in self.middleware:
            request = await middleware.process_request(request)

        # Route the request
        response = await self.routes.handle_request(request)

        # Apply response middleware
        for middleware in reversed(self.middleware):
            response = await middleware.process_response(response)

        return response


@contextlib.contextmanager
def lock_helper(
    lock: threading.Lock,
    lg: logging.Logger,
    where: str | None = None,
    timeout: float | None = None,
) -> Generator[None, None, None]:
    """
    Context manager for acquiring and releasing locks with logging.

    Provides safe lock acquisition with timeout support and detailed logging
    of lock acquisition/release timing and success/failure.

    Args:
        lock: Lock object to acquire
        lg: Logger instance for lock operation logging
        where: Description of where the lock is being used
        timeout: Timeout for lock acquisition (in seconds)

    Yields:
        None: When lock is successfully acquired

    Raises:
        TimeoutError: If lock acquisition times out

    Example:
        with lock_helper(my_lock, logger, "database_update", timeout=5.0):
            # Critical section code
            pass
    """
    start_t = time.start()
    if lock.acquire(timeout=timeout):  # type: ignore[arg-type]
        lg.trace("acquired lock", extra={"after": time.since(start_t), "where": where})  # type: ignore[attr-defined]
        locked_t = time.start()
        try:
            yield
        finally:
            lock.release()
            lg.trace(  # type: ignore[attr-defined]
                "released lock",
                extra={
                    "after": time.since(locked_t),
                    "total": time.since(start_t),
                    "where": where,
                },
            )
    else:
        elapsed = time.since(start_t)
        lg.error(
            "failed to acquire lock",
            extra={"after": elapsed, "where": where, "timeout": timeout},
        )
        raise TimeoutError(
            f"Failed to acquire lock{' at ' + where if where else ''} "
            f"after {elapsed:.3f}s (timeout: {timeout}s)"
        )


def get_server_routes(tool_list: list[Any]) -> dict[str, Any]:
    """
    Extract server routes from a list of tools.

    Collects route configurations from tools that have server_routes defined,
    supporting both dictionary and list-based route configurations.

    Args:
        tool_list: List of tool instances to extract routes from

    Returns:
        dict: Combined route mapping from all tools
    """
    routes = {}
    for tool in tool_list:
        if not hasattr(tool, "server_routes") or not tool.server_routes:
            continue
        if isinstance(tool.server_routes, dict):
            # Dictionary-based routes: update with tool's routes
            routes.update(tool.server_routes)
        else:
            # List-based routes: map each route to the tool
            for r in tool.server_routes:
                routes[r] = tool
    return routes
