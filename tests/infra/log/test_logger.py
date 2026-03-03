"""
Comprehensive tests for the logging system.

Tests Logger, LogConfig, and CallbackRegistry functionality including:
- Logger initialization and configuration
- Custom log levels (trace, trace2)
- Extra field handling
- Callback system
- Location tracking
- Microsecond timestamps
- Disabled logging
"""

import collections
import logging
from unittest.mock import Mock, patch

import pytest

from appinfra.log.callback import CallbackRegistry, listens_for
from appinfra.log.config import LogConfig
from appinfra.log.errors import (
    CallbackError,
    InvalidLogLevelError,
)
from appinfra.log.logger import Logger

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def basic_config():
    """Create basic LogConfig."""
    return LogConfig.from_params("info", location=0, micros=False)


@pytest.fixture
def callback_registry():
    """Create empty CallbackRegistry."""
    return CallbackRegistry()


@pytest.fixture
def basic_logger(basic_config, callback_registry):
    """Create basic Logger instance."""
    return Logger(
        "test_logger", config=basic_config, callback_registry=callback_registry
    )


@pytest.fixture
def mock_handler():
    """Create mock log handler."""
    handler = Mock(spec=logging.Handler)
    handler.level = logging.DEBUG
    return handler


# =============================================================================
# Test LogConfig
# =============================================================================


