# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Route management for server applications.

This module provides route management functionality with ReDoS protection
for pattern-based routes.
"""

from collections.abc import Callable
from re import Pattern
from typing import Any

from ...regex_utils import safe_compile


class RouteManager:
    """Manages server routes and request routing with ReDoS protection."""

    def __init__(self) -> None:
        self._routes: dict[str, dict[str, Callable]] = {}
        self._patterns: list[tuple[Pattern, dict[str, Callable]]] = []

    def add_route(self, path: str, handler: Callable, methods: list[str]) -> None:
        """
        Add a route to the manager.

        Args:
            path: URL path pattern (supports regex with ReDoS protection)
            handler: Function to handle requests
            methods: HTTP methods to handle

        Raises:
            RegexComplexityError: If pattern is too complex or dangerous
            RegexTimeoutError: If pattern compilation times out
            re.error: If pattern is invalid

        Note:
            Pattern-based routes are protected against ReDoS attacks using
            timeout mechanisms and complexity validation.
        """
        if "*" in path or "{" in path or "[" in path:
            # Pattern-based route with ReDoS protection
            pattern = safe_compile(path, timeout=1.0)
            route_info = {method: handler for method in methods}
            self._patterns.append((pattern, route_info))
        else:
            # Simple string route
            if path not in self._routes:
                self._routes[path] = {}
            for method in methods:
                self._routes[path][method] = handler

    def get_handler(self, path: str, method: str) -> Callable | None:
        """
        Get handler for a path and method.

        Args:
            path: Request path
            method: HTTP method

        Returns:
            Handler function or None if not found
        """
        # Check simple routes first
        if path in self._routes and method in self._routes[path]:
            return self._routes[path][method]

        # Check pattern routes
        for pattern, route_info in self._patterns:
            if pattern.match(path) and method in route_info:
                return route_info[method]

        return None

    async def handle_request(self, request: Any) -> Any:
        """
        Handle a request by routing it to the appropriate handler.

        Args:
            request: HTTP request object

        Returns:
            Response object
        """
        path = getattr(request, "path", "/")
        method = getattr(request, "method", "GET")

        handler = self.get_handler(path, method)
        if handler:
            return await handler(request)

        # Return 404 if no handler found
        return self._create_404_response()

    def _create_404_response(self) -> Any:
        """Create a 404 Not Found response."""
        # This would be implemented based on the specific HTTP framework being used
        return {"status": 404, "message": "Not Found"}

    def list_routes(self) -> dict[str, list[str]]:
        """
        List all registered routes.

        Returns:
            Dictionary mapping paths to lists of supported methods
        """
        routes = {}

        # Add simple routes
        for path, methods in self._routes.items():
            routes[path] = list(methods.keys())

        # Add pattern routes
        for pattern, methods in self._patterns:
            routes[f"PATTERN: {pattern.pattern}"] = list(methods.keys())

        return routes
