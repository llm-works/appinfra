# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for infra.yaml module (YAML parsing with includes).

Comprehensive tests for custom YAML loader covering parsing, includes,
security, error handling, and edge cases.
"""

from io import StringIO
from pathlib import Path

import pytest
import yaml

from appinfra.security.envelope import Envelope
from appinfra.yaml import (
    ErrorContext,
    deep_merge,
    load,
)

# =============================================================================
# Unit Tests for ErrorContext
# =============================================================================


class TestErrorContext:
    """Unit tests for ErrorContext.format_location()."""

    def test_format_location_with_all_fields(self):
        """Test format_location with file, line, and column."""
        ctx = ErrorContext(
            current_file=Path("/path/to/config.yaml"),
            line=4,  # 0-indexed
            column=6,  # 0-indexed
        )
        result = ctx.format_location()
        assert result == "in '/path/to/config.yaml', line 5, column 7"

    def test_format_location_with_file_and_line_only(self):
        """Test format_location with file and line, no column."""
        ctx = ErrorContext(
            current_file=Path("/path/to/config.yaml"),
            line=9,
            column=None,
        )
        result = ctx.format_location()
        assert result == "in '/path/to/config.yaml', line 10"

    def test_format_location_with_file_only(self):
        """Test format_location with only file."""
        ctx = ErrorContext(
            current_file=Path("/path/to/config.yaml"),
            line=None,
            column=None,
        )
        result = ctx.format_location()
        assert result == "in '/path/to/config.yaml'"

    def test_format_location_with_no_fields(self):
        """Test format_location with no fields set."""
        ctx = ErrorContext()
        result = ctx.format_location()
        assert result == "unknown location"

    def test_format_location_with_line_zero(self):
        """Test format_location with line 0 (first line)."""
        ctx = ErrorContext(
            current_file=Path("test.yaml"),
            line=0,
            column=0,
        )
        result = ctx.format_location()
        assert result == "in 'test.yaml', line 1, column 1"

    def test_error_context_is_immutable(self):
        """Test that ErrorContext is frozen (immutable)."""
        ctx = ErrorContext(current_file=Path("test.yaml"), line=1, column=1)
        with pytest.raises(AttributeError):
            ctx.line = 5  # type: ignore[misc]


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def simple_yaml():
    """Provide simple YAML content."""
    return """
name: test_app
version: 1.0.0
enabled: true
"""


@pytest.fixture
def yaml_with_numbers():
    """Provide YAML with numeric keys."""
    return """
settings:
  2025: "year value"
  42: "answer"
  3.14: "pi"
  true: "boolean key"
"""


@pytest.fixture
def yaml_with_dates():
    """Provide YAML with date keys."""
    return """
schedules:
  2025-12-01: "New Year"
  2025-12-25: "Christmas"
"""


@pytest.fixture
def nested_yaml():
    """Provide nested YAML structure."""
    return """
app:
  name: test
  database:
    host: localhost
    port: 5432
    settings:
      pool_size: 10
      timeout: 30
"""


# =============================================================================
# Basic Parsing Tests
# =============================================================================


class TestBasicParsing:
    """Test basic YAML parsing functionality."""

    def test_parse_simple_yaml(self, simple_yaml):
        """Test parsing simple YAML."""
        data = load(StringIO(simple_yaml))

        assert data["name"] == "test_app"
        assert data["version"] == "1.0.0"
        assert data["enabled"] is True

    def test_parse_nested_structure(self, nested_yaml):
        """Test parsing nested YAML structure."""
        data = load(StringIO(nested_yaml))

        assert data["app"]["name"] == "test"
        assert data["app"]["database"]["host"] == "localhost"
        assert data["app"]["database"]["port"] == 5432
        assert data["app"]["database"]["settings"]["pool_size"] == 10

    def test_parse_empty_yaml(self):
        """Test parsing empty YAML."""
        data = load(StringIO(""))
        assert data is None

    def test_parse_yaml_with_list(self):
        """Test parsing YAML with lists."""
        yaml_content = """
items:
  - one
  - two
  - three
nested:
  - name: item1
    value: 100
  - name: item2
    value: 200
"""
        data = load(StringIO(yaml_content))

        assert data["items"] == ["one", "two", "three"]
        assert len(data["nested"]) == 2
        assert data["nested"][0]["name"] == "item1"

    def test_parse_yaml_with_multiline_string(self):
        """Test parsing YAML with multiline strings."""
        yaml_content = """
description: |
  This is a multiline
  string that spans
  multiple lines
