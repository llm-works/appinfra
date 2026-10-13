# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Main ServerBuilder for FastAPI servers."""

from __future__ import annotations

import multiprocessing as mp
import pickle
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import TYPE_CHECKING, Any, Self

from ..ratelimit.interface import RateLimiter

if TYPE_CHECKING:
    from fastapi import FastAPI
    from starlette.requests import Request
    from starlette.responses import Response

    from ....log import Logger

from dataclasses import replace

from ....subprocess import Lazy
from ..config.api import ApiConfig
from ..runtime.adapter import (
    CORSDefinition,
    ExceptionCallbackDefinition,
    ExceptionHandlerDefinition,
    FastAPIAdapter,
    LifecycleCallbackDefinition,
    LifespanDefinition,
    MiddlewareDefinition,
    RateLimitDefinition,
    RequestCallbackDefinition,
    ResponseCallbackDefinition,
    RouteDefinition,
    RouterDefinition,
)
from ..runtime.server import Server
from .route import RouteConfigurer
from .subprocess import SubprocessConfigurer
from .uvicorn import UvicornConfigurer


def _copy_api(config: ApiConfig) -> ApiConfig:
    """A copy of ``config`` with its nested objects copied as well.

    ``ApiConfig`` holds ``UvicornConfig`` and ``IPCConfig`` by reference, so a
    plain ``replace`` would leave those shared between two owners.
    """
    return replace(
        config,
        uvicorn=replace(config.uvicorn),
        ipc=replace(config.ipc) if config.ipc is not None else None,
    )


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
                .with_auto_restart(True).with_max_restarts(10)
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

    def __init__(self, lg: Logger, name: str) -> None:
        """
        Initialize builder.

        Args:
            lg: Logger for subprocess log forwarding
            name: Server name (used for logging)
        """
        self._lg = lg
        self._name = name
        # The builder's state is the config it will build; the facets are
        # views on it, so defaults live in the config dataclasses only.
        self._api = ApiConfig()
        self._request_q: mp.Queue[Any] | None = None
        self._response_q: mp.Queue[Any] | None = None
        self._init_routes_and_callbacks()

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
        self._rate_limiters: list[RateLimitDefinition] = []

    # Direct configuration methods

    def with_host(self, host: str) -> Self:
        """Set the bind address (default: "0.0.0.0")."""
        self._api.host = host
        return self

    def with_port(self, port: int) -> Self:
        """Set the bind port (default: 8000)."""
        self._api.port = port
        return self

    def with_title(self, title: str) -> Self:
        """Set API title for OpenAPI docs."""
        self._api.title = title
        return self

    def with_description(self, description: str) -> Self:
        """Set API description for OpenAPI docs."""
        self._api.description = description
        return self

    def with_version(self, version: str) -> Self:
        """Set API version."""
        self._api.version = version
        return self

    def with_docs(self, enabled: bool = True) -> Self:
        """
        Serve or drop /docs, /redoc and /openapi.json (default: dropped).

        The OpenAPI schema lists every route, so these stay off unless
        enabled. Set ``docs_url``, ``redoc_url`` and ``openapi_url`` on
        ``ApiConfig`` for other paths.
        """
        self._api.docs_url = "/docs" if enabled else None
        self._api.redoc_url = "/redoc" if enabled else None
        self._api.openapi_url = "/openapi.json" if enabled else None
        return self

    def with_timeout(self, timeout: float) -> Self:
        """Set default response timeout in seconds."""
        self._api.response_timeout = timeout
        return self

    def with_config(self, config: ApiConfig) -> Self:
        """
        Set entire API configuration at once.

        Useful when loading config from file or environment. The builder
        works on its own copy, so later setters and facets leave the given
        object alone and several builders can share one loaded config.
        """
        self._api = _copy_api(config)
        return self

    # Lifecycle callback methods

    def with_on_startup(
        self,
        callback: Callable[[FastAPI], Awaitable[None]] | Lazy,
        name: str | None = None,
        after_lifespan: bool = True,
    ) -> Self:
        """
        Register a startup callback.

        By default, callbacks run AFTER the user lifespan enters, so user
        dependencies (database, message queues) are initialized first.

        Args:
            callback: Async function with signature `async def callback(app: FastAPI) -> None`
            name: Optional name for debugging/logging
            after_lifespan: If True (default), run after user lifespan enters.
                If False, run before user lifespan (rare, for framework init).

        Example:
            async def log_ready(app: FastAPI) -> None:
                logger.info("Server ready")

            builder.with_on_startup(log_ready)  # runs after lifespan
        """
        self._startup_callbacks.append(
            LifecycleCallbackDefinition(
                callback=callback, name=name, after_lifespan=after_lifespan
            )
        )
        return self

    def with_on_shutdown(
        self,
        callback: Callable[[FastAPI], Awaitable[None]] | Lazy,
        name: str | None = None,
    ) -> Self:
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
        lifespan: Callable[[FastAPI], AbstractAsyncContextManager[None]] | Lazy,
    ) -> Self:
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
        callback: Callable[[Request], Awaitable[None]] | Lazy,
        name: str | None = None,
    ) -> Self:
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
        callback: Callable[[Request, Response], Awaitable[Response]] | Lazy,
        name: str | None = None,
    ) -> Self:
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
        callback: Callable[[Request, Exception], Awaitable[None]] | Lazy,
        name: str | None = None,
    ) -> Self:
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

    # Rate limiting

    def with_rate_limiter(
        self,
        limiter: RateLimiter | Lazy,
        exempt_paths: list[str] | None = None,
        cleanup_interval: float = 60.0,
    ) -> Self:
        """Configure HTTP rate limiting.

        The limiter controls both the algorithm (token bucket, sliding window,
        etc.) and the key extraction strategy (per-IP, global, custom).
        The middleware returns 429 with Retry-After header when rate limited,
        and injects X-RateLimit-* headers on successful responses.

        Args:
            limiter: Rate limiter instance implementing the RateLimiter ABC
                (from appinfra.app.fastapi.ratelimit).
            exempt_paths: Paths that bypass rate limiting (e.g., ["/health"]).
            cleanup_interval: Seconds between stale entry cleanup (default: 60).

        Returns:
            Self for method chaining.

        Example:
            from appinfra.app.fastapi.ratelimit import TokenBucketLimiter

            server = (ServerBuilder(lg, "api")
                .with_rate_limiter(
                    TokenBucketLimiter(rate="60/min", burst=10),
                    exempt_paths=["/health"],
                )
                .routes.with_route("/health", health).done()
                .build())
        """
        if cleanup_interval <= 0:
            raise ValueError(
                f"cleanup_interval must be positive, got: {cleanup_interval}"
            )
        self._rate_limiters.append(
            RateLimitDefinition(
                limiter=limiter,
                exempt_paths=list(exempt_paths) if exempt_paths else [],
                cleanup_interval=cleanup_interval,
            )
        )
        return self

    # Focused configurers

    @property
    def routes(self) -> RouteConfigurer[Self]:
        """Access route and middleware configuration."""
        return RouteConfigurer(self)

    @property
    def subprocess(self) -> SubprocessConfigurer[Self]:
        """Access subprocess and IPC configuration."""
        return SubprocessConfigurer(self)

    @property
    def uvicorn(self) -> UvicornConfigurer[Self]:
        """Access Uvicorn configuration."""
        return UvicornConfigurer(self)

    # Build

    def _build_config(self) -> ApiConfig:
        """A copy of the builder's config, so the Server owns its own and
        later facet calls cannot reach it."""
        return _copy_api(self._api)

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
        for rl in self._rate_limiters:
            adapter.add_rate_limiter(rl)

    def _is_subprocess_mode(self) -> bool:
        """Check if subprocess mode is configured."""
        return self._request_q is not None and self._response_q is not None

    def _validate_handler_pickling(self, handler: Any, exc_class_name: str) -> bool:
        """Validate a single handler can be pickled.

        Returns True if validation passed, raises ConfigError if handler cannot be
        pickled and doesn't implement LoggerInjectable.
        """
        from ..errors import ConfigError
        from ..handlers import LoggerInjectable

        try:
            pickle.dumps(handler)
            return True
        except Exception as e:
            # For LoggerInjectable handlers, verify __getstate__ result is picklable
            if isinstance(handler, LoggerInjectable) and hasattr(
                handler, "__getstate__"
            ):
                try:
                    state = handler.__getstate__()
                    pickle.dumps(state)
                    return True  # State without Logger is picklable
                except Exception as state_error:
                    raise ConfigError(
                        f"Exception handler for {exc_class_name} implements LoggerInjectable "
                        f"but __getstate__() result cannot be pickled: {state_error}\n"
                        f"Ensure __getstate__() strips all unpicklable attributes."
                    ) from state_error

            raise ConfigError(
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
                self._lg.warning(
                    "Exception handler contains Logger attribute that may not "
                    "work correctly in subprocess mode",
                    extra={
                        "handler": type(handler).__name__,
                        "attribute": attr,
                        "exc_class": exc_class_name,
                    },
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
            lg=self._lg,
            name=self._name,
            config=config,
            adapter=adapter,
            request_q=self._request_q,
            response_q=self._response_q,
        )
