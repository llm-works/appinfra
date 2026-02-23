"""Tests for Server runtime."""

import multiprocessing as mp
from unittest.mock import MagicMock, patch

import pytest

from appinfra.app.fastapi.config.api import ApiConfig
from appinfra.app.fastapi.config.ipc import IPCConfig


@pytest.mark.unit
class TestServer:
    """Tests for Server class."""

    @pytest.fixture
    def mock_dependencies(self):
        """Mock FastAPI dependencies."""
        with (
            patch("appinfra.app.fastapi.runtime.server.FASTAPI_AVAILABLE", True),
            patch("appinfra.app.fastapi.runtime.server.FastAPI") as mock_fastapi,
        ):
            mock_fastapi.return_value = MagicMock()
            yield mock_fastapi

    def test_initialization(self, mock_dependencies):
        """Test server initialization."""
        from appinfra.app.fastapi.runtime.server import Server

        config = ApiConfig()
        adapter = MagicMock()

        server = Server(name="test-server", config=config, adapter=adapter)

        assert server.name == "test-server"
        assert server.config is config
        assert server._adapter is adapter
        assert server._request_q is None
        assert server._response_q is None

    def test_initialization_with_queues(self, mock_dependencies):
        """Test server initialization with IPC queues."""
        from appinfra.app.fastapi.runtime.server import Server

        request_q: mp.Queue = mp.Queue()
        response_q: mp.Queue = mp.Queue()

        server = Server(
            name="test-server",
            config=ApiConfig(),
            adapter=MagicMock(),
            request_q=request_q,
            response_q=response_q,
        )

        assert server._request_q is request_q
        assert server._response_q is response_q

    def test_is_subprocess_mode_false(self, mock_dependencies):
        """Test is_subprocess_mode when no queues configured."""
        from appinfra.app.fastapi.runtime.server import Server

        server = Server(name="test", config=ApiConfig(), adapter=MagicMock())

        assert server.is_subprocess_mode is False

    def test_is_subprocess_mode_true(self, mock_dependencies):
        """Test is_subprocess_mode when queues configured."""
        from appinfra.app.fastapi.runtime.server import Server

        server = Server(
            name="test",
            config=ApiConfig(),
            adapter=MagicMock(),
            request_q=mp.Queue(),
            response_q=mp.Queue(),
        )

        assert server.is_subprocess_mode is True

    def test_is_running_no_subprocess(self, mock_dependencies):
        """Test is_running when no subprocess started."""
        from appinfra.app.fastapi.runtime.server import Server

        server = Server(name="test", config=ApiConfig(), adapter=MagicMock())

        assert server.is_running is False

    def test_request_queue_property(self, mock_dependencies):
        """Test request_queue property."""
        from appinfra.app.fastapi.runtime.server import Server

        request_q: mp.Queue = mp.Queue()
        server = Server(
            name="test",
            config=ApiConfig(),
            adapter=MagicMock(),
            request_q=request_q,
            response_q=mp.Queue(),
        )

        assert server.request_queue is request_q

    def test_response_queue_property(self, mock_dependencies):
        """Test response_queue property."""
        from appinfra.app.fastapi.runtime.server import Server

        response_q: mp.Queue = mp.Queue()
        server = Server(
            name="test",
            config=ApiConfig(),
            adapter=MagicMock(),
            request_q=mp.Queue(),
            response_q=response_q,
        )

        assert server.response_queue is response_q

    def test_app_property_builds_on_demand(self, mock_dependencies):
        """Test app property builds app on first access."""
        from appinfra.app.fastapi.runtime.server import Server

        adapter = MagicMock()
        adapter.build.return_value = MagicMock()

        server = Server(name="test", config=ApiConfig(), adapter=adapter)

        app1 = server.app
        app2 = server.app

        # Should only build once
        adapter.build.assert_called_once()
        assert app1 is app2


