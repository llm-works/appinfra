"""
Tests for log/handler_factory.py.

Tests key functionality including:
- Helper functions for handler configuration
- HandlerFactory class
- HandlerRegistry class
"""

import logging
import sys
from unittest.mock import Mock

import pytest

from appinfra.log.errors import LogConfigError
from appinfra.log.handler_factory import (
    HandlerFactory,
    HandlerRegistry,
    _convert_console_stream,
    _create_database_handler,
    _create_file_handler,
    _create_rotating_file_handler,
    _extract_json_format_options,
    _filter_metadata_fields,
    _is_handler_enabled,
    _preserve_special_fields,
    _resolve_log_level,
    _set_handler_name,
    _validate_handler_type,
)

# =============================================================================
# Test Helper Functions
# =============================================================================


@pytest.mark.unit
class TestValidateHandlerType:
    """Test _validate_handler_type helper."""

    def test_passes_when_type_present(self):
        """Test does nothing when type is present."""
        config = {"type": "console"}

        # Should not raise
        _validate_handler_type(config)

    def test_raises_when_type_missing(self):
        """Test raises LogConfigError when type missing."""
        config = {"level": "info"}

        with pytest.raises(LogConfigError) as exc_info:
            _validate_handler_type(config)

        assert "type" in str(exc_info.value)


@pytest.mark.unit
class TestIsHandlerEnabled:
    """Test _is_handler_enabled helper."""

    def test_returns_true_when_enabled(self):
        """Test returns True when enabled is True."""
        config = {"enabled": True}

        assert _is_handler_enabled(config) is True

    def test_returns_false_when_disabled(self):
        """Test returns False when enabled is False."""
        config = {"enabled": False}

        assert _is_handler_enabled(config) is False

    def test_returns_true_when_not_specified(self):
        """Test returns True when enabled not specified."""
        config = {}

        assert _is_handler_enabled(config) is True


@pytest.mark.unit
class TestFilterMetadataFields:
    """Test _filter_metadata_fields helper."""

    def test_removes_type_and_enabled(self):
        """Test removes type and enabled fields."""
        config = {
            "type": "console",
            "enabled": True,
            "level": "info",
            "format": "text",
        }

        result = _filter_metadata_fields(config)

        assert "type" not in result
        assert "enabled" not in result
        assert result["level"] == "info"
        assert result["format"] == "text"


@pytest.mark.unit
class TestResolveLogLevel:
    """Test _resolve_log_level helper."""

    def test_does_nothing_when_no_level(self):
        """Test does nothing when level not in config."""
        config = {}

        _resolve_log_level(config, None)

        assert "level" not in config

    def test_converts_string_level(self):
        """Test converts string level to int."""
        config = {"level": "debug"}

        _resolve_log_level(config, None)

        assert config["level"] == logging.DEBUG

    def test_converts_bool_level(self):
        """Test converts bool level."""
        config = {"level": True}
        _resolve_log_level(config, None)
        assert config["level"] == logging.INFO

        config = {"level": False}
        _resolve_log_level(config, None)
        assert config["level"] == 1000  # Disabled

    def test_uses_global_level_when_more_restrictive(self):
        """Test uses global level when more restrictive."""
        config = {"level": "debug"}

        _resolve_log_level(config, logging.WARNING)

        assert config["level"] == logging.WARNING


@pytest.mark.unit
class TestPreserveSpecialFields:
    """Test _preserve_special_fields helper."""

    def test_preserves_file_field_for_file_handler(self):
        """Test preserves 'file' field for file handlers."""
        handler_config = {"file": "/var/log/app.log"}
        filtered_config = {}

        _preserve_special_fields("file", handler_config, filtered_config)

        assert filtered_config["file"] == "/var/log/app.log"

    def test_preserves_table_field_for_database_handler(self):
        """Test preserves 'table' field for database handlers."""
        handler_config = {"table": "logs"}
        filtered_config = {}

        _preserve_special_fields("database", handler_config, filtered_config)

        assert filtered_config["table"] == "logs"


@pytest.mark.unit
class TestConvertConsoleStream:
    """Test _convert_console_stream helper."""

    def test_converts_stderr_string(self):
        """Test converts 'stderr' string to sys.stderr."""
        config = {"stream": "stderr"}

        _convert_console_stream(config)

        assert config["stream"] is sys.stderr

    def test_converts_stdout_string(self):
        """Test converts 'stdout' string to sys.stdout."""
        config = {"stream": "stdout"}

        _convert_console_stream(config)

        assert config["stream"] is sys.stdout

    def test_does_nothing_for_non_string(self):
        """Test does nothing when stream is not string."""
        config = {"stream": sys.stderr}

        _convert_console_stream(config)

        assert config["stream"] is sys.stderr

    def test_does_nothing_when_no_stream(self):
        """Test does nothing when stream not in config."""
        config = {}

        _convert_console_stream(config)

        assert "stream" not in config