@pytest.mark.unit
class TestLogConfig:
    """Test LogConfig creation and methods."""

    def test_from_params_with_string_level(self):
        """Test creating LogConfig from string level."""
        config = LogConfig.from_params("info", location=1, micros=True)
        assert config.level == logging.INFO
        assert config.location == 1
        assert config.micros is True

    def test_from_params_with_integer_level(self):
        """Test creating LogConfig from integer level."""
        config = LogConfig.from_params(logging.DEBUG, location=0, micros=False)
        assert config.level == logging.DEBUG
        assert config.location == 0
        assert config.micros is False

    def test_from_params_with_false_disables_logging(self):
        """Test that False level disables logging."""
        config = LogConfig.from_params(False, location=0, micros=False)
        assert config.level is False

    def test_from_params_with_bool_location(self):
        """Test location parameter as boolean."""
        config_true = LogConfig.from_params("info", location=True)
        assert config_true.location == 1

        config_false = LogConfig.from_params("info", location=False)
        assert config_false.location == 0

    def test_from_params_with_numeric_string_level(self):
        """Test numeric string level is converted to int."""
        config = LogConfig.from_params("10", location=0)
        assert config.level == 10

    def test_from_params_with_invalid_string_level(self):
        """Test invalid string level raises error."""
        with pytest.raises(InvalidLogLevelError):
            LogConfig.from_params("invalid_level", location=0)

    def test_from_params_default_colors(self):
        """Test default colors setting."""
        config = LogConfig.from_params("info", location=0)
        assert config.colors is True

    def test_from_config_dict_basic(self):
        """Test creating LogConfig from config dict."""
        config_dict = {
            "logging": {
                "level": "debug",
                "location": 2,
                "micros": True,
                "colors": False,
            }
        }
        config = LogConfig.from_config(config_dict, "logging")
        assert config.level == logging.DEBUG
        assert config.location == 2
        assert config.micros is True
        assert config.colors is False

    def test_from_config_dict_with_microseconds_key(self):
        """Test microseconds key is recognized."""
        config_dict = {
            "logging": {
                "level": "info",
                "microseconds": True,
            }
        }
        config = LogConfig.from_config(config_dict, "logging")
        assert config.micros is True

    def test_from_config_dict_with_colors_dict(self):
        """Test colors as dictionary with enabled key."""
        config_dict = {
            "logging": {
                "level": "info",
                "colors": {"enabled": False},
            }
        }
        config = LogConfig.from_config(config_dict, "logging")
        assert config.colors is False

    def test_from_config_dict_nested_section(self):
        """Test nested section path."""
        config_dict = {
            "app": {
                "test": {
                    "logging": {
                        "level": "warning",
                        "location": 3,
                    }
                }
            }
        }
        config = LogConfig.from_config(config_dict, "app.test.logging")
        assert config.level == logging.WARNING
        assert config.location == 3

    def test_from_config_dict_missing_section_uses_defaults(self):
        """Test missing section falls back to defaults."""
        config_dict = {"other": "value"}
        config = LogConfig.from_config(config_dict, "nonexistent")
        assert config.level == logging.INFO  # default
        assert config.location == 0  # default
        assert config.micros is False  # default

    def test_from_config_dict_false_string_disables_logging(self):
        """Test string 'false' disables logging."""
        config_dict = {"logging": {"level": "false"}}
        config = LogConfig.from_config(config_dict, "logging")
        assert config.level is False

    def test_config_is_frozen(self):
        """Test LogConfig is immutable."""
        config = LogConfig.from_params("info", location=0)
        with pytest.raises(Exception):  # FrozenInstanceError
            config.level = logging.DEBUG

    def test_from_params_with_location_color(self):
        """Test creating LogConfig with location_color."""
        from appinfra.log.colors import ColorManager

        config = LogConfig.from_params(
            "info", location=1, location_color=ColorManager.CYAN
        )
        assert config.location_color == ColorManager.CYAN

    def test_from_params_default_location_color(self):
        """Test default location_color is None."""
        config = LogConfig.from_params("info", location=1)
        assert config.location_color is None

    def test_from_config_dict_with_location_color(self):
        """Test creating LogConfig from config dict with location_color."""
        from appinfra.log.colors import ColorManager

        config_dict = {
            "logging": {
                "level": "info",
                "location": 1,
                "location_color": ColorManager.CYAN,
            }
        }
        config = LogConfig.from_config(config_dict, "logging")
        assert config.location_color == ColorManager.CYAN

    def test_from_config_dict_with_location_color_name(self):
        """Test creating LogConfig from config dict with color name."""
        from appinfra.log.colors import ColorManager

        config_dict = {
            "logging": {
                "level": "info",
                "location": 1,
                "location_color": "cyan",
            }
        }
        config = LogConfig.from_config(config_dict, "logging")
        assert config.location_color == ColorManager.CYAN

    def test_from_config_dict_with_gray_color_name(self):
        """Test creating LogConfig from config dict with gray level name."""
        from appinfra.log.colors import ColorManager

        config_dict = {
            "logging": {
                "level": "info",
                "location": 1,
                "location_color": "gray-12",
            }
        }
        config = LogConfig.from_config(config_dict, "logging")
        assert config.location_color == ColorManager.create_gray_level(12)

    def test_from_config_dict_with_invalid_color_name(self):
        """Test creating LogConfig from config dict with invalid color name."""
        config_dict = {
            "logging": {
                "level": "info",
                "location": 1,
                "location_color": "notacolor",
            }
        }
        config = LogConfig.from_config(config_dict, "logging")
        # Invalid color name is kept as-is (for backwards compatibility with raw ANSI codes)
        assert config.location_color == "notacolor"

    def test_default_values(self):
        """Test LogConfig default values."""
        config = LogConfig()
        assert config.location == 0
        assert config.micros is False
        assert config.colors is True
        assert config.level == logging.INFO


# =============================================================================
# Test CallbackRegistry
# =============================================================================


