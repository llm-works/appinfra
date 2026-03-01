"""
FastAPI server framework for appinfra.

Provides production-ready FastAPI + Uvicorn server framework with subprocess
isolation and queue-based IPC.

Installation:
    pip install appinfra[fastapi]

Example (Simple Server - Direct Mode):
    from . import ServerBuilder

    async def health():
        return {"status": "ok"}

    server = (ServerBuilder("myapi")
        .with_port(8000)
        .routes.with_route("/health", health).done()
        .build())

    server.start()  # Blocking

Example (Subprocess Mode with IPC):
    import multiprocessing as mp
    from . import ServerBuilder

    request_q, response_q = mp.Queue(), mp.Queue()

    server = (ServerBuilder("worker-api")
        .with_port(8000)
        .routes.with_route("/health", health).done()
        .subprocess
            .with_ipc(request_q, response_q)
            .with_auto_restart(enabled=True)
            .done()
        .build())

    proc = server.start_subprocess()  # Non-blocking

    # Main process handles requests
    while True:
        request = request_q.get()
        result = process(request)
        response_q.put(result)

Example (AppBuilder Integration):
    from .. import AppBuilder
    from . import ServerBuilder, ServerPlugin

    server = ServerBuilder("myapi").with_port(8000).build()

    app = (AppBuilder("myapp")
        .tools.with_plugin(ServerPlugin(server)).done()
        .build())

    # CLI: myapp serve
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

# Config classes are always available (no FastAPI dependency)
from .config.api import ApiConfig
from .config.ipc import IPCConfig
from .config.uvicorn import UvicornConfig

_INSTALL_MSG = "FastAPI is not installed. Install with: pip install appinfra[fastapi]"

# Flag to track if real implementations are available
_HAS_FASTAPI = False

# Guard runtime imports for optional dependency
try:
    from .builder.server import ServerBuilder
    from .handlers import ExceptionHandler, LoggerInjectable
    from .plugin import ServerPlugin
    from .runtime.ipc import IPCChannel
    from .runtime.server import Server

    _HAS_FASTAPI = True

except ImportError:
    # FastAPI not installed - provide stub classes with clear error messages
    if TYPE_CHECKING:
        # For type checking, import the real types
        from .builder.server import ServerBuilder as ServerBuilder
        from .handlers import ExceptionHandler as ExceptionHandler
        from .handlers import LoggerInjectable as LoggerInjectable
        from .plugin import ServerPlugin as ServerPlugin
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

        class ServerPlugin:
            """Stub for ServerPlugin when FastAPI is not installed."""

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
    # Plugin
    "ServerPlugin",
    # Exception handlers (subprocess support)
    "ExceptionHandler",
    "LoggerInjectable",
]
