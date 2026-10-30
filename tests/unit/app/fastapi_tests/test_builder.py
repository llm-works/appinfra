# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for FastAPI ServerBuilder."""

import multiprocessing as mp
from unittest.mock import MagicMock, patch

import pytest

from appinfra.app.fastapi.config.api import ApiConfig
from appinfra.app.fastapi.config.ipc import IPCConfig
from appinfra.app.fastapi.config.uvicorn import UvicornConfig


@pytest.fixture
def mock_lg():
    """Mock logger for ServerBuilder."""
    return MagicMock()


@pytest.mark.unit
class TestServerBuilder:
    """Tests for ServerBuilder fluent interface."""

    @pytest.fixture
    def mock_fastapi(self):
        """Mock FastAPI to avoid import dependency."""
        with patch("appinfra.app.fastapi.builder.server.FastAPIAdapter") as mock:
            mock.return_value = MagicMock()
            yield mock

    def test_basic_configuration(self, mock_fastapi, mock_lg):
        """Test basic server configuration."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        builder = ServerBuilder(mock_lg, "test-api")
        builder.with_host("127.0.0.1").with_port(9000)

        assert builder._api.host == "127.0.0.1"
        assert builder._api.port == 9000

    def test_metadata_configuration(self, mock_fastapi, mock_lg):
        """Test API metadata configuration."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        builder = (
            ServerBuilder(mock_lg, "test-api")
            .with_title("My API")
            .with_description("Test description")
            .with_version("2.0.0")
        )

        assert builder._api.title == "My API"
        assert builder._api.description == "Test description"
        assert builder._api.version == "2.0.0"

    def test_docs_off_by_default(self, mock_fastapi, mock_lg):
        """A new builder serves no docs pages and no OpenAPI schema."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        api = ServerBuilder(mock_lg, "test-api")._api
        assert (api.docs_url, api.redoc_url, api.openapi_url) == (None, None, None)

    def test_with_docs_toggles_all_three(self, mock_fastapi, mock_lg):
        """with_docs() sets FastAPI's default paths; with_docs(False) clears them."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        builder = ServerBuilder(mock_lg, "test-api").with_docs()
        api = builder._api
        assert (api.docs_url, api.redoc_url, api.openapi_url) == (
            "/docs",
            "/redoc",
            "/openapi.json",
        )

        builder.with_docs(False)
        assert (api.docs_url, api.redoc_url, api.openapi_url) == (None, None, None)

    def test_timeout_configuration(self, mock_fastapi, mock_lg):
        """Test timeout configuration."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        builder = ServerBuilder(mock_lg, "test-api").with_timeout(120.0)
        assert builder._api.response_timeout == 120.0

    def test_with_config(self, mock_fastapi, mock_lg):
        """Test bulk configuration via ApiConfig."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        config = ApiConfig(
            host="192.168.1.1",
            port=8080,
            title="Bulk Config API",
            version="3.0.0",
            auto_restart=False,
        )

        builder = ServerBuilder(mock_lg, "test-api").with_config(config)

        assert builder._api.host == "192.168.1.1"
        assert builder._api.port == 8080
        assert builder._api.title == "Bulk Config API"
        assert builder._api.version == "3.0.0"
        assert builder._api.auto_restart is False

    def test_fluent_chaining(self, mock_fastapi, mock_lg):
        """Test method chaining returns builder."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        builder = ServerBuilder(mock_lg, "test-api")

        result = builder.with_host("localhost")
        assert result is builder

        result = builder.with_port(8000)
        assert result is builder

        result = builder.with_title("API")
        assert result is builder

    def test_with_config_including_ipc(self, mock_fastapi, mock_lg):
        """Test with_config with IPC configuration."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        config = ApiConfig(
            host="192.168.1.1",
            port=8080,
            ipc=IPCConfig(max_pending=200),
        )

        builder = ServerBuilder(mock_lg, "test-api").with_config(config)

        assert builder._api.ipc is not None
        assert builder._api.ipc.max_pending == 200

    def test_build_creates_server(self, mock_fastapi, mock_lg):
        """Test build() creates a Server instance."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        def handler():
            return {"status": "ok"}

        builder = (
            ServerBuilder(mock_lg, "test-api")
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
            assert call_kwargs["lg"] is mock_lg
            assert call_kwargs["name"] == "test-api"
            assert call_kwargs["config"].host == "127.0.0.1"
            assert call_kwargs["config"].port == 9000

    def test_build_with_routers_middleware_handlers(self, mock_fastapi, mock_lg):
        """Test build() with routers, middleware, and exception handlers."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        mock_router = MagicMock()

        class CustomMiddleware:
            pass

        def error_handler(request, exc):
            pass

        builder = (
            ServerBuilder(mock_lg, "test-api")
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

    def test_add_route(self, mock_fastapi, mock_lg):
        """Test adding a route."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        def handler():
            return {"status": "ok"}

        builder = ServerBuilder(mock_lg, "test-api")
        builder.routes.with_route("/health", handler).done()

        assert len(builder._defs.routes) == 1
        assert builder._defs.routes[0].path == "/health"
        assert builder._defs.routes[0].handler is handler
        assert builder._defs.routes[0].methods == ["GET"]

    def test_add_route_with_methods(self, mock_fastapi, mock_lg):
        """Test adding a route with custom methods."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        def handler():
            pass

        builder = ServerBuilder(mock_lg, "test-api")
        builder.routes.with_route("/data", handler, methods=["POST", "PUT"]).done()

        assert builder._defs.routes[0].methods == ["POST", "PUT"]

    def test_add_multiple_routes(self, mock_fastapi, mock_lg):
        """Test adding multiple routes."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        builder = ServerBuilder(mock_lg, "test-api")
        builder.routes.with_route("/a", lambda: None).with_route(
            "/b", lambda: None
        ).done()

        assert len(builder._defs.routes) == 2

    def test_cors_configuration(self, mock_fastapi, mock_lg):
        """Test CORS configuration."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        builder = ServerBuilder(mock_lg, "test-api")
        builder.routes.with_cors(
            origins=["http://localhost:3000"],
            allow_credentials=True,
            allow_methods=["GET", "POST"],
        ).done()

        assert builder._defs.cors is not None
        assert builder._defs.cors.origins == ["http://localhost:3000"]
        assert builder._defs.cors.allow_credentials is True
        assert builder._defs.cors.allow_methods == ["GET", "POST"]

    def test_done_returns_builder(self, mock_fastapi, mock_lg):
        """Test that done() returns parent builder."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        builder = ServerBuilder(mock_lg, "test-api")
        result = builder.routes.done()
        assert result is builder

    def test_add_router(self, mock_fastapi, mock_lg):
        """Test adding a router."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        mock_router = MagicMock()
        builder = ServerBuilder(mock_lg, "test-api")
        builder.routes.with_router(mock_router, prefix="/api/v1", tags=["v1"]).done()

        assert len(builder._defs.routers) == 1
        assert builder._defs.routers[0].router is mock_router
        assert builder._defs.routers[0].prefix == "/api/v1"
        assert builder._defs.routers[0].tags == ["v1"]

    def test_add_exception_handler(self, mock_fastapi, mock_lg):
        """Test adding an exception handler."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        def handler(request, exc):
            pass

        builder = ServerBuilder(mock_lg, "test-api")
        builder.routes.with_exception_handler(ValueError, handler).done()

        assert len(builder._defs.exception_handlers) == 1
        assert builder._defs.exception_handlers[0].exc_class is ValueError
        assert builder._defs.exception_handlers[0].handler is handler

    def test_add_middleware(self, mock_fastapi, mock_lg):
        """Test adding middleware."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        class CustomMiddleware:
            pass

        builder = ServerBuilder(mock_lg, "test-api")
        builder.routes.with_middleware(CustomMiddleware, timeout=30).done()

        assert len(builder._defs.middleware) == 1
        assert builder._defs.middleware[0].middleware_class is CustomMiddleware
        assert builder._defs.middleware[0].options == {"timeout": 30}


@pytest.mark.unit
class TestSubprocessConfigurer:
    """Tests for SubprocessConfigurer."""

    @pytest.fixture
    def mock_fastapi(self):
        """Mock FastAPI to avoid import dependency."""
        with patch("appinfra.app.fastapi.builder.server.FastAPIAdapter") as mock:
            mock.return_value = MagicMock()
            yield mock

    def test_ipc_configuration(self, mock_fastapi, mock_lg):
        """Test IPC queue configuration."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        request_q: mp.Queue = mp.Queue()
        response_q: mp.Queue = mp.Queue()

        builder = ServerBuilder(mock_lg, "test-api")
        builder.subprocess.with_ipc(request_q, response_q).done()

        assert builder._request_q is request_q
        assert builder._response_q is response_q

    def test_auto_restart_configuration(self, mock_fastapi, mock_lg):
        """Test auto-restart configuration."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        builder = ServerBuilder(mock_lg, "test-api")
        builder.subprocess.with_auto_restart(True).with_restart_delay(
            2.0
        ).with_max_restarts(10).done()

        assert builder._api.auto_restart is True
        assert builder._api.restart_delay == 2.0
        assert builder._api.max_restarts == 10

    def test_start_method_configuration(self, mock_fastapi, mock_lg):
        """with_start_method() sets the subprocess's multiprocessing start method."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        builder = ServerBuilder(mock_lg, "test-api")
        assert builder._api.start_method is None
        builder.subprocess.with_start_method("forkserver").done()

        assert builder._api.start_method == "forkserver"

    def test_toggling_auto_restart_keeps_delay_and_limit(self, mock_fastapi, mock_lg):
        """Each restart setting is its own setter; toggling one leaves the others."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        builder = ServerBuilder(mock_lg, "test-api").with_config(
            ApiConfig(restart_delay=5.0, max_restarts=20)
        )
        builder.subprocess.with_auto_restart(True).done()

        assert builder._api.restart_delay == 5.0
        assert builder._api.max_restarts == 20

    def test_log_file_configuration(self, mock_fastapi, mock_lg):
        """Test log file configuration."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        builder = ServerBuilder(mock_lg, "test-api")
        builder.subprocess.with_log_file("/var/log/server.log").done()

        assert builder._api.log_file == "/var/log/server.log"

    def test_ipc_stays_unset_until_an_ipc_setting(self, mock_fastapi, mock_lg):
        """Opening the facet keeps the direct-mode ipc value of None."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        builder = ServerBuilder(mock_lg, "test-api")
        builder.subprocess.with_log_file("/var/log/api.log").done()

        assert builder._api.ipc is None

        builder.subprocess.with_poll_interval(0.05).done()

        assert builder._api.ipc is not None
        assert builder._api.ipc.poll_interval == 0.05

    def test_ipc_config(self, mock_fastapi, mock_lg):
        """Test IPCConfig configuration."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        request_q: mp.Queue = mp.Queue()
        response_q: mp.Queue = mp.Queue()
        ipc_config = IPCConfig(max_pending=500, response_timeout=120.0)

        builder = ServerBuilder(mock_lg, "test-api")
        # Must enable subprocess mode with_ipc() before with_config() takes effect
        builder.subprocess.with_ipc(request_q, response_q).with_config(
            ipc_config
        ).done()

        assert builder._api.ipc == ipc_config
        assert builder._api.ipc is not ipc_config
        assert builder._api.ipc.max_pending == 500

    def test_poll_interval(self, mock_fastapi, mock_lg):
        """Test poll interval configuration."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        request_q: mp.Queue = mp.Queue()
        response_q: mp.Queue = mp.Queue()

        builder = ServerBuilder(mock_lg, "test-api")
        builder.subprocess.with_ipc(request_q, response_q).with_poll_interval(
            0.05
        ).done()

        assert builder._api.ipc.poll_interval == 0.05

    def test_reopening_facet_keeps_earlier_settings(self, mock_fastapi, mock_lg):
        """Log file set in one opening survives auto-restart set in another."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        builder = ServerBuilder(mock_lg, "test-api")
        builder.subprocess.with_log_file("/var/log/server.log").done()
        builder.subprocess.with_auto_restart(False).done()

        assert builder._api.log_file == "/var/log/server.log"
        assert builder._api.auto_restart is False
        assert builder._api.restart_delay == ApiConfig().restart_delay

    def test_response_timeout(self, mock_fastapi, mock_lg):
        """Test response timeout configuration."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        request_q: mp.Queue = mp.Queue()
        response_q: mp.Queue = mp.Queue()

        builder = ServerBuilder(mock_lg, "test-api")
        builder.subprocess.with_ipc(request_q, response_q).with_response_timeout(
            30.0
        ).done()

        assert builder._api.ipc.response_timeout == 30.0

    def test_max_pending(self, mock_fastapi, mock_lg):
        """Test max pending configuration."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        request_q: mp.Queue = mp.Queue()
        response_q: mp.Queue = mp.Queue()

        builder = ServerBuilder(mock_lg, "test-api")
        builder.subprocess.with_ipc(request_q, response_q).with_max_pending(200).done()

        assert builder._api.ipc.max_pending == 200

    def test_health_reporting(self, mock_fastapi, mock_lg):
        """Test health reporting configuration."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        request_q: mp.Queue = mp.Queue()
        response_q: mp.Queue = mp.Queue()

        builder = ServerBuilder(mock_lg, "test-api")
        builder.subprocess.with_ipc(request_q, response_q).with_health_reporting(
            False
        ).done()

        assert builder._api.ipc.enable_health_reporting is False


