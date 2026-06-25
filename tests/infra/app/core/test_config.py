"""
Tests for app/core/config.py.

Tests key functionality including:
- ConfigLoader class methods
- create_config function
"""

import argparse
import os
import tempfile
from pathlib import Path
from unittest.mock import Mock

import pytest

from appinfra.app.core.config import (
    LOG_LEVEL_QUIET,
    ConfigLoader,
    create_config,
)
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
# Test create_config function
# =============================================================================


@pytest.mark.unit
@pytest.mark.usefixtures("clean_env")
class TestCreateConfig:
    """Test create_config function (lines 168-224)."""

    def test_with_file_path(self):
        """Test loading config from specific file path (lines 172-176)."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("key: value\n")
            f.flush()
            temp_path = f.name

        try:
            config = create_config(file_path=temp_path)
            assert config.key == "value"
        finally:
            os.unlink(temp_path)

    def test_with_nonexistent_file_path_raises(self):
        """Test raises FileNotFoundError for nonexistent path (lines 174-175)."""
        with pytest.raises(FileNotFoundError, match="Config file not found"):
            create_config(file_path="/nonexistent/path/config.yaml")

    def test_uses_default_dir_name(self):
        """Test uses default etc dir when dir_name is None (lines 168-169)."""
        # This test just verifies the code path is executed
        # We expect FileNotFoundError because the default file likely doesn't exist
        with pytest.raises(FileNotFoundError):
            create_config(file_name="nonexistent.yaml")

    def test_load_all_yaml_files(self):
        """Test loading all YAML files from directory (lines 179-214)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create two YAML files
            (Path(tmpdir) / "config1.yaml").write_text("key1: value1\n")
            (Path(tmpdir) / "config2.yaml").write_text("key2: value2\n")

            config = create_config(dir_name=tmpdir, load_all=True)

            assert config.key1 == "value1"
            assert config.key2 == "value2"

    def test_load_all_merges_configs(self):
        """Test load_all merges configurations."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "first.yaml").write_text(
                "shared: first\nonly_first: value1\n"
            )
            (Path(tmpdir) / "second.yaml").write_text(
                "shared: second\nonly_second: value2\n"
            )

            config = create_config(dir_name=tmpdir, load_all=True)

            # Both configs should be merged
            assert config.only_first == "value1"
            assert config.only_second == "value2"

    def test_load_all_nonexistent_dir_raises(self):
        """Test load_all raises for nonexistent directory (lines 181-182)."""
        with pytest.raises(FileNotFoundError, match="Config directory not found"):
            create_config(dir_name="/nonexistent/dir", load_all=True)

    def test_load_all_empty_dir_raises(self):
        """Test load_all raises for empty directory (lines 186-187)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(FileNotFoundError, match="No YAML files found"):
                create_config(dir_name=tmpdir, load_all=True)

    def test_load_all_handles_failed_files(self):
        """Test load_all continues on failed files with logger (lines 209-211)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create one valid and one invalid YAML file
            (Path(tmpdir) / "valid.yaml").write_text("key: value\n")
            (Path(tmpdir) / "invalid.yaml").write_text(
                "invalid: yaml: content: [unclosed\n"
            )

            lg = Mock()
            config = create_config(dir_name=tmpdir, load_all=True, lg=lg)

            # Should have loaded valid config
            assert config.key == "value"
            # Should have logged warning
            lg.warning.assert_called()

    def test_load_all_without_logger_silently_continues(self):
        """Test load_all continues without logger on failed files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "valid.yaml").write_text("key: value\n")
            (Path(tmpdir) / "invalid.yaml").write_text("invalid: yaml: [unclosed\n")

            # Should not raise, just skip invalid file
            config = create_config(dir_name=tmpdir, load_all=True)
            assert config.key == "value"

    def test_uses_default_file_name(self):
        """Test uses default file name when not specified (lines 217-218)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create infra.yaml (default name)
            # Use "loaded" instead of "default" to avoid collision with
            # INFRA_DEFAULT_CONFIG_FILE env var (would be interpreted as
            # config.default.config.file override)
            (Path(tmpdir) / "infra.yaml").write_text("loaded: true\n")

            config = create_config(dir_name=tmpdir)

            assert config.loaded is True

    def test_with_file_name_in_dir(self):
        """Test loading specific file from directory (lines 220-224)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "custom.yaml").write_text("custom: config\n")

            config = create_config(dir_name=tmpdir, file_name="custom.yaml")

            assert config.custom == "config"

    def test_nonexistent_file_in_dir_raises(self):
        """Test raises for nonexistent file in directory (lines 221-222)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(FileNotFoundError, match="Config file not found"):
                create_config(dir_name=tmpdir, file_name="missing.yaml")

    def test_load_all_with_yml_extension(self):
        """Test load_all finds .yml files too (line 184)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "config.yml").write_text("yml_key: yml_value\n")

            config = create_config(dir_name=tmpdir, load_all=True)

            assert config.yml_key == "yml_value"

    def test_load_all_nested_dict_conversion(self):
        """Test load_all converts nested structures (lines 196-204)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yaml_content = """
nested:
  level1:
    level2: value
list_item:
  - item1
  - item2
"""
            (Path(tmpdir) / "nested.yaml").write_text(yaml_content)

            config = create_config(dir_name=tmpdir, load_all=True)

            assert config.nested["level1"]["level2"] == "value"
            assert config.list_item == ["item1", "item2"]


# =============================================================================
# Test Integration Scenarios
# =============================================================================


@pytest.mark.integration
@pytest.mark.usefixtures("clean_env")
class TestConfigIntegration:
    """Test configuration integration scenarios."""

    def test_full_config_workflow(self):
        """Test complete configuration workflow."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create config file
            config_content = """
logging:
  level: warning
  location: 1
app:
  name: test_app
"""
            (Path(tmpdir) / "app.yaml").write_text(config_content)

            # Load config
            config = create_config(dir_name=tmpdir, file_name="app.yaml")

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
