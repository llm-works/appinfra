"""Tests for FastAPI ServerBuilder."""

import multiprocessing as mp
from unittest.mock import MagicMock, patch

import pytest

from appinfra.app.fastapi.config.api import ApiConfig
from appinfra.app.fastapi.config.ipc import IPCConfig
from appinfra.app.fastapi.config.uvicorn import UvicornConfig


@pytest.mark.unit
class TestServerBuilder:
    """Tests for ServerBuilder fluent interface."""

    @pytest.fixture
    def mock_fastapi(self):
        """Mock FastAPI to avoid import dependency."""
        with patch("appinfra.app.fastapi.builder.server.FastAPIAdapter") as mock:
            mock.return_value = MagicMock()
            yield mock

    def test_basic_configuration(self, mock_fastapi):
        """Test basic server configuration."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        builder = ServerBuilder("test-api")
        builder.with_host("127.0.0.1").with_port(9000)

        assert builder._host == "127.0.0.1"
        assert builder._port == 9000

    def test_metadata_configuration(self, mock_fastapi):
        """Test API metadata configuration."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        builder = (
            ServerBuilder("test-api")
            .with_title("My API")
            .with_description("Test description")
            .with_version("2.0.0")
        )

        assert builder._title == "My API"
        assert builder._description == "Test description"
        assert builder._version == "2.0.0"

    def test_timeout_configuration(self, mock_fastapi):
        """Test timeout configuration."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        builder = ServerBuilder("test-api").with_timeout(120.0)
        assert builder._response_timeout == 120.0

    def test_with_config(self, mock_fastapi):
        """Test bulk configuration via ApiConfig."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        config = ApiConfig(
            host="192.168.1.1",
            port=8080,
            title="Bulk Config API",
            version="3.0.0",
            auto_restart=False,
        )

        builder = ServerBuilder("test-api").with_config(config)

        assert builder._host == "192.168.1.1"
        assert builder._port == 8080
        assert builder._title == "Bulk Config API"
        assert builder._version == "3.0.0"
        assert builder._auto_restart is False

    def test_fluent_chaining(self, mock_fastapi):
        """Test method chaining returns builder."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        builder = ServerBuilder("test-api")

        result = builder.with_host("localhost")
        assert result is builder

        result = builder.with_port(8000)
        assert result is builder

        result = builder.with_title("API")
        assert result is builder

    def test_with_config_including_ipc(self, mock_fastapi):
        """Test with_config with IPC configuration."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        config = ApiConfig(
            host="192.168.1.1",
            port=8080,
            ipc=IPCConfig(max_pending=200),
        )

        builder = ServerBuilder("test-api").with_config(config)

        assert builder._ipc_config is not None
        assert builder._ipc_config.max_pending == 200

    def test_build_creates_server(self, mock_fastapi):
        """Test build() creates a Server instance."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        def handler():
            return {"status": "ok"}

        builder = (
            ServerBuilder("test-api")
            .with_host("127.0.0.1")
            .with_port(9000)
            .routes.with_route("/health", handler)
            .with_cors(origins=["*"])
            .done()
        )

        with (
            patch("appinfra.app.fastapi.builder.server.FastAPIAdapter") as mock_adapter,
            patch("appinfra.app.fastapi.builder.server.Server") as mock_server,
        ):
            server = builder.build()

            # Verify adapter was configured
            mock_adapter.return_value.add_route.assert_called()
            mock_adapter.return_value.set_cors.assert_called()

            # Verify Server was called with correct arguments
            mock_server.assert_called_once()
            call_kwargs = mock_server.call_args[1]
            assert call_kwargs["name"] == "test-api"
            assert call_kwargs["config"].host == "127.0.0.1"
            assert call_kwargs["config"].port == 9000

    def test_build_with_routers_middleware_handlers(self, mock_fastapi):
        """Test build() with routers, middleware, and exception handlers."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        mock_router = MagicMock()

        class CustomMiddleware:
            pass

        def error_handler(request, exc):
            pass

        builder = (
            ServerBuilder("test-api")
            .routes.with_router(mock_router, prefix="/api")
            .with_middleware(CustomMiddleware)
            .with_exception_handler(ValueError, error_handler)
            .done()
        )

        with (
            patch("appinfra.app.fastapi.builder.server.FastAPIAdapter") as mock_adapter,
            patch("appinfra.app.fastapi.builder.server.Server"),
        ):
            builder.build()

            # Verify all configurers were called
            mock_adapter.return_value.add_router.assert_called()
            mock_adapter.return_value.add_middleware.assert_called()
            mock_adapter.return_value.add_exception_handler.assert_called()