@pytest.mark.unit
class TestServerSubprocessMode:
    """Tests for Server subprocess mode."""

    @pytest.fixture
    def mock_dependencies(self):
        """Mock dependencies."""
        with (
            patch("appinfra.app.fastapi.runtime.server.FASTAPI_AVAILABLE", True),
            patch("appinfra.app.fastapi.runtime.server.FastAPI"),
            patch(
                "appinfra.app.fastapi.runtime.server.SubprocessManager"
            ) as mock_manager,
        ):
            mock_manager_instance = MagicMock()
            mock_manager.return_value = mock_manager_instance
            yield {"SubprocessManager": mock_manager, "instance": mock_manager_instance}

    def test_start_subprocess_requires_subprocess_mode(self, mock_dependencies):
        """Test start_subprocess raises if not in subprocess mode."""
        from appinfra.app.fastapi.runtime.server import Server

        server = Server(name="test", config=ApiConfig(), adapter=MagicMock())

        with pytest.raises(RuntimeError, match="subprocess mode"):
            server.start_subprocess()

    def test_start_subprocess_raises_if_running(self, mock_dependencies):
        """Test start_subprocess raises if already running."""
        from appinfra.app.fastapi.runtime.server import Server

        server = Server(
            name="test",
            config=ApiConfig(),
            adapter=MagicMock(),
            request_q=mp.Queue(),
            response_q=mp.Queue(),
        )

        mock_dependencies["instance"].is_alive.return_value = True
        server._subprocess_manager = mock_dependencies["instance"]

        with pytest.raises(RuntimeError, match="already running"):
            server.start_subprocess()

    def test_start_subprocess_creates_manager(self, mock_dependencies):
        """Test start_subprocess creates SubprocessManager."""
        from appinfra.app.fastapi.runtime.server import Server

        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_dependencies["instance"].start.return_value = mock_proc

        server = Server(
            name="test",
            config=ApiConfig(),
            adapter=MagicMock(),
            request_q=mp.Queue(),
            response_q=mp.Queue(),
        )

        proc = server.start_subprocess()

        assert proc is mock_proc
        mock_dependencies["SubprocessManager"].assert_called_once()
        mock_dependencies["instance"].start.assert_called_once()

    def test_start_subprocess_sets_default_ipc_config(self, mock_dependencies):
        """Test start_subprocess sets default IPCConfig if not set."""
        from appinfra.app.fastapi.runtime.server import Server

        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_dependencies["instance"].start.return_value = mock_proc

        config = ApiConfig()
        assert config.ipc is None

        server = Server(
            name="test",
            config=config,
            adapter=MagicMock(),
            request_q=mp.Queue(),
            response_q=mp.Queue(),
        )

        server.start_subprocess()

        assert server._config.ipc is not None
        assert isinstance(server._config.ipc, IPCConfig)

    def test_stop_clears_subprocess_manager(self, mock_dependencies):
        """Test stop clears subprocess manager."""
        from appinfra.app.fastapi.runtime.server import Server

        server = Server(
            name="test",
            config=ApiConfig(),
            adapter=MagicMock(),
            request_q=mp.Queue(),
            response_q=mp.Queue(),
        )

        server._subprocess_manager = mock_dependencies["instance"]

        server.stop()

        mock_dependencies["instance"].stop.assert_called_once()
        assert server._subprocess_manager is None

    def test_stop_does_nothing_if_not_running(self, mock_dependencies):
        """Test stop does nothing if subprocess not running."""
        from appinfra.app.fastapi.runtime.server import Server

        server = Server(name="test", config=ApiConfig(), adapter=MagicMock())

        # Should not raise
        server.stop()


@pytest.mark.unit
class TestServerValidation:
    """Tests for Server validation methods."""

    @pytest.fixture
    def mock_dependencies(self):
        """Mock dependencies."""
        with (
            patch("appinfra.app.fastapi.runtime.server.FASTAPI_AVAILABLE", True),
            patch("appinfra.app.fastapi.runtime.server.FastAPI"),
        ):
            yield

    def test_validate_subprocess_mode_not_configured(self, mock_dependencies):
        """Test _validate_subprocess_mode raises if not configured."""
        from appinfra.app.fastapi.runtime.server import Server

        server = Server(name="test", config=ApiConfig(), adapter=MagicMock())

        with pytest.raises(RuntimeError, match="subprocess mode"):
            server._validate_subprocess_mode()

    def test_validate_subprocess_mode_already_running(self, mock_dependencies):
        """Test _validate_subprocess_mode raises if already running."""
        from appinfra.app.fastapi.runtime.server import Server

        server = Server(
            name="test",
            config=ApiConfig(),
            adapter=MagicMock(),
            request_q=mp.Queue(),
            response_q=mp.Queue(),
        )

        mock_manager = MagicMock()
        mock_manager.is_alive.return_value = True
        server._subprocess_manager = mock_manager

        with pytest.raises(RuntimeError, match="already running"):
            server._validate_subprocess_mode()

    def test_validate_subprocess_mode_passes(self, mock_dependencies):
        """Test _validate_subprocess_mode passes when valid."""
        from appinfra.app.fastapi.runtime.server import Server

        server = Server(
            name="test",
            config=ApiConfig(),
            adapter=MagicMock(),
            request_q=mp.Queue(),
            response_q=mp.Queue(),
        )

        # Should not raise
        server._validate_subprocess_mode()


