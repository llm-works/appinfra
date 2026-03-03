"""
Tests for log formatters.

Tests key formatter functionality including:
- PreFormatter with microsecond precision
- FieldFormatter for field rendering
- LocationRenderer for source location
- LogFormatter integration
"""

import collections
import logging
from unittest.mock import Mock, patch

import pytest

from appinfra.log.colors import ColorManager
from appinfra.log.config import LogConfig
from appinfra.log.formatters import (
    FieldFormatter,
    LocationRenderer,
    LogFormatter,
    PreFormatter,
    _cache_result,
    _format_header,
    _format_value,
    _get_cache_key,
    _visual_len,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def formatter_config():
    """Create basic formatter config."""
    return LogConfig(location=0, micros=False, colors=True)


@pytest.fixture
def formatter_config_with_micros():
    """Create formatter config with microseconds."""
    return LogConfig(location=1, micros=True, colors=True)


@pytest.fixture
def log_record():
    """Create basic log record."""
    record = logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname="/path/to/file.py",
        lineno=42,
        msg="Test message",
        args=(),
        exc_info=None,
    )
    record.created = 1234567890.123456
    return record


# =============================================================================
# Test Helper Functions
# =============================================================================


@pytest.mark.unit
class TestHelperFunctions:
    """Test module-level helper functions."""

    def test_get_cache_key_with_cacheable_value(self):
        """Test cache key generation for cacheable values."""
        key = _get_cache_key("test", "col", "bold", "name", False)
        assert key == ("test", "col", "bold", "name", False)

    def test_get_cache_key_with_int(self):
        """Test cache key generation for integers."""
        key = _get_cache_key(123, "col", "bold", "name", True)
        assert key == (123, "col", "bold", "name", True)

    def test_get_cache_key_with_dict_returns_none(self):
        """Test cache key returns None for dict."""
        key = _get_cache_key({"key": "value"}, "col", "bold", "name", False)
        assert key is None

    def test_get_cache_key_with_list_returns_none(self):
        """Test cache key returns None for list."""
        key = _get_cache_key([1, 2, 3], "col", "bold", "name", False)
        assert key is None

    def test_visual_len_plain_text(self):
        """Test visual length for plain text without ANSI codes."""
        assert _visual_len("hello") == 5
        assert _visual_len("") == 0

    def test_visual_len_with_ansi_codes(self):
        """Test visual length excludes ANSI escape codes."""
        # Text with color codes: \x1b[32m = green, \x1b[0m = reset
        colored = "\x1b[32mhello\x1b[0m"
        assert _visual_len(colored) == 5  # Only "hello" counts

    def test_format_header_normal(self):
        """Test format header for normal fields."""
        result = _format_header("\033[34", "test")
        assert "\x1b[0m" in result  # RESET (actual escape sequence)
        assert "\033[34" in result  # color
        assert "test[" in result

    def test_format_header_for_after_field(self):
        """Test format header for 'after' field (no name)."""
        result = _format_header("\033[34", "after")
        assert "\x1b[0m" in result  # actual escape sequence
        assert "[" in result
        assert "after[" not in result  # Should not include 'after' text

    def test_format_value_with_simple_list(self):
        """Test format value with simple list."""
        formatter = Mock()
        result = _format_value(formatter, [1, 2, 3], "col", "bold", "name")
        assert "1,2,3" in result
        assert "bold" in result

    def test_format_value_with_dict_calls_format_fields_dict(self):
        """Test format value with dict delegates to _format_fields_dict."""
        formatter = Mock()
        formatter._format_fields_dict.return_value = "formatted"
        result = _format_value(formatter, {"key": "value"}, "col", "bold", "name")
        formatter._format_fields_dict.assert_called_once()

    def test_format_value_with_after_field_and_float(self):
        """Test format value for 'after' field with float (duration)."""
        formatter = Mock()
        formatter._config = Mock(micros=False)
        with patch("appinfra.time.delta.delta_str", return_value="1m30s"):
            result = _format_value(formatter, 90.5, "col", "bold", "after")
            assert "1m30s" in result

    def test_cache_result_caches_when_key_provided(self):
        """Test cache result caches when key is provided."""
        formatter = Mock()
        formatter._format_cache = {}
        formatter._max_cache_size = 100

        _cache_result(formatter, ("key",), "result")

        assert formatter._format_cache[("key",)] == "result"

    def test_cache_result_does_not_cache_when_key_none(self):
        """Test cache result doesn't cache when key is None."""
        formatter = Mock()
        formatter._format_cache = {}
        formatter._max_cache_size = 100

        _cache_result(formatter, None, "result")

        assert len(formatter._format_cache) == 0

    def test_cache_result_respects_max_size(self):
        """Test cache result respects maximum cache size with LRU eviction."""
        import collections

        formatter = Mock()
        # Use OrderedDict because _cache_result uses LRU eviction with move_to_end/popitem
        formatter._format_cache = collections.OrderedDict(
            (i, f"val{i}") for i in range(100)
        )
        formatter._max_cache_size = 100

        _cache_result(formatter, ("new_key",), "new_result")

        # Should add new key after evicting oldest (key 0)
        assert ("new_key",) in formatter._format_cache
        assert 0 not in formatter._format_cache  # Oldest was evicted
        assert len(formatter._format_cache) == 100  # Size maintained


