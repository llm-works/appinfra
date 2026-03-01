"""Main ServerBuilder for FastAPI servers."""

from __future__ import annotations

import logging
import multiprocessing as mp
import pickle
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastapi import FastAPI
    from starlette.requests import Request
    from starlette.responses import Response

from ..config.api import ApiConfig
from ..config.ipc import IPCConfig
from ..config.uvicorn import UvicornConfig
from ..runtime.adapter import (
    CORSDefinition,
    ExceptionCallbackDefinition,
    ExceptionHandlerDefinition,
    FastAPIAdapter,
    LifecycleCallbackDefinition,
    LifespanDefinition,
    MiddlewareDefinition,
    RequestCallbackDefinition,
    ResponseCallbackDefinition,
    RouteDefinition,
    RouterDefinition,
)
from ..runtime.server import Server
from .route import RouteConfigurer
from .subprocess import SubprocessConfigurer
from .uvicorn import UvicornConfigurer

logger = logging.getLogger("fastapi.builder")


class ServerBuilder:
    """
    Fluent builder for FastAPI servers with optional subprocess isolation.

    Follows appinfra.app.AppBuilder patterns:
    - Method chaining with with_*() methods
    - Focused configurers accessed via properties (.routes, .subprocess, .uvicorn)
    - .done() returns to parent builder
    - .build() creates runtime instance

    Example (simple server):
        server = (ServerBuilder("myapi")
            .with_port(8000)
            .routes
                .with_route("/health", health_handler)
                .with_cors(origins=["*"])
                .done()
            .build())

        server.start()  # Blocking

    Example (subprocess mode with IPC):
        request_q, response_q = mp.Queue(), mp.Queue()

        server = (ServerBuilder("worker-api")
            .with_port(8000)
            .routes
                .with_route("/process", process_handler, methods=["POST"])
                .done()
            .subprocess
                .with_ipc(request_q, response_q)
                .with_auto_restart(enabled=True, max_restarts=10)
                .done()
            .uvicorn
                .with_workers(4)
                .done()
            .build())

        proc = server.start_subprocess()  # Non-blocking

        # Main process handles requests via queues
        while True:
            request = request_q.get()
            result = process(request)
            response_q.put(result)
    """

    def __init__(self, name: str) -> None:
        """
        Initialize builder.

        Args:
            name: Server name (used for logging)
        """
        self._name = name
        self._init_api_defaults()
        self._init_subprocess_defaults()
        self._init_routes_and_callbacks()

    def _init_api_defaults(self) -> None:
        """Initialize API configuration defaults."""
        self._host = "0.0.0.0"
        self._port = 8000
        self._title = "API Server"
        self._description = ""
        self._version = "0.1.0"
        self._response_timeout = 60.0
        self._uvicorn_config = UvicornConfig()

    def _init_subprocess_defaults(self) -> None:
        """Initialize subprocess configuration defaults."""
        self._request_q: mp.Queue[Any] | None = None
        self._response_q: mp.Queue[Any] | None = None
        self._ipc_config: IPCConfig | None = None
        self._log_file: str | None = None
        self._auto_restart = True
        self._restart_delay = 1.0
        self._max_restarts = 5

    def _init_routes_and_callbacks(self) -> None:
        """Initialize routes, middleware, and callback storage."""
        self._routes: list[RouteDefinition] = []
        self._routers: list[RouterDefinition] = []
        self._middleware: list[MiddlewareDefinition] = []
        self._exception_handlers: list[ExceptionHandlerDefinition] = []
        self._cors: CORSDefinition | None = None
        self._startup_callbacks: list[LifecycleCallbackDefinition] = []
        self._shutdown_callbacks: list[LifecycleCallbackDefinition] = []
        self._lifespan: LifespanDefinition | None = None
        self._request_callbacks: list[RequestCallbackDefinition] = []
        self._response_callbacks: list[ResponseCallbackDefinition] = []
        self._exception_callbacks: list[ExceptionCallbackDefinition] = []

    # Direct configuration methods

    def with_host(self, host: str) -> ServerBuilder:
        """Set the bind address (default: "0.0.0.0")."""
        self._host = host
        return self

    def with_port(self, port: int) -> ServerBuilder:
        """Set the bind port (default: 8000)."""
        self._port = port
        return self

    def with_title(self, title: str) -> ServerBuilder:
        """Set API title for OpenAPI docs."""
        self._title = title
        return self

    def with_description(self, description: str) -> ServerBuilder:
        """Set API description for OpenAPI docs."""
        self._description = description
        return self

    def with_version(self, version: str) -> ServerBuilder:
        """Set API version."""
        self._version = version
        return self

    def with_timeout(self, timeout: float) -> ServerBuilder:
        """Set default response timeout in seconds."""
        self._response_timeout = timeout
        return self

    def with_config(self, config: ApiConfig) -> ServerBuilder:
        """
        Set entire API configuration at once.

        Useful when loading config from file or environment.
        """
        self._host = config.host
        self._port = config.port
        self._title = config.title
        self._description = config.description
        self._version = config.version
        self._response_timeout = config.response_timeout
        self._log_file = config.log_file
        self._auto_restart = config.auto_restart
        self._restart_delay = config.restart_delay
        self._max_restarts = config.max_restarts
        self._uvicorn_config = config.uvicorn

        if config.ipc:
            self._ipc_config = config.ipc

        return self

    # Lifecycle callback methods

    def with_on_startup(
        self,
        callback: Callable[[FastAPI], Awaitable[None]],
        name: str | None = None,
    ) -> ServerBuilder:
        """
        Register a startup callback.

        The callback runs when the FastAPI app starts, before accepting requests.
        Useful for initializing per-subprocess state.

        Args:
            callback: Async function with signature `async def callback(app: FastAPI) -> None`
            name: Optional name for debugging/logging

        Example:
            async def init_db(app: FastAPI) -> None:
                app.state.db = await create_db_pool()

            builder.with_on_startup(init_db)
        """
        self._startup_callbacks.append(
            LifecycleCallbackDefinition(callback=callback, name=name)
        )
        return self

    def with_on_shutdown(
        self,
        callback: Callable[[FastAPI], Awaitable[None]],
        name: str | None = None,
    ) -> ServerBuilder:
        """
        Register a shutdown callback.

        The callback runs when the FastAPI app shuts down, after stopping requests.
        Useful for cleaning up per-subprocess state.

        Args:
            callback: Async function with signature `async def callback(app: FastAPI) -> None`
            name: Optional name for debugging/logging

        Example:
            async def close_db(app: FastAPI) -> None:
                await app.state.db.close()

            builder.with_on_shutdown(close_db)
        """
        self._shutdown_callbacks.append(
            LifecycleCallbackDefinition(callback=callback, name=name)
        )
        return self

    def with_lifespan(
        self,
        lifespan: Callable[[FastAPI], AbstractAsyncContextManager[None]],
    ) -> ServerBuilder:
        """
        Register a lifespan context manager.

        The lifespan combines startup and shutdown in a single context manager.
        This is FastAPI's modern pattern for lifecycle management.

        Note: If lifespan is set, any startup/shutdown callbacks are ignored.

        Args:
            lifespan: Async context manager with signature matching FastAPI's lifespan

        Example:
            @asynccontextmanager
            async def lifespan(app: FastAPI):
                app.state.db = await create_db_pool()
                yield
                await app.state.db.close()

            builder.with_lifespan(lifespan)
        """
        self._lifespan = LifespanDefinition(lifespan=lifespan)
        return self

    def with_on_request(
        self,
        callback: Callable[[Request], Awaitable[None]],
        name: str | None = None,
    ) -> ServerBuilder:
        """
        Register a request callback.

        The callback runs before each request handler is invoked.
        Useful for logging, authentication checks, or request modification.

        Note: Due to BaseHTTPMiddleware limitations, reading the request body
        (via request.body() or request.json()) in this callback will prevent
        the route handler from reading it again. For body access, use custom
        middleware via routes.with_middleware() instead.

        Args:
            callback: Async function with signature `async def callback(request: Request) -> None`
            name: Optional name for debugging/logging

        Example:
            async def log_request(request: Request) -> None:
                logger.info(f"{request.method} {request.url}")

            builder.with_on_request(log_request)
        """
        self._request_callbacks.append(
            RequestCallbackDefinition(callback=callback, name=name)
        )
        return self

    def with_on_response(
        self,
        callback: Callable[[Request, Response], Awaitable[Response]],
        name: str | None = None,
    ) -> ServerBuilder:
        """
        Register a response callback.

        The callback runs after each request handler completes.
        Can modify and must return the response.

        Args:
            callback: Async function with signature
                `async def callback(request: Request, response: Response) -> Response`
            name: Optional name for debugging/logging

        Example:
            async def add_headers(request: Request, response: Response) -> Response:
                response.headers["X-Request-ID"] = str(uuid4())
                return response

            builder.with_on_response(add_headers)
        """
        self._response_callbacks.append(
            ResponseCallbackDefinition(callback=callback, name=name)
        )
        return self

    def with_on_exception(
        self,
        callback: Callable[[Request, Exception], Awaitable[None]],
        name: str | None = None,
    ) -> ServerBuilder:
        """
        Register an exception callback.

        The callback runs when an unhandled exception occurs during request handling.
        Useful for logging, metrics, or alerting. The exception is re-raised after
        all callbacks complete.

        Args:
            callback: Async function with signature
                `async def callback(request: Request, exc: Exception) -> None`
            name: Optional name for debugging/logging

        Example:
            async def log_error(request: Request, exc: Exception) -> None:
                logger.error(f"Error handling {request.url}: {exc}")

            builder.with_on_exception(log_error)
        """
        self._exception_callbacks.append(
            ExceptionCallbackDefinition(callback=callback, name=name)
        )
        return self

    # Focused configurers

    @property
    def routes(self) -> RouteConfigurer:
        """Access route and middleware configuration."""
        return RouteConfigurer(self)

    @property
    def subprocess(self) -> SubprocessConfigurer:
        """Access subprocess and IPC configuration."""
        return SubprocessConfigurer(self)

    @property
    def uvicorn(self) -> UvicornConfigurer:
        """Access Uvicorn configuration."""
        return UvicornConfigurer(self)

    # Build

    def _build_config(self) -> ApiConfig:
        """Build API configuration from builder state."""
        return ApiConfig(
            host=self._host,
            port=self._port,
            title=self._title,
            description=self._description,
            version=self._version,
            response_timeout=self._response_timeout,
            log_file=self._log_file,
            auto_restart=self._auto_restart,
            restart_delay=self._restart_delay,
            max_restarts=self._max_restarts,
            uvicorn=self._uvicorn_config,
            ipc=self._ipc_config,
        )

    def _configure_adapter(self, adapter: FastAPIAdapter) -> None:
        """Configure adapter with routes, middleware, handlers, and lifecycle callbacks."""
        for route in self._routes:
            adapter.add_route(route)
        for router in self._routers:
            adapter.add_router(router)
        for mw in self._middleware:
            adapter.add_middleware(mw)
        for handler in self._exception_handlers:
            adapter.add_exception_handler(handler)
        if self._cors:
            adapter.set_cors(self._cors)

        # Lifecycle callbacks
        for startup_cb in self._startup_callbacks:
            adapter.add_startup_callback(startup_cb)
        for shutdown_cb in self._shutdown_callbacks:
            adapter.add_shutdown_callback(shutdown_cb)
        if self._lifespan:
            adapter.set_lifespan(self._lifespan)
        for request_cb in self._request_callbacks:
            adapter.add_request_callback(request_cb)
        for response_cb in self._response_callbacks:
            adapter.add_response_callback(response_cb)
        for exception_cb in self._exception_callbacks:
            adapter.add_exception_callback(exception_cb)

    def _is_subprocess_mode(self) -> bool:
        """Check if subprocess mode is configured."""
        return self._request_q is not None and self._response_q is not None

    def _validate_handler_pickling(self, handler: Any, exc_class_name: str) -> bool:
        """Validate a single handler can be pickled.

        Returns True if validation passed, raises RuntimeError if handler cannot be
        pickled and doesn't implement LoggerInjectable.
        """
        from ..handlers import LoggerInjectable

        try:
            pickle.dumps(handler)
            return True
        except Exception as e:
            if isinstance(handler, LoggerInjectable):
                return True  # Protocol handlers will have logger injected

            raise RuntimeError(
                f"Exception handler for {exc_class_name} cannot be pickled for "
                f"subprocess mode: {e}\n"
                f"Use appinfra.app.fastapi.ExceptionHandler base class or implement "
                f"LoggerInjectable protocol (__getstate__, __setstate__, set_logger)."
            ) from e

    def _warn_on_logger_attributes(self, handler: Any, exc_class_name: str) -> None:
        """Warn if handler has Logger attributes without implementing LoggerInjectable."""
        from ....log import Logger
        from ..handlers import LoggerInjectable

        if not hasattr(handler, "__dict__") or isinstance(handler, LoggerInjectable):
            return

        for attr, value in handler.__dict__.items():
            if isinstance(value, Logger):
                logger.warning(
                    "Exception handler contains Logger attribute that may not "
                    "work correctly in subprocess mode. "
                    "handler=%s attribute=%s exc_class=%s",
                    type(handler).__name__,
                    attr,
                    exc_class_name,
                )

    def _validate_subprocess_handlers(self) -> None:
        """Validate exception handlers are subprocess-compatible."""
        for handler_def in self._exception_handlers:
            handler = handler_def.handler
            exc_class_name = handler_def.exc_class.__name__
            self._validate_handler_pickling(handler, exc_class_name)
            self._warn_on_logger_attributes(handler, exc_class_name)

    def build(self) -> Server:
        """
        Build the Server runtime instance.

        Returns:
            Configured Server ready to start

        Raises:
            RuntimeError: If subprocess mode is enabled and an exception handler
                cannot be pickled.
        """
        config = self._build_config()
        adapter = FastAPIAdapter(config)
        self._configure_adapter(adapter)

        # Validate handlers are subprocess-compatible
        if self._is_subprocess_mode():
            self._validate_subprocess_handlers()

        return Server(
            name=self._name,
            config=config,
            adapter=adapter,
            request_q=self._request_q,
            response_q=self._response_q,
        )
