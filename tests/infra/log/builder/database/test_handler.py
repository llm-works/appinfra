# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Comprehensive tests for DatabaseHandler.

Tests batching, critical flush, SQL caching, error handling, and performance optimizations.
"""

import logging
import signal
import time
from datetime import datetime
from unittest.mock import Mock, patch

import pytest

from appinfra.log.builder.database.config import DatabaseHandlerConfig
from appinfra.log.builder.database.handler import DatabaseHandler
from appinfra.log.config import LogConfig


@pytest.fixture
def mock_db_interface():
    """Create mock database interface."""
    db = Mock()
    session = Mock()
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=False)
    db.session.return_value = session
    return db


@pytest.fixture
def mock_logger():
    """Create mock logger for error logging."""
    return Mock()


@pytest.fixture
def handler_config(mock_db_interface):
    """Create basic handler configuration."""
    return DatabaseHandlerConfig(
        table_name="test_logs",
        db_interface=mock_db_interface,
        level="INFO",
        batch_size=10,
        flush_interval=5.0,
    )


@pytest.fixture
def log_config():
    """Create log configuration."""
    return LogConfig.from_params(level="info", location=0, micros=False, colors=False)


@pytest.fixture
def handler(mock_logger, handler_config, log_config):
    """Create DatabaseHandler instance for testing."""
    return DatabaseHandler(mock_logger, handler_config, log_config)


@pytest.mark.unit
class TestDatabaseHandlerInit:
    """Test DatabaseHandler initialization."""

    def test_basic_initialization(self, mock_logger, handler_config, log_config):
        """Test handler initializes with required parameters."""
        handler = DatabaseHandler(mock_logger, handler_config, log_config)

        assert handler._lg == mock_logger
        assert handler.handler_config == handler_config
        assert handler.log_config == log_config
        assert handler.batch == []
        assert isinstance(handler.last_flush, datetime)
        assert handler._sql_cache == {}

    def test_sets_handler_level_from_config(
        self, mock_logger, handler_config, log_config
    ):
        """Test handler level set from configuration."""
        handler = DatabaseHandler(mock_logger, handler_config, log_config)
        assert handler.level == logging.INFO

    def test_registers_with_lifecycle_manager(
        self, mock_logger, handler_config, log_config
    ):
        """Test handler registers with lifecycle manager if provided."""
        lifecycle_mgr = Mock()
        lifecycle_mgr.register_db_handler = Mock()

        handler = DatabaseHandler(
            mock_logger, handler_config, log_config, lifecycle_mgr
        )

        lifecycle_mgr.register_db_handler.assert_called_once_with(handler)


@pytest.mark.unit
class TestDatabaseHandlerEmit:
    """Test DatabaseHandler.emit() method."""

    def test_emits_normal_log_record(self, handler, mock_db_interface):
        """Test emitting a normal log record adds to batch."""
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        handler.emit(record)

        assert len(handler.batch) == 1
        assert handler.batch[0]["message"] == "Test message"

    def test_does_not_flush_until_batch_size_reached(self, handler):
        """Test batch doesn't flush until batch_size is reached."""
        handler.handler_config.batch_size = 5

        for i in range(4):
            record = logging.LogRecord(
                name="test",
                level=logging.INFO,
                pathname="test.py",
                lineno=10,
                msg=f"Message {i}",
                args=(),
                exc_info=None,
            )
            handler.emit(record)

        assert len(handler.batch) == 4  # Not flushed yet

    def test_flushes_when_batch_size_reached(self, handler, mock_db_interface):
        """Test batch flushes when batch_size is reached."""
        handler.handler_config.batch_size = 3

        for i in range(3):
            record = logging.LogRecord(
                name="test",
                level=logging.INFO,
                pathname="test.py",
                lineno=10,
                msg=f"Message {i}",
                args=(),
                exc_info=None,
            )
            handler.emit(record)

        # Batch should be flushed and empty
        assert len(handler.batch) == 0
        assert mock_db_interface.session.called

    def test_handles_emit_exceptions_gracefully(self, handler):
        """Test emit handles exceptions without crashing."""
        # Force data_mapper to raise exception
        handler.handler_config.data_mapper = Mock(side_effect=Exception("Test error"))

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test",
            args=(),
            exc_info=None,
        )

        # Should handle error gracefully (via handleError)
        handler.emit(record)  # Should not raise


@pytest.mark.unit
class TestShouldFlushBatch:
    """Test _should_flush_batch logic."""

    def test_flushes_when_batch_size_reached(self, handler):
        """Test returns True when batch size is reached."""
        handler.handler_config.batch_size = 5
        handler.batch = [{"msg": "test"}] * 5

        assert handler._should_flush_batch() is True

    def test_does_not_flush_when_batch_below_size(self, handler):
        """Test returns False when batch size not reached."""
        handler.handler_config.batch_size = 10
        handler.batch = [{"msg": "test"}] * 5
        handler.handler_config.flush_interval = 0  # Disable time-based flush

        assert handler._should_flush_batch() is False

    def test_flushes_when_flush_interval_exceeded(self, handler):
        """Test returns True when flush interval is exceeded."""
        handler.handler_config.batch_size = 100  # Large batch
        handler.handler_config.flush_interval = 0.1  # 100ms
        handler.batch = [{"msg": "test"}]
        handler.last_flush = datetime.now()

        # Wait for interval to pass
        time.sleep(0.15)

        assert handler._should_flush_batch() is True