@pytest.mark.unit
class TestCallbackRegistry:
    """Test CallbackRegistry functionality."""

    def test_init_creates_empty_registry(self):
        """Test initialization creates empty registry."""
        registry = CallbackRegistry()
        assert not registry.has_callbacks(logging.INFO)

    def test_register_callback(self):
        """Test registering a callback."""
        registry = CallbackRegistry()
        callback = Mock()
        registry.register(logging.INFO, callback, inherit=False)
        assert registry.has_callbacks(logging.INFO)
        assert registry.get_callback_count(logging.INFO) == 1

    def test_register_non_callable_raises_error(self):
        """Test registering non-callable raises CallbackError."""
        registry = CallbackRegistry()
        with pytest.raises(CallbackError, match="must be callable"):
            registry.register(logging.INFO, "not_callable")

    def test_register_multiple_callbacks_same_level(self):
        """Test multiple callbacks for same level."""
        registry = CallbackRegistry()
        callback1 = Mock()
        callback2 = Mock()
        registry.register(logging.INFO, callback1)
        registry.register(logging.INFO, callback2)
        assert registry.get_callback_count(logging.INFO) == 2

    def test_trigger_callbacks(self):
        """Test triggering callbacks."""
        registry = CallbackRegistry()
        callback = Mock()
        registry.register(logging.INFO, callback)

        mock_logger = Mock()
        registry.trigger(logging.INFO, mock_logger, "test message", (), {})

        callback.assert_called_once_with(mock_logger, logging.INFO, "test message", ())

    def test_trigger_no_callbacks_does_nothing(self):
        """Test triggering level with no callbacks."""
        registry = CallbackRegistry()
        mock_logger = Mock()
        # Should not raise
        registry.trigger(logging.INFO, mock_logger, "test", (), {})

    def test_trigger_callback_error_does_not_break_logging(self):
        """Test callback errors don't break logging."""
        registry = CallbackRegistry()
        callback = Mock(side_effect=Exception("callback error"))
        registry.register(logging.INFO, callback)

        mock_logger = Mock()
        # Should not raise
        registry.trigger(logging.INFO, mock_logger, "test", (), {})

    def test_inherit_to_copies_inheritable_callbacks(self):
        """Test inheriting callbacks to another registry."""
        source = CallbackRegistry()
        target = CallbackRegistry()

        callback1 = Mock()
        callback2 = Mock()
        source.register(logging.INFO, callback1, inherit=True)
        source.register(logging.DEBUG, callback2, inherit=False)

        source.inherit_to(target)

        # Inheritable callback should be copied
        assert target.has_callbacks(logging.INFO)
        assert target.get_callback_count(logging.INFO) == 1

        # Non-inheritable callback should not be copied
        assert not target.has_callbacks(logging.DEBUG)

    def test_has_callbacks_false_for_unregistered_level(self):
        """Test has_callbacks returns False for unregistered level."""
        registry = CallbackRegistry()
        assert not registry.has_callbacks(logging.INFO)

    def test_get_callback_count_zero_for_unregistered_level(self):
        """Test get_callback_count returns 0 for unregistered level."""
        registry = CallbackRegistry()
        assert registry.get_callback_count(logging.INFO) == 0

    def test_clear_removes_all_callbacks(self):
        """Test clear removes all callbacks."""
        registry = CallbackRegistry()
        callback = Mock()
        registry.register(logging.INFO, callback)
        registry.register(logging.DEBUG, callback)

        registry.clear()

        assert not registry.has_callbacks(logging.INFO)
        assert not registry.has_callbacks(logging.DEBUG)

    def test_remove_callback_removes_specific_callback(self):
        """Test removing a specific callback."""
        registry = CallbackRegistry()
        callback1 = Mock()
        callback2 = Mock()
        registry.register(logging.INFO, callback1)
        registry.register(logging.INFO, callback2)

        result = registry.remove_callback(logging.INFO, callback1)

        assert result is True
        assert registry.get_callback_count(logging.INFO) == 1

    def test_remove_callback_returns_false_if_not_found(self):
        """Test remove_callback returns False if callback not found."""
        registry = CallbackRegistry()
        callback = Mock()

        result = registry.remove_callback(logging.INFO, callback)

        assert result is False

    def test_remove_callback_cleans_up_empty_level(self):
        """Test removing last callback removes level from registry."""
        registry = CallbackRegistry()
        callback = Mock()
        registry.register(logging.INFO, callback)

        registry.remove_callback(logging.INFO, callback)

        assert not registry.has_callbacks(logging.INFO)


# =============================================================================
# Test listens_for decorator
# =============================================================================


