# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""FastAPI application adapter.

Invariant for new *Definition* dataclasses that carry a callable field
(handler, router, callback, middleware class, rate limiter, etc.):

    1. The callable field's type MUST include ``| Lazy`` (see the ``Lazy``
       class below).
    2. ``FastAPIAdapter._resolve_lazy`` MUST resolve that field in the same
       pass that walks the other definition lists.

Both sites are required. Missing either one silently regresses subprocess
mode on Python 3.14+ (default start method ``forkserver`` pickles the
target's args and rejects nested closures / non-module-level callables).
The failure is only observable when a user actually wraps that field in
``Lazy`` on 3.14 — no test on 3.13-and-earlier will catch it.
"""

from __future__ import annotations

import importlib
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

from ..config.api import ApiConfig
from ..ratelimit.interface import RateLimiter

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.responses import Response

    from ....log import Logger
    from .ipc import IPCChannel

# Guard FastAPI imports for optional dependency
try:
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.routing import APIRouter

    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False
    FastAPI = Any  # type: ignore[assignment,misc]
    CORSMiddleware = Any  # type: ignore[assignment,misc]
    APIRouter = Any  # type: ignore[assignment,misc]


@dataclass
class Lazy:
    """Deferred value resolved from a module qualname + config in the subprocess.

    Wraps a route handler, router, middleware class, or lifecycle callback so
    the callable itself never crosses the ``mp.Process`` pickle boundary. The
    subprocess imports the factory module and calls the factory during
    ``FastAPIAdapter.build()`` (via ``_resolve_lazy``).

    Required on Python 3.14+ where the default multiprocessing start method
    (``forkserver``) pickles the target's args. Optional on ``fork``.

    Fields:
        factory: Module qualname of a callable to import, in the form
            ``"pkg.mod:build_health"``. Split on the final ``":"``.
        config: Optional argument passed to the factory. Must be picklable
            (a dataclass with plain fields is the intended shape).

    Example:
        # Module producing the handler (nested closure OK — never pickled)
        def build_health(config: HealthConfig) -> Callable[[], dict]:
            async def health() -> dict:
                return {"ready": config.ready_flag.value}
            return health

        # Builder site
        (builder.routes
            .with_route("/health", Lazy("myapp.routes:build_health", HealthConfig(...)))
            .done())

    Unsupported: capturing parent-process state created after subprocess spawn
    (e.g. an ``mp.Value`` shared post-spawn) cannot cross ``forkserver``. Such
    consumers must stay on ``fork`` start method or Python <=3.13.
    """

    factory: str
    config: Any = None

    def resolve(self) -> Any:
        """Import the factory and invoke it (with ``config`` if set)."""
        module_name, _, attr = self.factory.rpartition(":")
        if not module_name or not attr:
            raise ValueError(
                f"Lazy.factory must be 'module.path:attr', got {self.factory!r}"
            )
        fn = getattr(importlib.import_module(module_name), attr)
        return fn(self.config) if self.config is not None else fn()


def _resolve_field(obj: Any, field_name: str) -> None:
    """If ``obj.<field_name>`` is a ``Lazy``, replace it with its resolved value."""
    value = getattr(obj, field_name)
    if isinstance(value, Lazy):
        setattr(obj, field_name, value.resolve())


@dataclass
class RouteDefinition:
    """Definition for a route to register."""

    path: str
    handler: Callable[..., Any] | Lazy
    methods: list[str] = field(default_factory=lambda: ["GET"])
    response_model: type[Any] | None = None
    tags: list[str] | None = None
    kwargs: dict[str, Any] = field(default_factory=dict)


@dataclass
class RouterDefinition:
    """Definition for a router to include."""

    router: Any | Lazy  # APIRouter or Lazy-wrapped factory returning one
    prefix: str = ""
    tags: list[str] | None = None


@dataclass
class MiddlewareDefinition:
    """Definition for middleware to add."""

    middleware_class: type[Any] | Lazy
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class RateLimitDefinition:
    """Definition for rate limiting configuration."""

    limiter: RateLimiter | Lazy
    exempt_paths: list[str] = field(default_factory=list)
    cleanup_interval: float = 60.0


@dataclass
class CORSDefinition:
    """Definition for CORS configuration."""

    origins: list[str]
    allow_credentials: bool = False
    allow_methods: list[str] = field(default_factory=lambda: ["*"])
    allow_headers: list[str] = field(default_factory=lambda: ["*"])


@dataclass
class ExceptionHandlerDefinition:
    """Definition for exception handler."""

    exc_class: type[Exception]
    handler: Callable[..., Any] | Lazy


@dataclass
class LifecycleCallbackDefinition:
    """Definition for startup/shutdown lifecycle callback.

    For startup callbacks, `after_lifespan` controls execution order:
    - True (default): runs AFTER user lifespan enters (dependencies ready)
    - False: runs BEFORE user lifespan enters (rare, for framework init)
    """

    callback: Callable[[FastAPI], Awaitable[None]] | Lazy
    name: str | None = None  # Optional name for debugging
    after_lifespan: bool = True  # For startup: run after user lifespan enters


# Type alias for lifespan context manager
LifespanCallable = Callable[[FastAPI], AbstractAsyncContextManager[None]]


@dataclass
class LifespanDefinition:
    """Definition for lifespan context manager."""

    lifespan: LifespanCallable | Lazy


@dataclass
class RequestCallbackDefinition:
    """Definition for request callback (runs before each request handler)."""

    callback: Callable[[Request], Awaitable[None]] | Lazy
    name: str | None = None


@dataclass
class ResponseCallbackDefinition:
    """Definition for response callback (runs after each request handler)."""

    callback: Callable[[Request, Response], Awaitable[Response]] | Lazy
    name: str | None = None


@dataclass
class ExceptionCallbackDefinition:
    """Definition for exception callback (runs when unhandled exceptions occur)."""

    callback: Callable[[Request, Exception], Awaitable[None]] | Lazy
    name: str | None = None


async def _run_exception_callbacks(
    exception_callbacks: list[ExceptionCallbackDefinition],
    request: Request,
    exc: Exception,
) -> None:
    """Run exception callbacks, raising CallbackError on failure."""
    from ..errors import CallbackError

    for exc_cb in exception_callbacks:
        # Post-``_resolve_lazy`` invariant: callback is a real callable.
        fn = cast(Callable[..., Awaitable[None]], exc_cb.callback)
        try:
            await fn(request, exc)
        except Exception as cb_exc:
            name = exc_cb.name or fn.__name__
            lg = getattr(request.state, "lg", None)
            if lg is not None:
                lg.error(
                    f"error in exception callback '{name}'", extra={"exception": cb_exc}
                )
            raise CallbackError(f"Exception callback '{name}' failed") from cb_exc


async def _run_startup_callbacks(
    callbacks: list[LifecycleCallbackDefinition],
    app: Any,
    lg: Logger | None,
) -> None:
    """Run startup callbacks, raising CallbackError on failure."""
    from ..errors import CallbackError

    for cb in callbacks:
        # Post-``_resolve_lazy`` invariant: callback is a real callable.
        fn = cast(Callable[..., Awaitable[None]], cb.callback)
        name = cb.name or fn.__name__
        if lg is not None:
            lg.trace("running startup callback...", extra={"callback": name})
        try:
            await fn(app)
            if lg is not None:
                lg.debug("startup callback completed", extra={"callback": name})
        except Exception as e:
            raise CallbackError(f"Startup callback '{name}' failed") from e


async def _run_shutdown_callbacks(
    callbacks: list[LifecycleCallbackDefinition],
    app: Any,
    lg: Logger | None,
) -> None:
    """Run shutdown callbacks, logging and raising CallbackError on failure."""
    from ..errors import CallbackError

    for cb in callbacks:
        # Post-``_resolve_lazy`` invariant: callback is a real callable.
        fn = cast(Callable[..., Awaitable[None]], cb.callback)
        name = cb.name or fn.__name__
        if lg is not None:
            lg.trace("running shutdown callback...", extra={"callback": name})
        try:
            await fn(app)
            if lg is not None:
                lg.debug("shutdown callback completed", extra={"callback": name})
        except Exception as e:
            if lg is not None:
                lg.error(
                    "error in shutdown callback",
                    extra={"callback": name, "exception": e},
                )
            raise CallbackError(f"Shutdown callback '{name}' failed") from e


async def _run_request_callbacks(
    request_callbacks: list[RequestCallbackDefinition], request: Request
) -> None:
    """Run request callbacks; raise RuntimeError on failure with callback name."""
    for req_cb in request_callbacks:
        # Post-``_resolve_lazy`` invariant: callback is a real callable.
        req_fn = cast(Callable[..., Awaitable[None]], req_cb.callback)
        try:
            await req_fn(request)
        except Exception as e:
            name = req_cb.name or req_fn.__name__
            raise RuntimeError(f"Request callback '{name}' failed") from e


async def _run_response_callbacks(
    response_callbacks: list[ResponseCallbackDefinition],
    request: Request,
    response: Response,
) -> Response:
    """Run response callbacks, threading response through each; raise on failure."""
    for resp_cb in response_callbacks:
        # Post-``_resolve_lazy`` invariant: callback is a real callable.
        # ``Any`` in the cast avoids a runtime reference to ``Response``
        # (imported only under TYPE_CHECKING).
        resp_fn = cast(Callable[..., Awaitable[Any]], resp_cb.callback)
        name = resp_cb.name or resp_fn.__name__
        try:
            response = await resp_fn(request, response)
        except Exception as e:
            raise RuntimeError(f"Response callback '{name}' failed") from e
        if response is None:
            raise RuntimeError(
                f"Response callback '{name}' returned None (must return Response)"
            )
    return response


def _create_callback_middleware(
    request_callbacks: list[RequestCallbackDefinition],
    response_callbacks: list[ResponseCallbackDefinition],
    exception_callbacks: list[ExceptionCallbackDefinition],
) -> type:
    """Create a middleware class for request/response/exception callbacks."""
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import Response as ResponseType

    class CallbackMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next: Any) -> Response:
            await _run_request_callbacks(request_callbacks, request)
            try:
                response = await call_next(request)
            except Exception as exc:
                await _run_exception_callbacks(exception_callbacks, request, exc)
                raise
            response = await _run_response_callbacks(
                response_callbacks, request, response
            )
            return cast(ResponseType, response)

    return CallbackMiddleware


class FastAPIAdapter:
    """
    Adapter for constructing FastAPI applications.

    Collects route/middleware definitions during build phase,
    then constructs the FastAPI app when build() is called.

    This separation allows the builder to collect configuration
    before FastAPI is imported (important for subprocess isolation
    where FastAPI should be imported inside the subprocess).
    """

    def __init__(self, config: ApiConfig) -> None:
        """
        Initialize adapter.

        Args:
            config: API configuration

        Raises:
            ImportError: If FastAPI is not installed
        """
        if not FASTAPI_AVAILABLE:
            raise ImportError(
                "FastAPI is not installed. Install with: pip install appinfra[fastapi]"
            )

        self._config = config
        self._routes: list[RouteDefinition] = []
        self._routers: list[RouterDefinition] = []
        self._middleware: list[MiddlewareDefinition] = []
        self._exception_handlers: list[ExceptionHandlerDefinition] = []
        self._cors: CORSDefinition | None = None

        # Lifecycle callbacks
        self._startup_callbacks: list[LifecycleCallbackDefinition] = []
        self._shutdown_callbacks: list[LifecycleCallbackDefinition] = []
        self._lifespan: LifespanDefinition | None = None
        self._request_callbacks: list[RequestCallbackDefinition] = []
        self._response_callbacks: list[ResponseCallbackDefinition] = []
        self._exception_callbacks: list[ExceptionCallbackDefinition] = []

        # Rate limiting
        self._rate_limiters: list[RateLimitDefinition] = []

        # Subprocess logger (injected after unpickling in subprocess mode)
        self._subprocess_lg: Logger | None = None

    def add_route(self, route: RouteDefinition) -> None:
        """Add a route definition."""
        self._routes.append(route)

    def add_router(self, router: RouterDefinition) -> None:
        """Add a router definition."""
        self._routers.append(router)

    def add_middleware(self, middleware: MiddlewareDefinition) -> None:
        """Add a middleware definition."""
        self._middleware.append(middleware)

    def add_exception_handler(self, handler: ExceptionHandlerDefinition) -> None:
        """Add an exception handler definition."""
        self._exception_handlers.append(handler)

    def set_cors(self, cors: CORSDefinition) -> None:
        """Set CORS configuration."""
        self._cors = cors

    def add_rate_limiter(self, definition: RateLimitDefinition) -> None:
        """Add a rate limiter configuration."""
        self._rate_limiters.append(definition)

    def add_startup_callback(self, callback: LifecycleCallbackDefinition) -> None:
        """Add a startup callback."""
        self._startup_callbacks.append(callback)

    def add_shutdown_callback(self, callback: LifecycleCallbackDefinition) -> None:
        """Add a shutdown callback."""
        self._shutdown_callbacks.append(callback)

    def set_lifespan(self, lifespan: LifespanDefinition) -> None:
        """Set the lifespan context manager."""
        self._lifespan = lifespan

    def add_request_callback(self, callback: RequestCallbackDefinition) -> None:
        """Add a request callback (runs before each request)."""
        self._request_callbacks.append(callback)

    def add_response_callback(self, callback: ResponseCallbackDefinition) -> None:
        """Add a response callback (runs after each request)."""
        self._response_callbacks.append(callback)

    def add_exception_callback(self, callback: ExceptionCallbackDefinition) -> None:
        """Add an exception callback (runs when unhandled exceptions occur)."""
        self._exception_callbacks.append(callback)

    def build(self, ipc_channel: IPCChannel | None = None) -> FastAPI:
        """
        Build the FastAPI application.

        Args:
            ipc_channel: Optional IPCChannel for IPC-based handlers and health reporting.

        Returns:
            Configured FastAPI application
        """
        self._resolve_lazy()
        lifespan = self._build_lifespan(ipc_channel)
        app = FastAPI(
            title=self._config.title,
            description=self._config.description,
            version=self._config.version,
            lifespan=lifespan,
        )

        self._configure_ipc(app, ipc_channel)
        self._configure_logger_injection(app)
        self._configure_request_response_middleware(app)
        self._configure_middleware(app)
        self._configure_rate_limiting(app)
        self._configure_exception_handlers(app)
        self._configure_routes(app)
        self._configure_routers(app)

        return app

    def _configure_ipc(self, app: FastAPI, ipc_channel: IPCChannel | None) -> None:
        """Configure IPC channel on the app."""
        if ipc_channel is None:
            return
        app.state.ipc_channel = ipc_channel
        if self._config.ipc and self._config.ipc.enable_health_reporting:
            self._add_health_route(app, ipc_channel)

    def _configure_logger_injection(self, app: FastAPI) -> None:
        """Configure logger access for subprocess mode.

        Only active in subprocess mode (when inject_subprocess_logger was called).

        Provides two access patterns:
        - app.state.lg: Available immediately, for middleware and lifespan
        - request.state.lg: Set per-request, for route handlers

        Middleware should use request.app.state.lg since request.state.lg
        is not set until after all middleware has processed the request.
        """
        if self._subprocess_lg is None:
            return

        lg = self._subprocess_lg

        # Store on app.state for middleware access (available immediately)
        app.state.lg = lg

        @app.middleware("http")
        async def inject_logger_middleware(
            request: Request, call_next: Callable[[Request], Awaitable[Response]]
        ) -> Response:
            # Also set on request.state for route handler convenience
            request.state.lg = lg
            return await call_next(request)

    def _build_lifespan(
        self, ipc_channel: IPCChannel | None = None
    ) -> LifespanCallable | None:
        """
        Build lifespan context manager from user callbacks and IPC lifecycle.

        If both lifespan and callbacks are provided, callbacks wrap the lifespan.
        If ipc_channel is provided, wrap the result with IPC start/stop.
        Returns None if no lifecycle callbacks configured and no IPC channel.
        """
        # Start with user-provided lifespan (may be None).
        # Post-``_resolve_lazy`` invariant: ``.lifespan`` is a real callable.
        result: LifespanCallable | None = None
        if self._lifespan is not None:
            result = cast(LifespanCallable, self._lifespan.lifespan)

        # Wrap with startup/shutdown callbacks if any
        if self._startup_callbacks or self._shutdown_callbacks:
            result = self._wrap_lifespan_with_callbacks(result)

        # Wrap with IPC lifecycle if channel provided
        if ipc_channel is not None:
            result = self._wrap_lifespan_with_ipc(result, ipc_channel)

        return result

    def _wrap_lifespan_with_callbacks(
        self, inner: LifespanCallable | None
    ) -> LifespanCallable:
        """Wrap a lifespan with startup/shutdown callbacks.

        Startup callbacks are partitioned by `after_lifespan`:
        - after_lifespan=False: run BEFORE user lifespan enters
        - after_lifespan=True: run AFTER user lifespan enters (default)

        This ensures callbacks like "server started" log after user
        dependencies (e.g., database, message queues) are initialized.
        """
        pre_startup = [c for c in self._startup_callbacks if not c.after_lifespan]
        post_startup = [c for c in self._startup_callbacks if c.after_lifespan]
        shutdown_callbacks = self._shutdown_callbacks
        lg = self._subprocess_lg

        @asynccontextmanager
        async def lifespan(app: Any) -> AsyncIterator[None]:
            await _run_startup_callbacks(pre_startup, app, lg)
            try:
                if inner is not None:
                    async with inner(app):
                        await _run_startup_callbacks(post_startup, app, lg)
                        yield
                else:
                    await _run_startup_callbacks(post_startup, app, lg)
                    yield
            finally:
                await _run_shutdown_callbacks(shutdown_callbacks, app, lg)

        return lifespan

    def _wrap_lifespan_with_ipc(
        self,
        user_lifespan: LifespanCallable | None,
        ipc_channel: IPCChannel,
    ) -> LifespanCallable:
        """
        Wrap a lifespan with IPC channel start/stop.

        IPC polling is started before user startup so it's available during
        user callbacks. IPC is stopped after user shutdown completes.
        """

        @asynccontextmanager
        async def ipc_lifespan(app: Any) -> AsyncIterator[None]:
            # Start IPC polling first so it's available during user callbacks
            await ipc_channel.start_polling()
            try:
                if user_lifespan is not None:
                    async with user_lifespan(app):
                        yield
                else:
                    yield
            finally:
                # Stop IPC polling after user shutdown completes
                await ipc_channel.stop_polling()

        return ipc_lifespan

    def _configure_request_response_middleware(self, app: FastAPI) -> None:
        """Configure request/response/exception callback middleware."""
        has_callbacks = (
            self._request_callbacks
            or self._response_callbacks
            or self._exception_callbacks
        )
        if not has_callbacks:
            return

        middleware_cls = _create_callback_middleware(
            self._request_callbacks,
            self._response_callbacks,
            self._exception_callbacks,
        )
        app.add_middleware(middleware_cls)  # type: ignore[arg-type]

    def _configure_middleware(self, app: FastAPI) -> None:
        """Configure middleware on the app."""
        # Add CORS middleware first (order matters for middleware)
        if self._cors:
            app.add_middleware(
                CORSMiddleware,
                allow_origins=self._cors.origins,
                allow_credentials=self._cors.allow_credentials,
                allow_methods=self._cors.allow_methods,
                allow_headers=self._cors.allow_headers,
            )

        # Add other middleware
        for mw in self._middleware:
            # Post-``_resolve_lazy`` invariant: ``middleware_class`` is a real type.
            app.add_middleware(cast(type, mw.middleware_class), **mw.options)  # type: ignore[arg-type]

    def _configure_rate_limiting(self, app: FastAPI) -> None:
        """Configure rate limiting middleware on the app.

        Each limiter gets its own middleware layer. Added last among middleware
        so they run outermost (Starlette applies in reverse order of
        add_middleware calls). Multiple limiters are checked independently -
        the first one to deny a request wins.
        """
        if not self._rate_limiters:
            return
        from ..ratelimit.middleware import RateLimitMiddleware

        for rl in self._rate_limiters:
            # Post-``_resolve_lazy`` invariant: ``limiter`` is a real RateLimiter.
            app.add_middleware(
                RateLimitMiddleware,
                limiter=cast(RateLimiter, rl.limiter),
                exempt_paths=rl.exempt_paths,
                cleanup_interval=rl.cleanup_interval,
            )

    def _configure_exception_handlers(self, app: FastAPI) -> None:
        """Configure exception handlers on the app."""
        for handler in self._exception_handlers:
            # Post-``_resolve_lazy`` invariant: ``handler`` is a real callable.
            app.add_exception_handler(
                handler.exc_class, cast(Callable[..., Any], handler.handler)
            )

    def _configure_routes(self, app: FastAPI) -> None:
        """Configure individual routes on the app."""
        for route in self._routes:
            # Post-``_resolve_lazy`` invariant: ``handler`` is a real callable.
            app.add_api_route(
                route.path,
                cast(Callable[..., Any], route.handler),
                methods=route.methods,
                response_model=route.response_model,
                tags=route.tags,  # type: ignore[arg-type]
                **route.kwargs,
            )

    def _configure_routers(self, app: FastAPI) -> None:
        """Configure routers on the app."""
        for router_def in self._routers:
            # Post-``_resolve_lazy`` invariant: ``router`` is a real APIRouter.
            app.include_router(
                cast(APIRouter, router_def.router),
                prefix=router_def.prefix,
                tags=router_def.tags,  # type: ignore[arg-type]
            )

    def _add_health_route(self, app: FastAPI, ipc_channel: IPCChannel) -> None:
        """
        Add built-in health check route.

        Reports server status and IPC health metrics.
        """

        async def health() -> dict[str, Any]:
            return {
                "status": "ok",
                "ipc": ipc_channel.health_status,
            }

        app.add_api_route(
            "/_health",
            health,
            methods=["GET"],
            tags=["Health"],
            summary="Health check with IPC status",
        )

    def _resolve_lazy(self) -> None:
        """Swap ``Lazy`` wrappers on every definition for their resolved values.

        Idempotent: after resolution the fields hold real callables/objects,
        so a second pass does nothing. Called at the top of ``build()`` — in
        subprocess mode that runs after unpickling, so factories execute in
        the child and the closures they build never crossed the pickle
        boundary. See :class:`Lazy`.

        Adding a new callable-carrying definition type? Extend this walker.
        See the module docstring's invariant.
        """
        for r in self._routes:
            _resolve_field(r, "handler")
        for rd in self._routers:
            _resolve_field(rd, "router")
        for mw in self._middleware:
            _resolve_field(mw, "middleware_class")
        for eh in self._exception_handlers:
            _resolve_field(eh, "handler")
        for su_cb in self._startup_callbacks:
            _resolve_field(su_cb, "callback")
        for sd_cb in self._shutdown_callbacks:
            _resolve_field(sd_cb, "callback")
        if self._lifespan is not None:
            _resolve_field(self._lifespan, "lifespan")
        for req_cb in self._request_callbacks:
            _resolve_field(req_cb, "callback")
        for resp_cb in self._response_callbacks:
            _resolve_field(resp_cb, "callback")
        for exc_cb in self._exception_callbacks:
            _resolve_field(exc_cb, "callback")
        for rl in self._rate_limiters:
            _resolve_field(rl, "limiter")

    def inject_subprocess_logger(self, lg: Logger) -> None:
        """Inject subprocess logger into adapter and LoggerInjectable handlers.

        Called in subprocess after unpickling, before build().
        This allows exception handlers and route handlers to access the logger.

        The logger is:
        1. Stored for injection into request.state.lg via middleware
        2. Injected into LoggerInjectable exception handlers

        Resolves any :class:`Lazy` wrappers first so the ``LoggerInjectable``
        check below sees the real handler instances (a Lazy is not a
        LoggerInjectable itself, so skipping the resolve would silently
        miss logger injection on Lazy-wrapped handlers).

        Args:
            lg: The Logger instance created in the subprocess.
        """
        self._resolve_lazy()

        # Store for request.state injection
        self._subprocess_lg = lg

        # Inject into exception handlers
        from ..handlers import LoggerInjectable

        for handler_def in self._exception_handlers:
            if isinstance(handler_def.handler, LoggerInjectable):
                handler_def.handler.set_logger(lg)