@pytest.mark.unit
class TestIsCriticalError:
    """Test _is_critical_error detection logic."""

    def test_returns_false_when_disabled(self, handler):
        """Test returns False when critical flush is disabled."""
        handler.handler_config.critical_flush_enabled = False

        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname="test.py",
            lineno=10,
            msg="Error",
            args=(),
            exc_info=(Exception, Exception("test"), None),
        )

        assert handler._is_critical_error(record) is False

    def test_detects_exception_info(self, handler):
        """Test detects critical error when exc_info is present."""
        handler.handler_config.critical_flush_enabled = True

        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname="test.py",
            lineno=10,
            msg="Error",
            args=(),
            exc_info=(Exception, Exception("test"), None),
        )

        assert handler._is_critical_error(record) is True

    def test_detects_trigger_fields_in_extra(self, handler):
        """Test detects critical error when trigger fields are in extra."""
        handler.handler_config.critical_flush_enabled = True
        handler.handler_config.critical_trigger_fields = ["fatal", "critical_error"]

        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname="test.py",
            lineno=10,
            msg="Error",
            args=(),
            exc_info=None,
        )
        record.extra = {"fatal": True, "user_id": 123}

        assert handler._is_critical_error(record) is True

    def test_returns_false_for_normal_records(self, handler):
        """Test returns False for normal records without critical indicators."""
        handler.handler_config.critical_flush_enabled = True

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Normal message",
            args=(),
            exc_info=None,
        )

        assert handler._is_critical_error(record) is False


@pytest.mark.unit
class TestGetInsertSQL:
    """Test SQL statement caching."""

    def test_caches_insert_statements(self, handler):
        """Test SQL statements are cached by column tuple."""
        columns = ("timestamp", "level", "message")

        sql1 = handler._get_insert_sql(columns)
        sql2 = handler._get_insert_sql(columns)

        assert sql1 == sql2  # Same statement
        assert columns in handler._sql_cache
        assert len(handler._sql_cache) == 1  # Only one cached

    def test_generates_correct_sql_format(self, handler):
        """Test generates correct parameterized SQL."""
        columns = ("timestamp", "message")

        sql = handler._get_insert_sql(columns)

        assert "INSERT INTO test_logs" in sql
        assert "(timestamp, message)" in sql
        assert "(:timestamp, :message)" in sql

    def test_caches_different_column_sets(self, handler):
        """Test different column sets are cached separately."""
        cols1 = ("timestamp", "message")
        cols2 = ("timestamp", "level", "message")

        sql1 = handler._get_insert_sql(cols1)
        sql2 = handler._get_insert_sql(cols2)

        assert sql1 != sql2
        assert len(handler._sql_cache) == 2


@pytest.mark.unit
class TestInsertSingleRecord:
    """Test single record insertion."""

    def test_inserts_record_with_cached_sql(self, handler):
        """Test inserts record using cached SQL."""
        session = Mock()
        row_data = {"timestamp": datetime.now(), "message": "Test"}

        handler._insert_single_record(session, row_data)

        session.execute.assert_called_once()
        # Verify SQL was cached
        assert len(handler._sql_cache) > 0

    def test_handles_empty_row_data(self, handler):
        """Test does nothing for empty row data."""
        session = Mock()

        handler._insert_single_record(session, {})

        session.execute.assert_not_called()


@pytest.mark.unit
class TestFlushBatch:
    """Test batch flushing logic."""

    def test_flushes_batch_to_database(self, handler, mock_db_interface):
        """Test batch is flushed to database."""
        handler.batch = [
            {"timestamp": datetime.now(), "message": "Test 1"},
            {"timestamp": datetime.now(), "message": "Test 2"},
        ]

        handler._flush_batch()

        assert len(handler.batch) == 0  # Batch cleared
        mock_db_interface.session.assert_called_once()

    def test_mixed_rows_insert_union_of_columns(self, handler, mock_db_interface):
        """Rows lacking optional columns are padded with None, not dropped."""
        handler.batch = [
            {"timestamp": 1, "message": "plain"},
            {"timestamp": 2, "message": "with extra", "extra_data": "{}"},
        ]

        handler._flush_batch()

        session = mock_db_interface.session.return_value.__enter__.return_value
        sql, rows = session.execute.call_args.args
        assert "extra_data" in str(sql)
        assert rows == [
            {"extra_data": None, "message": "plain", "timestamp": 1},
            {"extra_data": "{}", "message": "with extra", "timestamp": 2},
        ]

    def test_does_nothing_for_empty_batch(self, handler, mock_db_interface):
        """Test does nothing when batch is empty."""
        handler.batch = []

        handler._flush_batch()

        mock_db_interface.session.assert_not_called()

    def test_handles_database_errors_gracefully(
        self, handler, mock_logger, mock_db_interface
    ):
        """Test handles database errors without raising."""
        handler.batch = [{"timestamp": datetime.now(), "message": "Test"}]
        # Mock execute to fail (session.commit is now internal to context manager)
        mock_db_interface.session.return_value.__enter__.return_value.execute.side_effect = Exception(
            "DB error"
        )

        handler._flush_batch()

        # Error logged, batch cleared
        assert len(handler.batch) == 0
        mock_logger.error.assert_called()

    def test_updates_last_flush_timestamp(self, handler):
        """Test last_flush timestamp is updated after flush."""
        old_timestamp = handler.last_flush
        handler.batch = [{"timestamp": datetime.now(), "message": "Test"}]

        time.sleep(0.01)  # Small delay
        handler._flush_batch()

        assert handler.last_flush > old_timestamp