@pytest.mark.unit
class TestListensForDecorator:
    """Test listens_for decorator."""

    def test_decorator_registers_callback(self, basic_logger):
        """Test decorator registers callback with logger."""

        @listens_for(basic_logger, logging.INFO)
        def my_callback(logger, level, msg, args, **kwargs):
            pass

        assert basic_logger._callbacks.has_callbacks(logging.INFO)

    def test_decorator_with_inherit(self, basic_logger):
        """Test decorator with inherit parameter."""

        @listens_for(basic_logger, logging.INFO, inherit=True)
        def my_callback(logger, level, msg, args, **kwargs):
            pass

        assert basic_logger._callbacks.has_callbacks(logging.INFO)

    def test_decorator_on_non_callable_raises_error(self, basic_logger):
        """Test decorator on non-callable raises error."""
        with pytest.raises(CallbackError):
            listens_for(basic_logger, logging.INFO)("not_callable")


# =============================================================================
# Test Logger Initialization
# =============================================================================


@pytest.mark.unit
class TestLoggerInitialization:
    """Test Logger initialization."""

    def test_init_with_config_and_registry(self, basic_config, callback_registry):
        """Test initialization with explicit config and registry."""
        logger = Logger(
            "test", config=basic_config, callback_registry=callback_registry
        )
        assert logger.name == "test"
        assert logger.config == basic_config
        assert logger._callbacks == callback_registry

    def test_init_with_none_creates_defaults(self):
        """Test initialization with None creates default config and registry."""
        logger = Logger("test", config=None, callback_registry=None)
        assert isinstance(logger.config, LogConfig)
        assert isinstance(logger._callbacks, CallbackRegistry)
        assert logger.config.level == logging.INFO  # default

    def test_init_with_disabled_logging(self):
        """Test initialization with disabled logging."""
        config = LogConfig.from_params(False, location=0)
        logger = Logger("test", config=config)
        assert logger.disabled is True
        assert logger.level > logging.CRITICAL

    def test_init_with_extra_fields(self):
        """Test initialization with extra fields."""
        extra = {"request_id": "12345", "user": "alice"}
        logger = Logger("test", extra=extra)
        assert logger._extra == extra

    def test_init_with_ordered_dict_extra(self):
        """Test initialization with OrderedDict extra."""
        extra = collections.OrderedDict([("first", 1), ("second", 2)])
        logger = Logger("test", extra=extra)
        assert isinstance(logger._extra, collections.OrderedDict)


# =============================================================================
# Test Logger Properties
# =============================================================================


@pytest.mark.unit
class TestLoggerProperties:
    """Test Logger properties."""

    def test_config_property(self, basic_logger, basic_config):
        """Test config property returns LogConfig."""
        assert basic_logger.config == basic_config

    def test_location_property(self, basic_logger):
        """Test location property."""
        assert basic_logger.location == 0

    def test_micros_property(self, basic_logger):
        """Test micros property."""
        assert basic_logger.micros is False

    def test_disabled_property_get(self):
        """Test getting disabled property."""
        config = LogConfig.from_params(False, location=0)
        logger = Logger("test", config=config)
        assert logger.disabled is True

    def test_disabled_property_set(self, basic_logger):
        """Test setting disabled property."""
        basic_logger.disabled = True
        assert basic_logger.disabled is True

    def test_get_level(self):
        """Test get_level returns config level."""
        config = LogConfig.from_params("debug", location=0)
        logger = Logger("test", config=config)
        assert logger.get_level() == logging.DEBUG


# =============================================================================
# Test Logger makeRecord
# =============================================================================