@pytest.mark.unit
class TestBuildUvicornLogConfig:
    """Tests for _build_uvicorn_log_config function."""

    @pytest.fixture
    def mock_dependencies(self):
        """Mock dependencies."""
        with (
            patch("appinfra.app.fastapi.runtime.server.FASTAPI_AVAILABLE", True),
            patch("appinfra.app.fastapi.runtime.server.FastAPI"),
        ):
            yield

    def test_default_config(self, mock_dependencies):
        """Test log config with defaults."""
        from appinfra.app.fastapi.runtime.server import _build_uvicorn_log_config

        config = ApiConfig()
        log_config = _build_uvicorn_log_config(config)

        assert log_config["version"] == 1
        assert log_config["disable_existing_loggers"] is True
        assert "uvicorn" in log_config["loggers"]
        assert log_config["loggers"]["uvicorn"]["level"] == "WARNING"

    def test_access_log_enabled(self, mock_dependencies):
        """Test log config with access logging enabled."""
        from appinfra.app.fastapi.config.uvicorn import UvicornConfig
        from appinfra.app.fastapi.runtime.server import _build_uvicorn_log_config

        config = ApiConfig(uvicorn=UvicornConfig(access_log=True, log_level="info"))
        log_config = _build_uvicorn_log_config(config)

        assert log_config["loggers"]["uvicorn.access"]["level"] == "INFO"


@pytest.mark.unit
class TestServerStart:
    """Tests for server start methods."""

    @pytest.fixture
    def mock_dependencies(self):
        """Mock dependencies."""
        with (
            patch("appinfra.app.fastapi.runtime.server.FASTAPI_AVAILABLE", True),
            patch("appinfra.app.fastapi.runtime.server.FastAPI"),
        ):
            yield

    def test_is_running_true_when_alive(self, mock_dependencies):
        """Test is_running returns True when subprocess is alive."""
        from appinfra.app.fastapi.runtime.server import Server

        server = Server(
            name="test",
            config=ApiConfig(),
            adapter=MagicMock(),
            request_q=mp.Queue(),
            response_q=mp.Queue(),
        )

        mock_manager = MagicMock()
        mock_manager.is_alive.return_value = True
        server._subprocess_manager = mock_manager

        assert server.is_running is True

    def test_start_subprocess_mode(self, mock_dependencies):
        """Test start() in subprocess mode."""
        from appinfra.app.fastapi.runtime.server import Server

        server = Server(
            name="test",
            config=ApiConfig(),
            adapter=MagicMock(),
            request_q=mp.Queue(),
            response_q=mp.Queue(),
        )

        # Mock start_subprocess to return a mock process
        mock_proc = MagicMock()
        with patch.object(server, "start_subprocess", return_value=mock_proc):
            server.start()

            mock_proc.join.assert_called_once()

    def test_start_direct_mode(self, mock_dependencies):
        """Test start() in direct mode."""
        from appinfra.app.fastapi.runtime.server import Server

        server = Server(
            name="test",
            config=ApiConfig(),
            adapter=MagicMock(),
        )

        with patch.object(server, "_run_direct") as mock_run:
            server.start()
            mock_run.assert_called_once()

    def test_run_direct(self, mock_dependencies):
        """Test _run_direct runs uvicorn."""
        import sys
        from unittest.mock import MagicMock

        from appinfra.app.fastapi.runtime.server import Server

        mock_adapter = MagicMock()
        mock_app = MagicMock()
        mock_adapter.build.return_value = mock_app

        server = Server(
            name="test",
            config=ApiConfig(host="127.0.0.1", port=9000),
            adapter=mock_adapter,
        )

        # uvicorn is lazily imported, so mock it in sys.modules
        mock_uvicorn = MagicMock()
        with patch.dict(sys.modules, {"uvicorn": mock_uvicorn}):
            server._run_direct()

            mock_uvicorn.run.assert_called_once()
            call_args = mock_uvicorn.run.call_args
            assert call_args[0][0] is mock_app
            assert call_args[1]["host"] == "127.0.0.1"
            assert call_args[1]["port"] == 9000