@pytest.mark.unit
class TestClose:
    """Test handler close method."""

    def test_flushes_remaining_batch_on_close(self, handler, mock_db_interface):
        """Test close flushes any remaining batch data."""
        handler.batch = [{"timestamp": datetime.now(), "message": "Final"}]

        handler.close()

        assert len(handler.batch) == 0
        mock_db_interface.session.assert_called_once()


@pytest.mark.unit
class TestCriticalFlush:
    """Test critical error immediate flush."""

    @pytest.mark.skipif(
        not hasattr(signal, "SIGALRM"), reason="Requires SIGALRM (Unix only)"
    )
    def test_critical_flush_with_timeout(self, handler, mock_db_interface):
        """Test critical flush uses signal timeout."""
        import signal

        row_data = {"timestamp": datetime.now(), "message": "CRITICAL ERROR"}

        with patch.object(signal, "alarm") as mock_alarm:
            handler._critical_flush(row_data)

            # Verify alarm was set and cleared
            assert mock_alarm.call_count == 2
            mock_alarm.assert_any_call(
                int(handler.handler_config.critical_flush_timeout)
            )
            mock_alarm.assert_any_call(0)  # Cleared

    def test_critical_flush_fallback_to_console(
        self, handler, mock_logger, mock_db_interface
    ):
        """Test critical flush falls back to console on database error."""
        handler.handler_config.fallback_to_console = True
        row_data = {"timestamp": datetime.now(), "message": "CRITICAL"}

        # Make session raise exception
        mock_db_interface.session.return_value.__enter__.side_effect = Exception(
            "DB down"
        )

        with pytest.raises(Exception):
            handler._critical_flush(row_data)

        # Verify fallback to console
        mock_logger.critical.assert_called()
        assert "DB flush failed" in str(mock_logger.critical.call_args)


@pytest.mark.unit
class TestInsertBatch:
    """Test batch insertion."""

    def test_executes_one_statement_per_batch(self, handler):
        """A batch goes to the database as a single executemany call."""
        session = Mock()
        batch_data = [
            {"timestamp": datetime.now(), "message": "Test 1"},
            {"timestamp": datetime.now(), "message": "Test 2"},
        ]

        handler._insert_batch(session, batch_data)

        session.execute.assert_called_once()
        _, rows = session.execute.call_args.args
        assert len(rows) == 2

    def test_handles_empty_batch(self, handler):
        """Test does nothing for empty batch."""
        session = Mock()

        handler._insert_batch(session, [])

        session.execute.assert_not_called()


@pytest.mark.unit
class TestIntegration:
    """Integration tests for complete workflows."""

    def test_batching_workflow(self, handler, mock_db_interface):
        """Test complete batching workflow."""
        handler.handler_config.batch_size = 3

        # Emit 3 records (should trigger flush)
        for i in range(3):
            record = logging.LogRecord(
                name="test",
                level=logging.INFO,
                pathname="test.py",
                lineno=10,
                msg=f"Message {i}",
                args=(),
                exc_info=None,
            )
            handler.emit(record)

        # Verify batch was flushed
        assert len(handler.batch) == 0
        assert mock_db_interface.session.called

    def test_critical_error_bypasses_batch(self, handler, mock_db_interface):
        """Test critical errors bypass batching."""
        handler.handler_config.critical_flush_enabled = True

        # Create critical error record
        try:
            raise ValueError("Critical test error")
        except ValueError:
            import sys

            exc_info = sys.exc_info()

        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname="test.py",
            lineno=10,
            msg="Critical error",
            args=(),
            exc_info=exc_info,
        )

        with patch("signal.signal"), patch("signal.alarm"):
            handler.emit(record)

        # Batch should still be empty (critical flush bypassed it)
        assert len(handler.batch) == 0


@pytest.mark.unit
class TestPerformanceOptimizations:
    """Test performance optimization features."""

    def test_sql_caching_improves_performance(self, handler):
        """Test SQL caching reduces statement generation."""
        columns = ("timestamp", "message")

        # First call generates and caches
        sql1 = handler._get_insert_sql(columns)

        # Subsequent calls use cache
        for _ in range(100):
            sql = handler._get_insert_sql(columns)
            assert sql == sql1

        # Only one entry in cache
        assert len(handler._sql_cache) == 1
