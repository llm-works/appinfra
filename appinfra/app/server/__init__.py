# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Server framework for HTTP-based applications (EXPERIMENTAL).

.. warning::
    This module is **experimental** and not recommended for production use.
    The async server framework is incomplete and not fully integrated with
    the CLI application framework.

    The appinfra.app framework is primarily designed for CLI tools (synchronous).
    This async HTTP server module was added for future expansion but remains
    largely untested in production scenarios.

    For production HTTP servers, consider using established frameworks like:
    - FastAPI (async, modern)
    - Flask (sync, mature)
    - Starlette (async, lightweight)

This module provides server framework components:
- Base server class
- Route management
- Request handlers
- Async middleware support

Status: Experimental / Future Work
"""

from .base import Server
from .handlers import Middleware, RequestHandler
from .routes import RouteManager

__all__ = ["Server", "RouteManager", "RequestHandler", "Middleware"]
