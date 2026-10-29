# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for Server runtime."""

import multiprocessing as mp
import sys
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from appinfra.app.fastapi.config.api import ApiConfig
from appinfra.app.fastapi.config.ipc import IPCConfig


@pytest.mark.unit
class TestServer:
    """Tests for Server class."""

    @pytest.fixture
    def mock_lg(self):
        """Mock logger."""
        return MagicMock()

    @pytest.fixture
    def mock_dependencies(self):
        """Mock FastAPI dependencies."""
        with (
            patch("appinfra.app.fastapi.runtime.server.FASTAPI_AVAILABLE", True),
            patch("appinfra.app.fastapi.runtime.server.FastAPI") as mock_fastapi,
        ):
            mock_fastapi.return_value = MagicMock()
            yield mock_fastapi

    def test_initialization(self, mock_dependencies, mock_lg):
        """Test server initialization."""
        from appinfra.app.fastapi.runtime.server import Server

        config = ApiConfig()
        adapter = MagicMock()

        server = Server(mock_lg, name="test-server", config=config, adapter=adapter)

        assert server.name == "test-server"
        assert server.config is config
        assert server._adapter is adapter
        assert server._request_q is None
        assert server._response_q is None

    def test_initialization_with_queues(self, mock_dependencies, mock_lg):
        """Test server initialization with IPC queues."""
        from appinfra.app.fastapi.runtime.server import Server

        request_q: mp.Queue = mp.Queue()
        response_q: mp.Queue = mp.Queue()

        server = Server(
            mock_lg,
            name="test-server",
            config=ApiConfig(),
            adapter=MagicMock(),
            request_q=request_q,
            response_q=response_q,
        )

        assert server._request_q is request_q
        assert server._response_q is response_q

    def test_is_subprocess_mode_false(self, mock_dependencies, mock_lg):
        """Test is_subprocess_mode when no queues configured."""
        from appinfra.app.fastapi.runtime.server import Server

        server = Server(mock_lg, name="test", config=ApiConfig(), adapter=MagicMock())

        assert server.is_subprocess_mode is False

    def test_is_subprocess_mode_true(self, mock_dependencies, mock_lg):
        """Test is_subprocess_mode when queues configured."""
        from appinfra.app.fastapi.runtime.server import Server

        server = Server(
            mock_lg,
            name="test",
            config=ApiConfig(),
            adapter=MagicMock(),
            request_q=mp.Queue(),
            response_q=mp.Queue(),
        )

        assert server.is_subprocess_mode is True

    def test_is_running_no_subprocess(self, mock_dependencies, mock_lg):
        """Test is_running when no subprocess started."""
        from appinfra.app.fastapi.runtime.server import Server

        server = Server(mock_lg, name="test", config=ApiConfig(), adapter=MagicMock())

        assert server.is_running is False

    def test_request_queue_property(self, mock_dependencies, mock_lg):
        """Test request_queue property."""
        from appinfra.app.fastapi.runtime.server import Server

        request_q: mp.Queue = mp.Queue()
        server = Server(
            mock_lg,
            name="test",
            config=ApiConfig(),
            adapter=MagicMock(),
            request_q=request_q,
            response_q=mp.Queue(),
        )

        assert server.request_queue is request_q

    def test_response_queue_property(self, mock_dependencies, mock_lg):
        """Test response_queue property."""
        from appinfra.app.fastapi.runtime.server import Server

        response_q: mp.Queue = mp.Queue()
        server = Server(
            mock_lg,
            name="test",
            config=ApiConfig(),
            adapter=MagicMock(),
            request_q=mp.Queue(),
            response_q=response_q,
        )

        assert server.response_queue is response_q

    def test_app_property_builds_on_demand(self, mock_dependencies, mock_lg):
        """Test app property builds app on first access."""
        from appinfra.app.fastapi.runtime.server import Server

        adapter = MagicMock()
        adapter.build.return_value = MagicMock()

        server = Server(mock_lg, name="test", config=ApiConfig(), adapter=adapter)

        app1 = server.app
        app2 = server.app

        # Should only build once
        adapter.build.assert_called_once()
        assert app1 is app2


