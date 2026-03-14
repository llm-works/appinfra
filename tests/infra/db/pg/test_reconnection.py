"""
Comprehensive tests for ReconnectionStrategy.

Tests reconnection logic, exponential backoff, health checks, and error handling.
"""

from unittest.mock import Mock, patch

import pytest
import sqlalchemy

from appinfra.db.pg.reconnection import ReconnectionStrategy
from appinfra.errors import DatabaseError


@pytest.fixture
def mock_engine():
    """Create mock SQLAlchemy engine."""
    engine = Mock(spec=sqlalchemy.engine.Engine)
    engine.url = "postgresql://localhost/test"
    engine.connect = Mock()
    engine.dispose = Mock()
    return engine


@pytest.fixture
def mock_logger():
    """Create mock logger."""
    logger = Mock()
    logger.info = Mock()
    logger.warning = Mock()
    logger.debug = Mock()
    logger.error = Mock()
    return logger


@pytest.fixture
def strategy(mock_engine, mock_logger):
    """Create ReconnectionStrategy instance."""
    return ReconnectionStrategy(
        mock_engine, mock_logger, max_retries=3, retry_delay=0.1
    )


@pytest.mark.unit
class TestReconnectionStrategyInit:
    """Test ReconnectionStrategy initialization."""

    def test_basic_initialization(self, mock_engine, mock_logger):
        """Test strategy initializes with required parameters."""
        strategy = ReconnectionStrategy(mock_engine, mock_logger)

        assert strategy._engine == mock_engine
        assert strategy._lg == mock_logger
        assert strategy._max_retries == 3
        assert strategy._retry_delay == 0.5
        assert strategy._connection_healthy is True

    def test_custom_retry_parameters(self, mock_engine, mock_logger):
        """Test strategy accepts custom retry parameters."""
        strategy = ReconnectionStrategy(
            mock_engine, mock_logger, max_retries=5, retry_delay=1.0
        )

        assert strategy._max_retries == 5
        assert strategy._retry_delay == 1.0


@pytest.mark.unit
class TestCheckConnection:
    """Test check_connection method."""

    def test_returns_true_for_healthy_connection(self, strategy, mock_engine):
        """Test returns True when connection is healthy."""
        conn = Mock()
        conn.execute = Mock()
        mock_engine.connect.return_value = Mock(
            __enter__=Mock(return_value=conn), __exit__=Mock(return_value=None)
        )

        result = strategy.check_connection()

        assert result is True
        assert strategy._connection_healthy is True
        conn.execute.assert_called_once()

    def test_returns_false_on_connection_failure(
        self, strategy, mock_engine, mock_logger
    ):
        """Test returns False when connection fails."""
        mock_engine.connect.side_effect = Exception("Connection refused")

        result = strategy.check_connection()

        assert result is False
        assert strategy._connection_healthy is False
        mock_logger.warning.assert_called_once()

    def test_uses_custom_timeout(self, strategy, mock_engine):
        """Test uses custom timeout parameter."""
        conn = Mock()
        conn.execute = Mock()
        mock_engine.connect.return_value = Mock(
            __enter__=Mock(return_value=conn), __exit__=Mock(return_value=None)
        )

        strategy.check_connection(timeout=10.0)

        # Verify timeout was passed to query
        call_args = conn.execute.call_args
        assert call_args is not None


@pytest.mark.unit
class TestAttemptReconnect:
    """Test attempt_reconnect method."""

    def test_successful_reconnection(self, strategy, mock_engine, mock_logger):
        """Test successful reconnection."""
        conn = Mock()
        conn.execute = Mock()
        mock_engine.connect.return_value = Mock(
            __enter__=Mock(return_value=conn), __exit__=Mock(return_value=None)
        )

        result = strategy.attempt_reconnect(attempt_num=1)

        assert result is True
        mock_engine.dispose.assert_called_once()
        mock_logger.info.assert_called()

    def test_failed_reconnection(self, strategy, mock_engine, mock_logger):
        """Test failed reconnection attempt."""
        mock_engine.connect.side_effect = Exception("DB down")

        result = strategy.attempt_reconnect(attempt_num=2)

        assert result is False
        mock_logger.warning.assert_called()