@pytest.mark.unit
class TestUvicornConfigurer:
    """Tests for UvicornConfigurer."""

    @pytest.fixture
    def mock_fastapi(self):
        """Mock FastAPI to avoid import dependency."""
        with patch("appinfra.app.fastapi.builder.server.FastAPIAdapter") as mock:
            mock.return_value = MagicMock()
            yield mock

    def test_workers_configuration(self, mock_fastapi, mock_lg):
        """Test workers configuration."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        builder = ServerBuilder(mock_lg, "test-api")
        builder.uvicorn.with_workers(4).done()

        assert builder._api.uvicorn.workers == 4

    def test_keyword_form_sets_fields_and_returns_parent(self, mock_fastapi, mock_lg):
        """Calling the block with keywords sets fields and returns the ServerBuilder."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        builder = ServerBuilder(mock_lg, "test-api")
        result = builder.uvicorn(workers=4, access_log=True, log_level="debug")

        assert result is builder
        assert builder._api.uvicorn.workers == 4
        assert builder._api.uvicorn.access_log is True
        assert builder._api.uvicorn.log_level == "debug"

    def test_reopening_facet_keeps_earlier_settings(self, mock_fastapi, mock_lg):
        """The facet is a view on the builder's config, so nothing resets."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        builder = ServerBuilder(mock_lg, "test-api")
        builder.uvicorn.with_workers(4).done()
        builder.uvicorn(access_log=False)

        assert builder._api.uvicorn.workers == 4
        assert builder._api.uvicorn.access_log is False
        assert builder._build_config().uvicorn.workers == 4

    def test_with_config_leaves_the_callers_object_alone(self, mock_fastapi, mock_lg):
        """Two builders can share one loaded config without cross-talk."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        shared = ApiConfig(port=8000)
        first = ServerBuilder(mock_lg, "a").with_config(shared).with_port(8001)
        second = ServerBuilder(mock_lg, "b").with_config(shared).with_port(8002)
        first.uvicorn.with_workers(9).done()

        assert shared.port == 8000
        assert shared.uvicorn.workers == 1
        assert first._build_config().port == 8001
        assert second._build_config().port == 8002
        assert second._build_config().uvicorn.workers == 1

    def test_built_config_is_independent_of_later_facet_calls(
        self, mock_fastapi, mock_lg
    ):
        """The built config owns its nested objects; the builder stays mutable."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        builder = ServerBuilder(mock_lg, "test-api")
        builder.uvicorn.with_workers(4).done()
        built = builder._build_config()

        builder.uvicorn.with_workers(8).done()

        assert built.uvicorn.workers == 4
        assert built.uvicorn is not builder._api.uvicorn

    def test_keyword_form_rejects_unknown_field(self, mock_fastapi, mock_lg):
        """A keyword that is not a UvicornConfig field is a TypeError."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        builder = ServerBuilder(mock_lg, "test-api")

        with pytest.raises(TypeError, match="unknown uvicorn field"):
            builder.uvicorn(threads=4)  # type: ignore[call-arg]

    def test_keyword_fields_match_uvicorn_config(self):
        """UvicornFields keys equal UvicornConfig's fields, so the two cannot drift."""
        from dataclasses import fields

        from appinfra.app.fastapi.builder.uvicorn import UvicornFields

        assert set(UvicornFields.__annotations__) == {
            f.name for f in fields(UvicornConfig)
        }

    def test_log_level_configuration(self, mock_fastapi, mock_lg):
        """Test log level configuration."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        builder = ServerBuilder(mock_lg, "test-api")
        builder.uvicorn.with_log_level("debug").done()

        assert builder._api.uvicorn.log_level == "debug"

    def test_ssl_configuration(self, mock_fastapi, mock_lg):
        """Test SSL configuration."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        builder = ServerBuilder(mock_lg, "test-api")
        builder.uvicorn.with_ssl("/key.pem", "/cert.pem").done()

        assert builder._api.uvicorn.ssl_keyfile == "/key.pem"
        assert builder._api.uvicorn.ssl_certfile == "/cert.pem"

    def test_access_log_configuration(self, mock_fastapi, mock_lg):
        """Test access log configuration."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        builder = ServerBuilder(mock_lg, "test-api")
        builder.uvicorn.with_access_log(True).done()

        assert builder._api.uvicorn.access_log is True

    def test_full_config(self, mock_fastapi, mock_lg):
        """Test setting full UvicornConfig."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        config = UvicornConfig(workers=8, log_level="info")

        builder = ServerBuilder(mock_lg, "test-api")
        builder.uvicorn.with_config(config).done()

        assert builder._api.uvicorn == config
        assert builder._api.uvicorn is not config

    def test_timeout_keep_alive(self, mock_fastapi, mock_lg):
        """Test timeout_keep_alive configuration."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        builder = ServerBuilder(mock_lg, "test-api")
        builder.uvicorn.with_timeout_keep_alive(30).done()

        assert builder._api.uvicorn.timeout_keep_alive == 30

    def test_limit_concurrency(self, mock_fastapi, mock_lg):
        """Test limit_concurrency configuration."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        builder = ServerBuilder(mock_lg, "test-api")
        builder.uvicorn.with_limit_concurrency(100).done()

        assert builder._api.uvicorn.limit_concurrency == 100

    def test_limit_max_requests(self, mock_fastapi, mock_lg):
        """Test limit_max_requests configuration."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        builder = ServerBuilder(mock_lg, "test-api")
        builder.uvicorn.with_limit_max_requests(1000).done()

        assert builder._api.uvicorn.limit_max_requests == 1000

    def test_backlog(self, mock_fastapi, mock_lg):
        """Test backlog configuration."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        builder = ServerBuilder(mock_lg, "test-api")
        builder.uvicorn.with_backlog(4096).done()

        assert builder._api.uvicorn.backlog == 4096


