"""Tests for MPQueueHandler - multiprocessing-safe queue handler."""

import logging
import sys
from multiprocessing import Queue
from unittest.mock import MagicMock

import pytest

from appinfra.log.mp import MPQueueHandler


@pytest.fixture(autouse=True)
def reset_level_manager():
    """Reset LogLevelManager singleton before and after each test."""
    from appinfra.log import LogLevelManager

    LogLevelManager.reset_instance()
    yield
    LogLevelManager.reset_instance()


@pytest.fixture
def queue():
    """Create a multiprocessing queue for testing."""
    return Queue()


@pytest.fixture
def handler(queue):
    """Create an MPQueueHandler for testing."""
    return MPQueueHandler(queue)


@pytest.fixture
def log_record():
    """Create a basic log record for testing."""
    return logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname="/test/file.py",
        lineno=42,
        msg="Test message",
        args=(),
        exc_info=None,
    )


@pytest.mark.unit
class TestMPQueueHandlerInit:
    """Test MPQueueHandler initialization."""

    def test_basic_initialization(self, queue):
        """Test handler initializes with queue."""
        handler = MPQueueHandler(queue)
        assert handler.queue is queue

    def test_inherits_from_handler(self, handler):
        """Test handler inherits from logging.Handler."""
        assert isinstance(handler, logging.Handler)


@pytest.mark.unit
class TestMPQueueHandlerEmit:
    """Test MPQueueHandler.emit() method."""

    def test_emit_puts_record_on_queue(self, handler, queue, log_record):
        """Test emit puts prepared record on queue."""
        handler.emit(log_record)

        result = queue.get(timeout=1)
        assert result.name == "test.logger"
        assert result.levelno == logging.INFO
        assert result.msg == "Test message"

    def test_emit_handles_exception_gracefully(self, handler, log_record):
        """Test emit handles queue errors without raising."""
        handler.queue = MagicMock()
        handler.queue.put_nowait.side_effect = Exception("Queue full")

        # Should not raise
        handler.emit(log_record)

    def test_emit_formats_message_args(self, handler, queue):
        """Test emit formats message with args."""
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="/test.py",
            lineno=1,
            msg="Value: %s",
            args=("hello",),
            exc_info=None,
        )

        handler.emit(record)
        result = queue.get(timeout=1)

        assert result.msg == "Value: hello"
        assert result.args is None


