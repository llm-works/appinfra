"""
Tests for base logging builder.

Tests key functionality including:
- with_location method
- with_micros method
- with_extra method
- Exception handling in _add_handlers
- create_logger convenience function
"""

import logging
import tempfile
from pathlib import Path
from unittest.mock import Mock

import pytest

from appinfra.log.builder.builder import LoggingBuilder, create_logger
from appinfra.log.builder.interface import HandlerConfig
from appinfra.log.errors import LogConfigurationError
from appinfra.log.logger import Logger

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def temp_log_dir():
    """Create temporary directory for log files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


# =============================================================================
# Test LoggingBuilder Basic Methods
# =============================================================================


@pytest.mark.unit
class TestLoggingBuilderBasic:
    """Test LoggingBuilder basic methods."""

    def test_init(self):
        """Test basic initialization."""
        builder = LoggingBuilder("test_logger")

        assert builder._name == "test_logger"
        assert builder._level == "info"
        assert builder._location == 0
        assert builder._micros is False
        assert builder._colors is True
        assert builder._handlers == []
        assert builder._logger_class == Logger
        assert builder._extra == {}

    def test_with_level_string(self):
        """Test with_level with string."""
        builder = LoggingBuilder("test")
        result = builder.with_level("debug")

        assert result is builder
        assert builder._level == "debug"

    def test_with_level_int(self):
        """Test with_level with integer."""
        builder = LoggingBuilder("test")
        result = builder.with_level(logging.WARNING)

        assert result is builder
        assert builder._level == logging.WARNING

    def test_with_colors(self):
        """Test with_colors method."""
        builder = LoggingBuilder("test")

        result = builder.with_colors(False)
        assert result is builder
        assert builder._colors is False

        builder.with_colors(True)
        assert builder._colors is True

    def test_with_location_color(self):
        """Test with_location_color method."""
        from appinfra.log.colors import ColorManager

        builder = LoggingBuilder("test")
        result = builder.with_location_color(ColorManager.CYAN)

        assert result is builder
        assert builder._location_color == ColorManager.CYAN

    def test_with_location_color_default_none(self):
        """Test location_color defaults to None."""
        builder = LoggingBuilder("test")
        assert builder._location_color is None

    def test_with_location_color_gray_level(self):
        """Test with_location_color with gray level."""
        from appinfra.log.colors import ColorManager

        builder = LoggingBuilder("test")
        gray_color = ColorManager.create_gray_level(12)
        result = builder.with_location_color(gray_color)

        assert result is builder
        assert builder._location_color == gray_color


# =============================================================================
# Test Missing Coverage - Lines 77-78, 90-91, 137-138, 153-154
# =============================================================================


@pytest.mark.unit
class TestMissingCoverage:
    """Tests targeting specific uncovered lines."""

    def test_with_location_bool(self):
        """Test with_location with bool (lines 77-78)."""
        builder = LoggingBuilder("test")
        result = builder.with_location(True)

        assert result is builder  # Returns self for chaining
        assert builder._location is True

    def test_with_location_int(self):
        """Test with_location with integer (lines 77-78)."""
        builder = LoggingBuilder("test")
        result = builder.with_location(2)

        assert result is builder
        assert builder._location == 2

    def test_with_location_zero(self):
        """Test with_location with zero."""
        builder = LoggingBuilder("test")
        builder.with_location(0)

        assert builder._location == 0

    def test_with_micros_true(self):
        """Test with_micros enabled (lines 90-91)."""
        builder = LoggingBuilder("test")
        result = builder.with_micros(True)

        assert result is builder
        assert builder._micros is True

    def test_with_micros_false(self):
        """Test with_micros disabled."""
        builder = LoggingBuilder("test")
        builder.with_micros(True)
        result = builder.with_micros(False)

        assert result is builder
        assert builder._micros is False

    def test_with_micros_default_true(self):
        """Test with_micros with default argument."""
        builder = LoggingBuilder("test")
        result = builder.with_micros()

        assert result is builder
        assert builder._micros is True

    def test_with_extra_single_field(self):
        """Test with_extra with single field (lines 153-154)."""
        builder = LoggingBuilder("test")
        result = builder.with_extra(service="api")

        assert result is builder
        assert builder._extra == {"service": "api"}

    def test_with_extra_multiple_fields(self):
        """Test with_extra with multiple fields."""
        builder = LoggingBuilder("test")
        result = builder.with_extra(service="api", version="1.0.0", env="prod")

        assert result is builder
        assert builder._extra == {"service": "api", "version": "1.0.0", "env": "prod"}

    def test_with_extra_chained_calls(self):
        """Test chained with_extra calls accumulate fields."""
        builder = LoggingBuilder("test")
        builder.with_extra(service="api").with_extra(version="2.0.0")

        assert builder._extra == {"service": "api", "version": "2.0.0"}

    def test_with_extra_overwrites_existing(self):
        """Test with_extra overwrites existing keys."""
        builder = LoggingBuilder("test")
        builder.with_extra(service="api").with_extra(service="web")

        assert builder._extra == {"service": "web"}


# =============================================================================
# Test Exception Handling - Lines 328-329
# =============================================================================


@pytest.mark.unit
class TestExceptionHandling:
    """Test exception handling in builder."""

    def test_add_handlers_raises_on_handler_creation_failure(self):
        """Test _add_handlers raises LogConfigurationError on failure (lines 328-329)."""
        builder = LoggingBuilder("test")

        # Create a mock handler config that raises an exception
        mock_handler_config = Mock(spec=HandlerConfig)
        mock_handler_config.create_handler.side_effect = RuntimeError(
            "Handler creation failed"
        )

        builder._handlers.append(mock_handler_config)

        with pytest.raises(LogConfigurationError, match="Failed to create handler"):
            builder.build()

    def test_add_handlers_wraps_original_exception(self):
        """Test that original exception message is included."""
        builder = LoggingBuilder("test")

        mock_handler_config = Mock(spec=HandlerConfig)
        mock_handler_config.create_handler.side_effect = ValueError(
            "Invalid configuration"
        )

        builder._handlers.append(mock_handler_config)

        with pytest.raises(LogConfigurationError, match="Invalid configuration"):
            builder.build()

    def test_add_handlers_various_exception_types(self):
        """Test handler failure with different exception types."""
        for exc_type in [IOError, OSError, TypeError]:
            builder = LoggingBuilder("test")

            mock_handler_config = Mock(spec=HandlerConfig)
            mock_handler_config.create_handler.side_effect = exc_type("Test error")

            builder._handlers.append(mock_handler_config)

            with pytest.raises(LogConfigurationError):
                builder.build()


# =============================================================================
# Test create_logger Function - Line 342
# =============================================================================


@pytest.mark.unit
class TestCreateLoggerFunction:
    """Test create_logger convenience function."""

    def test_create_logger_returns_builder(self):
        """Test create_logger returns LoggingBuilder (line 342)."""
        builder = create_logger("my_logger")

        assert isinstance(builder, LoggingBuilder)
        assert builder._name == "my_logger"

    def test_create_logger_allows_chaining(self):
        """Test create_logger result allows method chaining."""
        builder = (
            create_logger("test")
            .with_level("debug")
            .with_location(1)
            .with_micros()
            .with_colors(True)
        )

        assert builder._level == "debug"
        assert builder._location == 1
        assert builder._micros is True
        assert builder._colors is True

    def test_create_logger_with_different_names(self):
        """Test create_logger with various logger names."""
        names = ["app", "app.module", "my.nested.logger", "__main__"]

        for name in names:
            builder = create_logger(name)
            assert builder._name == name


# =============================================================================
# Test with_config Method
# =============================================================================


@pytest.mark.unit
class TestWithConfig:
    """Test with_config method."""

    def test_with_config_full_dict(self):
        """Test with_config with all parameters."""
        builder = LoggingBuilder("test")
        config = {
            "level": "error",
            "location": 2,
            "micros": True,
            "colors": False,
        }

        result = builder.with_config(config)

        assert result is builder
        assert builder._level == "error"
        assert builder._location == 2
        assert builder._micros is True
        assert builder._colors is False

    def test_with_config_partial_dict(self):
        """Test with_config with partial parameters."""
        builder = LoggingBuilder("test")
        builder.with_config({"level": "warning", "micros": True})

        assert builder._level == "warning"
        assert builder._micros is True
        # Unchanged values
        assert builder._location == 0
        assert builder._colors is True

    def test_with_config_empty_dict(self):
        """Test with_config with empty dict does nothing."""
        builder = LoggingBuilder("test")
        builder.with_config({})

        # All defaults
        assert builder._level == "info"
        assert builder._location == 0
        assert builder._micros is False
        assert builder._colors is True

    def test_with_config_includes_location_color(self):
        """Test with_config with location_color parameter."""
        from appinfra.log.colors import ColorManager

        builder = LoggingBuilder("test")
        config = {
            "level": "info",
            "location": 1,
            "location_color": ColorManager.CYAN,
        }

        result = builder.with_config(config)

        assert result is builder
        assert builder._location_color == ColorManager.CYAN


# =============================================================================
# Test Handler Methods
# =============================================================================


@pytest.mark.unit
class TestHandlerMethods:
    """Test handler configuration methods."""

    def test_with_handler(self):
        """Test with_handler adds handler config."""
        builder = LoggingBuilder("test")
        mock_handler = Mock(spec=HandlerConfig)

        result = builder.with_handler(mock_handler)

        assert result is builder
        assert len(builder._handlers) == 1
        assert builder._handlers[0] is mock_handler

    def test_with_console_handler(self):
        """Test with_console_handler."""
        builder = LoggingBuilder("test")
        result = builder.with_console_handler()

        assert result is builder
        assert len(builder._handlers) == 1

    def test_with_file_handler(self, temp_log_dir):
        """Test with_file_handler."""
        log_file = temp_log_dir / "test.log"
        builder = LoggingBuilder("test")
        result = builder.with_file_handler(log_file)

        assert result is builder
        assert len(builder._handlers) == 1

    def test_with_rotating_file_handler(self, temp_log_dir):
        """Test with_rotating_file_handler."""
        log_file = temp_log_dir / "test.log"
        builder = LoggingBuilder("test")
        result = builder.with_rotating_file_handler(
            log_file, max_bytes=1024, backup_count=3
        )

        assert result is builder
        assert len(builder._handlers) == 1

    def test_with_timed_rotating_file_handler(self, temp_log_dir):
        """Test with_timed_rotating_file_handler."""
        log_file = temp_log_dir / "test.log"
        builder = LoggingBuilder("test")
        result = builder.with_timed_rotating_file_handler(
            log_file, when="midnight", backup_count=7
        )

        assert result is builder
        assert len(builder._handlers) == 1


# =============================================================================
# Test Integration Scenarios
# =============================================================================


@pytest.mark.integration
class TestIntegrationScenarios:
    """Test real-world builder usage scenarios."""

    def test_full_builder_chain(self, temp_log_dir):
        """Test complete builder configuration chain."""
        log_file = temp_log_dir / "app.log"
        builder = (
            create_logger("app")
            .with_level("debug")
            .with_location(1)
            .with_micros()
            .with_colors(False)
            .with_extra(service="test", version="1.0")
            .with_file_handler(log_file)
        )

        assert builder._level == "debug"
        assert builder._location == 1
        assert builder._micros is True
        assert builder._colors is False
        assert builder._extra == {"service": "test", "version": "1.0"}
        assert len(builder._handlers) == 1

    def test_build_logger_with_file_handler(self, temp_log_dir):
        """Test building complete logger with file handler."""
        log_file = temp_log_dir / "app.log"
        builder = (
            LoggingBuilder("test_app")
            .with_level(logging.INFO)
            .with_file_handler(log_file)
        )

        logger = builder.build()

        assert logger is not None
        assert len(logger.handlers) == 1

        # Clean up
        for handler in logger.handlers[:]:
            handler.close()
            logger.removeHandler(handler)

    def test_build_with_extra_fields(self):
        """Test that extra fields are passed to logger."""
        builder = (
            LoggingBuilder("extra_test")
            .with_level("debug")
            .with_extra(service="api", version="2.0")
            .with_console_handler()
        )

        logger = builder.build()
        assert logger is not None

        # Clean up
        for handler in logger.handlers[:]:
            handler.close()
            logger.removeHandler(handler)

    def test_multiple_handlers(self, temp_log_dir):
        """Test builder with multiple handlers."""
        log_file = temp_log_dir / "multi.log"
        builder = (
            LoggingBuilder("multi")
            .with_level("info")
            .with_console_handler()
            .with_file_handler(log_file)
        )

        assert len(builder._handlers) == 2

        logger = builder.build()
        assert len(logger.handlers) == 2

        # Clean up
        for handler in logger.handlers[:]:
            handler.close()
            logger.removeHandler(handler)
