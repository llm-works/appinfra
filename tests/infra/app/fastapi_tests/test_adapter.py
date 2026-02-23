"""Tests for FastAPIAdapter."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from appinfra.app.fastapi.config.api import ApiConfig
from appinfra.app.fastapi.runtime.adapter import (
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


@pytest.mark.unit
class TestRouteDefinition:
    """Tests for RouteDefinition dataclass."""

    def test_default_values(self):
        """Test default values."""
        route = RouteDefinition(path="/test", handler=lambda: None)

        assert route.path == "/test"
        assert route.methods == ["GET"]
        assert route.response_model is None
        assert route.tags is None
        assert route.kwargs == {}

    def test_custom_values(self):
        """Test custom values."""
        handler = lambda: None
        route = RouteDefinition(
            path="/api/data",
            handler=handler,
            methods=["POST", "PUT"],
            response_model=dict,
            tags=["data"],
            kwargs={"summary": "Test endpoint"},
        )

        assert route.path == "/api/data"
        assert route.handler is handler
        assert route.methods == ["POST", "PUT"]
        assert route.response_model is dict
        assert route.tags == ["data"]
        assert route.kwargs == {"summary": "Test endpoint"}


@pytest.mark.unit
class TestRouterDefinition:
    """Tests for RouterDefinition dataclass."""

    def test_default_values(self):
        """Test default values."""
        router = MagicMock()
        router_def = RouterDefinition(router=router)

        assert router_def.router is router
        assert router_def.prefix == ""
        assert router_def.tags is None

    def test_custom_values(self):
        """Test custom values."""
        router = MagicMock()
        router_def = RouterDefinition(router=router, prefix="/api/v1", tags=["v1"])

        assert router_def.prefix == "/api/v1"
        assert router_def.tags == ["v1"]


@pytest.mark.unit
class TestMiddlewareDefinition:
    """Tests for MiddlewareDefinition dataclass."""

    def test_default_values(self):
        """Test default values."""

        class TestMiddleware:
            pass

        mw_def = MiddlewareDefinition(middleware_class=TestMiddleware)

        assert mw_def.middleware_class is TestMiddleware
        assert mw_def.options == {}

    def test_with_options(self):
        """Test with options."""

        class TestMiddleware:
            pass

        mw_def = MiddlewareDefinition(
            middleware_class=TestMiddleware, options={"timeout": 30}
        )

        assert mw_def.options == {"timeout": 30}


@pytest.mark.unit
class TestCORSDefinition:
    """Tests for CORSDefinition dataclass."""

    def test_default_values(self):
        """Test default values."""
        cors = CORSDefinition(origins=["http://localhost"])

        assert cors.origins == ["http://localhost"]
        assert cors.allow_credentials is False
        assert cors.allow_methods == ["*"]
        assert cors.allow_headers == ["*"]

    def test_custom_values(self):
        """Test custom values."""
        cors = CORSDefinition(
            origins=["http://example.com"],
            allow_credentials=True,
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization"],
        )

        assert cors.origins == ["http://example.com"]
        assert cors.allow_credentials is True
        assert cors.allow_methods == ["GET", "POST"]
        assert cors.allow_headers == ["Authorization"]


@pytest.mark.unit
class TestExceptionHandlerDefinition:
    """Tests for ExceptionHandlerDefinition dataclass."""

    def test_values(self):
        """Test definition values."""

        def handler(request, exc):
            pass

        exc_def = ExceptionHandlerDefinition(exc_class=ValueError, handler=handler)

        assert exc_def.exc_class is ValueError
        assert exc_def.handler is handler


@pytest.mark.unit
class TestFastAPIAdapter:
    """Tests for FastAPIAdapter."""

    @pytest.fixture
    def mock_fastapi(self):
        """Mock FastAPI module."""
        with (
            patch("appinfra.app.fastapi.runtime.adapter.FASTAPI_AVAILABLE", True),
            patch("appinfra.app.fastapi.runtime.adapter.FastAPI") as mock_fastapi,
            patch("appinfra.app.fastapi.runtime.adapter.CORSMiddleware") as mock_cors,
        ):
            mock_app = MagicMock()
            mock_fastapi.return_value = mock_app
            yield {
                "FastAPI": mock_fastapi,
                "CORSMiddleware": mock_cors,
                "app": mock_app,
            }

    def test_initialization(self, mock_fastapi):
        """Test adapter initialization."""
        config = ApiConfig(title="Test API")
        adapter = FastAPIAdapter(config)

        assert adapter._config is config
        assert adapter._routes == []
        assert adapter._routers == []
        assert adapter._middleware == []
        assert adapter._exception_handlers == []
        assert adapter._cors is None

    def test_add_route(self, mock_fastapi):
        """Test adding a route."""
        adapter = FastAPIAdapter(ApiConfig())
        route = RouteDefinition(path="/test", handler=lambda: None)

        adapter.add_route(route)

        assert len(adapter._routes) == 1
        assert adapter._routes[0] is route

    def test_add_router(self, mock_fastapi):
        """Test adding a router."""
        adapter = FastAPIAdapter(ApiConfig())
        router_def = RouterDefinition(router=MagicMock())

        adapter.add_router(router_def)

        assert len(adapter._routers) == 1
        assert adapter._routers[0] is router_def

    def test_add_middleware(self, mock_fastapi):
        """Test adding middleware."""
        adapter = FastAPIAdapter(ApiConfig())
        mw_def = MiddlewareDefinition(middleware_class=MagicMock)

        adapter.add_middleware(mw_def)

        assert len(adapter._middleware) == 1
        assert adapter._middleware[0] is mw_def

    def test_add_exception_handler(self, mock_fastapi):
        """Test adding exception handler."""
        adapter = FastAPIAdapter(ApiConfig())
        handler_def = ExceptionHandlerDefinition(
            exc_class=ValueError, handler=lambda r, e: None
        )

        adapter.add_exception_handler(handler_def)

        assert len(adapter._exception_handlers) == 1
        assert adapter._exception_handlers[0] is handler_def

    def test_set_cors(self, mock_fastapi):
        """Test setting CORS."""
        adapter = FastAPIAdapter(ApiConfig())
        cors = CORSDefinition(origins=["*"])

        adapter.set_cors(cors)

        assert adapter._cors is cors

    def test_build_creates_app(self, mock_fastapi):
        """Test build creates FastAPI app."""
        config = ApiConfig(title="My API", description="Test", version="1.0.0")
        adapter = FastAPIAdapter(config)

        app = adapter.build()

        mock_fastapi["FastAPI"].assert_called_once_with(
            title="My API", description="Test", version="1.0.0", lifespan=None
        )
        assert app is mock_fastapi["app"]

    def test_build_adds_routes(self, mock_fastapi):
        """Test build adds routes to app."""
        adapter = FastAPIAdapter(ApiConfig())

        handler = lambda: None
        adapter.add_route(
            RouteDefinition(
                path="/test",
                handler=handler,
                methods=["POST"],
                response_model=dict,
                tags=["test"],
            )
        )

        adapter.build()

        mock_fastapi["app"].add_api_route.assert_called_once()

    def test_build_adds_cors(self, mock_fastapi):
        """Test build adds CORS middleware."""
        adapter = FastAPIAdapter(ApiConfig())
        adapter.set_cors(CORSDefinition(origins=["http://localhost:3000"]))

        adapter.build()

        mock_fastapi["app"].add_middleware.assert_called()

    def test_build_with_ipc_channel(self, mock_fastapi):
        """Test build stores IPC channel in app state."""
        adapter = FastAPIAdapter(ApiConfig())
        ipc_channel = MagicMock()

        app = adapter.build(ipc_channel=ipc_channel)

        assert mock_fastapi["app"].state.ipc_channel is ipc_channel

    def test_build_adds_middleware(self, mock_fastapi):
        """Test build adds custom middleware."""

        class CustomMiddleware:
            pass

        adapter = FastAPIAdapter(ApiConfig())
        adapter.add_middleware(MiddlewareDefinition(CustomMiddleware, {"timeout": 30}))

        adapter.build()

        # Check that add_middleware was called with the custom middleware
        calls = mock_fastapi["app"].add_middleware.call_args_list
        # First call might be CORS, find our middleware
        found = False
        for call in calls:
            if call[0][0] is CustomMiddleware:
                found = True
                assert call[1]["timeout"] == 30
        assert found

    def test_build_adds_exception_handlers(self, mock_fastapi):
        """Test build adds exception handlers."""

        def error_handler(request, exc):
            pass

        adapter = FastAPIAdapter(ApiConfig())
        adapter.add_exception_handler(
            ExceptionHandlerDefinition(ValueError, error_handler)
        )

        adapter.build()

        mock_fastapi["app"].add_exception_handler.assert_called()

    def test_build_adds_routers(self, mock_fastapi):
        """Test build adds routers."""
        mock_router = MagicMock()

        adapter = FastAPIAdapter(ApiConfig())
        adapter.add_router(RouterDefinition(mock_router, prefix="/v1", tags=["api"]))

        adapter.build()

        mock_fastapi["app"].include_router.assert_called_once()

    def test_build_adds_health_route_with_ipc(self, mock_fastapi):
        """Test build adds health route when IPC enabled with health reporting."""
        from appinfra.app.fastapi.config.ipc import IPCConfig

        config = ApiConfig(ipc=IPCConfig(enable_health_reporting=True))
        adapter = FastAPIAdapter(config)

        ipc_channel = MagicMock()
        ipc_channel.health_status = {"status": "ok"}

        adapter.build(ipc_channel=ipc_channel)

        # Should have called add_api_route for /_health
        calls = mock_fastapi["app"].add_api_route.call_args_list
        health_call = [c for c in calls if c[0][0] == "/_health"]
        assert len(health_call) == 1


@pytest.mark.unit
class TestLifecycleCallbackDefinition:
    """Tests for LifecycleCallbackDefinition dataclass."""

    def test_default_values(self):
        """Test default values."""

        async def callback(app):
            pass

        cb_def = LifecycleCallbackDefinition(callback=callback)

        assert cb_def.callback is callback
        assert cb_def.name is None

    def test_with_name(self):
        """Test with name."""

        async def callback(app):
            pass

        cb_def = LifecycleCallbackDefinition(callback=callback, name="init_db")

        assert cb_def.name == "init_db"


@pytest.mark.unit
class TestLifespanDefinition:
    """Tests for LifespanDefinition dataclass."""

    def test_values(self):
        """Test lifespan definition."""
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def lifespan(app):
            yield

        lifespan_def = LifespanDefinition(lifespan=lifespan)

        assert lifespan_def.lifespan is lifespan


@pytest.mark.unit
class TestRequestCallbackDefinition:
    """Tests for RequestCallbackDefinition dataclass."""

    def test_default_values(self):
        """Test default values."""

        async def callback(request):
            pass

        cb_def = RequestCallbackDefinition(callback=callback)

        assert cb_def.callback is callback
        assert cb_def.name is None


@pytest.mark.unit
class TestResponseCallbackDefinition:
    """Tests for ResponseCallbackDefinition dataclass."""

    def test_default_values(self):
        """Test default values."""

        async def callback(request, response):
            return response

        cb_def = ResponseCallbackDefinition(callback=callback)

        assert cb_def.callback is callback
        assert cb_def.name is None


@pytest.mark.unit
class TestExceptionCallbackDefinition:
    """Tests for ExceptionCallbackDefinition dataclass."""

    def test_default_values(self):
        """Test default values."""

        async def callback(request, exc):
            pass

        cb_def = ExceptionCallbackDefinition(callback=callback)

        assert cb_def.callback is callback
        assert cb_def.name is None


@pytest.mark.unit
class TestFastAPIAdapterLifecycleCallbacks:
    """Tests for FastAPIAdapter lifecycle callback methods."""

    @pytest.fixture
    def mock_fastapi(self):
        """Mock FastAPI and dependencies."""
        with (
            patch("appinfra.app.fastapi.runtime.adapter.FASTAPI_AVAILABLE", True),
            patch("appinfra.app.fastapi.runtime.adapter.FastAPI") as mock_fastapi_cls,
            patch("appinfra.app.fastapi.runtime.adapter.CORSMiddleware") as mock_cors,
        ):
            mock_app = MagicMock()
            mock_app.state = MagicMock()
            mock_fastapi_cls.return_value = mock_app
            yield {
                "FastAPI": mock_fastapi_cls,
                "app": mock_app,
                "CORSMiddleware": mock_cors,
            }

    def test_add_startup_callback(self, mock_fastapi):
        """Test add_startup_callback stores callback."""
        adapter = FastAPIAdapter(ApiConfig())

        async def startup(app):
            pass

        cb_def = LifecycleCallbackDefinition(callback=startup, name="startup")
        adapter.add_startup_callback(cb_def)

        assert len(adapter._startup_callbacks) == 1
        assert adapter._startup_callbacks[0] is cb_def

    def test_add_shutdown_callback(self, mock_fastapi):
        """Test add_shutdown_callback stores callback."""
        adapter = FastAPIAdapter(ApiConfig())

        async def shutdown(app):
            pass

        cb_def = LifecycleCallbackDefinition(callback=shutdown, name="shutdown")
        adapter.add_shutdown_callback(cb_def)

        assert len(adapter._shutdown_callbacks) == 1
        assert adapter._shutdown_callbacks[0] is cb_def

    def test_set_lifespan(self, mock_fastapi):
        """Test set_lifespan stores lifespan."""
        from contextlib import asynccontextmanager

        adapter = FastAPIAdapter(ApiConfig())

        @asynccontextmanager
        async def lifespan(app):
            yield

        lifespan_def = LifespanDefinition(lifespan=lifespan)
        adapter.set_lifespan(lifespan_def)

        assert adapter._lifespan is lifespan_def

    def test_add_request_callback(self, mock_fastapi):
        """Test add_request_callback stores callback."""
        adapter = FastAPIAdapter(ApiConfig())

        async def on_request(request):
            pass

        cb_def = RequestCallbackDefinition(callback=on_request)
        adapter.add_request_callback(cb_def)

        assert len(adapter._request_callbacks) == 1
        assert adapter._request_callbacks[0] is cb_def

    def test_add_response_callback(self, mock_fastapi):
        """Test add_response_callback stores callback."""
        adapter = FastAPIAdapter(ApiConfig())

        async def on_response(request, response):
            return response

        cb_def = ResponseCallbackDefinition(callback=on_response)
        adapter.add_response_callback(cb_def)

        assert len(adapter._response_callbacks) == 1
        assert adapter._response_callbacks[0] is cb_def

    def test_add_exception_callback(self, mock_fastapi):
        """Test add_exception_callback stores callback."""
        adapter = FastAPIAdapter(ApiConfig())

        async def on_exception(request, exc):
            pass

        cb_def = ExceptionCallbackDefinition(callback=on_exception)
        adapter.add_exception_callback(cb_def)

        assert len(adapter._exception_callbacks) == 1
        assert adapter._exception_callbacks[0] is cb_def

    def test_build_with_startup_shutdown_creates_lifespan(self, mock_fastapi):
        """Test build creates lifespan from startup/shutdown callbacks."""
        adapter = FastAPIAdapter(ApiConfig())

        async def startup(app):
            pass

        async def shutdown(app):
            pass

        adapter.add_startup_callback(LifecycleCallbackDefinition(callback=startup))
        adapter.add_shutdown_callback(LifecycleCallbackDefinition(callback=shutdown))

        adapter.build()

        # FastAPI should be called with a lifespan (not None)
        call_kwargs = mock_fastapi["FastAPI"].call_args.kwargs
        assert call_kwargs["lifespan"] is not None

    def test_build_with_explicit_lifespan(self, mock_fastapi):
        """Test build uses explicit lifespan when provided."""
        from contextlib import asynccontextmanager

        adapter = FastAPIAdapter(ApiConfig())

        @asynccontextmanager
        async def my_lifespan(app):
            yield

        adapter.set_lifespan(LifespanDefinition(lifespan=my_lifespan))

        adapter.build()

        call_kwargs = mock_fastapi["FastAPI"].call_args.kwargs
        assert call_kwargs["lifespan"] is my_lifespan

    def test_build_with_lifespan_and_callbacks_warns(self, mock_fastapi, caplog):
        """Test build warns when both lifespan and startup/shutdown callbacks are set."""
        import logging
        from contextlib import asynccontextmanager

        adapter = FastAPIAdapter(ApiConfig())

        @asynccontextmanager
        async def my_lifespan(app):
            yield

        async def startup(app):
            pass

        adapter.set_lifespan(LifespanDefinition(lifespan=my_lifespan))
        adapter.add_startup_callback(LifecycleCallbackDefinition(callback=startup))

        with caplog.at_level(logging.WARNING):
            adapter.build()

        assert "startup/shutdown callbacks will be ignored" in caplog.text

    def test_build_with_request_response_callbacks_adds_middleware(self, mock_fastapi):
        """Test build adds middleware for request/response callbacks."""
        adapter = FastAPIAdapter(ApiConfig())

        async def on_request(request):
            pass

        adapter.add_request_callback(RequestCallbackDefinition(callback=on_request))

        adapter.build()

        # Should have called add_middleware
        mock_fastapi["app"].add_middleware.assert_called()


@pytest.mark.unit
class TestLifecycleCallbackExecution:
    """Tests for lifecycle callback execution."""

    @pytest.mark.asyncio
    async def test_lifespan_runs_startup_callbacks(self):
        """Test that startup callbacks are executed in lifespan."""
        from appinfra.app.fastapi.runtime.adapter import (
            FastAPIAdapter,
            LifecycleCallbackDefinition,
        )

        called = []

        async def startup1(app):
            called.append("startup1")

        async def startup2(app):
            called.append("startup2")

        with (
            patch("appinfra.app.fastapi.runtime.adapter.FASTAPI_AVAILABLE", True),
            patch("appinfra.app.fastapi.runtime.adapter.FastAPI"),
            patch("appinfra.app.fastapi.runtime.adapter.CORSMiddleware"),
        ):
            adapter = FastAPIAdapter(ApiConfig())
            adapter.add_startup_callback(
                LifecycleCallbackDefinition(callback=startup1, name="s1")
            )
            adapter.add_startup_callback(
                LifecycleCallbackDefinition(callback=startup2, name="s2")
            )

            lifespan = adapter._create_lifespan_from_callbacks()

            # Run the lifespan context manager
            mock_app = MagicMock()
            async with lifespan(mock_app):
                pass

            assert called == ["startup1", "startup2"]

    @pytest.mark.asyncio
    async def test_lifespan_runs_shutdown_callbacks(self):
        """Test that shutdown callbacks are executed in lifespan."""
        from appinfra.app.fastapi.runtime.adapter import (
            FastAPIAdapter,
            LifecycleCallbackDefinition,
        )

        called = []

        async def shutdown1(app):
            called.append("shutdown1")

        with (
            patch("appinfra.app.fastapi.runtime.adapter.FASTAPI_AVAILABLE", True),
            patch("appinfra.app.fastapi.runtime.adapter.FastAPI"),
            patch("appinfra.app.fastapi.runtime.adapter.CORSMiddleware"),
        ):
            adapter = FastAPIAdapter(ApiConfig())
            adapter.add_shutdown_callback(
                LifecycleCallbackDefinition(callback=shutdown1)
            )

            lifespan = adapter._create_lifespan_from_callbacks()

            mock_app = MagicMock()
            async with lifespan(mock_app):
                assert called == []  # Not called yet

            assert called == ["shutdown1"]

    @pytest.mark.asyncio
    async def test_callback_middleware_runs_request_callbacks(self):
        """Test that request callbacks are executed by middleware."""
        from appinfra.app.fastapi.runtime.adapter import (
            RequestCallbackDefinition,
            _create_callback_middleware,
        )

        called = []

        async def on_request(request):
            called.append("request")

        middleware_cls = _create_callback_middleware(
            request_callbacks=[RequestCallbackDefinition(callback=on_request)],
            response_callbacks=[],
            exception_callbacks=[],
        )

        # Create middleware instance and call dispatch
        mock_app = MagicMock()
        middleware = middleware_cls(mock_app)

        mock_request = MagicMock()
        mock_response = MagicMock()

        async def mock_call_next(req):
            return mock_response

        result = await middleware.dispatch(mock_request, mock_call_next)

        assert called == ["request"]
        assert result is mock_response

    @pytest.mark.asyncio
    async def test_callback_middleware_runs_response_callbacks(self):
        """Test that response callbacks are executed by middleware."""
        from appinfra.app.fastapi.runtime.adapter import (
            ResponseCallbackDefinition,
            _create_callback_middleware,
        )

        called = []

        async def on_response(request, response):
            called.append("response")
            return response

        middleware_cls = _create_callback_middleware(
            request_callbacks=[],
            response_callbacks=[ResponseCallbackDefinition(callback=on_response)],
            exception_callbacks=[],
        )

        mock_app = MagicMock()
        middleware = middleware_cls(mock_app)

        mock_request = MagicMock()
        mock_response = MagicMock()

        async def mock_call_next(req):
            return mock_response

        await middleware.dispatch(mock_request, mock_call_next)

        assert called == ["response"]

    @pytest.mark.asyncio
    async def test_callback_middleware_runs_exception_callbacks(self):
        """Test that exception callbacks are executed on error."""
        from appinfra.app.fastapi.runtime.adapter import (
            ExceptionCallbackDefinition,
            _create_callback_middleware,
        )

        called = []

        async def on_exception(request, exc):
            called.append(("exception", str(exc)))

        middleware_cls = _create_callback_middleware(
            request_callbacks=[],
            response_callbacks=[],
            exception_callbacks=[ExceptionCallbackDefinition(callback=on_exception)],
        )

        mock_app = MagicMock()
        middleware = middleware_cls(mock_app)

        mock_request = MagicMock()

        async def mock_call_next(req):
            raise ValueError("test error")

        with pytest.raises(ValueError, match="test error"):
            await middleware.dispatch(mock_request, mock_call_next)

        assert called == [("exception", "test error")]

    @pytest.mark.asyncio
    async def test_startup_callback_failure_wraps_exception(self):
        """Test that startup callback failure wraps exception with context."""
        from appinfra.app.fastapi.runtime.adapter import (
            FastAPIAdapter,
            LifecycleCallbackDefinition,
        )

        async def failing_startup(app):
            raise ValueError("db connection failed")

        with (
            patch("appinfra.app.fastapi.runtime.adapter.FASTAPI_AVAILABLE", True),
            patch("appinfra.app.fastapi.runtime.adapter.FastAPI"),
            patch("appinfra.app.fastapi.runtime.adapter.CORSMiddleware"),
        ):
            adapter = FastAPIAdapter(ApiConfig())
            adapter.add_startup_callback(
                LifecycleCallbackDefinition(callback=failing_startup, name="init_db")
            )

            lifespan = adapter._create_lifespan_from_callbacks()

            mock_app = MagicMock()
            with pytest.raises(RuntimeError, match="Startup callback 'init_db' failed"):
                async with lifespan(mock_app):
                    pass

    @pytest.mark.asyncio
    async def test_shutdown_callbacks_continue_on_failure(self):
        """Test that shutdown callbacks continue even if one fails."""
        from appinfra.app.fastapi.runtime.adapter import (
            FastAPIAdapter,
            LifecycleCallbackDefinition,
        )

        called = []

        async def failing_shutdown(app):
            called.append("failing")
            raise ValueError("cleanup failed")

        async def second_shutdown(app):
            called.append("second")

        with (
            patch("appinfra.app.fastapi.runtime.adapter.FASTAPI_AVAILABLE", True),
            patch("appinfra.app.fastapi.runtime.adapter.FastAPI"),
            patch("appinfra.app.fastapi.runtime.adapter.CORSMiddleware"),
        ):
            adapter = FastAPIAdapter(ApiConfig())
            adapter.add_shutdown_callback(
                LifecycleCallbackDefinition(callback=failing_shutdown, name="cleanup")
            )
            adapter.add_shutdown_callback(
                LifecycleCallbackDefinition(callback=second_shutdown, name="second")
            )

            lifespan = adapter._create_lifespan_from_callbacks()

            mock_app = MagicMock()
            async with lifespan(mock_app):
                pass

            # Both callbacks should have run despite the first one failing
            assert called == ["failing", "second"]

    @pytest.mark.asyncio
    async def test_request_callback_failure_wraps_exception(self):
        """Test that request callback failure wraps exception with context."""
        from appinfra.app.fastapi.runtime.adapter import (
            RequestCallbackDefinition,
            _create_callback_middleware,
        )

        async def failing_request(request):
            raise ValueError("auth failed")

        middleware_cls = _create_callback_middleware(
            request_callbacks=[
                RequestCallbackDefinition(callback=failing_request, name="auth_check")
            ],
            response_callbacks=[],
            exception_callbacks=[],
        )

        mock_app = MagicMock()
        middleware = middleware_cls(mock_app)
        mock_request = MagicMock()

        async def mock_call_next(req):
            return MagicMock()

        with pytest.raises(RuntimeError, match="Request callback 'auth_check' failed"):
            await middleware.dispatch(mock_request, mock_call_next)

    @pytest.mark.asyncio
    async def test_response_callback_failure_wraps_exception(self):
        """Test that response callback failure wraps exception with context."""
        from appinfra.app.fastapi.runtime.adapter import (
            ResponseCallbackDefinition,
            _create_callback_middleware,
        )

        async def failing_response(request, response):
            raise ValueError("header injection failed")

        middleware_cls = _create_callback_middleware(
            request_callbacks=[],
            response_callbacks=[
                ResponseCallbackDefinition(
                    callback=failing_response, name="add_headers"
                )
            ],
            exception_callbacks=[],
        )

        mock_app = MagicMock()
        middleware = middleware_cls(mock_app)
        mock_request = MagicMock()
        mock_response = MagicMock()

        async def mock_call_next(req):
            return mock_response

        with pytest.raises(
            RuntimeError, match="Response callback 'add_headers' failed"
        ):
            await middleware.dispatch(mock_request, mock_call_next)

    @pytest.mark.asyncio
    async def test_exception_callback_failure_does_not_swallow_original(self):
        """Test that failing exception callback doesn't swallow original exception."""
        from appinfra.app.fastapi.runtime.adapter import (
            ExceptionCallbackDefinition,
            _create_callback_middleware,
        )

        called = []

        async def failing_exc_callback(request, exc):
            called.append("failing_cb")
            raise RuntimeError("logging service unavailable")

        async def second_exc_callback(request, exc):
            called.append("second_cb")

        middleware_cls = _create_callback_middleware(
            request_callbacks=[],
            response_callbacks=[],
            exception_callbacks=[
                ExceptionCallbackDefinition(
                    callback=failing_exc_callback, name="error_logger"
                ),
                ExceptionCallbackDefinition(
                    callback=second_exc_callback, name="metrics"
                ),
            ],
        )

        mock_app = MagicMock()
        middleware = middleware_cls(mock_app)
        mock_request = MagicMock()

        async def mock_call_next(req):
            raise ValueError("original request error")

        # Should raise the ORIGINAL exception, not the callback's exception
        with pytest.raises(ValueError, match="original request error"):
            await middleware.dispatch(mock_request, mock_call_next)

        # Both exception callbacks should have been called despite first one failing
        assert called == ["failing_cb", "second_cb"]

    @pytest.mark.asyncio
    async def test_response_callback_returning_none_raises_error(self):
        """Test that response callback returning None raises clear error."""
        from appinfra.app.fastapi.runtime.adapter import (
            ResponseCallbackDefinition,
            _create_callback_middleware,
        )

        async def bad_callback(request, response):
            # Forgot to return response!
            pass

        middleware_cls = _create_callback_middleware(
            request_callbacks=[],
            response_callbacks=[
                ResponseCallbackDefinition(callback=bad_callback, name="bad_cb")
            ],
            exception_callbacks=[],
        )

        mock_app = MagicMock()
        middleware = middleware_cls(mock_app)
        mock_request = MagicMock()
        mock_response = MagicMock()

        async def mock_call_next(req):
            return mock_response

        with pytest.raises(
            RuntimeError, match="Response callback 'bad_cb' returned None"
        ):
            await middleware.dispatch(mock_request, mock_call_next)


