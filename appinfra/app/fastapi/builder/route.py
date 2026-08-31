# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Route and middleware configuration builder."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from ....subprocess import Lazy
from ..runtime.adapter import (
    CORSDefinition,
    ExceptionHandlerDefinition,
    MiddlewareDefinition,
    RouteDefinition,
    RouterDefinition,
)

if TYPE_CHECKING:
    from .server import ServerBuilder


class RouteConfigurer:
    """
    Focused builder for route and middleware configuration.

    Follows appinfra configurer pattern:
    - with_*() methods return self for chaining
    - done() returns parent builder

    Example:
        server = (ServerBuilder("myapi")
            .routes
                .with_route("/health", health_handler)
                .with_route("/api/users", get_users, methods=["GET"])
                .with_route("/api/users", create_user, methods=["POST"])
                .with_router(my_router, prefix="/v1")
                .with_cors(origins=["http://localhost:3000"])
                .with_middleware(GZipMiddleware, minimum_size=1000)
                .done()
            .build())
    """

    def __init__(self, parent: ServerBuilder) -> None:
        """
        Initialize configurer.

        Args:
            parent: Parent ServerBuilder instance
        """
        self._parent = parent

    def with_route(
        self,
        path: str,
        handler: Callable[..., Any] | Lazy,
        methods: list[str] | None = None,
        response_model: type[Any] | None = None,
        tags: list[str] | None = None,
        **kwargs: Any,
    ) -> RouteConfigurer:
        """
        Add a route.

        Args:
            path: URL path (e.g., "/users/{user_id}")
            handler: Async function to handle requests, or a :class:`Lazy`
                wrapping a module-level factory that returns one. Wrap in
                ``Lazy`` when subprocess mode runs under Python 3.14+ (where
                the ``forkserver`` start method cannot pickle nested
                closures).
            methods: HTTP methods (default: ["GET"])
            response_model: Pydantic model for response serialization
            tags: OpenAPI tags for documentation grouping
            **kwargs: Additional FastAPI route kwargs

        Returns:
            Self for method chaining
        """
        self._parent._routes.append(
            RouteDefinition(
                path=path,
                handler=handler,
                methods=methods or ["GET"],
                response_model=response_model,
                tags=tags,
                kwargs=kwargs,
            )
        )
        return self

    def with_router(
        self,
        router: Any | Lazy,  # APIRouter, or Lazy returning one
        prefix: str = "",
        tags: list[str] | None = None,
    ) -> RouteConfigurer:
        """
        Include a FastAPI router.

        Args:
            router: APIRouter instance with routes defined
            prefix: URL prefix for all routes in router
            tags: OpenAPI tags for documentation grouping

        Returns:
            Self for method chaining
        """
        self._parent._routers.append(
            RouterDefinition(
                router=router,
                prefix=prefix,
                tags=tags,
            )
        )
        return self

    def with_exception_handler(
        self,
        exc_class: type[Exception],
        handler: Callable[..., Any] | Lazy,
    ) -> RouteConfigurer:
        """
        Add an exception handler.

        Args:
            exc_class: Exception class to handle
            handler: Async function to handle the exception

        Returns:
            Self for method chaining
        """
        self._parent._exception_handlers.append(
            ExceptionHandlerDefinition(
                exc_class=exc_class,
                handler=handler,
            )
        )
        return self

    def with_middleware(
        self,
        middleware_class: type[Any] | Lazy,
        **options: Any,
    ) -> RouteConfigurer:
        """
        Add middleware.

        Args:
            middleware_class: Starlette/FastAPI middleware class
            **options: Options passed to middleware constructor

        Returns:
            Self for method chaining
        """
        self._parent._middleware.append(
            MiddlewareDefinition(
                middleware_class=middleware_class,
                options=options,
            )
        )
        return self

    def with_cors(
        self,
        origins: list[str],
        allow_credentials: bool = False,
        allow_methods: list[str] | None = None,
        allow_headers: list[str] | None = None,
    ) -> RouteConfigurer:
        """
        Configure CORS.

        Args:
            origins: Allowed origins (e.g., ["http://localhost:3000", "*"])
            allow_credentials: Allow cookies/auth headers
            allow_methods: Allowed HTTP methods (default: ["*"])
            allow_headers: Allowed request headers (default: ["*"])

        Returns:
            Self for method chaining
        """
        self._parent._cors = CORSDefinition(
            origins=origins,
            allow_credentials=allow_credentials,
            allow_methods=allow_methods or ["*"],
            allow_headers=allow_headers or ["*"],
        )
        return self

    def done(self) -> ServerBuilder:
        """
        Finish route configuration and return to parent builder.

        Returns:
            Parent ServerBuilder instance for continued chaining
        """
        return self._parent