@pytest.mark.unit
class TestExtractJsonFormatOptions:
    """Test _extract_json_format_options helper."""

    def test_preserves_text_format(self):
        """Test preserves text format unchanged."""
        config = {"format": "text"}

        _extract_json_format_options(config)

        assert config["format"] == "text"

    def test_extracts_json_options(self):
        """Test extracts JSON-specific options."""
        config = {
            "format": "json",
            "timestamp_format": "%Y-%m-%d",
            "pretty_print": True,
            "custom_fields": {"app": "test"},
            "exclude_fields": ["debug"],
        }

        _extract_json_format_options(config)

        assert config["format"] == "json"
        assert config["format_timestamp_format"] == "%Y-%m-%d"
        assert config["format_pretty_print"] is True
        assert config["format_custom_fields"] == {"app": "test"}
        assert config["format_exclude_fields"] == ["debug"]
        # Original keys should be removed
        assert "timestamp_format" not in config
        assert "pretty_print" not in config


@pytest.mark.unit
class TestSetHandlerName:
    """Test _set_handler_name helper."""

    def test_sets_handler_name_when_present(self):
        """Test sets _handler_name attribute."""
        handler = Mock()
        config = {"_handler_name": "my_handler"}

        _set_handler_name(handler, config)

        assert handler._handler_name == "my_handler"

    def test_does_nothing_when_name_missing(self):
        """Test does nothing when _handler_name not in config."""
        handler = Mock(spec=[])
        config = {}

        _set_handler_name(handler, config)


# =============================================================================
# Test File Handler Creation Helpers
# =============================================================================


@pytest.mark.unit
class TestCreateFileHandler:
    """Test _create_file_handler helper."""

    def test_creates_handler_with_file_param(self):
        """Test creates handler using 'file' parameter."""
        handler_class = Mock()
        config = {"file": "/var/log/app.log", "level": 10}

        _create_file_handler(handler_class, config)

        handler_class.assert_called_once_with("/var/log/app.log", level=10)

    def test_creates_handler_with_filename_param(self):
        """Test creates handler using 'filename' parameter."""
        handler_class = Mock()
        config = {"filename": "/var/log/app.log"}

        _create_file_handler(handler_class, config)

        handler_class.assert_called_once_with("/var/log/app.log")

    def test_raises_when_no_filename(self):
        """Test raises when no filename provided."""
        handler_class = Mock()
        config = {"level": 10}

        with pytest.raises(LogConfigError) as exc_info:
            _create_file_handler(handler_class, config)

        assert "filename" in str(exc_info.value)


@pytest.mark.unit
class TestCreateRotatingFileHandler:
    """Test _create_rotating_file_handler helper."""

    def test_creates_handler_with_file_param(self):
        """Test creates handler using 'file' parameter."""
        handler_class = Mock()
        config = {"file": "/var/log/app.log", "maxBytes": 1024}

        _create_rotating_file_handler(handler_class, config)

        handler_class.assert_called_once_with("/var/log/app.log", maxBytes=1024)

    def test_raises_when_no_filename(self):
        """Test raises when no filename provided."""
        handler_class = Mock(__name__="RotatingFileHandler")
        config = {"maxBytes": 1024}

        with pytest.raises(LogConfigError) as exc_info:
            _create_rotating_file_handler(handler_class, config)

        assert "filename" in str(exc_info.value)


@pytest.mark.unit
class TestCreateDatabaseHandler:
    """Test _create_database_handler helper."""

    def test_creates_handler_with_required_params(self):
        """Test creates handler with table and db parameters."""
        handler_class = Mock()
        db_interface = Mock()
        config = {"table": "logs", "db": db_interface, "level": 10}

        _create_database_handler(handler_class, config)

        handler_class.assert_called_once_with("logs", db_interface, level=10)

    def test_raises_when_no_table(self):
        """Test raises when table not provided."""
        handler_class = Mock()
        config = {"db": Mock()}

        with pytest.raises(LogConfigError) as exc_info:
            _create_database_handler(handler_class, config)

        assert "table" in str(exc_info.value)

    def test_raises_when_no_db(self):
        """Test raises when db not provided."""
        handler_class = Mock()
        config = {"table": "logs"}

        with pytest.raises(LogConfigError) as exc_info:
            _create_database_handler(handler_class, config)

        assert "db" in str(exc_info.value)