"""
        data = load(StringIO(yaml_content))

        assert "multiline" in data["description"]
        assert data["description"].count("\n") > 1


# =============================================================================
# Key Conversion Tests
# =============================================================================


class TestKeyConversion:
    """Test automatic key type conversion."""

    def test_convert_numeric_keys_to_strings(self, yaml_with_numbers):
        """Test numeric keys are converted to strings."""
        data = load(StringIO(yaml_with_numbers))

        assert "2025" in data["settings"]
        assert "42" in data["settings"]
        assert "3.14" in data["settings"]
        assert data["settings"]["2025"] == "year value"
        assert data["settings"]["42"] == "answer"

    def test_convert_date_keys_to_strings(self, yaml_with_dates):
        """Test date keys are converted to strings."""
        data = load(StringIO(yaml_with_dates))

        # Date keys should be converted to strings
        assert "2025-12-01" in data["schedules"]
        assert "2025-12-25" in data["schedules"]

    def test_boolean_keys_not_converted(self, yaml_with_numbers):
        """Test boolean keys are NOT converted to strings."""
        data = load(StringIO(yaml_with_numbers))

        # Boolean 'true' key should remain boolean
        assert True in data["settings"]
        assert data["settings"][True] == "boolean key"

    def test_string_keys_unchanged(self, simple_yaml):
        """Test string keys remain unchanged."""
        data = load(StringIO(simple_yaml))

        assert isinstance(list(data.keys())[0], str)


# =============================================================================
# Deep Merge Tests
# =============================================================================


class TestDeepMerge:
    """Test deep_merge functionality."""

    def test_merge_simple_dicts(self):
        """Test merging simple dictionaries."""
        base = {"a": 1, "b": 2}
        override = {"b": 3, "c": 4}

        result = deep_merge(base, override)

        assert result == {"a": 1, "b": 3, "c": 4}

    def test_merge_nested_dicts(self):
        """Test merging nested dictionaries."""
        base = {
            "app": {"name": "old", "version": "1.0"},
            "db": {"host": "localhost"},
        }
        override = {
            "app": {"version": "2.0", "enabled": True},
            "cache": {"enabled": False},
        }

        result = deep_merge(base, override)

        assert result["app"]["name"] == "old"  # Preserved from base
        assert result["app"]["version"] == "2.0"  # Overridden
        assert result["app"]["enabled"] is True  # Added from override
        assert result["db"]["host"] == "localhost"  # Preserved
        assert result["cache"]["enabled"] is False  # New from override

    def test_merge_replaces_non_dict_values(self):
        """Test that non-dict values are replaced, not merged."""
        base = {"key": "old_value"}
        override = {"key": "new_value"}

        result = deep_merge(base, override)

        assert result["key"] == "new_value"

    def test_merge_replaces_list_values(self):
        """Test that lists are replaced, not merged."""
        base = {"items": [1, 2, 3]}
        override = {"items": [4, 5]}

        result = deep_merge(base, override)

        assert result["items"] == [4, 5]

    def test_merge_doesnt_modify_originals(self):
        """Test that merge doesn't modify original dictionaries."""
        base = {"a": 1, "b": {"c": 2}}
        override = {"b": {"d": 3}}

        result = deep_merge(base, override)

        # Original should be unchanged
        assert "d" not in base["b"]
        assert "d" in result["b"]

    def test_merge_empty_dicts(self):
        """Test merging empty dictionaries."""
        assert deep_merge({}, {}) == {}
        assert deep_merge({"a": 1}, {}) == {"a": 1}
        assert deep_merge({}, {"a": 1}) == {"a": 1}

    def test_merge_deeply_nested(self):
        """Test merging deeply nested structures."""
        base = {"level1": {"level2": {"level3": {"value": "old"}}}}
        override = {"level1": {"level2": {"level3": {"value": "new"}}}}

        result = deep_merge(base, override)

        assert result["level1"]["level2"]["level3"]["value"] == "new"


# =============================================================================
# Source Tracking Tests
# =============================================================================


class TestSourceTracking:
    """Test source file tracking functionality."""

    @pytest.mark.integration
    def test_source_tracking_basic(self, yaml_files_dir):
        """Test basic source tracking."""
        main_file = yaml_files_dir / "main.yaml"

        with open(main_file) as f:
            data, source_map = load(f, current_file=main_file, track_sources=True)

        assert source_map is not None
        assert isinstance(source_map, dict)

    @pytest.mark.integration
    def test_source_tracking_with_includes(self, yaml_files_dir):
        """Test source tracking with includes."""
        main_file = yaml_files_dir / "main.yaml"

        with open(main_file) as f:
            data, source_map = load(f, current_file=main_file, track_sources=True)

        # Main file entries
        assert "app" in source_map
        assert source_map["app"] == main_file

        # Included file entries (database comes from db.yaml)
        assert "database" in source_map

    def test_source_tracking_disabled_returns_data_only(self, simple_yaml):
        """Test that without source tracking, only data is returned."""
        result = load(StringIO(simple_yaml), track_sources=False)

        # Should return just the data, not a tuple
        assert isinstance(result, dict)
        assert "name" in result


# =============================================================================
# Error Handling Tests
# =============================================================================


class TestErrorHandling:
    """Test error handling in various scenarios."""

    def test_invalid_yaml_syntax(self):
        """Test that invalid YAML syntax raises error."""
        # Malformed YAML with invalid indentation
        invalid_yaml = """
key: value
    bad_indent: value
  also_bad: value
"""
        with pytest.raises(yaml.YAMLError):
            load(StringIO(invalid_yaml))

    def test_unclosed_brackets(self):
        """Test unclosed brackets raise error."""
        invalid_yaml = """
list: [1, 2, 3
"""
        with pytest.raises(yaml.YAMLError):
            load(StringIO(invalid_yaml))

    @pytest.mark.integration
    def test_invalid_include_path_type(self, yaml_files_dir):
        """Test that non-string include paths fail."""
        # This would be caught by YAML parser before reaching our code
        yaml_content = """
data: !include 12345
"""
        # YAML parser will convert 12345 to string "12345"
        with pytest.raises(yaml.YAMLError, match="Include file not found"):
            load(StringIO(yaml_content), current_file=yaml_files_dir / "test.yaml")

    @pytest.mark.integration
    def test_empty_include_path(self, yaml_files_dir):
        """Test empty include path fails."""
        yaml_content = """
data: !include ""
"""
        # Empty path resolves to current directory, which won't be a valid YAML file
        with pytest.raises((yaml.YAMLError, IsADirectoryError)):
            load(StringIO(yaml_content), current_file=yaml_files_dir / "test.yaml")


