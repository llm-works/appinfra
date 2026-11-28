# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
FastAPI server framework for appinfra.

Provides production-ready FastAPI + Uvicorn server framework with subprocess
isolation and Chan-based IPC.

Installation:
    pip install appinfra[fastapi]

Example (Simple Server - Direct Mode):
    from appinfra.app.fastapi import ServerBuilder
    from appinfra.log import Logger

    async def health():
        return {"status": "ok"}

    server = (ServerBuilder(Logger("myapi"), "myapi")
        .with_port(8000)
        .routes.with_route("/health", health).done()
        .build())

    server.start()  # Blocking

Example (Subprocess Mode with IPC):
    import threading

    from fastapi import Request

    from appinfra.app.fastapi import ServerBuilder
    from appinfra.log import Logger
    from appinfra.runtime import ChanClosedError

    async def work(data: str, request: Request):
        ipc = request.app.state.ipc_channel
        return {"result": await ipc.submit(data, timeout=10.0)}

    server = (ServerBuilder(Logger("worker-api"), "worker-api")
        .with_port(8000)
        .routes.with_route("/work/{data}", work).done()
        .subprocess
            .with_ipc()
            .with_auto_restart(True)
            .done()
        .build())

    # The main process answers each request on the Chan it came with, until
    # the requests Chan is closed; a restarted server sends to the same one
    def answer():
        for data, reply in server.requests:
            try:
                reply.send(data.upper())
            except ChanClosedError:
                pass  # the route stopped waiting for it

    serving = threading.Thread(target=answer)
    serving.start()
    try:
        server.start()  # Blocking; start_subprocess() returns once it serves
    finally:
        server.requests.close()
        serving.join()
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

# ``Lazy`` lives in appinfra.subprocess (parent→child boundary helper);
# re-exported here as a convenience for FastAPI users.
from ...subprocess import Lazy

# Config classes are always available (no FastAPI dependency)
from .config.api import ApiConfig
from .config.ipc import IPCConfig
from .config.uvicorn import UvicornConfig

# Error classes are always available
from .errors import CallbackError, ConfigError
from .ratelimit import RateLimiter, RateLimitMiddleware, TokenBucketLimiter

_INSTALL_MSG = "FastAPI is not installed. Install with: pip install appinfra[fastapi]"

# Guard runtime imports for optional dependency
try:
    from .builder.server import ServerBuilder
    from .handlers import ExceptionHandler, LoggerInjectable
    from .runtime.ipc import IPCChannel
    from .runtime.server import Server

except ImportError:
    # FastAPI not installed - provide stub classes with clear error messages
    if TYPE_CHECKING:
        # For type checking, import the real types
        from .builder.server import ServerBuilder as ServerBuilder
        from .handlers import ExceptionHandler as ExceptionHandler
        from .handlers import LoggerInjectable as LoggerInjectable
        from .runtime.ipc import IPCChannel as IPCChannel
        from .runtime.server import Server as Server
    else:
        # At runtime without FastAPI, provide helpful stubs

        class ServerBuilder:
            """Stub for ServerBuilder when FastAPI is not installed."""

            def __init__(self, *args: Any, **kwargs: Any) -> None:
                raise ImportError(_INSTALL_MSG)

        class Server:
            """Stub for Server when FastAPI is not installed."""

            def __init__(self, *args: Any, **kwargs: Any) -> None:
                raise ImportError(_INSTALL_MSG)

        class IPCChannel:
            """Stub for IPCChannel when FastAPI is not installed."""

            def __init__(self, *args: Any, **kwargs: Any) -> None:
                raise ImportError(_INSTALL_MSG)

        class ExceptionHandler:
            """Stub for ExceptionHandler when FastAPI is not installed."""

            def __init__(self, *args: Any, **kwargs: Any) -> None:
                raise ImportError(_INSTALL_MSG)

        class LoggerInjectable:
            """Stub for LoggerInjectable when FastAPI is not installed."""

            def __init__(self, *args: Any, **kwargs: Any) -> None:
                raise ImportError(_INSTALL_MSG)


__all__ = [
    # Builder
    "ServerBuilder",
    # Runtime
    "Server",
    "IPCChannel",
    # Config (always available)
    "ApiConfig",
    "UvicornConfig",
    "IPCConfig",
    # Exception handlers (subprocess support)
    "ExceptionHandler",
    "LoggerInjectable",
    # Rate limiting (always available)
    "RateLimiter",
    "RateLimitMiddleware",
    "TokenBucketLimiter",
    # Errors (always available)
    "CallbackError",
    "ConfigError",
    # Subprocess factory wrapper (always available)
    "Lazy",
]