@pytest.mark.unit
class TestServerSubprocessMode:
    """Tests for Server subprocess mode."""

    @pytest.fixture
    def mock_lg(self):
        """Mock logger."""
        lg = MagicMock()
        lg.queue_config.return_value = {"level": "info", "queue": MagicMock()}
        return lg

    @pytest.fixture
    def mock_dependencies(self):
        """Mock dependencies."""
        with (
            patch("appinfra.app.fastapi.runtime.server.FASTAPI_AVAILABLE", True),
            patch("appinfra.app.fastapi.runtime.server.FastAPI"),
            patch(
                "appinfra.app.fastapi.runtime.server.ProcessRunner"
            ) as mock_runner_cls,
        ):
            mock_runner = MagicMock()
            mock_runner_cls.return_value = mock_runner
            yield {"ProcessRunner": mock_runner_cls, "instance": mock_runner}

    def test_start_subprocess_requires_subprocess_mode(
        self, mock_dependencies, mock_lg
    ):
        """Test start_subprocess raises if not in subprocess mode."""
        from appinfra.app.fastapi.runtime.server import Server

        server = Server(mock_lg, name="test", config=ApiConfig(), adapter=MagicMock())

        with pytest.raises(RuntimeError, match="subprocess mode"):
            server.start_subprocess()

    def test_start_subprocess_raises_if_running(self, mock_dependencies, mock_lg):
        """Test start_subprocess raises if already running."""
        from appinfra.app.fastapi.runtime.server import Server

        server = Server(
            mock_lg,
            name="test",
            config=ApiConfig(),
            adapter=MagicMock(),
            request_q=mp.Queue(),
            response_q=mp.Queue(),
        )

        mock_dependencies["instance"].is_alive.return_value = True
        server._runner = mock_dependencies["instance"]

        with pytest.raises(RuntimeError, match="already running"):
            server.start_subprocess()

    def test_start_subprocess_creates_runner(self, mock_dependencies, mock_lg):
        """Test start_subprocess creates ProcessRunner."""
        from appinfra.app.fastapi.runtime.server import Server

        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_dependencies["instance"].process = mock_proc

        server = Server(
            mock_lg,
            name="test",
            config=ApiConfig(),
            adapter=MagicMock(),
            request_q=mp.Queue(),
            response_q=mp.Queue(),
        )

        proc = server.start_subprocess()

        assert proc is mock_proc
        mock_dependencies["ProcessRunner"].assert_called_once()
        mock_dependencies["instance"].start.assert_called_once()
        mock_dependencies["instance"].wait_healthy.assert_called_once()

    @pytest.mark.parametrize("start_method", [None, "spawn"])
    def test_start_subprocess_passes_start_method(
        self, mock_dependencies, mock_lg, start_method
    ):
        """The configured start method reaches the ProcessRunner (None: the default)."""
        from appinfra.app.fastapi.runtime.server import Server

        mock_dependencies["instance"].process = MagicMock(pid=12345)
        server = Server(
            mock_lg,
            name="test",
            config=ApiConfig(start_method=start_method),
            adapter=MagicMock(),
            request_q=mp.Queue(),
            response_q=mp.Queue(),
        )

        server.start_subprocess()

        kwargs = mock_dependencies["ProcessRunner"].call_args.kwargs
        assert kwargs["start_method"] == start_method

    @pytest.mark.parametrize(
        ("max_restarts", "max_retries"), [(0, sys.maxsize), (3, 3)]
    )
    def test_start_subprocess_maps_max_restarts(
        self, mock_dependencies, mock_lg, max_restarts, max_retries
    ):
        """max_restarts=0 means unlimited restarts; other values pass through."""
        from appinfra.app.fastapi.runtime.server import Server

        mock_dependencies["instance"].process = MagicMock(pid=12345)
        server = Server(
            mock_lg,
            name="test",
            config=ApiConfig(max_restarts=max_restarts),
            adapter=MagicMock(),
            request_q=mp.Queue(),
            response_q=mp.Queue(),
        )

        server.start_subprocess()

        policy = mock_dependencies["ProcessRunner"].call_args.kwargs["policy"]
        assert policy.max_retries == max_retries

    def test_start_subprocess_sets_default_ipc_config(self, mock_dependencies, mock_lg):
        """Test start_subprocess sets default IPCConfig if not set."""
        from appinfra.app.fastapi.runtime.server import Server

        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_dependencies["instance"].process = mock_proc

        config = ApiConfig()
        assert config.ipc is None

        server = Server(
            mock_lg,
            name="test",
            config=config,
            adapter=MagicMock(),
            request_q=mp.Queue(),
            response_q=mp.Queue(),
        )

        server.start_subprocess()

        assert server._config.ipc is not None
        assert isinstance(server._config.ipc, IPCConfig)

    def test_start_subprocess_starts_monitor_when_auto_restart(
        self, mock_dependencies, mock_lg
    ):
        """Test start_subprocess starts monitor thread when auto_restart is True."""
        from appinfra.app.fastapi.runtime.server import (
            PROCESS_MONITOR_INTERVAL,
            Server,
        )

        mock_proc = MagicMock()
        mock_dependencies["instance"].process = mock_proc

        server = Server(
            mock_lg,
            name="test",
            config=ApiConfig(auto_restart=True),
            adapter=MagicMock(),
            request_q=mp.Queue(),
            response_q=mp.Queue(),
        )

        server.start_subprocess()

        mock_dependencies["instance"].start_monitor.assert_called_once_with(
            interval=PROCESS_MONITOR_INTERVAL
        )

    def test_start_subprocess_no_monitor_when_auto_restart_disabled(
        self, mock_dependencies, mock_lg
    ):
        """Test start_subprocess doesn't start monitor when auto_restart is False."""
        from appinfra.app.fastapi.runtime.server import Server

        mock_proc = MagicMock()
        mock_dependencies["instance"].process = mock_proc

        server = Server(
            mock_lg,
            name="test",
            config=ApiConfig(auto_restart=False),
            adapter=MagicMock(),
            request_q=mp.Queue(),
            response_q=mp.Queue(),
        )

        server.start_subprocess()

        mock_dependencies["instance"].start_monitor.assert_not_called()

    def test_stop_clears_runner(self, mock_dependencies, mock_lg):
        """Test stop clears runner."""
        from appinfra.app.fastapi.runtime.server import Server

        server = Server(
            mock_lg,
            name="test",
            config=ApiConfig(),
            adapter=MagicMock(),
            request_q=mp.Queue(),
            response_q=mp.Queue(),
        )

        server._runner = mock_dependencies["instance"]

        server.stop()

        mock_dependencies["instance"].stop.assert_called_once()
        assert server._runner is None

    def test_stop_does_nothing_if_not_running(self, mock_dependencies, mock_lg):
        """Test stop does nothing if subprocess not running."""
        from appinfra.app.fastapi.runtime.server import Server

        server = Server(mock_lg, name="test", config=ApiConfig(), adapter=MagicMock())

        # Should not raise
        server.stop()