# =============================================================================
# Edge Cases
# =============================================================================


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    @pytest.mark.integration
    def test_include_empty_file(self, yaml_files_dir):
        """Test including an empty YAML file."""
        empty_file = yaml_files_dir / "empty.yaml"
        empty_file.write_text("")

        yaml_content = """
data: !include "./empty.yaml"
"""
        data = load(StringIO(yaml_content), current_file=yaml_files_dir / "test.yaml")

        assert data["data"] is None

    @pytest.mark.integration
    def test_include_file_with_only_comments(self, yaml_files_dir):
        """Test including file with only comments."""
        comments_file = yaml_files_dir / "comments.yaml"
        comments_file.write_text(
            """
# This is a comment
# Another comment
"""
        )

        yaml_content = """
data: !include "./comments.yaml"
"""
        data = load(StringIO(yaml_content), current_file=yaml_files_dir / "test.yaml")

        assert data["data"] is None

    def test_unicode_in_yaml(self):
        """Test YAML with Unicode characters."""
        yaml_content = """
message: "Hello 世界 🌍"
emoji: "🎉🎊"
"""
        data = load(StringIO(yaml_content))

        assert "世界" in data["message"]
        assert data["emoji"] == "🎉🎊"

    def test_very_long_key(self):
        """Test YAML with very long key."""
        long_key = "a" * 1000
        yaml_content = f"{long_key}: value"

        data = load(StringIO(yaml_content))

        assert long_key in data
        assert data[long_key] == "value"

    def test_null_values(self):
        """Test YAML with null values."""
        yaml_content = """
explicit_null: null
implicit_null:
tilde_null: ~
"""
        data = load(StringIO(yaml_content))

        assert data["explicit_null"] is None
        assert data["implicit_null"] is None
        assert data["tilde_null"] is None

    def test_special_characters_in_keys(self):
        """Test keys with special characters."""
        yaml_content = """
"key-with-dashes": value1
"key.with.dots": value2
"key_with_underscores": value3
"key with spaces": value4
"""
        data = load(StringIO(yaml_content))

        assert data["key-with-dashes"] == "value1"
        assert data["key.with.dots"] == "value2"
        assert data["key_with_underscores"] == "value3"
        assert data["key with spaces"] == "value4"


# =============================================================================
# Solo !secret rejection
# =============================================================================


class TestSecretRejection:
    """Solo !secret is not supported — chain with !env is the only form."""

    def test_solo_secret_raises(self):
        yaml_content = """
password: !secret ${DB_PASSWORD}
"""
        with pytest.raises(yaml.YAMLError, match="Solo `!secret`"):
            load(StringIO(yaml_content))

    def test_solo_secret_literal_also_raises(self):
        yaml_content = """
key: !secret plaintext
"""
        with pytest.raises(yaml.YAMLError, match="Solo `!secret`"):
            load(StringIO(yaml_content))

    def test_error_points_to_chain_syntax(self):
        yaml_content = "k: !secret ${VAR}\n"
        with pytest.raises(yaml.YAMLError) as exc_info:
            load(StringIO(yaml_content))
        assert "!env VAR !secret" in str(exc_info.value)


# =============================================================================
# !env override map + !env !secret chain
# =============================================================================


class TestEnvOverrides:
    """!env must consult env_overrides before os.environ."""

    def test_env_reads_override_before_ambient(self, monkeypatch):
        monkeypatch.setenv("FOO", "from_ambient")
        data = load(
            StringIO("value: !env FOO\n"),
            env_overrides={"FOO": "from_override"},
        )
        assert data["value"] == "from_override"

    def test_env_falls_through_to_ambient_when_missing_in_overrides(self, monkeypatch):
        monkeypatch.setenv("FOO", "from_ambient")
        data = load(
            StringIO("value: !env FOO\n"),
            env_overrides={"OTHER": "x"},
        )
        assert data["value"] == "from_ambient"

    def test_env_optional_returns_none_when_missing_everywhere(self, monkeypatch):
        monkeypatch.delenv("MISSING_VAR", raising=False)
        data = load(
            StringIO("value: !env? MISSING_VAR\n"),
            env_overrides={},
        )
        assert data["value"] is None

    def test_env_default_applies_when_missing(self, monkeypatch):
        monkeypatch.delenv("MISSING_VAR", raising=False)
        data = load(
            StringIO("value: !env MISSING_VAR:fallback\n"),
            env_overrides={},
        )
        assert data["value"] == "fallback"


class TestSecretEnvChain:
    """!env !secret / !secret !env returns a Envelope wrapping the resolved value."""

    def test_prefix_form_returns_secret_str(self):
        data = load(
            StringIO("password: !secret !env DB_PASSWORD\n"),
            env_overrides={"DB_PASSWORD": "hunter2"},
        )
        assert isinstance(data["password"], Envelope)
        assert data["password"].reveal() == "hunter2"

    def test_postfix_form_returns_secret_str(self):
        data = load(
            StringIO("password: !env DB_PASSWORD !secret\n"),
            env_overrides={"DB_PASSWORD": "hunter2"},
        )
        assert isinstance(data["password"], Envelope)
        assert data["password"].reveal() == "hunter2"

    def test_both_orderings_equivalent(self):
        prefix = load(
            StringIO("k: !secret !env X\n"),
            env_overrides={"X": "v"},
        )
        postfix = load(
            StringIO("k: !env X !secret\n"),
            env_overrides={"X": "v"},
        )
        assert prefix["k"] == postfix["k"]

    def test_chain_masks_in_repr(self):
        data = load(
            StringIO("k: !env X !secret\n"),
            env_overrides={"X": "sensitive"},
        )
        assert "sensitive" not in repr(data)
        assert "sensitive" not in str(data)

    def test_optional_env_secret_returns_none_when_missing(self, monkeypatch):
        monkeypatch.delenv("MISSING", raising=False)
        data = load(
            StringIO("k: !env? MISSING !secret\n"),
            env_overrides={},
        )
        assert data["k"] is None

    def test_optional_env_secret_wraps_when_present(self):
        data = load(
            StringIO("k: !env? X !secret\n"),
            env_overrides={"X": "v"},
        )
        assert isinstance(data["k"], Envelope)
        assert data["k"].reveal() == "v"

    def test_missing_required_env_raises(self, monkeypatch):
        monkeypatch.delenv("MISSING", raising=False)
        with pytest.raises(yaml.YAMLError, match="not set"):
            load(
                StringIO("k: !env MISSING !secret\n"),
                env_overrides={},
            )


# =============================================================================
# Env Tag Tests
# =============================================================================


