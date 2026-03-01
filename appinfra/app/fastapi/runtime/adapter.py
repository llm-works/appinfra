"""FastAPI application adapter."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

from ..config.api import ApiConfig

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.responses import Response

    from .ipc import IPCChannel

logger = logging.getLogger("fastapi.adapter")

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
class RouteDefinition:
    """Definition for a route to register."""

    path: str
    handler: Callable[..., Any]
    methods: list[str] = field(default_factory=lambda: ["GET"])
    response_model: type[Any] | None = None
    tags: list[str] | None = None
    kwargs: dict[str, Any] = field(default_factory=dict)


@dataclass
class RouterDefinition:
    """Definition for a router to include."""

    router: Any  # APIRouter
    prefix: str = ""
    tags: list[str] | None = None


@dataclass
class MiddlewareDefinition:
    """Definition for middleware to add."""

    middleware_class: type[Any]
    options: dict[str, Any] = field(default_factory=dict)


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
    handler: Callable[..., Any]


@dataclass
class LifecycleCallbackDefinition:
    """Definition for startup/shutdown lifecycle callback."""

    callback: Callable[[FastAPI], Awaitable[None]]
    name: str | None = None  # Optional name for debugging


# Type alias for lifespan context manager
LifespanCallable = Callable[[FastAPI], AbstractAsyncContextManager[None]]


@dataclass
class LifespanDefinition:
    """Definition for lifespan context manager."""

    lifespan: LifespanCallable


@dataclass
class RequestCallbackDefinition:
    """Definition for request callback (runs before each request handler)."""

    callback: Callable[[Request], Awaitable[None]]
    name: str | None = None


@dataclass
class ResponseCallbackDefinition:
    """Definition for response callback (runs after each request handler)."""

    callback: Callable[[Request, Response], Awaitable[Response]]
    name: str | None = None


@dataclass
class ExceptionCallbackDefinition:
    """Definition for exception callback (runs when unhandled exceptions occur)."""

    callback: Callable[[Request, Exception], Awaitable[None]]
    name: str | None = None


async def _run_exception_callbacks(
    exception_callbacks: list[ExceptionCallbackDefinition],
    request: Request,
    exc: Exception,
) -> None:
    """Run exception callbacks, logging errors but not raising."""
    for exc_cb in exception_callbacks:
        try:
            await exc_cb.callback(request, exc)
        except Exception:
            name = exc_cb.name or exc_cb.callback.__name__
            logger.exception(f"Error in exception callback '{name}'")


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
            for req_cb in request_callbacks:
                try:
                    await req_cb.callback(request)
                except Exception as e:
                    name = req_cb.name or req_cb.callback.__name__
                    raise RuntimeError(f"Request callback '{name}' failed") from e
            try:
                response = await call_next(request)
            except Exception as exc:
                await _run_exception_callbacks(exception_callbacks, request, exc)
                raise
            for resp_cb in response_callbacks:
                name = resp_cb.name or resp_cb.callback.__name__
                try:
                    response = await resp_cb.callback(request, response)
                except Exception as e:
                    raise RuntimeError(f"Response callback '{name}' failed") from e
                if response is None:
                    raise RuntimeError(
                        f"Response callback '{name}' returned None (must return Response)"
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
        lifespan = self._build_lifespan(ipc_channel)
        app = FastAPI(
            title=self._config.title,
            description=self._config.description,
            version=self._config.version,
            lifespan=lifespan,
        )

        self._configure_ipc(app, ipc_channel)
        self._configure_request_response_middleware(app)
        self._configure_middleware(app)
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

    def _build_lifespan(
        self, ipc_channel: IPCChannel | None = None
    ) -> LifespanCallable | None:
        """
        Build lifespan context manager from user callbacks and IPC lifecycle.

        If user provided a lifespan, use it directly.
        Otherwise, wrap startup/shutdown callbacks into a lifespan.
        If ipc_channel is provided, wrap the result with IPC start/stop.
        Returns None if no lifecycle callbacks configured and no IPC channel.
        """
        # Get user-provided lifespan or create one from callbacks
        user_lifespan: LifespanCallable | None = None

        if self._lifespan is not None:
            if self._startup_callbacks or self._shutdown_callbacks:
                logger.warning(
                    "Both lifespan and startup/shutdown callbacks provided. "
                    "startup/shutdown callbacks will be ignored when lifespan is set."
                )
            user_lifespan = self._lifespan.lifespan
        elif self._startup_callbacks or self._shutdown_callbacks:
            user_lifespan = self._create_lifespan_from_callbacks()

        # If no IPC channel, just return user lifespan (may be None)
        if ipc_channel is None:
            return user_lifespan

        # Wrap with IPC lifecycle - IPC polling must be integrated into lifespan
        # because FastAPI ignores on_event() handlers when a lifespan is present
        return self._wrap_lifespan_with_ipc(user_lifespan, ipc_channel)

    def _create_lifespan_from_callbacks(self) -> LifespanCallable:
        """Create a lifespan context manager from startup/shutdown callbacks."""
        startup_callbacks = self._startup_callbacks
        shutdown_callbacks = self._shutdown_callbacks

        @asynccontextmanager
        async def lifespan(app: Any) -> AsyncIterator[None]:
            for cb in startup_callbacks:
                name = cb.name or cb.callback.__name__
                logger.debug(f"Running startup callback: {name}")
                try:
                    await cb.callback(app)
                except Exception as e:
                    raise RuntimeError(f"Startup callback '{name}' failed") from e
            yield
            for cb in shutdown_callbacks:
                name = cb.name or cb.callback.__name__
                logger.debug(f"Running shutdown callback: {name}")
                try:
                    await cb.callback(app)
                except Exception:
                    logger.exception(f"Error in shutdown callback '{name}'")

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
            app.add_middleware(mw.middleware_class, **mw.options)  # type: ignore[arg-type]

    def _configure_exception_handlers(self, app: FastAPI) -> None:
        """Configure exception handlers on the app."""
        for handler in self._exception_handlers:
            app.add_exception_handler(handler.exc_class, handler.handler)

    def _configure_routes(self, app: FastAPI) -> None:
        """Configure individual routes on the app."""
        for route in self._routes:
            app.add_api_route(
                route.path,
                route.handler,
                methods=route.methods,
                response_model=route.response_model,
                tags=route.tags,  # type: ignore[arg-type]
                **route.kwargs,
            )

    def _configure_routers(self, app: FastAPI) -> None:
        """Configure routers on the app."""
        for router_def in self._routers:
            app.include_router(
                router_def.router,
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

    def inject_subprocess_logger(self, lg: Any) -> None:
        """Inject subprocess logger into LoggerInjectable handlers.

        Called in subprocess after unpickling, before build().
        This allows exception handlers that need logging to work correctly
        in subprocess mode.

        Args:
            lg: The Logger instance created in the subprocess.
        """
        from ..handlers import LoggerInjectable

        for handler_def in self._exception_handlers:
            if isinstance(handler_def.handler, LoggerInjectable):
                handler_def.handler.set_logger(lg)
