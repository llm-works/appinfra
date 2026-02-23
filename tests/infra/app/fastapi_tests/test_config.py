"""Tests for FastAPI config dataclasses."""

import pytest

from appinfra.app.fastapi.config.api import ApiConfig
from appinfra.app.fastapi.config.ipc import IPCConfig
from appinfra.app.fastapi.config.uvicorn import UvicornConfig


@pytest.mark.unit
class TestUvicornConfig:
    """Tests for UvicornConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        config = UvicornConfig()
        assert config.workers == 1
        assert config.timeout_keep_alive == 5
        assert config.limit_concurrency is None
        assert config.limit_max_requests is None
        assert config.backlog == 2048
        assert config.log_level == "warning"
        assert config.access_log is False
        assert config.ssl_keyfile is None
        assert config.ssl_certfile is None

    def test_custom_values(self):
        """Test custom configuration values."""
        config = UvicornConfig(
            workers=4,
            timeout_keep_alive=30,
            limit_concurrency=100,
            limit_max_requests=1000,
            backlog=4096,
            log_level="debug",
            access_log=True,
            ssl_keyfile="/path/to/key.pem",
            ssl_certfile="/path/to/cert.pem",
        )
        assert config.workers == 4
        assert config.timeout_keep_alive == 30
        assert config.limit_concurrency == 100
        assert config.limit_max_requests == 1000
        assert config.backlog == 4096
        assert config.log_level == "debug"
        assert config.access_log is True
        assert config.ssl_keyfile == "/path/to/key.pem"
        assert config.ssl_certfile == "/path/to/cert.pem"

    def test_to_uvicorn_kwargs_minimal(self):
        """Test kwargs generation with defaults."""
        config = UvicornConfig()
        kwargs = config.to_uvicorn_kwargs()

        assert kwargs["workers"] == 1
        assert kwargs["timeout_keep_alive"] == 5
        assert kwargs["backlog"] == 2048
        assert kwargs["log_level"] == "warning"
        assert kwargs["access_log"] is False
        assert "limit_concurrency" not in kwargs  # None excluded
        assert "limit_max_requests" not in kwargs  # None excluded
        assert "ssl_keyfile" not in kwargs  # None excluded

    def test_to_uvicorn_kwargs_full(self):
        """Test kwargs generation with all options."""
        config = UvicornConfig(
            workers=4,
            timeout_keep_alive=30,
            limit_concurrency=100,
            limit_max_requests=1000,
            log_level="info",
            access_log=True,
            ssl_keyfile="/key.pem",
            ssl_certfile="/cert.pem",
        )
        kwargs = config.to_uvicorn_kwargs()

        assert kwargs["workers"] == 4
        assert kwargs["timeout_keep_alive"] == 30
        assert kwargs["limit_concurrency"] == 100
        assert kwargs["limit_max_requests"] == 1000
        assert kwargs["log_level"] == "info"
        assert kwargs["access_log"] is True
        assert kwargs["ssl_keyfile"] == "/key.pem"
        assert kwargs["ssl_certfile"] == "/cert.pem"


@pytest.mark.unit
class TestIPCConfig:
    """Tests for IPCConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        config = IPCConfig()
        assert config.poll_interval == 0.01
        assert config.response_timeout == 60.0
        assert config.max_pending == 100
        assert config.enable_health_reporting is True

    def test_custom_values(self):
        """Test custom configuration values."""
        config = IPCConfig(
            poll_interval=0.05,
            response_timeout=30.0,
            max_pending=50,
            enable_health_reporting=False,
        )
        assert config.poll_interval == 0.05
        assert config.response_timeout == 30.0
        assert config.max_pending == 50
        assert config.enable_health_reporting is False


@pytest.mark.unit
class TestApiConfig:
    """Tests for ApiConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        config = ApiConfig()
        assert config.host == "0.0.0.0"
        assert config.port == 8000
        assert config.title == "API Server"
        assert config.description == ""
        assert config.version == "0.1.0"
        assert config.response_timeout == 60.0
        assert config.log_file is None
        assert config.auto_restart is True
        assert config.restart_delay == 1.0
        assert config.max_restarts == 5
        assert config.uvicorn is not None
        assert config.ipc is None

    def test_custom_values(self):
        """Test custom configuration values."""
        uvicorn = UvicornConfig(workers=2)
        ipc = IPCConfig(max_pending=200)

        config = ApiConfig(
            host="127.0.0.1",
            port=9000,
            title="My API",
            description="Test API",
            version="1.0.0",
            response_timeout=120.0,
            log_file="/var/log/api.log",
            auto_restart=False,
            restart_delay=2.0,
            max_restarts=10,
            uvicorn=uvicorn,
            ipc=ipc,
        )

        assert config.host == "127.0.0.1"
        assert config.port == 9000
        assert config.title == "My API"
        assert config.description == "Test API"
        assert config.version == "1.0.0"
        assert config.response_timeout == 120.0
        assert config.log_file == "/var/log/api.log"
        assert config.auto_restart is False
        assert config.restart_delay == 2.0
        assert config.max_restarts == 10
        assert config.uvicorn.workers == 2
        assert config.ipc.max_pending == 200

    def test_default_uvicorn_config(self):
        """Test that default uvicorn config is created."""
        config = ApiConfig()
        assert isinstance(config.uvicorn, UvicornConfig)
        assert config.uvicorn.workers == 1