class TestEnvTag:
    """Test !env and !env? tag functionality for environment variable resolution."""

    def test_env_tag_resolves_set_variable(self, monkeypatch):
        """Test !env resolves a set environment variable."""
        monkeypatch.setenv("TEST_API_KEY", "secret123")
        yaml_content = """
api_key: !env TEST_API_KEY
"""
        data = load(StringIO(yaml_content))
        assert data["api_key"] == "secret123"

    def test_env_tag_raises_for_missing_variable(self, monkeypatch):
        """Test !env raises error for missing environment variable."""
        monkeypatch.delenv("NONEXISTENT_VAR_12345", raising=False)
        yaml_content = """
api_key: !env NONEXISTENT_VAR_12345
"""
        with pytest.raises(yaml.YAMLError) as exc_info:
            load(StringIO(yaml_content))
        assert "NONEXISTENT_VAR_12345" in str(exc_info.value)
        assert "not set" in str(exc_info.value)

    def test_env_tag_with_default_uses_default_when_missing(self, monkeypatch):
        """Test !env VAR:default returns default when VAR is not set."""
        monkeypatch.delenv("NONEXISTENT_TIMEOUT", raising=False)
        yaml_content = """
timeout: !env NONEXISTENT_TIMEOUT:30
"""
        data = load(StringIO(yaml_content))
        assert data["timeout"] == "30"

    def test_env_tag_with_default_uses_value_when_set(self, monkeypatch):
        """Test !env VAR:default returns value when VAR is set."""
        monkeypatch.setenv("MY_TIMEOUT", "60")
        yaml_content = """
timeout: !env MY_TIMEOUT:30
"""
        data = load(StringIO(yaml_content))
        assert data["timeout"] == "60"

    def test_env_tag_with_empty_default(self, monkeypatch):
        """Test !env VAR: returns empty string as default."""
        monkeypatch.delenv("NONEXISTENT_VAR", raising=False)
        yaml_content = """
optional_value: !env "NONEXISTENT_VAR:"
"""
        data = load(StringIO(yaml_content))
        assert data["optional_value"] == ""

    def test_env_tag_with_colon_in_default(self, monkeypatch):
        """Test !env VAR:default:with:colons preserves colons in default."""
        monkeypatch.delenv("NONEXISTENT_URL", raising=False)
        yaml_content = """
url: !env NONEXISTENT_URL:http://localhost:8080
"""
        data = load(StringIO(yaml_content))
        assert data["url"] == "http://localhost:8080"

    def test_env_optional_tag_returns_none_when_missing(self, monkeypatch):
        """Test !env? returns None for missing environment variable."""
        monkeypatch.delenv("NONEXISTENT_DEBUG_KEY", raising=False)
        yaml_content = """
debug_key: !env? NONEXISTENT_DEBUG_KEY
"""
        data = load(StringIO(yaml_content))
        assert data["debug_key"] is None

    def test_env_optional_tag_returns_value_when_set(self, monkeypatch):
        """Test !env? returns value when environment variable is set."""
        monkeypatch.setenv("DEBUG_KEY", "debug123")
        yaml_content = """
debug_key: !env? DEBUG_KEY
"""
        data = load(StringIO(yaml_content))
        assert data["debug_key"] == "debug123"

    def test_env_optional_tag_with_default_when_missing(self, monkeypatch):
        """Test !env? VAR:default returns default when VAR is not set."""
        monkeypatch.delenv("NONEXISTENT_LOG_LEVEL", raising=False)
        yaml_content = """
log_level: !env? NONEXISTENT_LOG_LEVEL:INFO
"""
        data = load(StringIO(yaml_content))
        assert data["log_level"] == "INFO"

    def test_env_tag_multiple_vars(self, monkeypatch):
        """Test multiple !env tags in same document."""
        monkeypatch.setenv("DB_HOST", "localhost")
        monkeypatch.setenv("DB_PORT", "5432")
        monkeypatch.delenv("DB_USER", raising=False)
        monkeypatch.delenv("DB_PASSWORD", raising=False)
        yaml_content = """
database:
  host: !env DB_HOST
  port: !env DB_PORT
  user: !env DB_USER:postgres
  password: !env? DB_PASSWORD
"""
        data = load(StringIO(yaml_content))
        assert data["database"]["host"] == "localhost"
        assert data["database"]["port"] == "5432"
        assert data["database"]["user"] == "postgres"
        assert data["database"]["password"] is None

    def test_env_tag_error_includes_location(self, monkeypatch):
        """Test that !env error message includes file location."""
        monkeypatch.delenv("MISSING_VAR_XYZ", raising=False)
        yaml_content = """
first: value
second: !env MISSING_VAR_XYZ
third: value
"""
        with pytest.raises(yaml.YAMLError) as exc_info:
            load(StringIO(yaml_content))
        error_msg = str(exc_info.value)
        assert "MISSING_VAR_XYZ" in error_msg
        assert "line" in error_msg.lower()

    def test_env_tag_empty_var_name_raises(self):
        """Test !env :default raises error for empty variable name."""
        yaml_content = """
value: !env ":default"
"""
        with pytest.raises(yaml.YAMLError) as exc_info:
            load(StringIO(yaml_content))
        assert "Empty environment variable name" in str(exc_info.value)

    def test_env_optional_tag_empty_var_name_raises(self):
        """Test !env? :default raises error for empty variable name."""
        yaml_content = """
value: !env? ":default"
"""
        with pytest.raises(yaml.YAMLError) as exc_info:
            load(StringIO(yaml_content))
        assert "Empty environment variable name" in str(exc_info.value)


