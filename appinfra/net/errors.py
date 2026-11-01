# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Custom exceptions for the appinfra.net package.

This module contains all custom exception classes used by the networking
components to avoid circular import issues.
"""


class ServerError(Exception):
    """Base exception for server-related errors."""


class ServerStartupError(ServerError):
    """Raised when server fails to start."""


class ServerShutdownError(ServerError):
    """Raised when server fails to shutdown gracefully."""


class HandlerError(ServerError):
    """Raised when request handler encounters an error."""