# =============================================================================
# Test HandlerFactory
# =============================================================================


@pytest.mark.unit
class TestHandlerFactoryGetHandlerClass:
    """Test HandlerFactory.get_handler_class method."""

    def test_returns_console_handler_class(self):
        """Test returns ConsoleHandlerConfig for 'console'."""
        from appinfra.log.builder.console import ConsoleHandlerConfig

        result = HandlerFactory.get_handler_class("console")

        assert result is ConsoleHandlerConfig

    def test_returns_file_handler_class(self):
        """Test returns FileHandlerConfig for 'file'."""
        from appinfra.log.builder.file import FileHandlerConfig

        result = HandlerFactory.get_handler_class("file")

        assert result is FileHandlerConfig

    def test_raises_for_unknown_type(self):
        """Test raises LogConfigError for unknown type."""
        with pytest.raises(LogConfigError) as exc_info:
            HandlerFactory.get_handler_class("unknown")

        assert "Unknown handler type" in str(exc_info.value)
        assert "unknown" in str(exc_info.value)


@pytest.mark.unit
class TestHandlerFactoryGetSupportedTypes:
    """Test HandlerFactory.get_supported_types method."""

    def test_returns_list_of_types(self):
        """Test returns list of all supported types."""
        result = HandlerFactory.get_supported_types()

        assert "console" in result
        assert "file" in result
        assert "rotating_file" in result
        assert "timed_rotating_file" in result
        assert "database" in result


@pytest.mark.unit
class TestHandlerFactoryIterSupportedTypes:
    """Test HandlerFactory.iter_supported_types method."""

    def test_yields_all_types(self):
        """Test yields all supported types."""
        result = list(HandlerFactory.iter_supported_types())

        assert "console" in result
        assert "file" in result


@pytest.mark.unit
class TestHandlerFactoryCreateHandlerConfig:
    """Test HandlerFactory.create_handler_config method."""

    def test_creates_console_handler(self):
        """Test creates console handler config."""
        result = HandlerFactory.create_handler_config("console", {})

        from appinfra.log.builder.console import ConsoleHandlerConfig

        assert isinstance(result, ConsoleHandlerConfig)

    def test_raises_on_invalid_config(self):
        """Test raises LogConfigError on invalid config."""
        with pytest.raises(LogConfigError):
            # File handler requires filename
            HandlerFactory.create_handler_config("file", {})


# =============================================================================
# Test HandlerRegistry
# =============================================================================


@pytest.mark.unit
class TestHandlerRegistryInit:
    """Test HandlerRegistry initialization."""

    def test_init_with_global_level(self):
        """Test initialization with global level."""
        registry = HandlerRegistry(global_level=logging.WARNING)

        assert registry.global_level == logging.WARNING
        assert registry.handlers == []

    def test_init_without_global_level(self):
        """Test initialization without global level."""
        registry = HandlerRegistry()

        assert registry.global_level is None
        assert registry.handlers == []


@pytest.mark.unit
class TestHandlerRegistryAddHandler:
    """Test HandlerRegistry.add_handler_from_config method."""

    def test_adds_console_handler(self):
        """Test adds console handler from config."""
        registry = HandlerRegistry()
        config = {"type": "console", "level": "info"}

        registry.add_handler_from_config(config)

        assert len(registry.handlers) == 1

    def test_skips_disabled_handler(self):
        """Test skips disabled handlers."""
        registry = HandlerRegistry()
        config = {"type": "console", "enabled": False}

        registry.add_handler_from_config(config)

        assert len(registry.handlers) == 0

    def test_raises_for_missing_type(self):
        """Test raises for config without type."""
        registry = HandlerRegistry()
        config = {"level": "info"}

        with pytest.raises(LogConfigError):
            registry.add_handler_from_config(config)


@pytest.mark.unit
class TestHandlerRegistryGetHandler:
    """Test HandlerRegistry.get_handler method."""

    def test_returns_handler_by_index(self):
        """Test returns handler at specified index."""
        registry = HandlerRegistry()
        registry.add_handler_from_config({"type": "console"})

        result = registry.get_handler(0)

        assert result is not None

    def test_returns_none_for_invalid_index(self):
        """Test returns None for out of range index."""
        registry = HandlerRegistry()

        result = registry.get_handler(0)

        assert result is None

    def test_returns_none_for_negative_index(self):
        """Test returns None for negative index that's too large."""
        registry = HandlerRegistry()

        # Valid range is 0 to len-1
        result = registry.get_handler(-100)

        assert result is None