@pytest.mark.unit
class TestMPQueueHandlerPrepare:
    """Test MPQueueHandler._prepare() method."""

    def test_prepare_clears_exc_info(self, handler, log_record):
        """Test prepare clears exc_info after formatting."""
        try:
            raise ValueError("test error")
        except ValueError:
            log_record.exc_info = sys.exc_info()

        prepared = handler._prepare(log_record)

        assert prepared.exc_info is None
        assert prepared.exc_text is not None
        assert "ValueError" in prepared.exc_text
        assert "test error" in prepared.exc_text

    def test_prepare_formats_infra_extra_exception(self, handler, log_record):
        """Test prepare handles exception in __infra__extra."""
        try:
            raise RuntimeError("extra exception")
        except RuntimeError as e:
            setattr(log_record, "__infra__extra", {"exception": e, "key": "value"})

            prepared = handler._prepare(log_record)
            extra = getattr(prepared, "__infra__extra")

            assert "exception" not in extra
            assert "exception_formatted" in extra
            assert "RuntimeError" in extra["exception_formatted"]
            assert extra["key"] == "value"

    def test_prepare_preserves_other_infra_attrs(self, handler, log_record):
        """Test prepare preserves __infra__pathnames and __infra__linenos."""
        setattr(log_record, "__infra__pathnames", ["/a.py", "/b.py"])
        setattr(log_record, "__infra__linenos", [10, 20])
        setattr(log_record, "__infra__extra", {"key": "value"})

        prepared = handler._prepare(log_record)

        assert getattr(prepared, "__infra__pathnames") == ["/a.py", "/b.py"]
        assert getattr(prepared, "__infra__linenos") == [10, 20]

    def test_prepare_handles_getMessage_failure(self, handler, log_record):
        """Test prepare handles getMessage failure gracefully."""
        log_record.msg = "Format: %s %s"
        log_record.args = ("only_one",)  # Missing argument

        # Should not raise, just clear args
        prepared = handler._prepare(log_record)
        assert prepared.args is None

    def test_prepare_handles_exception_in_non_standard_key(self, handler, log_record):
        """Test prepare handles exception in non-standard key (not 'exception')."""
        import pickle

        exc = ValueError("test error")
        setattr(log_record, "__infra__extra", {"error": exc, "key": "value"})

        prepared = handler._prepare(log_record)
        extra = getattr(prepared, "__infra__extra")

        # Non-standard key should be converted in-place (not renamed)
        assert "error" in extra
        assert isinstance(extra["error"], str)
        assert "ValueError" in extra["error"]
        assert extra["key"] == "value"

        # Should be picklable
        pickled = pickle.dumps(prepared)
        unpickled = pickle.loads(pickled)
        assert "ValueError" in getattr(unpickled, "__infra__extra")["error"]

    def test_prepare_handles_nested_exception(self, handler, log_record):
        """Test prepare handles exception nested in dict."""
        import pickle

        exc = RuntimeError("nested error")
        setattr(log_record, "__infra__extra", {"context": {"exc": exc}})

        prepared = handler._prepare(log_record)
        extra = getattr(prepared, "__infra__extra")

        assert isinstance(extra["context"]["exc"], str)
        assert "RuntimeError" in extra["context"]["exc"]

        # Should be picklable
        pickled = pickle.dumps(prepared)
        unpickled = pickle.loads(pickled)
        assert "RuntimeError" in getattr(unpickled, "__infra__extra")["context"]["exc"]

    def test_prepare_handles_exception_in_list(self, handler, log_record):
        """Test prepare handles exception in list."""
        import pickle

        exc1 = KeyError("key1")
        exc2 = KeyError("key2")
        setattr(log_record, "__infra__extra", {"errors": [exc1, exc2]})

        prepared = handler._prepare(log_record)
        extra = getattr(prepared, "__infra__extra")

        assert len(extra["errors"]) == 2
        assert all(isinstance(e, str) for e in extra["errors"])
        assert "key1" in extra["errors"][0]
        assert "key2" in extra["errors"][1]

        # Should be picklable
        pickled = pickle.dumps(prepared)
        pickle.loads(pickled)

    def test_prepare_handles_exception_in_tuple_and_set(self, handler, log_record):
        """Test prepare handles exceptions in tuple and set."""
        import pickle

        exc_tuple = ValueError("tuple error")
        exc_set = RuntimeError("set error")
        setattr(
            log_record,
            "__infra__extra",
            {"tuple_errors": (exc_tuple,), "set_errors": {exc_set}},
        )

        prepared = handler._prepare(log_record)
        extra = getattr(prepared, "__infra__extra")

        assert isinstance(extra["tuple_errors"], tuple)
        assert isinstance(extra["tuple_errors"][0], str)
        assert "ValueError" in extra["tuple_errors"][0]

        assert isinstance(extra["set_errors"], set)
        assert all(isinstance(e, str) for e in extra["set_errors"])

        # Should be picklable
        pickled = pickle.dumps(prepared)
        pickle.loads(pickled)

    def test_prepare_handles_cyclic_reference(self, handler, log_record):
        """Test prepare handles cyclic references without infinite recursion."""
        import pickle

        # Create a cyclic structure
        cyclic_dict: dict = {"key": "value"}
        cyclic_dict["self"] = cyclic_dict

        setattr(log_record, "__infra__extra", cyclic_dict)

        # Should not hang or raise RecursionError
        prepared = handler._prepare(log_record)
        extra = getattr(prepared, "__infra__extra")

        assert extra["key"] == "value"
        assert extra["self"] == "<cyclic reference>"

        # Should be picklable
        pickled = pickle.dumps(prepared)
        pickle.loads(pickled)


@pytest.mark.unit
class TestMPQueueHandlerFormatException:
    """Test exception formatting methods."""

    def test_format_exc_info_with_traceback(self, handler):
        """Test _format_exc_info formats full traceback."""
        try:
            raise ValueError("test")
        except ValueError:
            exc_info = sys.exc_info()
            result = handler._format_exc_info(exc_info)

            assert "ValueError" in result
            assert "test" in result
            assert "Traceback" in result

    def test_format_exc_info_with_none(self, handler):
        """Test _format_exc_info with None exc_info."""
        result = handler._format_exc_info((None, None, None))
        assert result == ""

    def test_format_exception_in_context_current_exception(self, handler):
        """Test _format_exception_in_context with current exception."""
        try:
            raise TypeError("context error")
        except TypeError as e:
            result = handler._format_exception_in_context(e)

            assert "TypeError" in result
            assert "context error" in result
            assert "Traceback" in result

    def test_format_exception_in_context_not_current(self, handler):
        """Test _format_exception_in_context with non-current exception."""
        old_exc = ValueError("old error")

        # No exception context
        result = handler._format_exception_in_context(old_exc)

        assert result == "ValueError: old error"
        assert "Traceback" not in result


@pytest.mark.unit
class TestMPQueueHandlerClose:
    """Test MPQueueHandler.close() method."""

    def test_close_calls_parent_close(self, handler):
        """Test close calls parent class close."""
        handler.close()
        # Should not raise