@pytest.mark.unit
class TestLoggerMakeRecord:
    """Test Logger custom makeRecord functionality."""

    def test_makerecord_merges_extra_fields(self):
        """Test makeRecord merges pre-populated extra fields."""
        pre_extra = {"request_id": "12345"}
        logger = Logger("test", extra=pre_extra)

        record = logger.makeRecord(
            name="test",
            level=logging.INFO,
            fn="test.py",
            lno=10,
            msg="test message",
            args=(),
            exc_info=None,
            extra={"user": "alice"},
        )

        assert hasattr(record, "__infra__extra")
        extra = getattr(record, "__infra__extra")
        assert extra["request_id"] == "12345"
        assert extra["user"] == "alice"

    def test_makerecord_with_no_extra(self):
        """Test makeRecord with no extra fields."""
        logger = Logger("test")

        record = logger.makeRecord(
            name="test",
            level=logging.INFO,
            fn="test.py",
            lno=10,
            msg="test message",
            args=(),
            exc_info=None,
        )

        assert hasattr(record, "__infra__extra")
        assert getattr(record, "__infra__extra") == {}

    def test_makerecord_preserves_ordered_dict(self):
        """Test makeRecord preserves OrderedDict type."""
        pre_extra = collections.OrderedDict([("first", 1)])
        logger = Logger("test", extra=pre_extra)

        record = logger.makeRecord(
            name="test",
            level=logging.INFO,
            fn="test.py",
            lno=10,
            msg="test message",
            args=(),
            exc_info=None,
            extra=collections.OrderedDict([("second", 2)]),
        )

        assert isinstance(getattr(record, "__infra__extra"), collections.OrderedDict)


# =============================================================================
# Test Logger Custom Log Levels
# =============================================================================


@pytest.mark.unit
class TestLoggerCustomLevels:
    """Test custom log levels (trace, trace2)."""

    def test_trace_method_logs_when_enabled(self, basic_logger, mock_handler):
        """Test trace method logs when level is enabled."""
        basic_logger.setLevel(logging.TRACE)
        basic_logger.addHandler(mock_handler)

        with patch.object(basic_logger, "_log") as mock_log:
            basic_logger.trace("trace message")
            mock_log.assert_called_once()

    def test_trace_disabled_when_logging_disabled(self):
        """Test trace doesn't log when logging is disabled."""
        config = LogConfig.from_params(False, location=0)
        logger = Logger("test", config=config)

        with patch.object(logger, "_log") as mock_log:
            logger.trace("trace message")
            mock_log.assert_not_called()

    def test_trace2_method_logs_when_enabled(self, basic_logger):
        """Test trace2 method logs when level is enabled."""
        basic_logger.setLevel(logging.TRACE2)

        with patch.object(basic_logger, "_log") as mock_log:
            basic_logger.trace2("trace2 message")
            mock_log.assert_called_once()

    def test_trace2_disabled_when_logging_disabled(self):
        """Test trace2 doesn't log when logging is disabled."""
        config = LogConfig.from_params(False, location=0)
        logger = Logger("test", config=config)

        with patch.object(logger, "_log") as mock_log:
            logger.trace2("trace2 message")
            mock_log.assert_not_called()


# =============================================================================
# Test Logger _log Method
# =============================================================================


@pytest.mark.unit
class TestLoggerLogMethod:
    """Test Logger _log method with callback support."""

    def test_log_triggers_callbacks(self, basic_logger):
        """Test _log triggers registered callbacks."""
        callback = Mock()
        basic_logger._callbacks.register(logging.INFO, callback)

        basic_logger.info("test message")

        callback.assert_called_once()

    def test_log_with_disabled_logging_doesnt_call_callbacks(self):
        """Test _log doesn't trigger callbacks when disabled."""
        config = LogConfig.from_params(False, location=0)
        logger = Logger("test", config=config)
        callback = Mock()
        logger._callbacks.register(logging.INFO, callback)

        logger.info("test message")

        callback.assert_not_called()

    def test_log_handles_logging_errors_gracefully(self, basic_logger, capsys):
        """Test _log handles logging errors without crashing."""
        # Force an error by using invalid arguments
        with patch.object(logging.Logger, "_log", side_effect=Exception("log error")):
            # Should print error but not raise
            basic_logger.info("test message")

        captured = capsys.readouterr()
        assert "Logger failed" in captured.err


# =============================================================================
# Test Logger is_logged Method
# =============================================================================