@pytest.mark.unit
class TestHandlerRegistryGetHandlerByName:
    """Test HandlerRegistry.get_handler_by_name method."""

    def test_returns_handler_by_name(self):
        """Test returns handler with matching _handler_name."""
        registry = HandlerRegistry()
        registry.add_handler_from_config(
            {"type": "console", "_handler_name": "console_handler"}
        )

        result = registry.get_handler_by_name("console_handler")

        assert result is not None
        assert result._handler_name == "console_handler"

    def test_returns_none_when_not_found(self):
        """Test returns None when name not found."""
        registry = HandlerRegistry()
        registry.add_handler_from_config({"type": "console"})

        result = registry.get_handler_by_name("nonexistent")

        assert result is None


@pytest.mark.unit
class TestHandlerRegistryGetEnabledHandlers:
    """Test HandlerRegistry.get_enabled_handlers method."""

    def test_returns_all_enabled_handlers(self):
        """Test returns all enabled handlers."""
        registry = HandlerRegistry()
        registry.add_handler_from_config({"type": "console"})
        registry.add_handler_from_config({"type": "console"})

        result = registry.get_enabled_handlers()

        assert len(result) == 2


@pytest.mark.unit
class TestHandlerRegistryIterHandlers:
    """Test HandlerRegistry.iter_handlers method."""

    def test_yields_all_handlers(self):
        """Test yields all handlers in order."""
        registry = HandlerRegistry()
        registry.add_handler_from_config({"type": "console"})
        registry.add_handler_from_config({"type": "console"})

        result = list(registry.iter_handlers())

        assert len(result) == 2


@pytest.mark.unit
class TestHandlerRegistryIterEnabledHandlers:
    """Test HandlerRegistry.iter_enabled_handlers method."""

    def test_yields_enabled_handlers(self):
        """Test yields only enabled handlers."""
        registry = HandlerRegistry()
        registry.add_handler_from_config({"type": "console"})

        result = list(registry.iter_enabled_handlers())

        assert len(result) == 1


@pytest.mark.unit
class TestHandlerRegistryLoadFromConfig:
    """Test HandlerRegistry.load_from_config method."""

    def test_loads_dict_config(self):
        """Test loads handlers from dictionary config."""
        registry = HandlerRegistry()
        config = {
            "console_handler": {"type": "console", "level": "info"},
            "debug_handler": {"type": "console", "level": "debug"},
        }

        registry.load_from_config(config)

        assert len(registry.handlers) == 2

    def test_sets_handler_names(self):
        """Test sets _handler_name from dict keys."""
        registry = HandlerRegistry()
        config = {
            "my_handler": {"type": "console"},
        }

        registry.load_from_config(config)

        assert registry.handlers[0]._handler_name == "my_handler"

    def test_raises_for_non_dict_config(self):
        """Test raises for non-dictionary config."""
        registry = HandlerRegistry()

        with pytest.raises(LogConfigError) as exc_info:
            registry.load_from_config(["invalid"])

        assert "dictionary" in str(exc_info.value)


# =============================================================================
# Integration Tests
# =============================================================================


@pytest.mark.integration
class TestHandlerFactoryIntegration:
    """Integration tests for handler factory."""

    def test_create_multiple_handler_types(self):
        """Test creating handlers of different types."""
        registry = HandlerRegistry()

        registry.add_handler_from_config({"type": "console", "level": "info"})
        # Note: file handler would need a filename, which we can't easily test here

        assert len(registry.handlers) >= 1

    def test_full_registry_workflow(self):
        """Test complete registry workflow."""
        registry = HandlerRegistry(global_level=logging.INFO)

        config = {
            "main_console": {
                "type": "console",
                "level": "debug",  # Will be adjusted to INFO
                "stream": "stdout",
            },
            "error_console": {
                "type": "console",
                "level": "error",
                "stream": "stderr",
            },
        }

        registry.load_from_config(config)

        assert len(registry.handlers) == 2
        assert registry.get_handler_by_name("main_console") is not None
        assert registry.get_handler_by_name("error_console") is not None

        enabled = list(registry.iter_enabled_handlers())
        assert len(enabled) == 2