@pytest.mark.unit
class TestLoggerWithQueue:
    """Test Logger.with_queue() class method."""

    def test_with_queue_creates_logger(self, queue):
        """Test with_queue creates a logger with queue handler."""
        from appinfra.log import Logger

        lg = Logger.with_queue(queue, name="test.worker")

        assert lg.name == "test.worker"
        assert len(lg.handlers) == 1
        assert isinstance(lg.handlers[0], MPQueueHandler)

    def test_with_queue_sets_level(self, queue):
        """Test with_queue sets the log level."""
        from appinfra.log import Logger

        lg = Logger.with_queue(queue, name="test.worker", level="debug")

        assert lg.level == logging.DEBUG

    def test_with_queue_level_string(self, queue):
        """Test with_queue accepts string level."""
        from appinfra.log import Logger

        lg = Logger.with_queue(queue, name="test", level="warning")

        assert lg.level == logging.WARNING

    def test_with_queue_logs_to_queue(self, queue):
        """Test logger created with_queue sends records to queue."""
        from appinfra.log import Logger

        lg = Logger.with_queue(queue, name="test.queue")
        lg.info("test message")

        record = queue.get(timeout=1)
        assert record.msg == "test message"


@pytest.mark.integration
class TestMPQueueHandlerIntegration:
    """Integration tests for MPQueueHandler."""

    def test_full_logging_flow(self, queue):
        """Test complete logging flow through queue handler."""
        logger = logging.getLogger("test.mp.handler")
        logger.setLevel(logging.DEBUG)
        logger.handlers.clear()

        handler = MPQueueHandler(queue)
        handler.setLevel(logging.DEBUG)
        logger.addHandler(handler)

        logger.info("Test info message")
        logger.warning("Test warning")

        record1 = queue.get(timeout=1)
        record2 = queue.get(timeout=1)

        assert record1.msg == "Test info message"
        assert record1.levelno == logging.INFO
        assert record2.msg == "Test warning"
        assert record2.levelno == logging.WARNING

    def test_exception_logging_flow(self, queue):
        """Test exception is properly captured and formatted."""
        logger = logging.getLogger("test.mp.exc")
        logger.setLevel(logging.DEBUG)
        logger.handlers.clear()

        handler = MPQueueHandler(queue)
        logger.addHandler(handler)

        try:
            raise KeyError("missing key")
        except KeyError:
            logger.exception("Error occurred")

        record = queue.get(timeout=1)

        assert record.exc_info is None  # Cleared
        assert record.exc_text is not None  # Formatted
        assert "KeyError" in record.exc_text
        assert "missing key" in record.exc_text