@pytest.mark.unit
class TestLoggerIsLogged:
    """Test is_logged method."""

    def test_is_logged_true_for_enabled_level(self):
        """Test is_logged returns True for enabled levels."""
        config = LogConfig.from_params("info", location=0)
        logger = Logger("test", config=config)
        assert logger.is_logged(logging.INFO) is True
        assert logger.is_logged(logging.WARNING) is True

    def test_is_logged_false_for_disabled_level(self):
        """Test is_logged returns False for disabled levels."""
        config = LogConfig.from_params("info", location=0)
        logger = Logger("test", config=config)
        assert logger.is_logged(logging.DEBUG) is False

    def test_is_logged_false_when_logging_disabled(self):
        """Test is_logged returns False when logging is disabled."""
        config = LogConfig.from_params(False, location=0)
        logger = Logger("test", config=config)
        assert logger.is_logged(logging.CRITICAL) is False


# =============================================================================
# Test Logger findCaller
# =============================================================================


@pytest.mark.unit
class TestLoggerFindCaller:
    """Test findCaller and location tracking."""

    def test_findcaller_returns_caller_info(self, basic_logger):
        """Test findCaller returns standard file, line, function info."""
        pathname, lineno, func, sinfo = basic_logger.findCaller()
        # Returns standard types for compatibility with external formatters
        assert isinstance(pathname, str)
        assert isinstance(lineno, int)
        assert isinstance(func, str)

    def test_findcaller_with_location_tracking(self):
        """Test findCaller with location > 0 stores trace in instance storage."""
        import threading

        config = LogConfig.from_params("info", location=2)
        logger = Logger("test", config=config)

        pathname, lineno, func, sinfo = logger.findCaller()

        # Standard types for compatibility
        assert isinstance(pathname, str)
        assert isinstance(lineno, int)
        # Full trace stored in _pending_traces keyed by thread ID
        tid = threading.get_ident()
        assert tid in logger._pending_traces
        pathnames, linenos = logger._pending_traces[tid]
        assert isinstance(pathnames, list)
        assert isinstance(linenos, list)
        # Clean up for other tests
        logger._pending_traces.pop(tid, None)


# =============================================================================
# Test Integration Scenarios
# =============================================================================


@pytest.mark.integration
class TestIntegrationScenarios:
    """Test real-world logger usage scenarios."""

    def test_logger_with_callbacks_and_extra_fields(self):
        """Test logger with both callbacks and extra fields."""
        callback_called = []

        def callback(logger, level, msg, args, **kwargs):
            callback_called.append((level, msg))

        extra = {"request_id": "req-123"}
        logger = Logger("test", extra=extra)
        logger._callbacks.register(logging.INFO, callback)
        logger.addHandler(logging.NullHandler())

        logger.info("test message")

        assert len(callback_called) == 1
        assert callback_called[0][0] == logging.INFO
        assert callback_called[0][1] == "test message"

    def test_logger_inheritance_of_callbacks(self):
        """Test callback inheritance to child loggers."""
        parent_registry = CallbackRegistry()
        child_registry = CallbackRegistry()

        callback = Mock()
        parent_registry.register(logging.INFO, callback, inherit=True)
        parent_registry.inherit_to(child_registry)

        # Child should have inherited callback
        assert child_registry.has_callbacks(logging.INFO)

    def test_multiple_loggers_with_separate_registries(self):
        """Test multiple loggers with separate callback registries."""
        callback1 = Mock()
        callback2 = Mock()

        logger1 = Logger("logger1")
        logger2 = Logger("logger2")

        logger1._callbacks.register(logging.INFO, callback1)
        logger2._callbacks.register(logging.INFO, callback2)

        logger1.info("message 1")
        logger2.info("message 2")

        # Each logger should only trigger its own callback
        callback1.assert_called_once()
        callback2.assert_called_once()

    def test_logger_from_config_dict_integration(self):
        """Test creating logger from config dictionary."""
        config_dict = {
            "logging": {
                "level": "debug",
                "location": 1,
                "micros": True,
            }
        }
        log_config = LogConfig.from_config(config_dict, "logging")
        logger = Logger("test", config=log_config)

        assert logger.level == logging.DEBUG
        # location and micros are read from holder which is set via factory
        # Direct Logger creation doesn't set holder, so falls back to config
        assert logger.location == 1
        assert logger.micros is True