class TestPathTag:
    """Test !path tag functionality for path resolution."""

    def test_path_tag_expands_tilde(self):
        """Test that !path expands ~ to home directory."""
        yaml_content = """
data_dir: !path ~/data/files
"""
        data = load(StringIO(yaml_content))
        expected = str(Path.home() / "data" / "files")
        assert data["data_dir"] == expected

    def test_path_tag_expands_tilde_with_subdirs(self):
        """Test that !path expands ~ in paths with multiple subdirectories."""
        yaml_content = """
config: !path ~/._appinfra_test_nonexistent/subdir/config.yaml
"""
        data = load(StringIO(yaml_content))
        expected = str(
            Path.home() / "._appinfra_test_nonexistent" / "subdir" / "config.yaml"
        )
        assert data["config"] == expected

    def test_path_tag_absolute_path_unchanged(self):
        """Test that !path leaves absolute paths unchanged."""
        yaml_content = """
path: !path /absolute/path/to/file
"""
        data = load(StringIO(yaml_content))
        assert data["path"] == "/absolute/path/to/file"

    @pytest.mark.integration
    def test_path_tag_relative_path_resolved(self, temp_dir: Path):
        """Test that !path resolves relative paths from config file directory."""
        config_file = temp_dir / "config.yaml"
        config_file.write_text("""
data: !path ./subdir/data.txt
""")
        with open(config_file) as f:
            data = load(f, current_file=config_file)

        expected = str((temp_dir / "subdir" / "data.txt").resolve())
        assert data["data"] == expected

    def test_path_tag_relative_path_without_context_raises(self):
        """Test that !path raises error for relative path without file context."""
        yaml_content = """
path: !path ./relative/path
"""
        with pytest.raises(yaml.YAMLError, match="Cannot resolve relative path"):
            load(StringIO(yaml_content))

    def test_path_tag_tilde_without_context_works(self):
        """Test that !path expands ~ even without file context."""
        yaml_content = """
home: !path ~/
"""
        data = load(StringIO(yaml_content))
        assert data["home"] == str(Path.home())


class TestYAMLMergeKeys:
    """Test YAML merge key (<<) support with anchors and aliases."""

    def test_merge_key_without_source_tracking(self):
        """Test basic merge key works without source tracking."""
        content = """
templates:
  common: &common
    setting1: value1
    setting2: value2

models:
  model_a:
    <<: *common
    setting3: value3
"""
        from io import StringIO

        result = load(StringIO(content), track_sources=False)
        assert result["models"]["model_a"] == {
            "setting1": "value1",
            "setting2": "value2",
            "setting3": "value3",
        }

    def test_merge_key_with_source_tracking(self):
        """Test merge key works with source tracking enabled."""
        content = """
templates:
  common: &common
    setting1: value1
    setting2: value2

models:
  model_a:
    <<: *common
    setting3: value3
"""
        from io import StringIO

        result, source_map = load(StringIO(content), track_sources=True)
        assert result["models"]["model_a"] == {
            "setting1": "value1",
            "setting2": "value2",
            "setting3": "value3",
        }
        assert source_map is not None

    def test_merge_key_override(self):
        """Test that local keys override merged keys."""
        content = """
defaults: &defaults
  adapter: postgres
  host: localhost
  port: 5432

production:
  <<: *defaults
  host: prod-server
"""
        from io import StringIO

        result, _ = load(StringIO(content), track_sources=True)
        assert result["production"] == {
            "adapter": "postgres",
            "host": "prod-server",
            "port": 5432,
        }

    def test_multiple_merge_keys(self):
        """Test multiple merge keys in same mapping."""
        content = """
base: &base
  a: 1
extra: &extra
  b: 2
combined:
  <<: *base
  <<: *extra
  c: 3
"""
        from io import StringIO

        result, _ = load(StringIO(content), track_sources=True)
        assert result["combined"] == {"a": 1, "b": 2, "c": 3}

    def test_nested_merge_keys(self):
        """Test merge keys in nested structures."""
        content = """
defaults: &defaults
  database:
    adapter: postgres

development:
  <<: *defaults
  database:
    name: dev_db

production:
  <<: *defaults
  database:
    name: prod_db
"""
        from io import StringIO

        result, _ = load(StringIO(content), track_sources=True)
        # Note: nested merge replaces entire sub-dict, doesn't deep merge
        assert result["development"]["database"] == {"name": "dev_db"}
        assert result["production"]["database"] == {"name": "prod_db"}

    def test_deeply_nested_merge_keys(self):
        """Test merge keys work in deeply nested structures with source tracking."""
        content = """
level1:
  defaults: &l1_defaults
    timeout: 30
  service:
    <<: *l1_defaults
    name: test
    level2:
      defaults: &l2_defaults
        retries: 3
      handler:
        <<: *l2_defaults
        endpoint: /api
"""
        from io import StringIO

        result, source_map = load(StringIO(content), track_sources=True)
        assert result["level1"]["service"]["timeout"] == 30
        assert result["level1"]["service"]["name"] == "test"
        assert result["level1"]["service"]["level2"]["handler"]["retries"] == 3
        assert result["level1"]["service"]["level2"]["handler"]["endpoint"] == "/api"
        assert source_map is not None


# =============================================================================
# Deep Merge Tag Tests (!deep)
# =============================================================================