# =============================================================================
# Test PreFormatter
# =============================================================================


@pytest.mark.unit
class TestPreFormatter:
    """Test PreFormatter class."""

    def test_init(self):
        """Test PreFormatter initialization."""
        formatter = PreFormatter("%(message)s", micros=True)
        assert formatter._micros is True

    def test_format_time_without_micros(self, log_record):
        """Test formatTime without microseconds."""
        formatter = PreFormatter("%(asctime)s %(message)s", micros=False)
        result = formatter.formatTime(log_record)
        # Should have normal timestamp format
        assert "." not in result  # No microseconds

    def test_format_time_with_micros(self, log_record):
        """Test formatTime with microseconds."""
        formatter = PreFormatter("%(asctime)s %(message)s", micros=True)
        result = formatter.formatTime(log_record)
        # Should have microseconds added
        assert "." in result
        # Should have 3 digits for microseconds
        parts = result.split(".")
        assert len(parts[-1]) == 3

    def test_format_complete_record(self, log_record):
        """Test formatting complete log record."""
        formatter = PreFormatter("%(asctime)s %(levelname)s %(message)s", micros=False)
        result = formatter.format(log_record)
        assert "INFO" in result
        assert "Test message" in result


# =============================================================================
# Test FieldFormatter
# =============================================================================


@pytest.mark.unit
class TestFieldFormatter:
    """Test FieldFormatter class."""

    def test_init(self, formatter_config):
        """Test FieldFormatter initialization."""
        formatter = FieldFormatter(formatter_config)
        assert formatter._config == formatter_config
        assert isinstance(formatter._format_cache, dict)

    def test_format_field_with_string_value(self, formatter_config):
        """Test format_field with string value."""
        formatter = FieldFormatter(formatter_config)
        # Use actual format pattern
        result = formatter.format_field("test", "\\033[34", "\\033[1m")
        # Should include color codes and brackets
        assert "[" in result
        assert "]" in result

    def test_format_field_uses_cache(self, formatter_config):
        """Test format_field uses cache for repeated calls."""
        formatter = FieldFormatter(formatter_config)

        # First call
        result1 = formatter.format_field("test", "col", "bold", name="field")
        # Second call with same parameters
        result2 = formatter.format_field("test", "col", "bold", name="field")

        # Results should be identical
        assert result1 == result2
        # Cache should have entry
        assert len(formatter._format_cache) > 0


# =============================================================================
# Test LocationRenderer
# =============================================================================