@pytest.mark.unit
class TestIPCLifespanIntegration:
    """Tests for IPC lifecycle integration with lifespan."""

    @pytest.mark.asyncio
    async def test_ipc_lifespan_starts_and_stops_polling(self):
        """Test that IPC polling is started and stopped via lifespan."""
        from appinfra.app.fastapi.runtime.adapter import FastAPIAdapter

        mock_ipc_channel = MagicMock()
        mock_ipc_channel.start_polling = AsyncMock()
        mock_ipc_channel.stop_polling = AsyncMock()

        with (
            patch("appinfra.app.fastapi.runtime.adapter.FASTAPI_AVAILABLE", True),
            patch("appinfra.app.fastapi.runtime.adapter.FastAPI"),
            patch("appinfra.app.fastapi.runtime.adapter.CORSMiddleware"),
        ):
            adapter = FastAPIAdapter(ApiConfig())
            lifespan = adapter._build_lifespan(ipc_channel=mock_ipc_channel)

            assert lifespan is not None

            # Run the lifespan
            mock_app = MagicMock()
            async with lifespan(mock_app):
                # During lifespan, polling should have started
                mock_ipc_channel.start_polling.assert_called_once()
                mock_ipc_channel.stop_polling.assert_not_called()

            # After lifespan exits, polling should have stopped
            mock_ipc_channel.stop_polling.assert_called_once()

    @pytest.mark.asyncio
    async def test_ipc_lifespan_with_user_startup_callbacks(self):
        """Test that IPC + user startup callbacks work together (bug fix test)."""
        from appinfra.app.fastapi.runtime.adapter import (
            FastAPIAdapter,
            LifecycleCallbackDefinition,
        )

        call_order = []

        async def user_startup(app):
            call_order.append("user_startup")

        async def user_shutdown(app):
            call_order.append("user_shutdown")

        mock_ipc_channel = MagicMock()

        async def mock_start_polling():
            call_order.append("ipc_start")

        async def mock_stop_polling():
            call_order.append("ipc_stop")

        mock_ipc_channel.start_polling = mock_start_polling
        mock_ipc_channel.stop_polling = mock_stop_polling

        with (
            patch("appinfra.app.fastapi.runtime.adapter.FASTAPI_AVAILABLE", True),
            patch("appinfra.app.fastapi.runtime.adapter.FastAPI"),
            patch("appinfra.app.fastapi.runtime.adapter.CORSMiddleware"),
        ):
            adapter = FastAPIAdapter(ApiConfig())
            adapter.add_startup_callback(
                LifecycleCallbackDefinition(callback=user_startup, name="user_startup")
            )
            adapter.add_shutdown_callback(
                LifecycleCallbackDefinition(
                    callback=user_shutdown, name="user_shutdown"
                )
            )

            lifespan = adapter._build_lifespan(ipc_channel=mock_ipc_channel)

            mock_app = MagicMock()
            async with lifespan(mock_app):
                pass

            # Verify order: IPC starts first, then user startup
            # On shutdown: user shutdown first, then IPC stops
            assert call_order == [
                "ipc_start",
                "user_startup",
                "user_shutdown",
                "ipc_stop",
            ]

    @pytest.mark.asyncio
    async def test_ipc_lifespan_with_explicit_user_lifespan(self):
        """Test that IPC wraps user-provided lifespan correctly."""
        from contextlib import asynccontextmanager

        from appinfra.app.fastapi.runtime.adapter import (
            FastAPIAdapter,
            LifespanDefinition,
        )

        call_order = []

        @asynccontextmanager
        async def user_lifespan(app):
            call_order.append("user_startup")
            yield
            call_order.append("user_shutdown")

        mock_ipc_channel = MagicMock()

        async def mock_start_polling():
            call_order.append("ipc_start")

        async def mock_stop_polling():
            call_order.append("ipc_stop")

        mock_ipc_channel.start_polling = mock_start_polling
        mock_ipc_channel.stop_polling = mock_stop_polling

        with (
            patch("appinfra.app.fastapi.runtime.adapter.FASTAPI_AVAILABLE", True),
            patch("appinfra.app.fastapi.runtime.adapter.FastAPI"),
            patch("appinfra.app.fastapi.runtime.adapter.CORSMiddleware"),
        ):
            adapter = FastAPIAdapter(ApiConfig())
            adapter.set_lifespan(LifespanDefinition(lifespan=user_lifespan))

            lifespan = adapter._build_lifespan(ipc_channel=mock_ipc_channel)

            mock_app = MagicMock()
            async with lifespan(mock_app):
                pass

            # IPC wraps user lifespan
            assert call_order == [
                "ipc_start",
                "user_startup",
                "user_shutdown",
                "ipc_stop",
            ]

    @pytest.mark.asyncio
    async def test_no_ipc_returns_user_lifespan_unchanged(self):
        """Test that without IPC, user lifespan is returned unchanged."""
        from contextlib import asynccontextmanager

        from appinfra.app.fastapi.runtime.adapter import (
            FastAPIAdapter,
            LifespanDefinition,
        )

        @asynccontextmanager
        async def user_lifespan(app):
            yield

        with (
            patch("appinfra.app.fastapi.runtime.adapter.FASTAPI_AVAILABLE", True),
            patch("appinfra.app.fastapi.runtime.adapter.FastAPI"),
            patch("appinfra.app.fastapi.runtime.adapter.CORSMiddleware"),
        ):
            adapter = FastAPIAdapter(ApiConfig())
            adapter.set_lifespan(LifespanDefinition(lifespan=user_lifespan))

            # Without IPC channel, should return user lifespan directly
            lifespan = adapter._build_lifespan(ipc_channel=None)
            assert lifespan is user_lifespan

    @pytest.mark.asyncio
    async def test_ipc_only_no_user_callbacks(self):
        """Test IPC lifespan when no user callbacks are provided."""
        from appinfra.app.fastapi.runtime.adapter import FastAPIAdapter

        mock_ipc_channel = MagicMock()
        mock_ipc_channel.start_polling = AsyncMock()
        mock_ipc_channel.stop_polling = AsyncMock()

        with (
            patch("appinfra.app.fastapi.runtime.adapter.FASTAPI_AVAILABLE", True),
            patch("appinfra.app.fastapi.runtime.adapter.FastAPI"),
            patch("appinfra.app.fastapi.runtime.adapter.CORSMiddleware"),
        ):
            adapter = FastAPIAdapter(ApiConfig())
            # No user callbacks added

            lifespan = adapter._build_lifespan(ipc_channel=mock_ipc_channel)
            assert lifespan is not None

            mock_app = MagicMock()
            async with lifespan(mock_app):
                mock_ipc_channel.start_polling.assert_called_once()

            mock_ipc_channel.stop_polling.assert_called_once()