class TestDeepMergeTag:
    """Test !deep tag for recursive deep merging with YAML merge keys (<<)."""

    def test_deep_merge_basic(self):
        """Test basic deep merge preserves nested keys from template."""
        content = """
templates:
  defaults: &defaults
    nested:
      a: 1
      b: 2

config:
  <<: !deep *defaults
  nested:
    c: 3
"""
        result = load(StringIO(content), track_sources=False)
        # Deep merge should preserve a, b from template and add c
        assert result["config"]["nested"] == {"a": 1, "b": 2, "c": 3}

    def test_deep_merge_hyphenated_anchor(self):
        """Test deep merge works with hyphenated anchor names (kebab-case)."""
        content = """
templates:
  my-defaults: &my-defaults
    nested:
      a: 1
      b: 2

config:
  <<: !deep *my-defaults
  nested:
    c: 3
"""
        result = load(StringIO(content), track_sources=False)
        assert result["config"]["nested"] == {"a": 1, "b": 2, "c": 3}

    def test_deep_merge_inline_mapping(self):
        """Test !deep with inline mapping (no anchor reference)."""
        content = """
config:
  <<: !deep {nested: {a: 1, b: 2}}
  nested:
    c: 3
"""
        result = load(StringIO(content), track_sources=False)
        # Inline mapping should also deep merge
        assert result["config"]["nested"] == {"a": 1, "b": 2, "c": 3}

    def test_deep_merge_override(self):
        """Test deep merge allows overriding specific nested values."""
        content = """
templates:
  server_default: &server_default
    timeout: 30
    options:
      debug: false
      max_connections: 100

servers:
  api:
    <<: !deep *server_default
    options:
      port: 8080
      debug: true
"""
        result = load(StringIO(content), track_sources=False)
        server = result["servers"]["api"]
        assert server["timeout"] == 30
        assert server["options"]["debug"] is True  # overridden
        assert server["options"]["max_connections"] == 100  # preserved from template
        assert server["options"]["port"] == 8080  # added

    def test_deep_merge_deeply_nested(self):
        """Test deep merge works with deeply nested structures."""
        content = """
base: &base
  level1:
    level2:
      level3:
        a: 1
        b: 2

config:
  <<: !deep *base
  level1:
    level2:
      level3:
        c: 3
      new_key: value
"""
        result = load(StringIO(content), track_sources=False)
        assert result["config"]["level1"]["level2"]["level3"] == {
            "a": 1,
            "b": 2,
            "c": 3,
        }
        assert result["config"]["level1"]["level2"]["new_key"] == "value"

    def test_deep_merge_vs_shallow_merge(self):
        """Test that !deep behaves differently from standard merge."""
        # Standard merge (shallow)
        shallow_content = """
base: &base
  nested:
    a: 1
    b: 2

config:
  <<: *base
  nested:
    c: 3
"""
        # Deep merge
        deep_content = """
base: &base
  nested:
    a: 1
    b: 2

config:
  <<: !deep *base
  nested:
    c: 3
"""
        shallow_result = load(StringIO(shallow_content), track_sources=False)
        deep_result = load(StringIO(deep_content), track_sources=False)

        # Shallow: nested is completely replaced
        assert shallow_result["config"]["nested"] == {"c": 3}

        # Deep: nested is merged
        assert deep_result["config"]["nested"] == {"a": 1, "b": 2, "c": 3}

    def test_deep_merge_multiple_anchors(self):
        """Test deep merge with multiple anchors in sequence."""
        content = """
base1: &base1
  shared:
    a: 1
  only_in_base1: true

base2: &base2
  shared:
    b: 2
  only_in_base2: true

config:
  <<: !deep *base1
  <<: !deep *base2
  shared:
    c: 3
"""
        result = load(StringIO(content), track_sources=False)
        # Both bases should be deep merged, then local overrides
        assert result["config"]["only_in_base1"] is True
        assert result["config"]["only_in_base2"] is True
        assert result["config"]["shared"] == {"a": 1, "b": 2, "c": 3}

    def test_deep_merge_with_lists(self):
        """Test that lists are replaced, not merged (list merge is ambiguous)."""
        content = """
base: &base
  items:
    - a
    - b

config:
  <<: !deep *base
  items:
    - c
"""
        result = load(StringIO(content), track_sources=False)
        # Lists should be replaced, not concatenated
        assert result["config"]["items"] == ["c"]

    def test_deep_merge_with_source_tracking(self):
        """Test deep merge works with source tracking enabled."""
        content = """
base: &base
  nested:
    a: 1

config:
  <<: !deep *base
  nested:
    b: 2
"""
        result, source_map = load(StringIO(content), track_sources=True)
        assert result["config"]["nested"] == {"a": 1, "b": 2}
        assert source_map is not None

    @pytest.mark.integration
    def test_include_always_deep_merges(self, tmp_path):
        """Test !include always deep merges (no !deep needed)."""
        # Create base config file
        base_file = tmp_path / "base.yaml"
        base_file.write_text("""
nested:
  a: 1
  b: 2
top_level: value
""")

        # !include now always deep merges - no !deep prefix needed
        main_content = f"""
config:
  <<: !include "{base_file}"
  nested:
    c: 3
"""
        result = load(StringIO(main_content), current_file=tmp_path / "main.yaml")
        assert result["config"]["top_level"] == "value"
        # Deep merged - all nested keys present
        assert result["config"]["nested"] == {"a": 1, "b": 2, "c": 3}

    def test_deep_merge_non_dict_raises_error(self):
        """Test that !deep on non-dict value raises clear error."""
        content = """
list_anchor: &list_anchor
  - item1
  - item2

config:
  <<: !deep *list_anchor
"""
        with pytest.raises(yaml.YAMLError) as exc_info:
            load(StringIO(content), track_sources=False)
        assert "requires a mapping" in str(exc_info.value)
        assert "list" in str(exc_info.value)

    def test_deep_merge_preserves_types(self):
        """Test that deep merge preserves value types correctly."""
        content = """
base: &base
  nested:
    string_val: hello
    int_val: 42
    float_val: 3.14
    bool_val: true
    null_val: null

config:
  <<: !deep *base
  nested:
    new_val: added
"""
        result = load(StringIO(content), track_sources=False)
        nested = result["config"]["nested"]
        assert nested["string_val"] == "hello"
        assert nested["int_val"] == 42
        assert nested["float_val"] == 3.14
        assert nested["bool_val"] is True
        assert nested["null_val"] is None
        assert nested["new_val"] == "added"

    def test_deep_merge_empty_override(self):
        """Test deep merge when local dict is empty (inherits all)."""
        content = """
base: &base
  nested:
    a: 1
    b: 2

config:
  <<: !deep *base
"""
        result = load(StringIO(content), track_sources=False)
        assert result["config"]["nested"] == {"a": 1, "b": 2}

    def test_deep_merge_list_syntax(self):
        """Test <<: !deep [*a, *b] applies deep merge to all items."""
        content = """
a: &a
  nested:
    x: 1
b: &b
  nested:
    y: 2

config:
  <<: !deep [*a, *b]
  nested:
    z: 3
"""
        result = load(StringIO(content), track_sources=False)
        # All nested keys should be merged
        assert result["config"]["nested"] == {"x": 1, "y": 2, "z": 3}

    def test_deep_merge_mixed_list_syntax(self):
        """Test <<: [*a, !deep *b] for mixed shallow/deep merge."""
        content = """
a: &a
  top_level: from_a

b: &b
  nested:
    x: 1

config:
  <<: [*a, !deep *b]
  nested:
    y: 2
"""
        result = load(StringIO(content), track_sources=False)
        assert result["config"]["top_level"] == "from_a"
        # Only *b is deep merged, so nested should have both x and y
        assert result["config"]["nested"] == {"x": 1, "y": 2}

    def test_deep_merge_multiple_merge_keys(self):
        """Test multiple <<: keys with mixed shallow and deep merge."""
        content = """
behavior: &behavior
  logging:
    enabled: true

settings: &settings
  timeout: 30
  database:
    pool_size: 10

service:
  <<: *behavior
  <<: !deep *settings
  database:
    host: localhost
"""
        result = load(StringIO(content), track_sources=False)
        service = result["service"]
        # behavior is shallow merged
        assert service["logging"] == {"enabled": True}
        # settings.timeout is inherited
        assert service["timeout"] == 30
        # database is deep merged
        assert service["database"]["pool_size"] == 10
        assert service["database"]["host"] == "localhost"

    @pytest.mark.integration
    def test_deep_merge_in_included_file(self, tmp_path):
        """Test !deep *anchor works inside an included file."""
        # Create services.yaml with anchors and !deep usage
        services_file = tmp_path / "services.yaml"
        services_file.write_text("""
templates:
  small_server: &small_server
    max_connections: 100
    options:
      debug: true

services:
  api:
    <<: !deep *small_server
    options:
      port: 8080
""")

        # Create main config that includes services.yaml
        main_content = f"""
config: !include "{services_file}"
"""
        result = load(StringIO(main_content), current_file=tmp_path / "main.yaml")

        service = result["config"]["services"]["api"]
        # Inherited from anchor
        assert service["max_connections"] == 100
        # Deep merged - both keys present
        assert service["options"]["debug"] is True
        assert service["options"]["port"] == 8080


