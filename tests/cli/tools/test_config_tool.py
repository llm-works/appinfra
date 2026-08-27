# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for cli/tools/config_tool.py.

Tests key functionality including:
- ConfigTool initialization
- YAML output formatting
- JSON output formatting
- Flat output formatting
- Section filtering
- Environment variable override handling
- Error handling for missing files and parse errors
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml

from appinfra.cli.tools.config_tool import ConfigTool

# =============================================================================
# Test Initialization
# =============================================================================


@pytest.mark.unit
class TestConfigToolInit:
    """Test ConfigTool initialization."""

    def test_basic_initialization(self):
        """Test tool initializes with correct name and aliases."""
        tool = ConfigTool()

        assert tool.name == "config"
        assert "c" in tool.config.aliases
        assert "cfg" in tool.config.aliases

    def test_has_help_text(self):
        """Test tool has help text."""
        tool = ConfigTool()

        assert tool.config.help_text is not None
        assert len(tool.config.help_text) > 0

    def test_has_description(self):
        """Test tool has description."""
        tool = ConfigTool()

        assert tool.config.description is not None
        assert "resolved" in tool.config.description.lower()


@pytest.mark.unit
class TestAddArgs:
    """Test argument parsing setup."""

    def test_adds_config_file_argument(self):
        """Test adds config_file positional argument."""
        tool = ConfigTool()
        parser = Mock()

        tool.add_args(parser)

        call_args = [c[0][0] for c in parser.add_argument.call_args_list]
        assert "config_file" in call_args

    def test_adds_format_argument(self):
        """Test adds --format argument with choices."""
        tool = ConfigTool()
        parser = Mock()

        tool.add_args(parser)

        calls = parser.add_argument.call_args_list
        format_call = next(
            (c for c in calls if "--format" in c[0] or "-f" in c[0]), None
        )
        assert format_call is not None
        assert format_call[1]["choices"] == ["yaml", "json", "flat"]

    def test_adds_no_env_argument(self):
        """Test adds --no-env flag."""
        tool = ConfigTool()
        parser = Mock()

        tool.add_args(parser)

        calls = parser.add_argument.call_args_list
        no_env_call = next((c for c in calls if "--no-env" in c[0]), None)
        assert no_env_call is not None
        assert no_env_call[1]["action"] == "store_true"

    def test_adds_section_argument(self):
        """Test adds --section argument."""
        tool = ConfigTool()
        parser = Mock()

        tool.add_args(parser)

        calls = parser.add_argument.call_args_list
        section_call = next(
            (c for c in calls if "--section" in c[0] or "-s" in c[0]), None
        )
        assert section_call is not None


# =============================================================================
# Test YAML Output
# =============================================================================


@pytest.mark.unit
class TestYAMLOutput:
    """Test YAML output formatting."""

    def test_format_yaml_simple(self):
        """Test YAML output for simple config."""
        tool = ConfigTool()
        data = {"key": "value", "number": 42}

        result = tool._format_yaml(data)

        assert "key: value" in result
        assert "number: 42" in result

    def test_format_yaml_nested(self):
        """Test YAML output preserves nested structure."""
        tool = ConfigTool()
        data = {"database": {"host": "localhost", "port": 5432}}

        result = tool._format_yaml(data)

        assert "database:" in result
        assert "host: localhost" in result
        assert "port: 5432" in result

    def test_format_yaml_valid(self):
        """Test YAML output is valid YAML."""
        tool = ConfigTool()
        data = {"key": "value", "nested": {"a": 1, "b": 2}}

        result = tool._format_yaml(data)
        parsed = yaml.safe_load(result)

        assert parsed == data


# =============================================================================
# Test JSON Output
# =============================================================================


@pytest.mark.unit
class TestJSONOutput:
    """Test JSON output formatting."""

    def test_format_json_simple(self):
        """Test JSON output for simple config."""
        tool = ConfigTool()
        data = {"key": "value", "number": 42}

        result = tool._format_json(data)

        assert '"key": "value"' in result
        assert '"number": 42' in result

    def test_format_json_valid(self):
        """Test JSON output is valid JSON."""
        tool = ConfigTool()
        data = {"key": "value", "nested": {"a": 1, "b": 2}}

        result = tool._format_json(data)
        parsed = json.loads(result)

        assert parsed == data

    def test_format_json_indented(self):
        """Test JSON output is properly indented."""
        tool = ConfigTool()
        data = {"key": "value"}

        result = tool._format_json(data)

        assert "\n" in result  # Multi-line output