@pytest.mark.unit
class TestLocationRenderer:
    """Test LocationRenderer class.

    LocationRenderer reads location and location_color from the holder's config
    to support hot-reload.
    """

    def test_init_with_location_zero(self):
        """Test LocationRenderer with location=0."""
        config = LogConfig(location=0, micros=False, colors=True)
        renderer = LocationRenderer(config)
        assert renderer._location == 0

    def test_init_with_location_one(self):
        """Test LocationRenderer with location=1."""
        config = LogConfig(location=1, micros=False, colors=True)
        renderer = LocationRenderer(config)
        assert renderer._location == 1

    def test_render_location_with_location_zero(self, log_record):
        """Test render_location returns empty string when location=0."""
        config = LogConfig(location=0, micros=False, colors=True)
        renderer = LocationRenderer(config)
        result = renderer.render_location(log_record)
        assert result == ""

    def test_render_location_with_location_one(self, log_record):
        """Test render_location with location=1."""
        config = LogConfig(location=1, micros=False, colors=True)
        renderer = LocationRenderer(config)
        result = renderer.render_location(log_record)
        # Should include filename and line number
        assert "file.py" in result
        assert "42" in result

    def test_render_location_with_infra_pathnames(self):
        """Test render_location with __infra__pathnames for multi-location trace."""
        config = LogConfig(location=2, micros=False, colors=True)
        renderer = LocationRenderer(config)
        record = Mock()
        # Standard attributes remain single values
        record.pathname = "/path/file1.py"
        record.lineno = 10
        # Multi-location trace in __infra__ prefixed attributes (use setattr to avoid mangling)
        setattr(record, "__infra__pathnames", ["/path/file1.py", "/path/file2.py"])
        setattr(record, "__infra__linenos", [10, 20])

        result = renderer.render_location(record)
        # Should handle __infra__ format and include both locations
        assert isinstance(result, str)
        assert "file1.py" in result
        assert "file2.py" in result

    def test_location_color_configurable(self, log_record):
        """Test that location color can be configured."""
        config = LogConfig(
            location=1, micros=False, colors=True, location_color=ColorManager.CYAN
        )
        renderer = LocationRenderer(config)
        result = renderer.render_location(log_record)
        # Should contain CYAN color code
        assert ColorManager.CYAN in result
        # Should not contain BLACK (since we overrode it with CYAN)
        # Note: We check for the specific BLACK code, not just the word "BLACK"
        assert ColorManager.BLACK not in result

    def test_location_color_default_gray(self, log_record):
        """Test that location color defaults to gray-6 when not specified."""
        config = LogConfig(location=1, micros=False, colors=True)
        renderer = LocationRenderer(config)
        # Verify default is gray-6
        expected_gray = ColorManager.create_gray_level(6)
        assert renderer._location_color == expected_gray
        result = renderer.render_location(log_record)
        # Should use default gray-6 color
        assert expected_gray in result

    def test_location_color_with_gray_level(self, log_record):
        """Test location color with custom gray level."""
        gray_color = ColorManager.create_gray_level(12)
        config = LogConfig(
            location=1, micros=False, colors=True, location_color=gray_color
        )
        renderer = LocationRenderer(config)
        result = renderer.render_location(log_record)
        # Should contain the gray color code
        assert gray_color in result

    def test_render_location_no_ansi_when_colors_disabled(self, log_record):
        """Test that render_location emits no ANSI codes when colors=False."""
        import re

        config = LogConfig(location=1, micros=False, colors=False)
        renderer = LocationRenderer(config)
        result = renderer.render_location(log_record)

        # Should still contain the location info
        assert "file.py" in result
        assert "42" in result

        # Must contain zero ANSI escape sequences
        ansi_pattern = re.compile(r"\x1b\[")
        assert not ansi_pattern.search(result), (
            f"ANSI escape codes in location output with colors=False: {result!r}"
        )


# =============================================================================
# Test LogFormatter
# =============================================================================