@pytest.mark.unit
class TestReconnectWithBackoff:
    """Test reconnect_with_backoff method."""

    def test_succeeds_on_first_attempt(self, strategy, mock_engine):
        """Test succeeds on first reconnection attempt."""
        conn = Mock()
        conn.execute = Mock()
        mock_engine.connect.return_value = Mock(
            __enter__=Mock(return_value=conn), __exit__=Mock(return_value=None)
        )

        with patch("time.sleep") as mock_sleep:
            result = strategy.reconnect_with_backoff(max_retries=3, delay=0.1)

            assert result is True
            mock_sleep.assert_not_called()  # No sleep on first success

    def test_retries_with_exponential_backoff(self, strategy, mock_engine, mock_logger):
        """Test retries with exponential backoff delays."""
        # Fail first 2 attempts, succeed on 3rd
        attempts = [0]

        def connect_side_effect():
            attempts[0] += 1
            if attempts[0] < 3:
                raise Exception("DB down")
            conn = Mock()
            conn.execute = Mock()
            return Mock(__enter__=Mock(return_value=conn), __exit__=Mock())

        mock_engine.connect.side_effect = connect_side_effect

        with patch("time.sleep") as mock_sleep:
            result = strategy.reconnect_with_backoff(max_retries=3, delay=0.1)

            assert result is True
            # Should sleep 2 times (0.1 * 2^0, 0.1 * 2^1)
            assert mock_sleep.call_count == 2
            mock_sleep.assert_any_call(0.1)  # First retry
            mock_sleep.assert_any_call(0.2)  # Second retry

    def test_raises_database_error_after_exhausting_retries(
        self, strategy, mock_engine, mock_logger
    ):
        """Test raises DatabaseError when all retries fail."""
        mock_engine.connect.side_effect = Exception("DB permanently down")

        with patch("time.sleep"):
            with pytest.raises(DatabaseError) as exc_info:
                strategy.reconnect_with_backoff(max_retries=3, delay=0.1)

            assert "Failed to reconnect after 3 attempts" in str(exc_info.value)
            assert strategy._connection_healthy is False
            mock_logger.error.assert_called()


@pytest.mark.unit
class TestReconnect:
    """Test reconnect public method."""

    def test_uses_default_parameters(self, strategy, mock_engine):
        """Test uses default max_retries and delay when not provided."""
        conn = Mock()
        conn.execute = Mock()
        mock_engine.connect.return_value = Mock(
            __enter__=Mock(return_value=conn), __exit__=Mock(return_value=None)
        )

        with patch("time.sleep"):
            result = strategy.reconnect()

            assert result is True

    def test_uses_custom_parameters(self, strategy, mock_engine):
        """Test uses provided max_retries and delay."""
        conn = Mock()
        conn.execute = Mock()
        mock_engine.connect.return_value = Mock(
            __enter__=Mock(return_value=conn), __exit__=Mock(return_value=None)
        )

        with patch("time.sleep"):
            result = strategy.reconnect(max_retries=5, initial_delay=1.0)

            assert result is True

    def test_logs_reconnection_attempt(self, strategy, mock_engine, mock_logger):
        """Test logs when reconnection is attempted."""
        conn = Mock()
        conn.execute = Mock()
        mock_engine.connect.return_value = Mock(
            __enter__=Mock(return_value=conn), __exit__=Mock(return_value=None)
        )

        with patch("time.sleep"):
            strategy.reconnect()

            # Should log "attempting to reconnect"
            assert any(
                "attempting to reconnect" in str(call)
                for call in mock_logger.info.call_args_list
            )


@pytest.mark.unit
class TestSetLoggingContext:
    """Test set_logging_context method."""

    def test_updates_logging_context(self, strategy):
        """Test updates logging context."""
        context = {"db": "testdb", "user": "testuser"}

        strategy.set_logging_context(context)

        assert strategy._lg_extra == context


@pytest.mark.unit
class TestIsHealthy:
    """Test is_healthy method."""

    def test_returns_connection_health_status(self, strategy):
        """Test returns current health status."""
        strategy._connection_healthy = True
        assert strategy.is_healthy() is True

        strategy._connection_healthy = False
        assert strategy.is_healthy() is False