@pytest.mark.unit
class TestRouteConfigurer:
    """Tests for RouteConfigurer."""

    @pytest.fixture
    def mock_fastapi(self):
        """Mock FastAPI to avoid import dependency."""
        with patch("appinfra.app.fastapi.builder.server.FastAPIAdapter") as mock:
            mock.return_value = MagicMock()
            yield mock

    def test_add_route(self, mock_fastapi):
        """Test adding a route."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        def handler():
            return {"status": "ok"}

        builder = ServerBuilder("test-api")
        builder.routes.with_route("/health", handler).done()

        assert len(builder._routes) == 1
        assert builder._routes[0].path == "/health"
        assert builder._routes[0].handler is handler
        assert builder._routes[0].methods == ["GET"]

    def test_add_route_with_methods(self, mock_fastapi):
        """Test adding a route with custom methods."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        def handler():
            pass

        builder = ServerBuilder("test-api")
        builder.routes.with_route("/data", handler, methods=["POST", "PUT"]).done()

        assert builder._routes[0].methods == ["POST", "PUT"]

    def test_add_multiple_routes(self, mock_fastapi):
        """Test adding multiple routes."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        builder = ServerBuilder("test-api")
        builder.routes.with_route("/a", lambda: None).with_route(
            "/b", lambda: None
        ).done()

        assert len(builder._routes) == 2

    def test_cors_configuration(self, mock_fastapi):
        """Test CORS configuration."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        builder = ServerBuilder("test-api")
        builder.routes.with_cors(
            origins=["http://localhost:3000"],
            allow_credentials=True,
            allow_methods=["GET", "POST"],
        ).done()

        assert builder._cors is not None
        assert builder._cors.origins == ["http://localhost:3000"]
        assert builder._cors.allow_credentials is True
        assert builder._cors.allow_methods == ["GET", "POST"]

    def test_done_returns_builder(self, mock_fastapi):
        """Test that done() returns parent builder."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        builder = ServerBuilder("test-api")
        result = builder.routes.done()
        assert result is builder

    def test_add_router(self, mock_fastapi):
        """Test adding a router."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        mock_router = MagicMock()
        builder = ServerBuilder("test-api")
        builder.routes.with_router(mock_router, prefix="/api/v1", tags=["v1"]).done()

        assert len(builder._routers) == 1
        assert builder._routers[0].router is mock_router
        assert builder._routers[0].prefix == "/api/v1"
        assert builder._routers[0].tags == ["v1"]

    def test_add_exception_handler(self, mock_fastapi):
        """Test adding an exception handler."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        def handler(request, exc):
            pass

        builder = ServerBuilder("test-api")
        builder.routes.with_exception_handler(ValueError, handler).done()

        assert len(builder._exception_handlers) == 1
        assert builder._exception_handlers[0].exc_class is ValueError
        assert builder._exception_handlers[0].handler is handler

    def test_add_middleware(self, mock_fastapi):
        """Test adding middleware."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        class CustomMiddleware:
            pass

        builder = ServerBuilder("test-api")
        builder.routes.with_middleware(CustomMiddleware, timeout=30).done()

        assert len(builder._middleware) == 1
        assert builder._middleware[0].middleware_class is CustomMiddleware
        assert builder._middleware[0].options == {"timeout": 30}