# =============================================================================
# Test Flat Output
# =============================================================================


@pytest.mark.unit
class TestFlatOutput:
    """Test flat key=value output formatting."""

    def test_format_flat_simple(self):
        """Test flat output for simple config."""
        tool = ConfigTool()
        data = {"key": "value", "number": 42}

        result = tool._format_flat(data)

        assert "key=value" in result
        assert "number=42" in result

    def test_format_flat_nested(self):
        """Test flat output correctly flattens nested keys."""
        tool = ConfigTool()
        data = {"database": {"host": "localhost", "port": 5432}}

        result = tool._format_flat(data)

        assert "database.host=localhost" in result
        assert "database.port=5432" in result

    def test_format_flat_deeply_nested(self):
        """Test flat output handles deeply nested structures."""
        tool = ConfigTool()
        data = {"a": {"b": {"c": {"d": "value"}}}}

        result = tool._format_flat(data)

        assert "a.b.c.d=value" in result

    def test_format_flat_list_simple(self):
        """Test flat output for simple list values."""
        tool = ConfigTool()
        data = {"items": ["a", "b", "c"]}

        result = tool._format_flat(data)

        assert "items=a,b,c" in result

    def test_format_flat_list_numbers(self):
        """Test flat output for list of numbers."""
        tool = ConfigTool()
        data = {"ports": [80, 443, 8080]}

        result = tool._format_flat(data)

        assert "ports=80,443,8080" in result

    def test_format_flat_bool_lowercase(self):
        """Test flat output converts booleans to lowercase."""
        tool = ConfigTool()
        data = {"enabled": True, "disabled": False}

        result = tool._format_flat(data)

        assert "enabled=true" in result
        assert "disabled=false" in result

    def test_format_flat_none_empty(self):
        """Test flat output converts None to empty string."""
        tool = ConfigTool()
        data = {"empty": None}

        result = tool._format_flat(data)

        assert "empty=" in result


# =============================================================================
# Test Section Filtering
# =============================================================================


@pytest.mark.unit
class TestSectionFiltering:
    """Test --section argument filtering."""

    def test_filter_top_level_section(self):
        """Test filtering to top-level section."""
        tool = ConfigTool()
        tool._parsed_args = Mock(section="database")
        data = {"database": {"host": "localhost"}, "logging": {"level": "info"}}

        result = tool._filter_section(data)

        assert result == {"host": "localhost"}

    def test_filter_nested_section(self):
        """Test filtering to nested section."""
        tool = ConfigTool()
        tool._parsed_args = Mock(section="database.connection")
        data = {"database": {"connection": {"host": "localhost", "port": 5432}}}

        result = tool._filter_section(data)

        assert result == {"host": "localhost", "port": 5432}

    def test_filter_nonexistent_section_returns_none(self):
        """Test filtering to nonexistent section returns None."""
        tool = ConfigTool()
        tool._parsed_args = Mock(section="nonexistent")
        tool._logger = Mock()
        data = {"database": {"host": "localhost"}}

        result = tool._filter_section(data)

        assert result is None
        tool._logger.error.assert_called_once()

    def test_filter_no_section_returns_full_data(self):
        """Test no section filter returns full data."""
        tool = ConfigTool()
        tool._parsed_args = Mock(section=None)
        data = {"database": {"host": "localhost"}, "logging": {"level": "info"}}

        result = tool._filter_section(data)

        assert result == data

    def test_filter_scalar_value_wraps_in_dict(self):
        """Test filtering to scalar value wraps it in a dict."""
        tool = ConfigTool()
        tool._parsed_args = Mock(section="database.host")
        data = {"database": {"host": "localhost", "port": 5432}}

        result = tool._filter_section(data)

        assert result == {"host": "localhost"}