# =============================================================================
# Test Edge Cases
# =============================================================================


@pytest.mark.unit
class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_logger_with_empty_extra(self):
        """Test logger with empty extra dict."""
        logger = Logger("test", extra={})
        assert logger._extra == {}

    def test_callback_with_extra_kwargs(self):
        """Test callback receives extra kwargs."""
        callback = Mock()
        logger = Logger("test")
        logger._callbacks.register(logging.INFO, callback)

        logger.info("message", extra={"key": "value"})

        # Callback should be called (exact args depend on implementation)
        callback.assert_called_once()

    def test_multiple_callbacks_same_level_all_triggered(self):
        """Test all callbacks for same level are triggered."""
        callbacks = [Mock(), Mock(), Mock()]
        logger = Logger("test")

        for cb in callbacks:
            logger._callbacks.register(logging.INFO, cb)

        logger.info("test message")

        for cb in callbacks:
            cb.assert_called_once()

    def test_logger_name_preserved(self):
        """Test logger name is preserved correctly."""
        logger = Logger("my.custom.logger")
        assert logger.name == "my.custom.logger"

    def test_config_with_high_location_value(self):
        """Test config with high location tracking value."""
        config = LogConfig.from_params("info", location=10)
        logger = Logger("test", config=config)
        assert logger.location == 10


# =============================================================================
# Test Level Inheritance (Parent Chain)
# =============================================================================