@pytest.mark.unit
class TestLoggerQueueConfig:
    """Test Logger.queue_config() and Logger.from_queue_config() methods."""

    def test_queue_config_returns_dict_with_queue_and_level(self, queue):
        """Test queue_config returns a dict with queue and level."""
        from appinfra.log import Logger

        lg = Logger.with_queue(queue, name="parent", level="debug")
        config = lg.queue_config(queue)

        assert isinstance(config, dict)
        assert config["queue"] is queue
        assert config["level"] == logging.DEBUG

    def test_queue_config_captures_effective_level(self, queue):
        """Test queue_config captures the logger's effective level."""
        from appinfra.log import Logger

        lg = Logger.with_queue(queue, name="parent", level="warning")
        config = lg.queue_config(queue)

        assert config["level"] == logging.WARNING

    def test_from_queue_config_creates_logger(self, queue):
        """Test from_queue_config creates a logger with queue handler."""
        from appinfra.log import Logger

        config = {"queue": queue, "level": logging.DEBUG}
        lg = Logger.from_queue_config(config, name="worker")

        assert lg.name == "worker"
        assert len(lg.handlers) == 1
        assert isinstance(lg.handlers[0], MPQueueHandler)
        assert lg.level == logging.DEBUG

    def test_from_queue_config_respects_level(self, queue):
        """Test from_queue_config sets the correct level."""
        from appinfra.log import Logger

        config = {"queue": queue, "level": logging.ERROR}
        lg = Logger.from_queue_config(config, name="worker")

        assert lg.level == logging.ERROR

    def test_queue_config_roundtrip(self, queue):
        """Test queue_config -> from_queue_config roundtrip."""
        from appinfra.log import Logger

        parent_lg = Logger.with_queue(queue, name="parent", level="info")
        config = parent_lg.queue_config(queue)
        worker_lg = Logger.from_queue_config(config, name="worker")

        assert worker_lg.level == parent_lg.level
        assert worker_lg.handlers[0].queue is queue

    def test_from_queue_config_logs_to_queue(self, queue):
        """Test logger from from_queue_config sends records to queue."""
        from appinfra.log import Logger

        config = {"queue": queue, "level": logging.INFO}
        lg = Logger.from_queue_config(config, name="worker")
        lg.info("test message from worker")

        record = queue.get(timeout=1)
        assert record.msg == "test message from worker"
        assert record.name == "worker"

    def test_queue_config_with_logging_builder(self, queue):
        """Test queue_config works with LoggingBuilder-created loggers."""
        from appinfra.log import LoggingBuilder

        parent_lg = LoggingBuilder("parent").with_level("debug").build()
        config = parent_lg.queue_config(queue)

        assert config["queue"] is queue
        assert config["level"] == logging.DEBUG

    def test_queue_config_includes_level_rules(self, queue):
        """Test queue_config includes LogLevelManager rules."""
        from appinfra.log import Logger, LogLevelManager

        # Setup rules in parent
        level_manager = LogLevelManager.get_instance()
        level_manager.clear_rules()
        level_manager.add_rule("/worker/*", "warning", source="test", priority=1)

        lg = Logger.with_queue(queue, name="parent", level="debug")
        config = lg.queue_config(queue)

        assert "level_rules" in config
        assert len(config["level_rules"]["rules"]) == 1
        assert config["level_rules"]["rules"][0]["pattern"] == "/worker/*"
        assert config["level_rules"]["rules"][0]["level"] == "warning"

        # Cleanup
        level_manager.clear_rules()

    def test_from_queue_config_applies_level_rules(self, queue):
        """Test from_queue_config applies pattern-based level rules."""
        from appinfra.log import Logger, LogLevelManager

        # Setup: create config with rules
        level_manager = LogLevelManager.get_instance()
        level_manager.clear_rules()
        level_manager.add_rule("/worker/*", "warning", source="test", priority=1)

        parent_lg = Logger.with_queue(queue, name="parent", level="debug")
        config = parent_lg.queue_config(queue)

        # Clear rules to simulate fresh subprocess
        level_manager.clear_rules()

        # Create worker logger - should get WARNING level from pattern match
        worker_lg = Logger.from_queue_config(config, name="/worker/task1")

        assert worker_lg.level == logging.WARNING

        # Cleanup
        level_manager.clear_rules()

    def test_from_queue_config_falls_back_to_base_level(self, queue):
        """Test from_queue_config uses base level when no pattern matches."""
        from appinfra.log import Logger, LogLevelManager

        # Setup: create config with rules that won't match
        level_manager = LogLevelManager.get_instance()
        level_manager.clear_rules()
        level_manager.add_rule("/other/*", "warning", source="test", priority=1)

        parent_lg = Logger.with_queue(queue, name="parent", level="debug")
        config = parent_lg.queue_config(queue)

        # Clear rules to simulate fresh subprocess
        level_manager.clear_rules()

        # Create worker logger - should fall back to DEBUG (base level)
        worker_lg = Logger.from_queue_config(config, name="/worker/task1")

        assert worker_lg.level == logging.DEBUG

        # Cleanup
        level_manager.clear_rules()

    def test_from_queue_config_restores_multiple_rules(self, queue):
        """Test from_queue_config correctly restores multiple rules."""
        from appinfra.log import Logger, LogLevelManager

        # Setup: create config with multiple rules
        level_manager = LogLevelManager.get_instance()
        level_manager.clear_rules()
        level_manager.add_rule("/worker/*", "warning", source="test", priority=1)
        level_manager.add_rule("/worker/verbose/*", "debug", source="test", priority=2)

        parent_lg = Logger.with_queue(queue, name="parent", level="info")
        config = parent_lg.queue_config(queue)

        # Clear rules to simulate fresh subprocess
        level_manager.clear_rules()

        # Create workers - more specific pattern should win
        worker1 = Logger.from_queue_config(config, name="/worker/task1")
        worker2 = Logger.from_queue_config(config, name="/worker/verbose/task2")

        assert worker1.level == logging.WARNING  # Matches /worker/*
        assert (
            worker2.level == logging.DEBUG
        )  # Matches /worker/verbose/* (higher priority)

        # Cleanup
        level_manager.clear_rules()

    def test_queue_config_includes_default_level(self, queue):
        """Test queue_config includes LogLevelManager default level."""
        from appinfra.log import Logger, LogLevelManager

        level_manager = LogLevelManager.get_instance()
        level_manager.clear_rules()
        level_manager.set_default_level("error")

        lg = Logger.with_queue(queue, name="parent", level="debug")
        config = lg.queue_config(queue)

        assert config["level_rules"]["default_level"] == "error"

        # Cleanup
        level_manager.set_default_level(logging.INFO)
        level_manager.clear_rules()