# =============================================================================
# Test Config Loading
# =============================================================================


@pytest.mark.unit
class TestConfigLoading:
    """Test configuration file loading."""

    def test_load_valid_config(self):
        """Test loading a valid config file."""
        tool = ConfigTool()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("database:\n  host: localhost\n  port: 5432\n")
            f.flush()

            tool._parsed_args = Mock(config_file=f.name, no_env=True)
            tool._logger = Mock()

            result = tool._load_config()

            assert result is not None
            assert result["database"]["host"] == "localhost"
            assert result["database"]["port"] == 5432

        Path(f.name).unlink()

    def test_load_missing_file_returns_none(self):
        """Test loading missing file returns None."""
        tool = ConfigTool()
        tool._parsed_args = Mock(config_file="/nonexistent/path.yaml", no_env=True)
        tool._logger = Mock()

        result = tool._load_config()

        assert result is None
        tool._logger.error.assert_called_once()

    def test_load_invalid_yaml_returns_none(self):
        """Test loading invalid YAML returns None."""
        tool = ConfigTool()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("invalid: yaml: content: [")
            f.flush()

            tool._parsed_args = Mock(config_file=f.name, no_env=True)
            tool._logger = Mock()

            result = tool._load_config()

            assert result is None
            tool._logger.error.assert_called_once()

        Path(f.name).unlink()


# =============================================================================
# Test Environment Variable Handling
# =============================================================================


@pytest.mark.unit
@pytest.mark.usefixtures("clean_env")
class TestEnvVarHandling:
    """Test environment variable override handling."""

    def test_env_overrides_applied_by_default(self, monkeypatch):
        """Test environment variables are applied by default."""
        tool = ConfigTool()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("database:\n  host: localhost\n")
            f.flush()

            monkeypatch.setenv("INFRA_DATABASE_HOST", "remote.host.com")

            tool._parsed_args = Mock(config_file=f.name, no_env=False)
            tool._logger = Mock()

            result = tool._load_config()

            assert result is not None
            assert result["database"]["host"] == "remote.host.com"

        Path(f.name).unlink()

    def test_no_env_flag_disables_overrides(self, monkeypatch):
        """Test --no-env flag disables env overrides."""
        tool = ConfigTool()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("database:\n  host: localhost\n")
            f.flush()

            monkeypatch.setenv("INFRA_DATABASE_HOST", "remote.host.com")

            tool._parsed_args = Mock(config_file=f.name, no_env=True)
            tool._logger = Mock()

            result = tool._load_config()

            assert result is not None
            assert result["database"]["host"] == "localhost"

        Path(f.name).unlink()


# =============================================================================
# Integration Tests
# =============================================================================