@pytest.mark.unit
class TestServerBuilderLifecycleCallbacks:
    """Tests for ServerBuilder lifecycle callback methods."""

    @pytest.fixture
    def mock_fastapi(self):
        """Mock FastAPI to avoid import dependency."""
        with patch("appinfra.app.fastapi.builder.server.FastAPIAdapter") as mock:
            mock.return_value = MagicMock()
            yield mock

    def test_with_on_startup(self, mock_fastapi, mock_lg):
        """Test with_on_startup adds callback."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        async def startup(app):
            pass

        builder = ServerBuilder(mock_lg, "test-api").with_on_startup(
            startup, name="init"
        )

        assert len(builder._defs.startup_callbacks) == 1
        assert builder._defs.startup_callbacks[0].callback is startup
        assert builder._defs.startup_callbacks[0].name == "init"

    def test_with_on_shutdown(self, mock_fastapi, mock_lg):
        """Test with_on_shutdown adds callback."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        async def shutdown(app):
            pass

        builder = ServerBuilder(mock_lg, "test-api").with_on_shutdown(shutdown)

        assert len(builder._defs.shutdown_callbacks) == 1
        assert builder._defs.shutdown_callbacks[0].callback is shutdown

    def test_with_lifespan(self, mock_fastapi, mock_lg):
        """Test with_lifespan sets lifespan."""
        from contextlib import asynccontextmanager

        from appinfra.app.fastapi.builder.server import ServerBuilder

        @asynccontextmanager
        async def lifespan(app):
            yield

        builder = ServerBuilder(mock_lg, "test-api").with_lifespan(lifespan)

        assert builder._defs.lifespan is not None
        assert builder._defs.lifespan.lifespan is lifespan

    def test_with_on_request(self, mock_fastapi, mock_lg):
        """Test with_on_request adds callback."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        async def on_request(request):
            pass

        builder = ServerBuilder(mock_lg, "test-api").with_on_request(on_request)

        assert len(builder._defs.request_callbacks) == 1
        assert builder._defs.request_callbacks[0].callback is on_request

    def test_with_on_response(self, mock_fastapi, mock_lg):
        """Test with_on_response adds callback."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        async def on_response(request, response):
            return response

        builder = ServerBuilder(mock_lg, "test-api").with_on_response(on_response)

        assert len(builder._defs.response_callbacks) == 1
        assert builder._defs.response_callbacks[0].callback is on_response

    def test_with_on_exception(self, mock_fastapi, mock_lg):
        """Test with_on_exception adds callback."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        async def on_exception(request, exc):
            pass

        builder = ServerBuilder(mock_lg, "test-api").with_on_exception(on_exception)

        assert len(builder._defs.exception_callbacks) == 1
        assert builder._defs.exception_callbacks[0].callback is on_exception

    def test_lifecycle_callbacks_chaining(self, mock_fastapi, mock_lg):
        """Test lifecycle callbacks can be chained."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        async def startup(app):
            pass

        async def shutdown(app):
            pass

        async def on_request(request):
            pass

        builder = (
            ServerBuilder(mock_lg, "test-api")
            .with_on_startup(startup)
            .with_on_shutdown(shutdown)
            .with_on_request(on_request)
            .with_port(8080)
        )

        assert len(builder._defs.startup_callbacks) == 1
        assert len(builder._defs.shutdown_callbacks) == 1
        assert len(builder._defs.request_callbacks) == 1
        assert builder._api.port == 8080

    def test_configure_adapter_passes_lifecycle_callbacks(self, mock_fastapi, mock_lg):
        """Test _configure_adapter passes lifecycle callbacks to adapter."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        async def startup(app):
            pass

        async def on_request(request):
            pass

        builder = (
            ServerBuilder(mock_lg, "test-api")
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


_DOCS_PATHS = ["/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"]


@pytest.mark.unit
class TestDocsRoutes:
    """Docs and schema routes served by a real FastAPI app."""

    def _get_all(self, mock_lg, *, docs: bool | None) -> dict[str, int]:
        """Status of each docs path on a server built with the given setting."""
        from starlette.testclient import TestClient

        from appinfra.app.fastapi.builder.server import ServerBuilder

        builder = ServerBuilder(mock_lg, "test-api").routes.with_route(
            "/health", lambda: {"status": "ok"}
        )
        builder = builder.done()
        if docs is not None:
            builder.with_docs(docs)
        with TestClient(builder.build().app) as client:
            assert client.get("/health").status_code == 200
            return {path: client.get(path).status_code for path in _DOCS_PATHS}

    @pytest.mark.parametrize("docs", [None, False], ids=["default", "disabled"])
    def test_docs_routes_absent(self, mock_lg, docs):
        """Without with_docs(True) every docs path answers 404."""
        assert self._get_all(mock_lg, docs=docs) == dict.fromkeys(_DOCS_PATHS, 404)

    def test_docs_routes_served_when_enabled(self, mock_lg):
        """with_docs() serves the Swagger UI, ReDoc and the schema."""
        assert self._get_all(mock_lg, docs=True) == dict.fromkeys(_DOCS_PATHS, 200)