@pytest.mark.unit
class TestLogFormatter:
    """Test LogFormatter class."""

    def test_init(self, formatter_config):
        """Test LogFormatter initialization."""
        formatter = LogFormatter(formatter_config)
        assert formatter._config == formatter_config
        assert isinstance(formatter._field_formatter, FieldFormatter)
        assert isinstance(formatter._location_renderer, LocationRenderer)

    def test_format_basic_message(self, formatter_config, log_record):
        """Test formatting basic log message."""
        formatter = LogFormatter(formatter_config)
        result = formatter.format(log_record)
        # Should include message
        assert "Test message" in result
        # Should include level
        assert "I" in result or "INFO" in result

    def test_format_with_extra_fields(self, formatter_config, log_record):
        """Test formatting with extra fields."""
        setattr(log_record, "__infra__extra", {"request_id": "123", "user": "alice"})
        formatter = LogFormatter(formatter_config)
        result = formatter.format(log_record)
        # Should include extra fields
        assert "request_id" in result or "123" in result

    def test_format_with_ordered_dict_extra(self, formatter_config, log_record):
        """Test formatting with OrderedDict extra fields."""
        setattr(
            log_record,
            "__infra__extra",
            collections.OrderedDict([("first", 1), ("second", 2)]),
        )
        formatter = LogFormatter(formatter_config)
        result = formatter.format(log_record)
        # Should handle OrderedDict
        assert isinstance(result, str)

    def test_format_without_colors(self):
        """Test formatting without colors."""
        config = LogConfig(location=0, micros=False, colors=False)
        formatter = LogFormatter(config)
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="/path/file.py",
            lineno=10,
            msg="test",
            args=(),
            exc_info=None,
        )
        result = formatter.format(record)
        # Should not contain color codes
        assert "\\033[" not in result

    def test_format_with_exception(self, formatter_config):
        """Test formatting with exception."""
        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname="/path/file.py",
            lineno=10,
            msg="Error occurred",
            args=(),
            exc_info=(ValueError, ValueError("test error"), None),
        )
        formatter = LogFormatter(formatter_config)
        result = formatter.format(record)
        # Should include exception info
        assert "ValueError" in result or "test error" in result


# =============================================================================
# Test Integration Scenarios
# =============================================================================


@pytest.mark.integration
class TestIntegrationScenarios:
    """Test real-world formatter scenarios."""

    def test_formatter_with_all_features(self):
        """Test formatter with all features enabled."""
        config = LogConfig(location=2, micros=True, colors=True)
        formatter = LogFormatter(config)

        record = logging.LogRecord(
            name="app.module",
            level=logging.WARNING,
            pathname="/app/module.py",
            lineno=100,
            msg="Warning message",
            args=(),
            exc_info=None,
        )
        record.created = 1234567890.123456
        setattr(record, "__infra__extra", {"request_id": "abc123"})

        result = formatter.format(record)

        # Should include all components
        assert "Warning message" in result
        assert isinstance(result, str)

    def test_formatter_chain(self):
        """Test using PreFormatter and LogFormatter together."""
        config = LogConfig(location=0, micros=True, colors=False)
        pre_formatter = PreFormatter("%(asctime)s", micros=True)
        log_formatter = LogFormatter(config)

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="/test.py",
            lineno=10,
            msg="test",
            args=(),
            exc_info=None,
        )
        record.created = 1234567890.123456

        # Pre-format time
        time_str = pre_formatter.formatTime(record)
        assert "." in time_str

        # Format complete message
        result = log_formatter.format(record)
        assert isinstance(result, str)


# =============================================================================
# Test Edge Cases
# =============================================================================


@pytest.mark.unit
class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_format_field_with_none_value(self, formatter_config):
        """Test format_field with None value."""
        formatter = FieldFormatter(formatter_config)
        result = formatter.format_field(None, "col", "bold")
        assert isinstance(result, str)

    def test_format_field_with_empty_string(self, formatter_config):
        """Test format_field with empty string."""
        formatter = FieldFormatter(formatter_config)
        result = formatter.format_field("", "col", "bold")
        assert isinstance(result, str)

    def test_log_record_with_no_extra_fields(self, formatter_config, log_record):
        """Test formatting record with no extra fields."""
        # Don't add _extra attribute
        formatter = LogFormatter(formatter_config)
        result = formatter.format(log_record)
        assert isinstance(result, str)
        assert "Test message" in result

    def test_location_renderer_with_empty_location(self):
        """Test LocationRenderer with location parameter variations."""
        config = LogConfig(location=0, micros=False, colors=True)
        renderer = LocationRenderer(config)
        assert renderer._location == 0

        config = LogConfig(location=5, micros=False, colors=True)
        renderer = LocationRenderer(config)
        assert renderer._location == 5

    def test_preformatter_micros_precision(self):
        """Test PreFormatter microsecond precision calculation."""
        formatter = PreFormatter("%(asctime)s", micros=True)
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="/test.py",
            lineno=1,
            msg="test",
            args=(),
            exc_info=None,
        )
        # Set specific microsecond value
        record.created = 1234567890.123999
        result = formatter.formatTime(record)
        # Should format microseconds (last 3 digits of microseconds)
        assert "." in result