@pytest.mark.integration
class TestConfigToolIntegration:
    """Integration tests with real config files."""

    def test_full_run_yaml_output(self, capsys):
        """Test full run with YAML output."""
        tool = ConfigTool()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("app:\n  name: test\n  version: 1.0\n")
            f.flush()

            tool._parsed_args = Mock(
                config_file=f.name, format="yaml", no_env=True, section=None
            )
            tool._logger = Mock()

            result = tool.run()

            assert result == 0
            captured = capsys.readouterr()
            assert "app:" in captured.out
            assert "name: test" in captured.out

        Path(f.name).unlink()

    def test_full_run_json_output(self, capsys):
        """Test full run with JSON output."""
        tool = ConfigTool()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("app:\n  name: test\n")
            f.flush()

            tool._parsed_args = Mock(
                config_file=f.name, format="json", no_env=True, section=None
            )
            tool._logger = Mock()

            result = tool.run()

            assert result == 0
            captured = capsys.readouterr()
            parsed = json.loads(captured.out)
            assert parsed["app"]["name"] == "test"

        Path(f.name).unlink()

    def test_full_run_flat_output(self, capsys):
        """Test full run with flat output."""
        tool = ConfigTool()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("app:\n  name: test\n  port: 8080\n")
            f.flush()

            tool._parsed_args = Mock(
                config_file=f.name, format="flat", no_env=True, section=None
            )
            tool._logger = Mock()

            result = tool.run()

            assert result == 0
            captured = capsys.readouterr()
            assert "app.name=test" in captured.out
            assert "app.port=8080" in captured.out

        Path(f.name).unlink()

    def test_full_run_with_section(self, capsys):
        """Test full run with section filter."""
        tool = ConfigTool()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("app:\n  name: test\ndb:\n  host: localhost\n")
            f.flush()

            tool._parsed_args = Mock(
                config_file=f.name, format="yaml", no_env=True, section="app"
            )
            tool._logger = Mock()

            result = tool.run()

            assert result == 0
            captured = capsys.readouterr()
            assert "name: test" in captured.out
            assert "db:" not in captured.out

        Path(f.name).unlink()

    def test_full_run_missing_file(self):
        """Test full run with missing file returns error."""
        tool = ConfigTool()
        tool._parsed_args = Mock(
            config_file="/nonexistent/path.yaml", no_env=True, section=None
        )
        tool._logger = Mock()

        result = tool.run()

        assert result == 1

    def test_default_config_path_when_none(self, tmp_path, monkeypatch):
        """Test that default config path is used when config_file is None."""
        # Change to a temp directory so etc/infra.yaml doesn't exist
        monkeypatch.chdir(tmp_path)

        tool = ConfigTool()
        tool._parsed_args = Mock(config_file=None, no_env=True)
        tool._logger = Mock()

        # Should try to load etc/infra.yaml which won't exist in tmp_path
        result = tool._load_config()

        # Should return None because file doesn't exist, and log error
        assert result is None
        tool._logger.error.assert_called_once()
        assert "etc/infra.yaml" in str(tool._logger.error.call_args)

    def test_load_config_generic_exception(self, tmp_path, monkeypatch):
        """Test that generic exceptions during config load are handled."""
        tool = ConfigTool()
        config_file = tmp_path / "test.yaml"
        config_file.write_text("valid: yaml\n")

        tool._parsed_args = Mock(config_file=str(config_file), no_env=False)
        tool._logger = Mock()

        # Patch Config to raise a generic exception (not YAMLError)
        from appinfra.cli.tools import config_tool

        original_config = config_tool.Config

        class FailingConfig:
            def __init__(self, *args, **kwargs):
                raise RuntimeError("Simulated generic error")

        monkeypatch.setattr(config_tool, "Config", FailingConfig)

        result = tool._load_config()

        assert result is None
        tool._logger.error.assert_called_once()
        assert "failed to load config" in str(tool._logger.error.call_args)

    def test_format_output_json(self):
        """Test _format_output selects JSON formatter."""
        tool = ConfigTool()
        tool._parsed_args = Mock(format="json")
        data = {"key": "value"}

        result = tool._format_output(data)

        assert '"key": "value"' in result

    def test_format_output_flat(self):
        """Test _format_output selects flat formatter."""
        tool = ConfigTool()
        tool._parsed_args = Mock(format="flat")
        data = {"key": "value"}

        result = tool._format_output(data)

        assert "key=value" in result

    def test_format_output_yaml_default(self):
        """Test _format_output defaults to YAML formatter."""
        tool = ConfigTool()
        tool._parsed_args = Mock(format="yaml")
        data = {"key": "value"}

        result = tool._format_output(data)

        assert "key: value" in result

    def test_format_list_value_complex_objects(self):
        """Test _format_list_value falls back to JSON for complex objects."""
        tool = ConfigTool()
        # List with complex objects (dicts)
        complex_list = [{"a": 1}, {"b": 2}]

        result = tool._format_list_value(complex_list)

        # Should be JSON format, not comma-separated
        assert "[" in result
        assert '"a":' in result or '"a": ' in result

    def test_full_run_returns_1_on_section_filter_failure(self):
        """Test run returns 1 when section filter fails."""
        tool = ConfigTool()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("app:\n  name: test\n")
            f.flush()

            tool._parsed_args = Mock(
                config_file=f.name,
                format="yaml",
                no_env=True,
                section="nonexistent",
            )
            tool._logger = Mock()

            result = tool.run()

            assert result == 1

        Path(f.name).unlink()
