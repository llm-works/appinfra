"""
Custom exceptions for the appinfra.net package.

This module contains all custom exception classes used by the networking
components to avoid circular import issues.
"""


class ServerError(Exception):
    """Base exception for server-related errors."""

    pass


class ServerStartupError(ServerError):
    """Raised when server fails to start."""

    pass


class ServerShutdownError(ServerError):
    """Raised when server fails to shutdown gracefully."""

    pass


class HandlerError(ServerError):
    """Raised when request handler encounters an error."""

    pass
