# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for app/core/config.py.

Tests key functionality including:
- ConfigLoader class methods
"""

import argparse

import pytest

from appinfra.app.core.config import LOG_LEVEL_QUIET, ConfigLoader
from appinfra.dot_dict import DotDict

# =============================================================================
# Test ConfigLoader._ensure_nested_section
# =============================================================================


@pytest.mark.unit
class TestEnsureNestedSection:
    """Test ConfigLoader._ensure_nested_section method (lines 39-44)."""

    def test_creates_single_level(self):
        """Test creating single level section."""
        config = DotDict()
        result = ConfigLoader._ensure_nested_section(config, "logging")

        assert hasattr(config, "logging")
        assert isinstance(config.logging, DotDict)

    def test_creates_multiple_levels(self):
        """Test creating multiple nested levels."""
        config = DotDict()
        result = ConfigLoader._ensure_nested_section(
            config, "logging", "handlers", "console"
        )

        assert hasattr(config, "logging")
        assert hasattr(config.logging, "handlers")
        assert hasattr(config.logging.handlers, "console")

    def test_preserves_existing_sections(self):
        """Test that existing sections are preserved."""
        config = DotDict(logging=DotDict(level="debug"))
        result = ConfigLoader._ensure_nested_section(config, "logging", "handlers")

        assert config.logging.level == "debug"
        assert hasattr(config.logging, "handlers")

    def test_returns_innermost_section(self):
        """Test that method returns the innermost section."""
        config = DotDict()
        result = ConfigLoader._ensure_nested_section(config, "a", "b", "c")

        assert result is config.a.b.c


# =============================================================================
# Test ConfigLoader._get_arg
# =============================================================================


@pytest.mark.unit
class TestGetArg:
    """Test ConfigLoader._get_arg method (line 59)."""

    def test_returns_value_when_present(self):
        """Test returns argument value when present."""
        args = argparse.Namespace(foo="bar")
        result = ConfigLoader._get_arg(args, "foo")
        assert result == "bar"

    def test_returns_default_when_not_present(self):
        """Test returns default when argument not present (line 59)."""
        args = argparse.Namespace()
        result = ConfigLoader._get_arg(args, "missing", default="default_value")
        assert result == "default_value"

    def test_returns_none_when_not_present_no_default(self):
        """Test returns None when not present and no default."""
        args = argparse.Namespace()
        result = ConfigLoader._get_arg(args, "missing")
        assert result is None


# =============================================================================
# Test ConfigLoader._set_if_present
# =============================================================================


@pytest.mark.unit
class TestSetIfPresent:
    """Test ConfigLoader._set_if_present method (lines 74-88)."""

    def test_does_nothing_when_arg_not_present(self):
        """Test does nothing when arg not present (line 74-75)."""
        config = DotDict()
        args = argparse.Namespace()

        ConfigLoader._set_if_present(config, args, "missing_arg", "some.path")

        assert not hasattr(config, "some")

    def test_does_nothing_when_value_is_none(self):
        """Test does nothing when arg value is None (line 78-79)."""
        config = DotDict()
        args = argparse.Namespace(log_level=None)

        ConfigLoader._set_if_present(config, args, "log_level", "logging.level")

        assert not hasattr(config, "logging")

    def test_sets_simple_path(self):
        """Test sets value for simple path."""
        config = DotDict()
        args = argparse.Namespace(verbose=True)

        ConfigLoader._set_if_present(config, args, "verbose", "verbose")

        assert config.verbose is True

    def test_sets_nested_path(self):
        """Test sets value for nested path (lines 81-88)."""
        config = DotDict()
        args = argparse.Namespace(log_level="debug")

        ConfigLoader._set_if_present(config, args, "log_level", "logging.level")

        assert config.logging.level == "debug"

    def test_sets_deeply_nested_path(self):
        """Test sets value for deeply nested path."""
        config = DotDict()
        args = argparse.Namespace(console_level="info")

        ConfigLoader._set_if_present(
            config, args, "console_level", "logging.handlers.console.level"
        )

        assert config.logging.handlers.console.level == "info"

    def test_preserves_existing_nested_values(self):
        """Test preserves other values in nested path."""
        config = DotDict(logging=DotDict(format="custom"))
        args = argparse.Namespace(log_level="warning")

        ConfigLoader._set_if_present(config, args, "log_level", "logging.level")

        assert config.logging.level == "warning"
        assert config.logging.format == "custom"


# =============================================================================
# Test ConfigLoader.from_args
# =============================================================================


@pytest.mark.unit
class TestFromArgs:
    """Test ConfigLoader.from_args method (lines 106-130)."""

    def test_creates_default_config_when_none_provided(self):
        """Test creates config when none provided (line 106)."""
        args = argparse.Namespace()
        config = ConfigLoader.from_args(args)

        assert hasattr(config, "logging")
        assert config.logging.level == "info"
        assert config.logging.location == 0
        assert config.logging.micros is False

    def test_uses_existing_config(self):
        """Test uses existing config when provided."""
        existing = DotDict(custom="value")
        args = argparse.Namespace()

        config = ConfigLoader.from_args(args, existing)

        assert config.custom == "value"
        assert hasattr(config, "logging")

    def test_sets_defaults_when_missing(self):
        """Test sets defaults when logging section empty (lines 112-117)."""
        existing = DotDict(logging=DotDict())
        args = argparse.Namespace()

        config = ConfigLoader.from_args(args, existing)

        assert config.logging.level == "info"
        assert config.logging.location == 0
        assert config.logging.micros is False

    def test_quiet_mode_sets_high_level(self):
        """Test quiet mode sets LOG_LEVEL_QUIET (lines 119-121)."""
        args = argparse.Namespace(quiet=True)

        config = ConfigLoader.from_args(args)

        assert config.logging.level == LOG_LEVEL_QUIET

    def test_applies_log_level_arg(self):
        """Test applies log_level argument (line 124)."""
        args = argparse.Namespace(quiet=False, log_level="debug")

        config = ConfigLoader.from_args(args)

        assert config.logging.level == "debug"

    def test_applies_log_location_arg(self):
        """Test applies log_location argument (line 126)."""
        args = argparse.Namespace(log_location=2)

        config = ConfigLoader.from_args(args)

        assert config.logging.location == 2

    def test_applies_log_micros_arg(self):
        """Test applies log_micros argument (line 127)."""
        args = argparse.Namespace(log_micros=True)

        config = ConfigLoader.from_args(args)

        assert config.logging.micros is True

    def test_applies_default_tool_arg(self):
        """Test applies default_tool argument (line 128)."""
        args = argparse.Namespace(default_tool="my_tool")

        config = ConfigLoader.from_args(args)

        assert config.default_tool == "my_tool"


# =============================================================================
# Test ConfigLoader.default
# =============================================================================


@pytest.mark.unit
class TestDefault:
    """Test ConfigLoader.default method (line 135)."""

    def test_returns_default_config(self):
        """Test returns default configuration."""
        config = ConfigLoader.default()

        assert isinstance(config, DotDict)
        assert config.logging.level == "info"
        assert config.logging.location == 0
        assert config.logging.micros is False


# =============================================================================
# Test Integration Scenarios
# =============================================================================


@pytest.mark.integration
@pytest.mark.usefixtures("clean_env")
class TestConfigIntegration:
    """Test configuration integration scenarios."""

    def test_full_config_workflow(self, tmp_path):
        """Test complete configuration workflow."""
        from appinfra.config import Config

        config_file = tmp_path / "app.yaml"
        config_file.write_text(
            "logging:\n  level: warning\n  location: 1\napp:\n  name: test_app\n"
        )
        config = Config(str(config_file))

        # Apply args
        args = argparse.Namespace(log_level="debug", log_micros=True)
        final_config = ConfigLoader.from_args(args, config)

        # Args should override file config
        assert final_config.logging.level == "debug"
        assert final_config.logging.micros is True
        # File config preserved
        assert final_config.app.name == "test_app"

    def test_quiet_mode_overrides_all(self):
        """Test quiet mode overrides all logging settings."""
        args = argparse.Namespace(quiet=True, log_level="debug")

        config = ConfigLoader.from_args(args)

        # Quiet mode should win
        assert config.logging.level == LOG_LEVEL_QUIET