@pytest.mark.unit
class TestSubprocessConfigurer:
    """Tests for SubprocessConfigurer."""

    @pytest.fixture
    def mock_fastapi(self):
        """Mock FastAPI to avoid import dependency."""
        with patch("appinfra.app.fastapi.builder.server.FastAPIAdapter") as mock:
            mock.return_value = MagicMock()
            yield mock

    def test_ipc_configuration(self, mock_fastapi):
        """Test IPC queue configuration."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        request_q: mp.Queue = mp.Queue()
        response_q: mp.Queue = mp.Queue()

        builder = ServerBuilder("test-api")
        builder.subprocess.with_ipc(request_q, response_q).done()

        assert builder._request_q is request_q
        assert builder._response_q is response_q

    def test_auto_restart_configuration(self, mock_fastapi):
        """Test auto-restart configuration."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        builder = ServerBuilder("test-api")
        builder.subprocess.with_auto_restart(
            enabled=True, delay=2.0, max_restarts=10
        ).done()

        assert builder._auto_restart is True
        assert builder._restart_delay == 2.0
        assert builder._max_restarts == 10

    def test_log_file_configuration(self, mock_fastapi):
        """Test log file configuration."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        builder = ServerBuilder("test-api")
        builder.subprocess.with_log_file("/var/log/server.log").done()

        assert builder._log_file == "/var/log/server.log"

    def test_ipc_config(self, mock_fastapi):
        """Test IPCConfig configuration."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        request_q: mp.Queue = mp.Queue()
        response_q: mp.Queue = mp.Queue()
        ipc_config = IPCConfig(max_pending=500, response_timeout=120.0)

        builder = ServerBuilder("test-api")
        # Must enable subprocess mode with_ipc() before with_config() takes effect
        builder.subprocess.with_ipc(request_q, response_q).with_config(
            ipc_config
        ).done()

        assert builder._ipc_config is ipc_config
        assert builder._ipc_config.max_pending == 500

    def test_poll_interval(self, mock_fastapi):
        """Test poll interval configuration."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        request_q: mp.Queue = mp.Queue()
        response_q: mp.Queue = mp.Queue()

        builder = ServerBuilder("test-api")
        builder.subprocess.with_ipc(request_q, response_q).with_poll_interval(
            0.05
        ).done()

        assert builder._ipc_config.poll_interval == 0.05

    def test_response_timeout(self, mock_fastapi):
        """Test response timeout configuration."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        request_q: mp.Queue = mp.Queue()
        response_q: mp.Queue = mp.Queue()

        builder = ServerBuilder("test-api")
        builder.subprocess.with_ipc(request_q, response_q).with_response_timeout(
            30.0
        ).done()

        assert builder._ipc_config.response_timeout == 30.0

    def test_max_pending(self, mock_fastapi):
        """Test max pending configuration."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        request_q: mp.Queue = mp.Queue()
        response_q: mp.Queue = mp.Queue()

        builder = ServerBuilder("test-api")
        builder.subprocess.with_ipc(request_q, response_q).with_max_pending(200).done()

        assert builder._ipc_config.max_pending == 200

    def test_health_reporting(self, mock_fastapi):
        """Test health reporting configuration."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        request_q: mp.Queue = mp.Queue()
        response_q: mp.Queue = mp.Queue()

        builder = ServerBuilder("test-api")
        builder.subprocess.with_ipc(request_q, response_q).with_health_reporting(
            False
        ).done()

        assert builder._ipc_config.enable_health_reporting is False


