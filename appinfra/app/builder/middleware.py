# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Middleware builder for the AppBuilder framework.

This module provides a fluent API for building middleware components
with request/response processing and conditional execution.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Self

from ..server.handlers import Middleware


class MiddlewareBuilder:
    """Builder for creating middleware with fluent API."""

    def __init__(self, name: str):
        """
        Initialize the middleware builder.

        Args:
            name: Middleware name
        """
        self._name = name
        self._request_processor: Callable | None = None
        self._response_processor: Callable | None = None
        self._error_handler: Callable | None = None
        self._conditions: list[Callable] = []
        self._priority: int = 0

    def process_request(self, func: Callable) -> Self:
        """
        Set the request processing function.

        Args:
            func: Function that processes requests
                  Signature: func(request) -> modified_request
        """
        self._request_processor = func
        return self

    def process_response(self, func: Callable) -> Self:
        """
        Set the response processing function.

        Args:
            func: Function that processes responses
                  Signature: func(response) -> modified_response
        """
        self._response_processor = func
        return self

    def handle_error(self, func: Callable) -> Self:
        """
        Set the error handling function.

        Args:
            func: Function that handles errors
                  Signature: func(error, request) -> response
        """
        self._error_handler = func
        return self

    def when(self, condition: Callable) -> Self:
        """
        Add a condition for when this middleware should run.

        Args:
            condition: Function that returns True if middleware should run
                       Signature: func(request) -> bool
        """
        self._conditions.append(condition)
        return self

    def with_priority(self, priority: int) -> Self:
        """
        Set the middleware priority (higher numbers run first).

        Args:
            priority: Priority level
        """
        self._priority = priority
        return self

    def build(self) -> BuiltMiddleware:
        """Build the middleware with all configured options."""
        return BuiltMiddleware(
            name=self._name,
            request_processor=self._request_processor,
            response_processor=self._response_processor,
            error_handler=self._error_handler,
            conditions=self._conditions,
            priority=self._priority,
        )


class BuiltMiddleware(Middleware):
    """Middleware implementation built by MiddlewareBuilder."""

    def __init__(
        self,
        name: str,
        request_processor: Callable | None = None,
        response_processor: Callable | None = None,
        error_handler: Callable | None = None,
        conditions: list[Callable] | None = None,
        priority: int = 0,
    ) -> None:
        """
        Initialize the built middleware.

        Args:
            name: Middleware name
            request_processor: Request processing function
            response_processor: Response processing function
            error_handler: Error handling function
            conditions: List of conditions for execution
            priority: Middleware priority
        """
        super().__init__()
        self.name = name
        self._request_processor = request_processor
        self._response_processor = response_processor
        self._error_handler = error_handler
        self._conditions = conditions or []
        self._priority = priority

    async def process_request(self, request: Any) -> Any:
        """Process an incoming request."""
        # Check conditions
        if not self._should_run(request):
            return request

        # Process request if processor is defined
        if self._request_processor:
            try:
                return self._request_processor(request)
            except Exception as e:
                if self._error_handler:
                    return self._error_handler(e, request)
                raise

        return request

    async def process_response(self, response: Any) -> Any:
        """Process an outgoing response."""
        # Process response if processor is defined
        if self._response_processor:
            try:
                return self._response_processor(response)
            except Exception as e:
                if self._error_handler:
                    return self._error_handler(e, response)
                raise

        return response

    def _should_run(self, request: Any) -> bool:
        """Check if middleware should run based on conditions."""
        if not self._conditions:
            return True

        for condition in self._conditions:
            try:
                if not condition(request):
                    return False
            except Exception:
                # If condition fails, don't run middleware
                return False

        return True

    def __lt__(self, other: Any) -> bool:
        """Compare middleware by priority for sorting."""
        if not hasattr(other, "_priority"):
            return NotImplemented
        return bool(self._priority > other._priority)


class LoggingMiddleware(Middleware):
    """Built-in logging middleware."""

    def __init__(
        self, logger: Any = None, log_requests: bool = True, log_responses: bool = False
    ) -> None:
        """
        Initialize logging middleware.

        Args:
            logger: Logger instance
            log_requests: Whether to log requests
            log_responses: Whether to log responses
        """
        super().__init__()
        self.logger = logger
        self.log_requests = log_requests
        self.log_responses = log_responses

    async def process_request(self, request: Any) -> Any:
        """Log incoming request."""
        if self.log_requests and self.logger:
            self.logger.info(
                f"request: {getattr(request, 'method', 'UNKNOWN')} {getattr(request, 'path', 'UNKNOWN')}"
            )
        return request

    async def process_response(self, response: Any) -> Any:
        """Log outgoing response."""
        if self.log_responses and self.logger:
            self.logger.info(f"response: {getattr(response, 'status_code', 'UNKNOWN')}")
        return response


class CORSMiddleware(Middleware):
    """Built-in CORS middleware."""

    def __init__(
        self, origins: list[str] | None = None, allow_credentials: bool = True
    ) -> None:
        """
        Initialize CORS middleware.

        Args:
            origins: List of allowed origins
            allow_credentials: Whether to allow credentials
        """
        super().__init__()
        self.origins = origins or ["*"]
        self.allow_credentials = allow_credentials

    async def process_request(self, request: Any) -> Any:
        """Process CORS request."""
        # Add CORS headers to request context
        if hasattr(request, "cors_origins"):
            request.cors_origins = self.origins
        return request

    async def process_response(self, response: Any) -> Any:
        """Add CORS headers to response."""
        if hasattr(response, "headers"):
            response.headers["Access-Control-Allow-Origin"] = ", ".join(self.origins)
            response.headers["Access-Control-Allow-Methods"] = (
                "GET, POST, PUT, DELETE, OPTIONS"
            )
            response.headers["Access-Control-Allow-Headers"] = (
                "Content-Type, Authorization"
            )
            if self.allow_credentials:
                response.headers["Access-Control-Allow-Credentials"] = "true"
        return response


def create_logging_middleware(logger: Any = None, **kwargs: Any) -> MiddlewareBuilder:
    """Create a logging middleware builder."""
    return (
        MiddlewareBuilder("logging")
        .process_request(LoggingMiddleware(logger, **kwargs).process_request)
        .process_response(LoggingMiddleware(logger, **kwargs).process_response)
    )


def create_cors_middleware(
    origins: list[str] | None = None, **kwargs: Any
) -> MiddlewareBuilder:
    """Create a CORS middleware builder."""
    return (
        MiddlewareBuilder("cors")
        .process_request(CORSMiddleware(origins, **kwargs).process_request)
        .process_response(CORSMiddleware(origins, **kwargs).process_response)
    )


def create_middleware_builder(name: str) -> MiddlewareBuilder:
    """
    Create a new middleware builder.

    Args:
        name: Name of the middleware

    Returns:
        MiddlewareBuilder instance

    Example:
        middleware = create_middleware_builder("custom").process_request(handler).build()
    """
    return MiddlewareBuilder(name)