@pytest.mark.unit
class TestServerValidation:
    """Tests for Server validation methods."""

    @pytest.fixture
    def mock_lg(self):
        """Mock logger."""
        return MagicMock()

    @pytest.fixture
    def mock_dependencies(self):
        """Mock dependencies."""
        with (
            patch("appinfra.app.fastapi.runtime.server.FASTAPI_AVAILABLE", True),
            patch("appinfra.app.fastapi.runtime.server.FastAPI"),
        ):
            yield

    def test_validate_subprocess_mode_not_configured(self, mock_dependencies, mock_lg):
        """Test _validate_subprocess_mode raises if not configured."""
        from appinfra.app.fastapi.runtime.server import Server

        server = Server(mock_lg, name="test", config=ApiConfig(), adapter=MagicMock())

        with pytest.raises(RuntimeError, match="subprocess mode"):
            server._validate_subprocess_mode()

    def test_validate_subprocess_mode_already_running(self, mock_dependencies, mock_lg):
        """Test _validate_subprocess_mode raises if already running."""
        from appinfra.app.fastapi.runtime.server import Server

        server = Server(
            mock_lg,
            name="test",
            config=ApiConfig(),
            adapter=MagicMock(),
            request_q=mp.Queue(),
            response_q=mp.Queue(),
        )

        mock_runner = MagicMock()
        mock_runner.is_alive.return_value = True
        server._runner = mock_runner

        with pytest.raises(RuntimeError, match="already running"):
            server._validate_subprocess_mode()

    def test_validate_subprocess_mode_passes(self, mock_dependencies, mock_lg):
        """Test _validate_subprocess_mode passes when valid."""
        from appinfra.app.fastapi.runtime.server import Server

        server = Server(
            mock_lg,
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
    def mock_lg(self):
        """Mock logger."""
        return MagicMock()

    @pytest.fixture
    def mock_dependencies(self):
        """Mock dependencies."""
        with (
            patch("appinfra.app.fastapi.runtime.server.FASTAPI_AVAILABLE", True),
            patch("appinfra.app.fastapi.runtime.server.FastAPI"),
        ):
            yield

    def test_is_running_true_when_alive(self, mock_dependencies, mock_lg):
        """Test is_running returns True when subprocess is alive."""
        from appinfra.app.fastapi.runtime.server import Server

        server = Server(
            mock_lg,
            name="test",
            config=ApiConfig(),
            adapter=MagicMock(),
            request_q=mp.Queue(),
            response_q=mp.Queue(),
        )

        mock_runner = MagicMock()
        mock_runner.is_alive.return_value = True
        server._runner = mock_runner

        assert server.is_running is True

    def test_start_subprocess_mode(self, mock_dependencies, mock_lg):
        """Test start() in subprocess mode blocks until process exits."""
        from appinfra.app.fastapi.runtime.server import Server

        server = Server(
            mock_lg,
            name="test",
            config=ApiConfig(),
            adapter=MagicMock(),
            request_q=mp.Queue(),
            response_q=mp.Queue(),
        )

        # Mock start_subprocess and _runner to simulate exit
        mock_runner = MagicMock()
        # Simulate process exiting after first check
        mock_runner.is_alive.side_effect = [True, False]
        mock_runner.monitoring = False  # no auto-restart

        with (
            patch.object(server, "start_subprocess"),
            patch("time.sleep"),
        ):
            server._runner = mock_runner
            server.start()

            # Should have checked is_alive until it returned False
            assert mock_runner.is_alive.call_count == 2

    def test_start_waits_while_a_restart_is_pending(self, mock_dependencies, mock_lg):
        """A dead process with restarts left keeps start() blocking until none are."""
        from appinfra.app.fastapi.runtime.server import Server

        server = Server(
            mock_lg,
            name="test",
            config=ApiConfig(),
            adapter=MagicMock(),
            request_q=mp.Queue(),
            response_q=mp.Queue(),
        )
        runner = MagicMock()
        runner.is_alive.return_value = False
        runner.monitoring = True
        type(runner).can_restart = PropertyMock(side_effect=[True, True, True, False])

        with patch.object(server, "start_subprocess"), patch("time.sleep") as sleep:
            server._runner = runner
            server.start()

        assert sleep.call_count == 3

    @pytest.mark.parametrize(
        ("monitoring", "can_restart"), [(False, True), (True, False)]
    )
    def test_start_returns_when_no_restart_can_follow(
        self, mock_dependencies, mock_lg, monitoring, can_restart
    ):
        """No monitor, or no restarts left: start() returns once the process is gone."""
        from appinfra.app.fastapi.runtime.server import Server

        server = Server(
            mock_lg,
            name="test",
            config=ApiConfig(),
            adapter=MagicMock(),
            request_q=mp.Queue(),
            response_q=mp.Queue(),
        )
        runner = MagicMock()
        runner.is_alive.return_value = False
        runner.monitoring = monitoring
        runner.can_restart = can_restart

        with patch.object(server, "start_subprocess"), patch("time.sleep") as sleep:
            server._runner = runner
            server.start()

        assert sleep.call_count == 0

    def test_start_direct_mode(self, mock_dependencies, mock_lg):
        """Test start() in direct mode."""
        from appinfra.app.fastapi.runtime.server import Server

        server = Server(
            mock_lg,
            name="test",
            config=ApiConfig(),
            adapter=MagicMock(),
        )

        with patch.object(server, "_run_direct") as mock_run:
            server.start()
            mock_run.assert_called_once()

    def test_run_direct(self, mock_dependencies, mock_lg):
        """Test _run_direct runs uvicorn."""
        import sys
        from unittest.mock import MagicMock

        from appinfra.app.fastapi.runtime.server import Server

        mock_adapter = MagicMock()
        mock_app = MagicMock()
        mock_adapter.build.return_value = mock_app

        server = Server(
            mock_lg,
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


@pytest.mark.unit
class TestUvicornServiceSetup:
    """Tests for UvicornService.setup() validation."""

    def test_rejects_multiple_workers(self):
        """workers != 1 fails setup: the subprocess passes uvicorn an app object."""
        from appinfra.app.fastapi.config.uvicorn import UvicornConfig
        from appinfra.app.fastapi.errors import ConfigError
        from appinfra.app.fastapi.runtime.service import UvicornService

        config = ApiConfig(uvicorn=UvicornConfig(workers=4))
        service = UvicornService(MagicMock(), MagicMock(), config)

        with pytest.raises(ConfigError, match="workers"):
            service.setup()

    def test_accepts_single_worker(self):
        """The default single worker passes setup."""
        from appinfra.app.fastapi.runtime.service import UvicornService

        UvicornService(MagicMock(), MagicMock(), ApiConfig()).setup()