@pytest.mark.unit
class TestUvicornConfigurer:
    """Tests for UvicornConfigurer."""

    @pytest.fixture
    def mock_fastapi(self):
        """Mock FastAPI to avoid import dependency."""
        with patch("appinfra.app.fastapi.builder.server.FastAPIAdapter") as mock:
            mock.return_value = MagicMock()
            yield mock

    def test_workers_configuration(self, mock_fastapi):
        """Test workers configuration."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        builder = ServerBuilder("test-api")
        builder.uvicorn.with_workers(4).done()

        assert builder._uvicorn_config.workers == 4

    def test_log_level_configuration(self, mock_fastapi):
        """Test log level configuration."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        builder = ServerBuilder("test-api")
        builder.uvicorn.with_log_level("debug").done()

        assert builder._uvicorn_config.log_level == "debug"

    def test_ssl_configuration(self, mock_fastapi):
        """Test SSL configuration."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        builder = ServerBuilder("test-api")
        builder.uvicorn.with_ssl("/key.pem", "/cert.pem").done()

        assert builder._uvicorn_config.ssl_keyfile == "/key.pem"
        assert builder._uvicorn_config.ssl_certfile == "/cert.pem"

    def test_access_log_configuration(self, mock_fastapi):
        """Test access log configuration."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        builder = ServerBuilder("test-api")
        builder.uvicorn.with_access_log(True).done()

        assert builder._uvicorn_config.access_log is True

    def test_full_config(self, mock_fastapi):
        """Test setting full UvicornConfig."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        config = UvicornConfig(workers=8, log_level="info")

        builder = ServerBuilder("test-api")
        builder.uvicorn.with_config(config).done()

        assert builder._uvicorn_config is config

    def test_timeout_keep_alive(self, mock_fastapi):
        """Test timeout_keep_alive configuration."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        builder = ServerBuilder("test-api")
        builder.uvicorn.with_timeout_keep_alive(30).done()

        assert builder._uvicorn_config.timeout_keep_alive == 30

    def test_limit_concurrency(self, mock_fastapi):
        """Test limit_concurrency configuration."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        builder = ServerBuilder("test-api")
        builder.uvicorn.with_limit_concurrency(100).done()

        assert builder._uvicorn_config.limit_concurrency == 100

    def test_limit_max_requests(self, mock_fastapi):
        """Test limit_max_requests configuration."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        builder = ServerBuilder("test-api")
        builder.uvicorn.with_limit_max_requests(1000).done()

        assert builder._uvicorn_config.limit_max_requests == 1000

    def test_backlog(self, mock_fastapi):
        """Test backlog configuration."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        builder = ServerBuilder("test-api")
        builder.uvicorn.with_backlog(4096).done()

        assert builder._uvicorn_config.backlog == 4096


@pytest.mark.unit
class TestServerBuilderLifecycleCallbacks:
    """Tests for ServerBuilder lifecycle callback methods."""

    @pytest.fixture
    def mock_fastapi(self):
        """Mock FastAPI to avoid import dependency."""
        with patch("appinfra.app.fastapi.builder.server.FastAPIAdapter") as mock:
            mock.return_value = MagicMock()
            yield mock

    def test_with_on_startup(self, mock_fastapi):
        """Test with_on_startup adds callback."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        async def startup(app):
            pass

        builder = ServerBuilder("test-api").with_on_startup(startup, name="init")

        assert len(builder._startup_callbacks) == 1
        assert builder._startup_callbacks[0].callback is startup
        assert builder._startup_callbacks[0].name == "init"

    def test_with_on_shutdown(self, mock_fastapi):
        """Test with_on_shutdown adds callback."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        async def shutdown(app):
            pass

        builder = ServerBuilder("test-api").with_on_shutdown(shutdown)

        assert len(builder._shutdown_callbacks) == 1
        assert builder._shutdown_callbacks[0].callback is shutdown

    def test_with_lifespan(self, mock_fastapi):
        """Test with_lifespan sets lifespan."""
        from contextlib import asynccontextmanager

        from appinfra.app.fastapi.builder.server import ServerBuilder

        @asynccontextmanager
        async def lifespan(app):
            yield

        builder = ServerBuilder("test-api").with_lifespan(lifespan)

        assert builder._lifespan is not None
        assert builder._lifespan.lifespan is lifespan

    def test_with_on_request(self, mock_fastapi):
        """Test with_on_request adds callback."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        async def on_request(request):
            pass

        builder = ServerBuilder("test-api").with_on_request(on_request)

        assert len(builder._request_callbacks) == 1
        assert builder._request_callbacks[0].callback is on_request

    def test_with_on_response(self, mock_fastapi):
        """Test with_on_response adds callback."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        async def on_response(request, response):
            return response

        builder = ServerBuilder("test-api").with_on_response(on_response)

        assert len(builder._response_callbacks) == 1
        assert builder._response_callbacks[0].callback is on_response

    def test_with_on_exception(self, mock_fastapi):
        """Test with_on_exception adds callback."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        async def on_exception(request, exc):
            pass

        builder = ServerBuilder("test-api").with_on_exception(on_exception)

        assert len(builder._exception_callbacks) == 1
        assert builder._exception_callbacks[0].callback is on_exception

    def test_lifecycle_callbacks_chaining(self, mock_fastapi):
        """Test lifecycle callbacks can be chained."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        async def startup(app):
            pass

        async def shutdown(app):
            pass

        async def on_request(request):
            pass

        builder = (
            ServerBuilder("test-api")
            .with_on_startup(startup)
            .with_on_shutdown(shutdown)
            .with_on_request(on_request)
            .with_port(8080)
        )

        assert len(builder._startup_callbacks) == 1
        assert len(builder._shutdown_callbacks) == 1
        assert len(builder._request_callbacks) == 1
        assert builder._port == 8080

    def test_configure_adapter_passes_lifecycle_callbacks(self, mock_fastapi):
        """Test _configure_adapter passes lifecycle callbacks to adapter."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        async def startup(app):
            pass

        async def on_request(request):
            pass

        builder = (
            ServerBuilder("test-api")
            .with_on_startup(startup)
            .with_on_request(on_request)
        )

        with (
            patch("appinfra.app.fastapi.builder.server.FastAPIAdapter") as mock_adapter,
            patch("appinfra.app.fastapi.builder.server.Server"),
        ):
            builder.build()

            # Verify adapter methods were called
            adapter = mock_adapter.return_value
            adapter.add_startup_callback.assert_called_once()
            adapter.add_request_callback.assert_called_once()
