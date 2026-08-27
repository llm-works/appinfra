# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Comprehensive tests for SessionManager.

Tests session lifecycle, automatic reconnection, retry logic, and error handling.
"""

from unittest.mock import Mock

import pytest
import sqlalchemy.exc

from appinfra.db.pg.session import SessionManager


@pytest.fixture
def mock_session_cls():
    """Create mock sessionmaker."""
    session = Mock()
    session_cls = Mock(return_value=session)
    return session_cls


@pytest.fixture
def mock_logger():
    """Create mock logger."""
    logger = Mock()
    logger.trace = Mock()
    logger.info = Mock()
    logger.error = Mock()
    return logger


@pytest.fixture
def mock_reconnect_strategy():
    """Create mock reconnection strategy."""
    strategy = Mock()
    strategy.check_connection = Mock(return_value=True)
    strategy.reconnect = Mock(return_value=True)
    strategy.is_healthy = Mock(return_value=True)
    return strategy


@pytest.fixture
def session_mgr(mock_session_cls, mock_logger):
    """Create SessionManager instance."""
    return SessionManager(mock_session_cls, mock_logger, auto_reconnect=True)


@pytest.mark.unit
class TestSessionManagerInit:
    """Test SessionManager initialization."""

    def test_basic_initialization(self, mock_session_cls, mock_logger):
        """Test manager initializes with required parameters."""
        mgr = SessionManager(mock_session_cls, mock_logger)

        assert mgr._SessionCls == mock_session_cls
        assert mgr._lg == mock_logger
        assert mgr._auto_reconnect is True
        assert mgr._connection_healthy is True

    def test_auto_reconnect_disabled(self, mock_session_cls, mock_logger):
        """Test can disable auto reconnect."""
        mgr = SessionManager(mock_session_cls, mock_logger, auto_reconnect=False)

        assert mgr._auto_reconnect is False


@pytest.mark.unit
class TestCreateSessionWithRetry:
    """Test create_session_with_retry method."""

    def test_creates_session_successfully(
        self, session_mgr, mock_session_cls, mock_logger
    ):
        """Test creates session when no errors."""
        session = session_mgr.create_session_with_retry()

        assert session is not None
        mock_session_cls.assert_called_once()
        mock_logger.trace.assert_called()

    def test_marks_connection_unhealthy_on_failure(self, session_mgr, mock_session_cls):
        """Test marks connection unhealthy when session creation fails."""
        mock_session_cls.side_effect = Exception("Session creation failed")
        session_mgr._auto_reconnect = False

        with pytest.raises(sqlalchemy.exc.SQLAlchemyError):
            session_mgr.create_session_with_retry()

        assert session_mgr._connection_healthy is False

    def test_retries_when_auto_reconnect_enabled(
        self, session_mgr, mock_session_cls, mock_reconnect_strategy
    ):
        """Test retries session creation when auto_reconnect is enabled."""
        session_mgr.set_reconnect_strategy(mock_reconnect_strategy)

        # Fail first, succeed on retry
        attempts = [0]

        def session_side_effect():
            attempts[0] += 1
            if attempts[0] == 1:
                raise Exception("First attempt fails")
            return Mock()

        mock_session_cls.side_effect = session_side_effect

        session = session_mgr.create_session_with_retry()

        assert session is not None
        mock_reconnect_strategy.reconnect.assert_called_once()

    def test_raises_when_auto_reconnect_disabled(self, session_mgr, mock_session_cls):
        """Test raises error when auto_reconnect is disabled."""
        session_mgr._auto_reconnect = False
        mock_session_cls.side_effect = Exception("Session failed")

        with pytest.raises(sqlalchemy.exc.SQLAlchemyError) as exc_info:
            session_mgr.create_session_with_retry()

        assert "Session creation failed" in str(exc_info.value)


@pytest.mark.unit
class TestRetrySessionAfterReconnect:
    """Test _retry_session_after_reconnect method."""

    def test_succeeds_after_reconnect(
        self, session_mgr, mock_session_cls, mock_reconnect_strategy, mock_logger
    ):
        """Test successfully creates session after reconnecting."""
        session_mgr.set_reconnect_strategy(mock_reconnect_strategy)

        # Mock successful session creation after reconnect
        mock_session = Mock()
        mock_session_cls.return_value = mock_session
        mock_session_cls.side_effect = None  # Clear any side effects

        # Call _retry_session_after_reconnect directly
        session = session_mgr._retry_session_after_reconnect(Exception("Original"))

        assert session is not None
        mock_reconnect_strategy.reconnect.assert_called_once()
        mock_logger.info.assert_called()

    def test_raises_when_retry_fails(
        self, session_mgr, mock_session_cls, mock_reconnect_strategy, mock_logger
    ):
        """Test raises error when retry fails even after reconnect."""
        session_mgr.set_reconnect_strategy(mock_reconnect_strategy)
        mock_session_cls.side_effect = Exception("Persistent failure")

        with pytest.raises(sqlalchemy.exc.SQLAlchemyError) as exc_info:
            session_mgr._retry_session_after_reconnect(Exception("Original"))

        assert "Session creation failed after reconnect" in str(exc_info.value)
        mock_logger.error.assert_called()


@pytest.mark.unit
class TestEnsureConnectionHealthy:
    """Test ensure_connection_healthy method."""

    def test_does_nothing_when_healthy(self, session_mgr, mock_reconnect_strategy):
        """Test does nothing when connection is already healthy."""
        session_mgr.set_reconnect_strategy(mock_reconnect_strategy)
        session_mgr._connection_healthy = True

        session_mgr.ensure_connection_healthy()

        mock_reconnect_strategy.check_connection.assert_not_called()

    def test_checks_connection_when_unhealthy(
        self, session_mgr, mock_reconnect_strategy
    ):
        """Test checks connection when marked unhealthy."""
        session_mgr.set_reconnect_strategy(mock_reconnect_strategy)
        session_mgr._connection_healthy = False
        mock_reconnect_strategy.check_connection.return_value = True

        session_mgr.ensure_connection_healthy()

        # Should check but not reconnect (check succeeded)
        mock_reconnect_strategy.check_connection.assert_called_once()
        mock_reconnect_strategy.reconnect.assert_not_called()

    def test_reconnects_when_check_fails(
        self, session_mgr, mock_reconnect_strategy, mock_logger
    ):
        """Test triggers reconnect when connection check fails."""
        session_mgr.set_reconnect_strategy(mock_reconnect_strategy)
        session_mgr._connection_healthy = False
        mock_reconnect_strategy.check_connection.return_value = False

        session_mgr.ensure_connection_healthy()

        mock_reconnect_strategy.check_connection.assert_called_once()
        mock_reconnect_strategy.reconnect.assert_called_once()

    def test_does_nothing_when_auto_reconnect_disabled(
        self, session_mgr, mock_reconnect_strategy
    ):
        """Test does nothing when auto_reconnect is disabled."""
        session_mgr._auto_reconnect = False
        session_mgr._connection_healthy = False
        session_mgr.set_reconnect_strategy(mock_reconnect_strategy)

        session_mgr.ensure_connection_healthy()

        mock_reconnect_strategy.check_connection.assert_not_called()


@pytest.mark.unit
class TestSession:
    """Test session public method."""

    def test_creates_session_when_healthy(self, session_mgr, mock_session_cls):
        """Test creates session when connection is healthy."""
        session = session_mgr.session()

        assert session is not None
        mock_session_cls.assert_called()

    def test_ensures_health_before_creating_session(
        self, session_mgr, mock_reconnect_strategy
    ):
        """Test ensures connection is healthy before creating session."""
        session_mgr.set_reconnect_strategy(mock_reconnect_strategy)
        session_mgr._connection_healthy = False
        mock_reconnect_strategy.check_connection.return_value = True

        session = session_mgr.session()

        assert session is not None
        mock_reconnect_strategy.check_connection.assert_called()


@pytest.mark.unit
class TestSetters:
    """Test setter methods."""

    def test_set_logging_context(self, session_mgr):
        """Test set_logging_context updates context."""
        context = {"db": "test", "user": "admin"}

        session_mgr.set_logging_context(context)

        assert session_mgr._lg_extra == context

    def test_set_reconnect_strategy(self, session_mgr, mock_reconnect_strategy):
        """Test set_reconnect_strategy sets strategy."""
        session_mgr.set_reconnect_strategy(mock_reconnect_strategy)

        assert session_mgr._reconnect_strategy == mock_reconnect_strategy

    def test_set_connection_health(self, session_mgr):
        """Test set_connection_health updates health status."""
        session_mgr.set_connection_health(False)
        assert session_mgr._connection_healthy is False

        session_mgr.set_connection_health(True)
        assert session_mgr._connection_healthy is True