# =============================================================================
# Reset Tag Tests
# =============================================================================


class TestResetTag:
    """Tests for !reset tag that bypasses deep merge."""

    @pytest.mark.integration
    def test_reset_bypasses_deep_merge_with_include(self, tmp_path):
        """Test !reset prevents deep merge when using !include."""
        base_file = tmp_path / "base.yaml"
        base_file.write_text("""
options:
  retries: 3
  timeout: 30
  debug: true
""")

        main_content = f"""
config:
  <<: !include "{base_file}"
  options: !reset {{cache: true}}
"""
        result = load(StringIO(main_content), current_file=tmp_path / "main.yaml")
        # !reset should completely replace options, not merge
        assert result["config"]["options"] == {"cache": True}
        assert "retries" not in result["config"]["options"]
        assert "timeout" not in result["config"]["options"]

    def test_reset_bypasses_deep_merge_with_anchor(self):
        """Test !reset prevents deep merge when using !deep *anchor."""
        content = """
defaults: &defaults
  options:
    a: 1
    b: 2

config:
  <<: !deep *defaults
  options: !reset {c: 3}
"""
        result = load(StringIO(content), track_sources=False)
        # !reset should completely replace options
        assert result["config"]["options"] == {"c": 3}
        assert "a" not in result["config"]["options"]

    def test_reset_with_scalar_value(self):
        """Test !reset works with scalar values."""
        content = """
defaults: &defaults
  count: 10

config:
  <<: !deep *defaults
  count: !reset 0
"""
        result = load(StringIO(content), track_sources=False)
        assert result["config"]["count"] == 0

    def test_reset_with_list_value(self):
        """Test !reset works with list values."""
        content = """
defaults: &defaults
  items:
    - a
    - b

config:
  <<: !deep *defaults
  items: !reset [c]
"""
        result = load(StringIO(content), track_sources=False)
        assert result["config"]["items"] == ["c"]

    def test_without_reset_deep_merges(self):
        """Test that without !reset, deep merge happens normally."""
        content = """
defaults: &defaults
  options:
    a: 1
    b: 2

config:
  <<: !deep *defaults
  options:
    c: 3
"""
        result = load(StringIO(content), track_sources=False)
        # Without !reset, options should be deep merged
        assert result["config"]["options"] == {"a": 1, "b": 2, "c": 3}

    def test_reset_in_nested_structure(self):
        """Test !reset works in nested structures."""
        content = """
defaults: &defaults
  level1:
    level2:
      a: 1
      b: 2

config:
  <<: !deep *defaults
  level1:
    level2: !reset {c: 3}
"""
        result = load(StringIO(content), track_sources=False)
        # level2 should be completely replaced
        assert result["config"]["level1"]["level2"] == {"c": 3}


# =============================================================================
# DeepMergeWrapper Unit Tests
# =============================================================================