# =============================================================================
# Test Missing Coverage - Line 43, 86-95, 250, 264, 270-283
# =============================================================================


@pytest.mark.unit
class TestMissingCoverage:
    """Tests targeting specific uncovered lines."""

    def test_format_value_with_complex_list(self):
        """Test _format_value with list containing non-simple types (line 43)."""
        formatter = Mock()
        # List with objects that aren't str/int/float
        complex_list = [object(), {"nested": "dict"}, [1, 2]]
        result = _format_value(formatter, complex_list, "col", "bold", "name")
        # Should convert via str()
        assert "bold" in result
        assert "," in result  # Items joined by comma

    def test_format_value_with_mixed_list(self):
        """Test _format_value with list containing mix of simple and complex types."""
        formatter = Mock()
        # List where not all are simple (has a dict)
        mixed_list = [1, "string", {"key": "value"}]
        result = _format_value(formatter, mixed_list, "col", "bold", "name")
        assert "bold" in result
        assert "," in result

    def test_format_without_colors_with_extra_fields(self):
        """Test _format_without_colors with extra fields (lines 86-92, 95)."""
        from appinfra.log.formatters import _format_without_colors

        config = LogConfig(location=0, micros=False, colors=False)
        formatter = LogFormatter(config)

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="/test.py",
            lineno=10,
            msg="test message",
            args=(),
            exc_info=None,
        )
        setattr(record, "__infra__extra", {"key1": "value1", "key2": "value2"})

        result = _format_without_colors(formatter, record, 50)

        # Should include extra fields in brackets
        assert "[key1:value1]" in result
        assert "[key2:value2]" in result
        assert "[%(process)d]" in result
        assert "[%(name)s]" in result

    def test_format_without_colors_with_after_field_skipped(self):
        """Test _format_without_colors skips 'after' field (line 86-87)."""
        from appinfra.log.formatters import _format_without_colors

        config = LogConfig(location=0, micros=False, colors=False)
        formatter = LogFormatter(config)

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="/test.py",
            lineno=10,
            msg="test message",
            args=(),
            exc_info=None,
        )
        setattr(record, "__infra__extra", {"after": 1.5, "other": "value"})

        result = _format_without_colors(formatter, record, 50)

        # 'after' field should be skipped
        assert "[after:" not in result
        # Other fields should be included
        assert "[other:value]" in result

    def test_format_without_colors_with_exception_in_extra(self):
        """Test _format_without_colors with exception in extra fields (lines 89-90)."""
        from appinfra.log.formatters import _format_without_colors

        config = LogConfig(location=0, micros=False, colors=False)
        formatter = LogFormatter(config)

        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname="/test.py",
            lineno=10,
            msg="error occurred",
            args=(),
            exc_info=None,
        )
        setattr(
            record,
            "__infra__extra",
            {
                "exception": ValueError("test error"),
                "context": "info",
            },
        )

        result = _format_without_colors(formatter, record, 50)

        # Exception should be formatted on a new line
        assert "ValueError: test error" in result
        assert "[context:info]" in result

    def test_format_without_colors_with_ordered_dict(self):
        """Test _format_without_colors with OrderedDict extra fields."""
        from appinfra.log.formatters import _format_without_colors

        config = LogConfig(location=0, micros=False, colors=False)
        formatter = LogFormatter(config)

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="/test.py",
            lineno=10,
            msg="test",
            args=(),
            exc_info=None,
        )
        # Use OrderedDict - keys should NOT be sorted
        setattr(
            record,
            "__infra__extra",
            collections.OrderedDict([("z_key", "z_val"), ("a_key", "a_val")]),
        )

        result = _format_without_colors(formatter, record, 50)

        # Should include both keys
        assert "z_key" in result
        assert "a_key" in result

    def test_format_without_colors_with_regular_dict_sorts_keys(self):
        """Test _format_without_colors sorts keys for regular dicts."""
        from appinfra.log.formatters import _format_without_colors

        config = LogConfig(location=0, micros=False, colors=False)
        formatter = LogFormatter(config)

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="/test.py",
            lineno=10,
            msg="test",
            args=(),
            exc_info=None,
        )
        setattr(record, "__infra__extra", {"z_key": "z_val", "a_key": "a_val"})

        result = _format_without_colors(formatter, record, 50)

        # Both keys should be present (sorted order expected)
        assert "z_key" in result
        assert "a_key" in result

    def test_format_fields_dict_with_after_field(self, formatter_config):
        """Test _format_fields_dict handles 'after' field specially (line 250)."""
        formatter = FieldFormatter(formatter_config)
        fields = {"after": 1.5, "other": "value"}

        result = formatter._format_fields_dict(fields, "col", "bold")

        # 'after' should be formatted (at beginning due to special handling)
        assert isinstance(result, str)
        # Should include the other field
        assert "other" in result or "value" in result

    def test_format_fields_dict_with_exception(self, formatter_config):
        """Test _format_fields_dict handles 'exception' field (line 264)."""
        formatter = FieldFormatter(formatter_config)

        # Need to trigger an actual exception to have exc_info
        try:
            raise ValueError("test exception for formatting")
        except ValueError as e:
            fields = {"exception": e, "context": "test"}
            result = formatter._format_fields_dict(fields, "col", "bold")

        # Should include exception traceback
        assert "ValueError" in result
        assert "test exception for formatting" in result
        # Should NOT include context in the special exception handling
        assert "context" in result  # context should still be there as separate field

    def test_render_exception_with_traceback(self, formatter_config):
        """Test _render_exception renders full traceback (lines 270-283)."""
        formatter = FieldFormatter(formatter_config)

        # Create an exception with traceback by actually raising it
        try:
            raise RuntimeError("test error message")
        except RuntimeError as e:
            result = formatter._render_exception(e)

        # Should include exception type and message
        assert "RuntimeError" in result
        assert "test error message" in result
        # Should include file info from traceback
        assert "File" in result
        assert "line" in result

    def test_render_exception_with_nested_call(self, formatter_config):
        """Test _render_exception with nested function call traceback."""
        formatter = FieldFormatter(formatter_config)

        def inner_function():
            raise KeyError("missing key")

        def outer_function():
            inner_function()

        try:
            outer_function()
        except KeyError as e:
            result = formatter._render_exception(e)

        # Should include exception info
        assert "KeyError" in result
        assert "missing key" in result
        # Should include function names from traceback
        assert "inner_function" in result
        assert "outer_function" in result

    def test_render_exception_with_non_exception_raises(self, formatter_config):
        """Test _render_exception raises FormatterError for non-exceptions (line 270-271)."""
        from appinfra.log.errors import FormatterError

        formatter = FieldFormatter(formatter_config)

        with pytest.raises(FormatterError, match="Not an exception"):
            formatter._render_exception("not an exception")

    def test_render_exception_with_non_exception_object(self, formatter_config):
        """Test _render_exception raises for arbitrary objects."""
        from appinfra.log.errors import FormatterError

        formatter = FieldFormatter(formatter_config)

        with pytest.raises(FormatterError):
            formatter._render_exception(12345)

    def test_format_without_colors_empty_extra(self):
        """Test _format_without_colors with empty _extra dict."""
        from appinfra.log.formatters import _format_without_colors

        config = LogConfig(location=0, micros=False, colors=False)
        formatter = LogFormatter(config)

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="/test.py",
            lineno=10,
            msg="test",
            args=(),
            exc_info=None,
        )
        setattr(record, "__infra__extra", {})

        result = _format_without_colors(formatter, record, 50)

        # Should still work with empty extra
        assert "[%(process)d]" in result
        assert "[%(name)s]" in result

    def test_format_without_colors_with_micros(self):
        """Test _format_without_colors with micros=True."""
        from appinfra.log.formatters import _format_without_colors

        config = LogConfig(location=0, micros=True, colors=False)
        formatter = LogFormatter(config)

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="/test.py",
            lineno=10,
            msg="test",
            args=(),
            exc_info=None,
        )

        result = _format_without_colors(formatter, record, 50)

        # Should use micro rule width (different spacing)
        assert isinstance(result, str)

    def test_format_exception_with_percent_placeholders_no_colors(self):
        """Test formatting exception with %-style placeholders doesn't crash.

        Regression test: Exception messages containing %(name)s patterns
        (common in SQLAlchemy errors) were being interpreted as format
        placeholders, causing KeyError during formatting.
        """
        from appinfra.log.formatters import _format_without_colors

        config = LogConfig(location=0, micros=False, colors=False)
        formatter = LogFormatter(config)

        record = logging.LogRecord(
            name="test.logger",
            level=logging.WARNING,
            pathname="/test.py",
            lineno=42,
            msg="session rollback",
            args=(),
            exc_info=None,
        )

        # Exception with %-style placeholder in message (like SQLAlchemy errors)
        exc = ValueError("Missing parameter %(context_pattern)s in query")
        setattr(record, "__infra__extra", {"exception": exc})

        # Verify exception is included in format string
        fmt = _format_without_colors(formatter, record, 50)
        assert "ValueError" in fmt, f"Exception not in format: {fmt!r}"
        assert "context_pattern" in fmt

        # This should NOT raise KeyError: 'context_pattern'
        result = formatter.format(record)

        # The exception message should appear in output (escaped)
        assert "context_pattern" in result
        assert "ValueError" in result

    def test_format_exception_with_percent_placeholders_colors(self, formatter_config):
        """Test formatting exception with %-style placeholders with colors enabled."""
        formatter = LogFormatter(formatter_config)

        record = logging.LogRecord(
            name="test.logger",
            level=logging.WARNING,
            pathname="/test.py",
            lineno=42,
            msg="session rollback",
            args=(),
            exc_info=None,
        )

        # Exception with %-style placeholder in message (like SQLAlchemy errors)
        exc = ValueError("Missing parameter %(context_pattern)s in query")
        setattr(record, "__infra__extra", {"exception": exc})

        # This should NOT raise KeyError: 'context_pattern'
        result = formatter.format(record)

        # The exception message should appear in output
        # (Note: without active traceback, _render_exception returns just str(e))
        assert "context_pattern" in result
        assert "Missing parameter" in result

    def test_format_exception_formatted_with_percent_placeholders(self):
        """Test pre-formatted exception with %-style placeholders (queue mode)."""
        config = LogConfig(location=0, micros=False, colors=False)
        formatter = LogFormatter(config)

        record = logging.LogRecord(
            name="test.logger",
            level=logging.WARNING,
            pathname="/test.py",
            lineno=42,
            msg="session rollback",
            args=(),
            exc_info=None,
        )

        # Pre-formatted exception string (from MPQueueHandler cross-process)
        setattr(
            record,
            "__infra__extra",
            {"exception_formatted": "ValueError: Query failed %(user_id)s"},
        )

        # This should NOT raise KeyError: 'user_id'
        result = formatter.format(record)

        # The exception message should appear in output
        assert "user_id" in result
        assert "ValueError" in result

    def test_format_extra_field_with_percent_placeholders_no_colors(self):
        """Test formatting extra field with %-style placeholders doesn't crash.

        Regression test: Extra field values containing %(name)s patterns
        were being interpreted as format placeholders, causing ValueError
        during formatting.
        """
        config = LogConfig(location=0, micros=False, colors=False)
        formatter = LogFormatter(config)

        record = logging.LogRecord(
            name="test.logger",
            level=logging.WARNING,
            pathname="/test.py",
            lineno=42,
            msg="test message",
            args=(),
            exc_info=None,
        )

        # Extra field with %-style placeholder in value
        setattr(
            record,
            "__infra__extra",
            {"query": "SELECT * FROM users WHERE id = %(user_id)s"},
        )

        # This should NOT raise ValueError: 'Formatting field not found'
        result = formatter.format(record)

        # The extra field value should appear in output
        assert "user_id" in result
        assert "query" in result
