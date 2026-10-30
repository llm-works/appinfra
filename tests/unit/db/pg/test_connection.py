# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Comprehensive tests for ConnectionManager.

Tests connection establishment, health checks, pool monitoring, and error handling.
"""

from unittest.mock import Mock, patch

import pytest
import sqlalchemy
import sqlalchemy.exc

from appinfra.db.pg.connection import ConnectionManager


@pytest.fixture
def mock_engine():
    """Create mock SQLAlchemy engine."""
    engine = Mock(spec=sqlalchemy.engine.Engine)
    engine.url = "postgresql://localhost/test"
    engine.connect = Mock()
    engine.pool = Mock()
    return engine


@pytest.fixture
def mock_logger():
    """Create mock logger."""
    logger = Mock()
    logger.trace = Mock()
    logger.debug = Mock()
    logger.info = Mock()
    logger.error = Mock()
    return logger


@pytest.fixture
def mock_cfg():
    """Create mock configuration with no attributes (getattr returns defaults)."""
    return Mock(spec=[])


@pytest.fixture
def conn_mgr(mock_engine, mock_logger, mock_cfg):
    """Create ConnectionManager instance."""
    return ConnectionManager(mock_engine, mock_logger, mock_cfg, readonly=False)


@pytest.mark.unit
class TestConnectionManagerInit:
    """Test ConnectionManager initialization."""

    def test_basic_initialization(self, mock_engine, mock_logger, mock_cfg):
        """Test manager initializes with required parameters."""
        mgr = ConnectionManager(mock_engine, mock_logger, mock_cfg, readonly=False)

        assert mgr._engine == mock_engine
        assert mgr._lg == mock_logger
        assert mgr._cfg == mock_cfg
        assert mgr._readonly is False

    def test_readonly_mode(self, mock_engine, mock_logger, mock_cfg):
        """Test readonly flag is set correctly."""
        mgr = ConnectionManager(mock_engine, mock_logger, mock_cfg, readonly=True)

        assert mgr._readonly is True


@pytest.mark.unit
class TestConnect:
    """Test connect method."""

    def test_connects_successfully(self, conn_mgr, mock_engine, mock_logger):
        """Test successful connection."""
        mock_conn = Mock()
        mock_engine.connect.return_value = mock_conn

        conn = conn_mgr.connect()

        assert conn == mock_conn
        mock_engine.connect.assert_called_once()
        mock_logger.debug.assert_called()

    def test_creates_database_when_configured(self, mock_engine, mock_logger):
        """Test creates database when create_db is True."""
        cfg = Mock()
        cfg.create_db = True  # Set attribute instead of mocking .get()
        conn_mgr = ConnectionManager(mock_engine, mock_logger, cfg, readonly=False)
        mock_conn = Mock()
        mock_engine.connect.return_value = mock_conn

        with patch("appinfra.db.pg.connection.handle_database_creation") as mock_create:
            conn_mgr.connect()

            mock_create.assert_called_once()

    def test_logs_readonly_mode(self, mock_engine, mock_logger, mock_cfg):
        """Test logs when connecting in readonly mode."""
        mgr = ConnectionManager(mock_engine, mock_logger, mock_cfg, readonly=True)
        mock_conn = Mock()
        mock_engine.connect.return_value = mock_conn

        mgr.connect()

        # Should log readonly status
        assert any("readonly" in str(call) for call in mock_logger.trace.call_args_list)

    def test_handles_sqlalchemy_error(self, conn_mgr, mock_engine):
        """Test handles SQLAlchemy errors properly."""
        mock_engine.connect.side_effect = sqlalchemy.exc.SQLAlchemyError(
            "Connection failed"
        )

        with pytest.raises(sqlalchemy.exc.SQLAlchemyError):
            conn_mgr.connect()

    def test_wraps_general_exceptions(self, conn_mgr, mock_engine):
        """Test wraps general exceptions in SQLAlchemyError."""
        mock_engine.connect.side_effect = ValueError("Unexpected error")

        with pytest.raises(sqlalchemy.exc.SQLAlchemyError) as exc_info:
            conn_mgr.connect()

        assert "Database connection failed" in str(exc_info.value)


@pytest.mark.unit
class TestHealthCheck:
    """Test health_check method."""

    def test_returns_healthy_on_success(self, conn_mgr, mock_engine):
        """Test returns healthy status when connection works."""
        mock_conn = Mock()
        mock_conn.execute = Mock()
        mock_conn.close = Mock()
        mock_engine.connect.return_value = mock_conn

        result = conn_mgr.health_check()

        assert result["status"] == "healthy"
        assert result["error"] is None
        assert "response_time_ms" in result
        mock_conn.execute.assert_called()
        mock_conn.close.assert_called()

    def test_returns_unhealthy_on_failure(self, conn_mgr, mock_engine, mock_logger):
        """Test returns unhealthy status when connection fails."""
        mock_engine.connect.side_effect = Exception("DB down")

        result = conn_mgr.health_check()

        assert result["status"] == "unhealthy"
        assert "DB down" in result["error"]  # Error message may be wrapped
        assert "response_time_ms" in result
        mock_logger.error.assert_called()


@pytest.mark.unit
class TestGetPoolStatus:
    """Test get_pool_status method."""

    def test_returns_pool_metrics(self, conn_mgr, mock_engine):
        """Test returns connection pool status metrics."""
        pool = Mock()
        pool.size = Mock(return_value=5)
        pool.checkedout = Mock(return_value=2)
        pool.overflow = Mock(return_value=1)
        pool.checkedin = Mock(return_value=3)
        pool.invalid = Mock(return_value=0)
        mock_engine.pool = pool

        status = conn_mgr.get_pool_status()

        assert status["pool_size"] == 5
        assert status["checked_out"] == 2
        assert status["overflow"] == 1
        assert status["checked_in"] == 3
        assert status["total_connections"] == 6  # size + overflow
        assert status["invalid"] == 0

    def test_handles_missing_invalid_method(self, conn_mgr, mock_engine):
        """Test handles pools without invalid() method."""
        pool = Mock()
        pool.size = Mock(return_value=5)
        pool.checkedout = Mock(return_value=2)
        pool.overflow = Mock(return_value=0)
        pool.checkedin = Mock(return_value=3)
        del pool.invalid  # Remove invalid method
        mock_engine.pool = pool

        status = conn_mgr.get_pool_status()

        assert status["invalid"] == 0  # Default value


@pytest.mark.unit
class TestSetLoggingContext:
    """Test set_logging_context method."""

    def test_updates_logging_context(self, conn_mgr):
        """Test updates logging context."""
        context = {"db": "testdb", "host": "localhost"}

        conn_mgr.set_logging_context(context)

        assert conn_mgr._lg_extra == context