class TestDeepMergeWrapper:
    """Unit tests for DeepMergeWrapper class."""

    def test_wrapper_accepts_dict(self):
        """Test wrapper accepts dict input."""
        from appinfra.yaml import DeepMergeWrapper

        data = {"key": "value"}
        wrapper = DeepMergeWrapper(data)
        assert wrapper.data == data

    def test_wrapper_rejects_list(self):
        """Test wrapper rejects list input."""
        from appinfra.yaml import DeepMergeWrapper

        with pytest.raises(TypeError) as exc_info:
            DeepMergeWrapper(["a", "b"])
        assert "requires a mapping" in str(exc_info.value)
        assert "list" in str(exc_info.value)

    def test_wrapper_rejects_string(self):
        """Test wrapper rejects string input."""
        from appinfra.yaml import DeepMergeWrapper

        with pytest.raises(TypeError) as exc_info:
            DeepMergeWrapper("string")
        assert "requires a mapping" in str(exc_info.value)
        assert "str" in str(exc_info.value)

    def test_wrapper_rejects_none(self):
        """Test wrapper rejects None input."""
        from appinfra.yaml import DeepMergeWrapper

        with pytest.raises(TypeError) as exc_info:
            DeepMergeWrapper(None)
        assert "requires a mapping" in str(exc_info.value)

    def test_wrapper_repr(self):
        """Test wrapper has useful repr."""
        from appinfra.yaml import DeepMergeWrapper

        wrapper = DeepMergeWrapper({"a": 1})
        assert "DeepMergeWrapper" in repr(wrapper)
        assert "a" in repr(wrapper)


# =============================================================================
# Tag Chain Mechanism Tests
# =============================================================================


class TestTagChainPreprocessing:
    """Tests for the generic tag chain preprocessor."""

    def test_prefix_and_postfix_produce_identical_canonical_form(self):
        """Both orderings normalize to the same synthetic !chain: tag."""
        from appinfra.yaml.loader import preprocess_tag_chains

        prefix = preprocess_tag_chains('a: !deep !include "x.yaml"')
        postfix = preprocess_tag_chains('a: !include "x.yaml" !deep')
        assert prefix == postfix == 'a: !chain:include+deep "x.yaml"'

    def test_arbitrary_length_chain(self):
        """Chains of 3+ tags are supported with policies sorted alphabetically."""
        from appinfra.yaml.loader import preprocess_tag_chains

        prefix = preprocess_tag_chains("a: !audit !secret !env FOO")
        postfix = preprocess_tag_chains("a: !env FOO !secret !audit")
        assert prefix == postfix == "a: !chain:env+audit+secret FOO"

    def test_policies_sorted_for_stable_canonical_form(self):
        """Policy order in source syntax does not affect the canonical form."""
        from appinfra.yaml.loader import preprocess_tag_chains

        a = preprocess_tag_chains("k: !audit !secret !env X")
        b = preprocess_tag_chains("k: !secret !audit !env X")
        assert a == b

    def test_single_tag_untouched(self):
        """A lone tag is not a chain and passes through unchanged."""
        from appinfra.yaml.loader import preprocess_tag_chains

        assert preprocess_tag_chains("a: !env FOO") == "a: !env FOO"
        assert preprocess_tag_chains("a: !secret X") == "a: !secret X"

    def test_optional_variant_preserved(self):
        """The ? marker on !include? / !env? survives the rewrite."""
        from appinfra.yaml.loader import preprocess_tag_chains

        assert (
            preprocess_tag_chains('a: !deep !include? "x.yaml"')
            == 'a: !chain:include?+deep "x.yaml"'
        )

    def test_adjacent_include_lines_not_treated_as_chain(self):
        """Document-level !include on consecutive lines must not merge into a chain.

        Regression test — the chain regex must be single-line-scoped so a following
        !include on the next line is a separate document-level tag, not a policy.
        """
        from appinfra.yaml.loader import preprocess_tag_chains

        content = '!include "./base1.yaml"\n!include "./base2.yaml"\nname: app\n'
        assert preprocess_tag_chains(content) == content

    def test_quoted_arg_with_spaces(self):
        """Quoted args containing whitespace are preserved intact."""
        from appinfra.yaml.loader import preprocess_tag_chains

        content = 'x: !deep !include "path with space.yaml"'
        result = preprocess_tag_chains(content)
        assert result == 'x: !chain:include+deep "path with space.yaml"'

    def test_reapplying_preprocessor_is_idempotent(self):
        """The synthetic !chain: tag is excluded from further matching."""
        from appinfra.yaml.loader import preprocess_tag_chains

        once = preprocess_tag_chains("a: !secret !env FOO")
        twice = preprocess_tag_chains(once)
        assert once == twice

    def test_tag_like_patterns_inside_quoted_values_not_rewritten(self):
        """Quoted scalar values containing tag-like patterns are left unchanged.

        Regression test for CodeRabbit finding: the chain preprocessor was
        matching tag patterns anywhere in the file, including inside quoted
        strings where they are literal text, not YAML tags.
        """
        from appinfra.yaml.loader import preprocess_tag_chains

        double_quoted = 'msg: "literal !deep !include x.yaml"'
        assert preprocess_tag_chains(double_quoted) == double_quoted

        single_quoted = "msg: 'literal !secret !env FOO'"
        assert preprocess_tag_chains(single_quoted) == single_quoted

    def test_quoted_values_with_tag_like_patterns_load_correctly(self):
        """End-to-end: quoted strings with tag-like patterns load as literals."""
        content = 'msg: "example !deep !include syntax"'
        data = load(StringIO(content))
        assert data["msg"] == "example !deep !include syntax"


class TestTagChainRegistry:
    """Tests for the composer registration and dispatch machinery."""

    def test_duplicate_registration_raises(self):
        """register_chain refuses to overwrite an existing composer."""
        from appinfra.yaml.loader import register_chain

        with pytest.raises(ValueError, match="already registered"):

            @register_chain("include", "deep")
            def _dup(loader, node):
                return None

    def test_unknown_chain_raises_with_supported_listing(self):
        """Chains not in the registry fail at parse time with a helpful message."""
        content = "a: !nosuch !env FOO"
        with pytest.raises(yaml.YAMLError) as exc:
            load(StringIO(content))
        msg = str(exc.value)
        assert "Unsupported tag chain" in msg
        assert "Supported chains" in msg
        # The one registered chain should be listed
        assert "!include" in msg and "!deep" in msg