@pytest.mark.unit
class TestLevelInheritance:
    """Test logger level inheritance through parent chain."""

    @pytest.fixture(autouse=True)
    def cleanup_loggers(self):
        """Clean up loggers before and after each test."""
        # Clean up before test
        for name in list(logging.root.manager.loggerDict.keys()):
            if name.startswith("/"):
                del logging.root.manager.loggerDict[name]
        yield
        # Clean up after test
        for name in list(logging.root.manager.loggerDict.keys()):
            if name.startswith("/"):
                del logging.root.manager.loggerDict[name]

    def test_child_inherits_parent_level_change(self):
        """Test child logger respects parent level changes."""
        from appinfra.log.factory import LoggerFactory

        config = LogConfig.from_params("info")
        root = LoggerFactory.create_root(config)
        child = LoggerFactory.create_child(root, "test_child")

        # Initially, DEBUG should be disabled (root is INFO)
        assert not root.isEnabledFor(logging.DEBUG)
        assert not child.isEnabledFor(logging.DEBUG)

        # Change root to DEBUG
        root.setLevel(logging.DEBUG)
        assert root.isEnabledFor(logging.DEBUG)
        assert child.isEnabledFor(logging.DEBUG)

        # Change root back to INFO
        root.setLevel(logging.INFO)
        assert not root.isEnabledFor(logging.DEBUG)
        assert not child.isEnabledFor(logging.DEBUG)

    def test_grandchild_inherits_root_level_change(self):
        """Test grandchild logger respects root level changes."""
        from appinfra.log.factory import LoggerFactory

        config = LogConfig.from_params("info")
        root = LoggerFactory.create_root(config)
        child = LoggerFactory.create_child(root, "test_child2")
        grandchild = LoggerFactory.create_child(child, "test_grandchild")

        # Initially, DEBUG should be disabled
        assert not grandchild.isEnabledFor(logging.DEBUG)

        # Change root to DEBUG
        root.setLevel(logging.DEBUG)
        assert grandchild.isEnabledFor(logging.DEBUG)

        # Change root back to INFO
        root.setLevel(logging.INFO)
        assert not grandchild.isEnabledFor(logging.DEBUG)

    def test_child_level_notset_by_default(self):
        """Test child logger has NOTSET level by default."""
        from appinfra.log.factory import LoggerFactory

        config = LogConfig.from_params("info")
        root = LoggerFactory.create_root(config)
        child = LoggerFactory.create_child(root, "test_child3")

        # Child should have NOTSET level
        assert child.level == logging.NOTSET

    def test_parent_reference_set_correctly(self):
        """Test parent reference is set on child loggers."""
        import logging

        from appinfra.log.factory import LoggerFactory

        config = LogConfig.from_params("info")
        root = LoggerFactory.create_root(config)
        child = LoggerFactory.create_child(root, "test_child4")
        grandchild = LoggerFactory.create_child(child, "test_grandchild4")

        assert child.parent is root
        assert grandchild.parent is child
        # Root logger's parent is logging.root for proper propagation
        assert root.parent is logging.root

    def test_setlevel_clears_cache(self):
        """Test that setLevel clears the logger's cache."""
        from appinfra.log.factory import LoggerFactory

        config = LogConfig.from_params("info")
        root = LoggerFactory.create_root(config)

        # Populate cache by calling isEnabledFor
        root.isEnabledFor(logging.DEBUG)
        assert len(root._cache) > 0

        # setLevel should clear cache
        root.setLevel(logging.DEBUG)
        assert len(root._cache) == 0

    def test_deep_nesting_inherits_level(self):
        """Test level inheritance works with deeply nested loggers."""
        from appinfra.log.factory import LoggerFactory

        config = LogConfig.from_params("warning")
        root = LoggerFactory.create_root(config)

        # Create deep hierarchy
        level1 = LoggerFactory.create_child(root, "l1")
        level2 = LoggerFactory.create_child(level1, "l2")
        level3 = LoggerFactory.create_child(level2, "l3")
        level4 = LoggerFactory.create_child(level3, "l4")
        level5 = LoggerFactory.create_child(level4, "l5")

        # All should respect WARNING level
        assert not level5.isEnabledFor(logging.INFO)
        assert level5.isEnabledFor(logging.WARNING)

        # Change root to DEBUG
        root.setLevel(logging.DEBUG)
        assert level5.isEnabledFor(logging.DEBUG)

        # Change root to ERROR
        root.setLevel(logging.ERROR)
        assert not level5.isEnabledFor(logging.WARNING)
        assert level5.isEnabledFor(logging.ERROR)

    def test_multiple_level_changes(self):
        """Test multiple consecutive level changes are respected."""
        from appinfra.log.factory import LoggerFactory

        config = LogConfig.from_params("info")
        root = LoggerFactory.create_root(config)
        child = LoggerFactory.create_child(root, "test_multi")

        levels = [
            logging.DEBUG,
            logging.INFO,
            logging.WARNING,
            logging.ERROR,
            logging.DEBUG,
        ]

        for level in levels:
            root.setLevel(level)
            assert root.level == level
            assert child.isEnabledFor(level)
            if level > logging.DEBUG:
                assert not child.isEnabledFor(logging.DEBUG)

    def test_does_not_interfere_with_plain_python_loggers(self):
        """Test our isEnabledFor doesn't break plain Python loggers."""
        from appinfra.log.factory import LoggerFactory

        # Create our logger first (sets logging.setLoggerClass)
        config = LogConfig.from_params("info")
        root = LoggerFactory.create_root(config)

        # Create a plain Python logger (will use our Logger class due to setLoggerClass)
        plain = logging.getLogger("plain.test.logger")
        plain.setLevel(logging.DEBUG)

        # Should work correctly - plain logger's parent is logging.root
        # which doesn't have _root_logger, so we don't walk up the chain
        assert plain.isEnabledFor(logging.DEBUG)

    def test_child_more_restrictive_than_parent(self):
        """Test child can be more restrictive than parent when explicitly set."""
        from appinfra.log.factory import LoggerFactory

        config = LogConfig.from_params("debug")
        root = LoggerFactory.create_root(config)
        child = LoggerFactory.create_child(root, "restrictive_child")

        # Child starts with NOTSET, inherits DEBUG
        assert child.isEnabledFor(logging.DEBUG)

        # Explicitly set child to WARNING
        child.setLevel(logging.WARNING)
        assert not child.isEnabledFor(logging.INFO)
        assert child.isEnabledFor(logging.WARNING)

        # But parent is still DEBUG
        assert root.isEnabledFor(logging.DEBUG)
