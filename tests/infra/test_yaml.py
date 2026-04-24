"""
Tests for infra.yaml module (YAML parsing with includes).

Comprehensive tests for custom YAML loader covering parsing, includes,
security, error handling, and edge cases.
"""

from io import StringIO
from pathlib import Path

import pytest
import yaml

from appinfra.yaml import (
    ErrorContext,
    SecretLiteralWarning,
    deep_merge,
    load,
    load_file,
)

# =============================================================================
# Unit Tests for ErrorContext
# =============================================================================


@pytest.mark.unit
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


@pytest.fixture
def yaml_files_dir(temp_dir: Path):
    """Create a directory with test YAML files."""
    # Main config
    (temp_dir / "main.yaml").write_text(
        """
app:
  name: main_app
  version: 1.0.0
database: !include "./db.yaml"
"""
    )

    # Database config
    (temp_dir / "db.yaml").write_text(
        """
host: localhost
port: 5432
name: test_db
"""
    )

    # Nested include
    (temp_dir / "nested.yaml").write_text(
        """
level1: !include "./level2.yaml"
"""
    )

    (temp_dir / "level2.yaml").write_text(
        """
level2: !include "./level3.yaml"
"""
    )

    (temp_dir / "level3.yaml").write_text(
        """
value: "deep"
"""
    )

    # Circular includes
    (temp_dir / "circular_a.yaml").write_text(
        """
data: !include "./circular_b.yaml"
"""
    )

    (temp_dir / "circular_b.yaml").write_text(
        """
data: !include "./circular_a.yaml"
"""
    )

    return temp_dir


@pytest.fixture
def malformed_yaml():
    """Provide malformed YAML content."""
    return """
app:
  name: test
  invalid: [unclosed list
  another: value
"""


# =============================================================================
# Basic Parsing Tests
# =============================================================================


@pytest.mark.unit
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


@pytest.mark.unit
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
# Include Tests
# =============================================================================


@pytest.mark.unit
class TestIncludeFunctionality:
    """Test !include tag functionality."""

    def test_include_basic_file(self, yaml_files_dir):
        """Test basic file inclusion."""
        main_file = yaml_files_dir / "main.yaml"

        with open(main_file) as f:
            data = load(f, current_file=main_file)

        assert data["app"]["name"] == "main_app"
        assert data["database"]["host"] == "localhost"
        assert data["database"]["port"] == 5432

    def test_include_nested_includes(self, yaml_files_dir):
        """Test nested (recursive) includes."""
        nested_file = yaml_files_dir / "nested.yaml"

        with open(nested_file) as f:
            data = load(f, current_file=nested_file)

        # Should resolve through level1 -> level2 -> level3
        assert data["level1"]["level2"]["value"] == "deep"

    def test_include_with_absolute_path(self, yaml_files_dir):
        """Test inclusion with absolute path."""
        db_file = yaml_files_dir / "db.yaml"
        yaml_content = f"""
database: !include "{db_file.absolute()}"
"""
        data = load(StringIO(yaml_content), current_file=yaml_files_dir / "test.yaml")

        assert data["database"]["host"] == "localhost"

    def test_include_without_current_file_fails(self):
        """Test inclusion fails without current_file context."""
        yaml_content = """
database: !include "./db.yaml"
"""
        with pytest.raises(
            yaml.YAMLError, match="Cannot resolve relative include path"
        ):
            load(StringIO(yaml_content))

    def test_include_nonexistent_file_fails(self, yaml_files_dir):
        """Test inclusion of non-existent file fails."""
        yaml_content = """
data: !include "./nonexistent.yaml"
"""
        with pytest.raises(yaml.YAMLError, match="Include file not found"):
            load(StringIO(yaml_content), current_file=yaml_files_dir / "test.yaml")

    def test_include_error_includes_location_info(self, yaml_files_dir):
        """Test that include errors include file and line/column info."""
        yaml_content = """name: test
data: !include "./nonexistent.yaml"
other: value
"""
        with pytest.raises(yaml.YAMLError) as exc_info:
            load(StringIO(yaml_content), current_file=yaml_files_dir / "test.yaml")

        error_msg = str(exc_info.value)
        # Should include file path
        assert "test.yaml" in error_msg
        # Should include line number (line 2, 0-indexed = 1, displayed as 2)
        assert "line 2" in error_msg


# =============================================================================
# Optional Include Tests
# =============================================================================


@pytest.mark.unit
class TestOptionalInclude:
    """Test !include? optional include directive."""

    def test_optional_include_returns_empty_dict_for_missing_file(self, tmp_path):
        """Test that !include? returns {} when file is missing."""
        yaml_content = """
name: test
data: !include? "./nonexistent.yaml"
"""
        result = load(StringIO(yaml_content), current_file=tmp_path / "test.yaml")
        assert result["name"] == "test"
        assert result["data"] == {}

    def test_optional_include_loads_existing_file(self, tmp_path):
        """Test that !include? loads file normally when it exists."""
        (tmp_path / "exists.yaml").write_text("key: value\n")
        yaml_content = """
data: !include? "./exists.yaml"
"""
        result = load(StringIO(yaml_content), current_file=tmp_path / "test.yaml")
        assert result["data"]["key"] == "value"

    def test_optional_include_with_section_anchor(self, tmp_path):
        """Test that !include? with section anchor returns {} when file missing."""
        yaml_content = """
data: !include? "./nonexistent.yaml#section"
"""
        result = load(StringIO(yaml_content), current_file=tmp_path / "test.yaml")
        assert result["data"] == {}

    def test_optional_include_still_validates_circular(self, tmp_path):
        """Test that !include? still detects circular includes for existing files."""
        (tmp_path / "circular.yaml").write_text('data: !include? "./circular.yaml"\n')
        yaml_content = """
data: !include? "./circular.yaml"
"""
        with pytest.raises(yaml.YAMLError, match="Circular include detected"):
            load(StringIO(yaml_content), current_file=tmp_path / "circular.yaml")

    def test_document_level_optional_include_missing(self, tmp_path):
        """Test document-level !include? returns empty when file missing."""
        yaml_content = """!include? "./nonexistent.yaml"

name: test
"""
        result = load(StringIO(yaml_content), current_file=tmp_path / "test.yaml")
        assert result["name"] == "test"

    def test_document_level_optional_include_existing(self, tmp_path):
        """Test document-level !include? loads and merges existing file."""
        (tmp_path / "base.yaml").write_text("base_key: base_value\n")
        yaml_content = """!include? "./base.yaml"

name: test
"""
        result = load(StringIO(yaml_content), current_file=tmp_path / "test.yaml")
        assert result["name"] == "test"
        assert result["base_key"] == "base_value"


# =============================================================================
# load_file() Convenience Function Tests
# =============================================================================


@pytest.mark.unit
class TestLoadFile:
    """Test load_file() convenience function."""

    def test_load_file_basic(self, tmp_path):
        """Test basic file loading."""
        (tmp_path / "config.yaml").write_text("name: test\nvalue: 42\n")
        result = load_file(tmp_path / "config.yaml")
        assert result["name"] == "test"
        assert result["value"] == 42

    def test_load_file_with_relative_include(self, tmp_path):
        """Test that load_file enables relative includes automatically."""
        (tmp_path / "base.yaml").write_text("base_key: base_value\n")
        (tmp_path / "config.yaml").write_text('data: !include "./base.yaml"\n')
        result = load_file(tmp_path / "config.yaml")
        assert result["data"]["base_key"] == "base_value"

    def test_load_file_with_optional_include(self, tmp_path):
        """Test that load_file works with optional includes."""
        (tmp_path / "config.yaml").write_text(
            'name: test\noverrides: !include? "./missing.yaml"\n'
        )
        result = load_file(tmp_path / "config.yaml")
        assert result["name"] == "test"
        assert result["overrides"] == {}

    def test_load_file_with_parent_relative_include(self, tmp_path):
        """Test that load_file resolves ../ paths correctly."""
        subdir = tmp_path / "etc"
        subdir.mkdir()
        (tmp_path / "env.yaml").write_text("env: production\n")
        (subdir / "config.yaml").write_text('settings: !include "../env.yaml"\n')
        result = load_file(subdir / "config.yaml")
        assert result["settings"]["env"] == "production"

    def test_load_file_string_path(self, tmp_path):
        """Test that load_file accepts string paths."""
        (tmp_path / "config.yaml").write_text("key: value\n")
        result = load_file(str(tmp_path / "config.yaml"))
        assert result["key"] == "value"


# =============================================================================
# Circular Dependency Tests
# =============================================================================


@pytest.mark.unit
class TestCircularDependencies:
    """Test circular include detection."""

    def test_detect_circular_include(self, yaml_files_dir):
        """Test circular includes are detected."""
        circular_file = yaml_files_dir / "circular_a.yaml"

        with open(circular_file) as f:
            with pytest.raises(yaml.YAMLError, match="Circular include detected"):
                load(f, current_file=circular_file)

    def test_detect_self_include(self, yaml_files_dir):
        """Test self-inclusion is detected as circular."""
        self_include_file = yaml_files_dir / "self.yaml"
        self_include_file.write_text(
            """
data: !include "./self.yaml"
"""
        )

        with open(self_include_file) as f:
            with pytest.raises(yaml.YAMLError, match="Circular include detected"):
                load(f, current_file=self_include_file)


# =============================================================================
# Include Depth Limit Tests
# =============================================================================


@pytest.mark.unit
class TestIncludeDepthLimit:
    """Test include depth limit to prevent stack overflow."""

    def test_depth_limit_prevents_deep_nesting(self, yaml_files_dir, tmp_path):
        """Test that deeply nested includes are rejected."""
        # Create a chain of 12 files that include each other
        files = []
        for i in range(12):
            file_path = tmp_path / f"level{i}.yaml"
            if i == 11:
                # Last file has actual content
                content = "value: 'deep'\n"
            else:
                # Each file includes the next
                next_file = f"level{i + 1}.yaml"
                content = f"data: !include './{next_file}'\n"
            file_path.write_text(content)
            files.append(file_path)

        # Try to load the first file with default depth limit (10)
        with open(files[0]) as f:
            with pytest.raises(
                yaml.YAMLError, match="Include depth exceeds maximum of 10"
            ):
                load(f, current_file=files[0])

    def test_depth_limit_allows_shallow_nesting(self, tmp_path):
        """Test that shallow nesting within limit is allowed."""
        # Create a chain of 5 files (well under default limit of 10)
        files = []
        for i in range(5):
            file_path = tmp_path / f"level{i}.yaml"
            if i == 4:
                content = "value: 'shallow'\n"
            else:
                next_file = f"level{i + 1}.yaml"
                content = f"data: !include './{next_file}'\n"
            file_path.write_text(content)
            files.append(file_path)

        # Should succeed
        with open(files[0]) as f:
            data = load(f, current_file=files[0])

        # Verify data was loaded correctly
        expected = {"data": {"data": {"data": {"data": {"value": "shallow"}}}}}
        assert data == expected

    def test_custom_depth_limit(self, tmp_path):
        """Test that custom depth limit can be specified."""
        # Create a chain of 4 files
        files = []
        for i in range(4):
            file_path = tmp_path / f"level{i}.yaml"
            if i == 3:
                content = "value: 'test'\n"
            else:
                next_file = f"level{i + 1}.yaml"
                content = f"data: !include './{next_file}'\n"
            file_path.write_text(content)
            files.append(file_path)

        # Should fail with custom limit of 2
        with open(files[0]) as f:
            with pytest.raises(
                yaml.YAMLError, match="Include depth exceeds maximum of 2"
            ):
                load(f, current_file=files[0], max_include_depth=2)

        # Should succeed with custom limit of 5
        with open(files[0]) as f:
            data = load(f, current_file=files[0], max_include_depth=5)
        assert data["data"]["data"]["data"]["value"] == "test"

    def test_depth_limit_error_shows_chain(self, tmp_path):
        """Test that depth limit error shows the include chain."""
        # Create a chain of 12 files
        files = []
        for i in range(12):
            file_path = tmp_path / f"file{i}.yaml"
            if i == 11:
                content = "value: 'end'\n"
            else:
                next_file = f"file{i + 1}.yaml"
                content = f"data: !include './{next_file}'\n"
            file_path.write_text(content)
            files.append(file_path)

        # Error message should include the include chain
        with open(files[0]) as f:
            with pytest.raises(yaml.YAMLError) as exc_info:
                load(f, current_file=files[0])

        error_msg = str(exc_info.value)
        assert "Include chain:" in error_msg
        # Should mention it's about recursive/deeply nested patterns
        assert "deeply nested" in error_msg or "recursive" in error_msg


# =============================================================================
# Security Tests
# =============================================================================


@pytest.mark.security
class TestSecurityValidation:
    """Test security aspects of YAML parsing."""

    @pytest.mark.parametrize(
        "payload",
        [
            "../../../nonexistent_file.yaml",
            "....//....//nonexistent.yaml",
            "/nonexistent/path/file.yaml",
        ],
    )
    def test_path_traversal_to_nonexistent_files(self, yaml_files_dir, payload):
        """Test that path traversal to non-existent files fails gracefully."""
        # Create a YAML with path traversal attempt to non-existent file
        yaml_content = f"""
data: !include "{payload}"
"""
        # Should fail with file not found, not crash
        with pytest.raises(yaml.YAMLError, match="Include file not found"):
            load(StringIO(yaml_content), current_file=yaml_files_dir / "test.yaml")

    def test_absolute_path_to_nonexistent_file(self, yaml_files_dir):
        """Test absolute paths to non-existent files fail."""
        # Try to include non-existent absolute path
        yaml_content = """
data: !include "/nonexistent/absolute/path/config.yaml"
"""
        # Should fail with file not found
        with pytest.raises(yaml.YAMLError, match="Include file not found"):
            load(StringIO(yaml_content), current_file=yaml_files_dir / "test.yaml")

    def test_malformed_yaml_raises_error(self, malformed_yaml):
        """Test malformed YAML raises appropriate error."""
        with pytest.raises(yaml.YAMLError):
            load(StringIO(malformed_yaml))

    def test_yaml_bomb_protection(self):
        """Test protection against YAML bombs (SafeLoader)."""
        # YAML bomb attempt (billion laughs attack)
        yaml_bomb = """
a: &a ["lol","lol","lol","lol","lol","lol","lol","lol","lol"]
b: &b [*a,*a,*a,*a,*a,*a,*a,*a,*a]
c: &c [*b,*b,*b,*b,*b,*b,*b,*b,*b]
d: &d [*c,*c,*c,*c,*c,*c,*c,*c,*c]
"""
        # SafeLoader should handle this gracefully (might be slow but won't crash)
        data = load(StringIO(yaml_bomb))
        assert data is not None

    def test_arbitrary_code_execution_prevented(self):
        """Test that arbitrary code execution is prevented."""
        # Attempt to use !!python/object to execute code
        malicious_yaml = """
data: !!python/object/apply:os.system ["echo pwned"]
"""
        # SafeLoader should reject this
        with pytest.raises(yaml.YAMLError):
            load(StringIO(malicious_yaml))

    def test_path_traversal_protection_with_project_root(self, tmp_path):
        """Test that path traversal is blocked when project_root is set."""
        # Create project structure
        project_root = tmp_path / "project"
        project_root.mkdir()
        config_dir = project_root / "config"
        config_dir.mkdir()

        # Create a file outside project root
        outside_file = tmp_path / "outside.yaml"
        outside_file.write_text("secret: password")

        # Create main config that tries to include file outside project root
        main_config = config_dir / "main.yaml"
        main_config.write_text(
            """
data: !include "../../outside.yaml"
"""
        )

        # Should raise security error
        with open(main_config) as f:
            with pytest.raises(yaml.YAMLError, match="Security.*outside project root"):
                load(f, current_file=main_config, project_root=project_root)

    def test_path_traversal_protection_allows_within_root(self, tmp_path):
        """Test that includes within project root work when project_root is set."""
        # Create project structure
        project_root = tmp_path / "project"
        project_root.mkdir()
        config_dir = project_root / "config"
        config_dir.mkdir()

        # Create included file within project root
        included_file = project_root / "shared.yaml"
        included_file.write_text("shared_value: 42")

        # Create main config that includes file within project root
        main_config = config_dir / "main.yaml"
        main_config.write_text(
            """
data: !include "../shared.yaml"
"""
        )

        # Should work fine
        with open(main_config) as f:
            result = load(f, current_file=main_config, project_root=project_root)

        assert result["data"]["shared_value"] == 42

    def test_path_traversal_without_project_root_unrestricted(self, tmp_path):
        """Test that includes work normally when project_root is not set."""
        # Create files outside the config directory
        parent_dir = tmp_path / "parent"
        parent_dir.mkdir()
        included_file = parent_dir / "included.yaml"
        included_file.write_text("value: 123")

        config_dir = parent_dir / "config"
        config_dir.mkdir()
        main_config = config_dir / "main.yaml"
        main_config.write_text(
            """
data: !include "../included.yaml"
"""
        )

        # Without project_root, traversal should work (backward compatibility)
        with open(main_config) as f:
            result = load(f, current_file=main_config)

        assert result["data"]["value"] == 123

    def test_absolute_path_outside_project_root_blocked(self, tmp_path):
        """Test that absolute paths outside project root are blocked."""
        # Create project structure
        project_root = tmp_path / "project"
        project_root.mkdir()

        # Create file outside project root with absolute path
        outside_file = tmp_path / "secrets.yaml"
        outside_file.write_text("password: secret123")

        # Create main config with absolute path to outside file
        main_config = project_root / "config.yaml"
        main_config.write_text(
            f"""
data: !include "{outside_file}"
"""
        )

        # Should raise security error
        with open(main_config) as f:
            with pytest.raises(yaml.YAMLError, match="Security.*outside project root"):
                load(f, current_file=main_config, project_root=project_root)


# =============================================================================
# Deep Merge Tests
# =============================================================================


@pytest.mark.unit
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


@pytest.mark.unit
class TestSourceTracking:
    """Test source file tracking functionality."""

    def test_source_tracking_basic(self, yaml_files_dir):
        """Test basic source tracking."""
        main_file = yaml_files_dir / "main.yaml"

        with open(main_file) as f:
            data, source_map = load(f, current_file=main_file, track_sources=True)

        assert source_map is not None
        assert isinstance(source_map, dict)

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


@pytest.mark.unit
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

    def test_invalid_include_path_type(self, yaml_files_dir):
        """Test that non-string include paths fail."""
        # This would be caught by YAML parser before reaching our code
        yaml_content = """
data: !include 12345
"""
        # YAML parser will convert 12345 to string "12345"
        with pytest.raises(yaml.YAMLError, match="Include file not found"):
            load(StringIO(yaml_content), current_file=yaml_files_dir / "test.yaml")

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


@pytest.mark.unit
class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_include_empty_file(self, yaml_files_dir):
        """Test including an empty YAML file."""
        empty_file = yaml_files_dir / "empty.yaml"
        empty_file.write_text("")

        yaml_content = """
data: !include "./empty.yaml"
"""
        data = load(StringIO(yaml_content), current_file=yaml_files_dir / "test.yaml")

        assert data["data"] is None

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
# Integration Tests
# =============================================================================


@pytest.mark.integration
class TestYAMLIntegration:
    """Integration tests for complete YAML workflows."""

    def test_complex_config_with_multiple_includes(self, yaml_files_dir):
        """Test complex configuration with multiple includes."""
        # Create a complex multi-file config
        (yaml_files_dir / "main_complex.yaml").write_text(
            """
app:
  name: complex_app
  database: !include "./db.yaml"
  logging:
    level: debug
    handlers: !include "./logging.yaml"
"""
        )

        (yaml_files_dir / "logging.yaml").write_text(
            """
console:
  enabled: true
  format: "%(message)s"
file:
  enabled: true
  path: "/var/log/app.log"
"""
        )

        main_file = yaml_files_dir / "main_complex.yaml"

        with open(main_file) as f:
            data = load(f, current_file=main_file)

        # Verify structure
        assert data["app"]["name"] == "complex_app"
        assert data["app"]["database"]["host"] == "localhost"
        assert data["app"]["logging"]["level"] == "debug"
        assert data["app"]["logging"]["handlers"]["console"]["enabled"] is True

    def test_real_world_config_structure(self, yaml_files_dir):
        """Test realistic configuration structure."""
        (yaml_files_dir / "production.yaml").write_text(
            """
environment: production

app:
  name: myapp
  version: "2.0.0"
  debug: false

database:
  primary:
    host: db-primary.example.com
    port: 5432
    pool_size: 20
  replica:
    host: db-replica.example.com
    port: 5432
    pool_size: 10

cache:
  enabled: true
  backend: redis
  servers:
    - redis-1.example.com:6379
    - redis-2.example.com:6379

logging:
  level: info
  format: json
  outputs:
    - type: console
    - type: file
      path: /var/log/app/production.log
    - type: syslog
      facility: local0
"""
        )

        config_file = yaml_files_dir / "production.yaml"

        with open(config_file) as f:
            data = load(f, current_file=config_file)

        # Verify complex structure loads correctly
        assert data["environment"] == "production"
        assert data["app"]["debug"] is False
        assert data["database"]["primary"]["pool_size"] == 20
        assert len(data["cache"]["servers"]) == 2
        assert len(data["logging"]["outputs"]) == 3


# =============================================================================
# Secret Tag Tests
# =============================================================================


@pytest.mark.unit
class TestSecretTag:
    """Test !secret tag functionality for sensitive value validation."""

    def test_secret_tag_accepts_env_var_syntax(self):
        """Test that !secret accepts proper ${VAR_NAME} syntax without warning."""
        yaml_content = """
database:
  password: !secret ${DB_PASSWORD}
"""
        import warnings

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            data = load(StringIO(yaml_content))

            assert data["database"]["password"] == "${DB_PASSWORD}"
            # No SecretLiteralWarning should be emitted
            secret_warnings = [
                x for x in w if issubclass(x.category, SecretLiteralWarning)
            ]
            assert len(secret_warnings) == 0

    def test_secret_tag_warns_on_literal_value(self):
        """Test that !secret emits SecretLiteralWarning for literal values."""
        yaml_content = """
database:
  password: !secret my_actual_password
"""
        import warnings

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            data = load(StringIO(yaml_content))

            assert data["database"]["password"] == "my_actual_password"
            # Should emit SecretLiteralWarning
            secret_warnings = [
                x for x in w if issubclass(x.category, SecretLiteralWarning)
            ]
            assert len(secret_warnings) == 1
            assert "literal" in str(secret_warnings[0].message).lower()

    def test_secret_tag_returns_value_regardless(self):
        """Test that !secret returns the value whether valid or not."""
        yaml_content = """
valid: !secret ${API_KEY}
invalid: !secret plaintext_secret
"""
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            data = load(StringIO(yaml_content))

            assert data["valid"] == "${API_KEY}"
            assert data["invalid"] == "plaintext_secret"

    @pytest.mark.parametrize(
        "env_var",
        [
            "${A}",
            "${VAR}",
            "${MY_VAR}",
            "${VAR_123}",
            "${_PRIVATE}",
            "${_}",
        ],
    )
    def test_secret_tag_various_env_var_formats(self, env_var):
        """Test !secret accepts various valid env var formats."""
        yaml_content = f"""
secret: !secret {env_var}
"""
        import warnings

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            data = load(StringIO(yaml_content))

            assert data["secret"] == env_var
            secret_warnings = [
                x for x in w if issubclass(x.category, SecretLiteralWarning)
            ]
            assert len(secret_warnings) == 0

    @pytest.mark.parametrize(
        "invalid_format",
        [
            "$VAR",  # Missing braces
            "${123VAR}",  # Starts with number
            "${}",  # Empty
            "${VAR-NAME}",  # Contains hyphen
            "VAR",  # No $ at all
            "${VAR} extra",  # Extra content
            "prefix ${VAR}",  # Prefix content
        ],
    )
    def test_secret_tag_warns_on_invalid_formats(self, invalid_format):
        """Test !secret warns on invalid env var formats."""
        yaml_content = f"""
secret: !secret "{invalid_format}"
"""
        import warnings

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            data = load(StringIO(yaml_content))

            assert data["secret"] == invalid_format
            secret_warnings = [
                x for x in w if issubclass(x.category, SecretLiteralWarning)
            ]
            assert len(secret_warnings) == 1

    def test_secret_tag_truncates_long_values_in_warning(self):
        """Test that long literal values are truncated in warning message."""
        long_value = "a" * 50
        yaml_content = f"""
secret: !secret {long_value}
"""
        import warnings

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            load(StringIO(yaml_content))

            secret_warnings = [
                x for x in w if issubclass(x.category, SecretLiteralWarning)
            ]
            assert len(secret_warnings) == 1
            warning_message = str(secret_warnings[0].message)
            # Should contain truncated value with "..."
            assert "..." in warning_message
            # Should NOT contain the full 50-char value
            assert long_value not in warning_message

    def test_secret_tag_multiple_secrets(self):
        """Test multiple !secret tags in same document."""
        yaml_content = """
database:
  password: !secret ${DB_PASSWORD}
  api_key: !secret literal_key
  token: !secret ${AUTH_TOKEN}
"""
        import warnings

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            data = load(StringIO(yaml_content))

            assert data["database"]["password"] == "${DB_PASSWORD}"
            assert data["database"]["api_key"] == "literal_key"
            assert data["database"]["token"] == "${AUTH_TOKEN}"

            # Should have exactly one warning (for literal_key)
            secret_warnings = [
                x for x in w if issubclass(x.category, SecretLiteralWarning)
            ]
            assert len(secret_warnings) == 1


# =============================================================================
# Env Tag Tests
# =============================================================================


@pytest.mark.unit
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


# =============================================================================
# Document-Level Include Tests
# =============================================================================


@pytest.mark.unit
class TestDocumentLevelIncludes:
    """Test document-level !include directive functionality."""

    def test_document_level_include_basic(self, tmp_path):
        """Test basic document-level include."""
        # Create base config
        base_file = tmp_path / "base.yaml"
        base_file.write_text(
            """
logging:
  level: INFO
server:
  port: 8080
"""
        )

        # Create main config with document-level include
        main_file = tmp_path / "main.yaml"
        main_file.write_text(
            """!include "./base.yaml"

name: app
"""
        )

        with open(main_file) as f:
            data = load(f, current_file=main_file)

        # Should have content from both files
        assert data["name"] == "app"
        assert data["logging"]["level"] == "INFO"
        assert data["server"]["port"] == 8080

    def test_document_level_include_override(self, tmp_path):
        """Test that main document overrides included content."""
        # Create base config
        base_file = tmp_path / "base.yaml"
        base_file.write_text(
            """
server:
  host: localhost
  port: 8080
"""
        )

        # Create main config that overrides some values
        main_file = tmp_path / "main.yaml"
        main_file.write_text(
            """!include "./base.yaml"

server:
  host: "0.0.0.0"
"""
        )

        with open(main_file) as f:
            data = load(f, current_file=main_file)

        # Main document value should override
        assert data["server"]["host"] == "0.0.0.0"
        # Base value should still be present
        assert data["server"]["port"] == 8080

    def test_document_level_include_multiple(self, tmp_path):
        """Test multiple document-level includes."""
        # Create first base config
        base1_file = tmp_path / "base1.yaml"
        base1_file.write_text(
            """
logging:
  level: INFO
"""
        )

        # Create second base config
        base2_file = tmp_path / "base2.yaml"
        base2_file.write_text(
            """
database:
  host: localhost
"""
        )

        # Create main config with multiple includes
        main_file = tmp_path / "main.yaml"
        main_file.write_text(
            """!include "./base1.yaml"
!include "./base2.yaml"

name: app
"""
        )

        with open(main_file) as f:
            data = load(f, current_file=main_file)

        # Should have content from all files
        assert data["name"] == "app"
        assert data["logging"]["level"] == "INFO"
        assert data["database"]["host"] == "localhost"

    def test_document_level_include_with_section_anchor(self, tmp_path):
        """Test document-level include with section anchor."""
        # Create base config with multiple sections
        base_file = tmp_path / "base.yaml"
        base_file.write_text(
            """
production:
  server:
    host: prod.example.com
    port: 443
development:
  server:
    host: localhost
    port: 8080
"""
        )

        # Create main config that includes only production section
        main_file = tmp_path / "main.yaml"
        main_file.write_text(
            """!include "./base.yaml#production"

name: app
"""
        )

        with open(main_file) as f:
            data = load(f, current_file=main_file)

        # Should only have production content
        assert data["name"] == "app"
        assert data["server"]["host"] == "prod.example.com"
        assert data["server"]["port"] == 443
        # Should NOT have development content
        assert "development" not in data
        assert "production" not in data

    def test_document_level_include_only(self, tmp_path):
        """Test document with only document-level include (no other content)."""
        # Create base config
        base_file = tmp_path / "base.yaml"
        base_file.write_text(
            """
name: base_app
version: "1.0"
"""
        )

        # Create main config with only an include
        main_file = tmp_path / "main.yaml"
        main_file.write_text('!include "./base.yaml"\n')

        with open(main_file) as f:
            data = load(f, current_file=main_file)

        assert data["name"] == "base_app"
        assert data["version"] == "1.0"

    def test_document_level_include_quoted_paths(self, tmp_path):
        """Test document-level include with various quote styles."""
        base_file = tmp_path / "base.yaml"
        base_file.write_text("value: 42\n")

        # Test double quotes
        main_file1 = tmp_path / "main1.yaml"
        main_file1.write_text('!include "./base.yaml"\n')
        with open(main_file1) as f:
            data1 = load(f, current_file=main_file1)
        assert data1["value"] == 42

        # Test single quotes
        main_file2 = tmp_path / "main2.yaml"
        main_file2.write_text("!include './base.yaml'\n")
        with open(main_file2) as f:
            data2 = load(f, current_file=main_file2)
        assert data2["value"] == 42

        # Test unquoted
        main_file3 = tmp_path / "main3.yaml"
        main_file3.write_text("!include ./base.yaml\n")
        with open(main_file3) as f:
            data3 = load(f, current_file=main_file3)
        assert data3["value"] == 42

    def test_document_level_include_with_comment(self, tmp_path):
        """Test document-level include with trailing comment."""
        base_file = tmp_path / "base.yaml"
        base_file.write_text("value: 42\n")

        main_file = tmp_path / "main.yaml"
        main_file.write_text(
            """!include "./base.yaml"  # Load base config

name: app
"""
        )

        with open(main_file) as f:
            data = load(f, current_file=main_file)

        assert data["value"] == 42
        assert data["name"] == "app"

    def test_document_level_include_deep_merge(self, tmp_path):
        """Test deep merge behavior with nested structures."""
        base_file = tmp_path / "base.yaml"
        base_file.write_text(
            """
server:
  http:
    host: localhost
    port: 8080
  https:
    enabled: false
    port: 443
"""
        )

        main_file = tmp_path / "main.yaml"
        main_file.write_text(
            """!include "./base.yaml"

server:
  http:
    port: 9000
  https:
    enabled: true
"""
        )

        with open(main_file) as f:
            data = load(f, current_file=main_file)

        # Deep merge should preserve unmodified nested keys
        assert data["server"]["http"]["host"] == "localhost"  # From base
        assert data["server"]["http"]["port"] == 9000  # Overridden
        assert data["server"]["https"]["enabled"] is True  # Overridden
        assert data["server"]["https"]["port"] == 443  # From base

    def test_document_level_include_circular_detection(self, tmp_path):
        """Test circular include detection with document-level includes."""
        # Create circular reference
        file_a = tmp_path / "a.yaml"
        file_b = tmp_path / "b.yaml"

        file_a.write_text('!include "./b.yaml"\nfrom_a: true\n')
        file_b.write_text('!include "./a.yaml"\nfrom_b: true\n')

        with open(file_a) as f:
            with pytest.raises(yaml.YAMLError, match="Circular include detected"):
                load(f, current_file=file_a)

    def test_document_level_include_security(self, tmp_path):
        """Test that document-level includes respect project_root."""
        # Create project structure
        project_root = tmp_path / "project"
        project_root.mkdir()

        outside_file = tmp_path / "outside.yaml"
        outside_file.write_text("secret: password\n")

        main_file = project_root / "main.yaml"
        main_file.write_text('!include "../outside.yaml"\n')

        with open(main_file) as f:
            with pytest.raises(yaml.YAMLError, match="Security.*outside project root"):
                load(f, current_file=main_file, project_root=project_root)

    def test_document_level_include_source_tracking(self, tmp_path):
        """Test source tracking with document-level includes."""
        base_file = tmp_path / "base.yaml"
        base_file.write_text(
            """
logging:
  level: INFO
"""
        )

        main_file = tmp_path / "main.yaml"
        main_file.write_text(
            """!include "./base.yaml"

name: app
"""
        )

        with open(main_file) as f:
            data, source_map = load(f, current_file=main_file, track_sources=True)

        assert data["name"] == "app"
        assert data["logging"]["level"] == "INFO"

        # Main file entries should point to main_file
        assert source_map.get("name") == main_file

    def test_document_level_include_nonexistent_file(self, tmp_path):
        """Test error handling for non-existent document-level include."""
        main_file = tmp_path / "main.yaml"
        main_file.write_text('!include "./nonexistent.yaml"\n')

        with open(main_file) as f:
            with pytest.raises(yaml.YAMLError, match="Include file not found"):
                load(f, current_file=main_file)

    def test_document_level_include_without_context(self, tmp_path):
        """Test that relative document-level includes fail without file context."""
        yaml_content = '!include "./base.yaml"\n\nname: app\n'

        with pytest.raises(
            yaml.YAMLError, match="Cannot resolve relative include path"
        ):
            load(StringIO(yaml_content))

    def test_document_level_include_preserves_key_level_includes(self, tmp_path):
        """Test that key-level includes still work alongside document-level includes."""
        # Create base config
        base_file = tmp_path / "base.yaml"
        base_file.write_text("shared: base_value\n")

        # Create database config (for key-level include)
        db_file = tmp_path / "db.yaml"
        db_file.write_text(
            """
host: localhost
port: 5432
"""
        )

        # Create main config with both types of includes
        main_file = tmp_path / "main.yaml"
        main_file.write_text(
            """!include "./base.yaml"

name: app
database: !include "./db.yaml"
"""
        )

        with open(main_file) as f:
            data = load(f, current_file=main_file)

        assert data["shared"] == "base_value"  # From document-level include
        assert data["name"] == "app"  # From main document
        assert data["database"]["host"] == "localhost"  # From key-level include
        assert data["database"]["port"] == 5432

    def test_document_level_include_nested_files(self, tmp_path):
        """Test document-level includes in nested files."""
        # Create a chain: main -> mid -> base
        base_file = tmp_path / "base.yaml"
        base_file.write_text("from_base: true\n")

        mid_file = tmp_path / "mid.yaml"
        mid_file.write_text('!include "./base.yaml"\n\nfrom_mid: true\n')

        main_file = tmp_path / "main.yaml"
        main_file.write_text('!include "./mid.yaml"\n\nfrom_main: true\n')

        with open(main_file) as f:
            data = load(f, current_file=main_file)

        assert data["from_base"] is True
        assert data["from_mid"] is True
        assert data["from_main"] is True

    def test_indented_include_not_document_level(self, tmp_path):
        """Test that indented !include is NOT treated as document-level."""
        base_file = tmp_path / "base.yaml"
        base_file.write_text("value: 42\n")

        # This should NOT be treated as document-level because it's indented
        main_file = tmp_path / "main.yaml"
        main_file.write_text(
            """
name: app
  # This is indented, not document level
"""
        )

        with open(main_file) as f:
            data = load(f, current_file=main_file)

        # Should just parse normally without treating indented content specially
        assert data["name"] == "app"


# =============================================================================
# Additional Edge Case Coverage Tests
# =============================================================================


@pytest.mark.unit
class TestIncludePathEdgeCases:
    """Test edge cases for include path resolution."""

    def test_absolute_include_path(self, tmp_path):
        """Test including a file with absolute path."""
        # Create include file
        include_file = tmp_path / "included.yaml"
        include_file.write_text("value: 42\n")

        # Create main file with absolute include path
        main_file = tmp_path / "main.yaml"
        main_file.write_text(f'data: !include "{include_file}"\n')

        with open(main_file) as f:
            data = load(f, current_file=main_file)

        assert data["data"]["value"] == 42

    def test_include_depth_exceeded(self, tmp_path):
        """Test error when include depth exceeds maximum."""
        # Create a chain of includes that exceeds depth limit (default is 10)
        # We need 11 files to exceed depth of 10
        for i in range(11):
            if i == 0:
                (tmp_path / f"level{i}.yaml").write_text("value: bottom\n")
            else:
                (tmp_path / f"level{i}.yaml").write_text(
                    f'nested: !include "./level{i - 1}.yaml"\n'
                )

        main_file = tmp_path / "main.yaml"
        main_file.write_text('root: !include "./level10.yaml"\n')

        with open(main_file) as f:
            with pytest.raises(yaml.YAMLError, match="Include depth exceeds maximum"):
                load(f, current_file=main_file)

    def test_include_depth_exceeded_with_custom_limit(self, tmp_path):
        """Test error when include depth exceeds custom maximum."""
        # Create chain of 4 includes
        for i in range(4):
            if i == 0:
                (tmp_path / f"level{i}.yaml").write_text("value: bottom\n")
            else:
                (tmp_path / f"level{i}.yaml").write_text(
                    f'nested: !include "./level{i - 1}.yaml"\n'
                )

        main_file = tmp_path / "main.yaml"
        main_file.write_text('root: !include "./level3.yaml"\n')

        # With max_include_depth=3, this should fail
        with open(main_file) as f:
            with pytest.raises(yaml.YAMLError, match="Include depth exceeds maximum"):
                load(f, current_file=main_file, max_include_depth=3)

    def test_document_level_include_depth_exceeded(self, tmp_path):
        """Test error when document-level include depth exceeds maximum."""
        # Create chain of document-level includes
        for i in range(4):
            if i == 0:
                (tmp_path / f"doc{i}.yaml").write_text("value: bottom\n")
            else:
                # Document-level include (at start of line)
                (tmp_path / f"doc{i}.yaml").write_text(
                    f'!include "./doc{i - 1}.yaml"\n\nlevel: {i}\n'
                )

        main_file = tmp_path / "main.yaml"
        main_file.write_text('!include "./doc3.yaml"\n\nname: app\n')

        # With max_include_depth=2, this should fail
        with open(main_file) as f:
            with pytest.raises(yaml.YAMLError, match="Include depth exceeds maximum"):
                load(f, current_file=main_file, max_include_depth=2)


@pytest.mark.unit
class TestIncludeSecurityEdgeCases:
    """Test security-related edge cases for includes."""

    def test_include_outside_project_root(self, tmp_path):
        """Test error when include path is outside project root."""
        # Create project directory
        project = tmp_path / "project"
        project.mkdir()

        # Create file outside project
        outside_file = tmp_path / "outside.yaml"
        outside_file.write_text("secret: exposed\n")

        # Create main file trying to include outside file
        main_file = project / "main.yaml"
        main_file.write_text('data: !include "../outside.yaml"\n')

        with open(main_file) as f:
            with pytest.raises(yaml.YAMLError, match="outside project root"):
                load(f, current_file=main_file, project_root=project)


@pytest.mark.unit
class TestIncludeSectionEdgeCases:
    """Test edge cases for include with section paths."""

    def test_section_path_on_non_dict(self, tmp_path):
        """Test error when navigating section path through non-dict."""
        include_file = tmp_path / "included.yaml"
        include_file.write_text(
            """
root:
  items:
    - item1
    - item2
"""
        )

        main_file = tmp_path / "main.yaml"
        # Try to navigate through the list (items.first doesn't work on list)
        main_file.write_text('data: !include "./included.yaml#root.items.first"\n')

        with open(main_file) as f:
            with pytest.raises(yaml.YAMLError, match="is not a mapping"):
                load(f, current_file=main_file)

    def test_section_path_not_found(self, tmp_path):
        """Test error when section path key not found."""
        include_file = tmp_path / "included.yaml"
        include_file.write_text(
            """
config:
  database:
    host: localhost
"""
        )

        main_file = tmp_path / "main.yaml"
        main_file.write_text('data: !include "./included.yaml#config.nonexistent"\n')

        with open(main_file) as f:
            with pytest.raises(yaml.YAMLError, match="not found"):
                load(f, current_file=main_file)

    def test_section_with_source_tracking(self, tmp_path):
        """Test section extraction with source tracking enabled."""
        include_file = tmp_path / "included.yaml"
        include_file.write_text(
            """
outer:
  inner:
    value: 42
    nested:
      deep: true
"""
        )

        main_file = tmp_path / "main.yaml"
        main_file.write_text('data: !include "./included.yaml#outer.inner"\n')

        with open(main_file) as f:
            data, source_map = load(f, current_file=main_file, track_sources=True)

        assert data["data"]["value"] == 42
        # Source map should have entries for the included data
        assert source_map is not None


@pytest.mark.unit
class TestSourceTrackingEdgeCases:
    """Test source tracking edge cases."""

    def test_source_tracking_with_sequences(self, tmp_path):
        """Test source tracking properly tracks sequence items."""
        main_file = tmp_path / "main.yaml"
        main_file.write_text(
            """
items:
  - first
  - second
  - third
"""
        )

        with open(main_file) as f:
            data, source_map = load(f, current_file=main_file, track_sources=True)

        assert data["items"] == ["first", "second", "third"]
        # Source map should track sequence items with indexed paths
        assert "items[0]" in source_map or "items" in source_map


@pytest.mark.unit
class TestDocumentMergeEdgeCases:
    """Test edge cases for document-level merge behavior."""

    def test_non_dict_main_takes_precedence(self, tmp_path):
        """Test that non-dict main data takes precedence over merged dict."""
        base_file = tmp_path / "base.yaml"
        base_file.write_text(
            """
config:
  key: value
"""
        )

        # Main file with non-dict content (a list)
        main_file = tmp_path / "main.yaml"
        main_file.write_text(
            """!include "./base.yaml"

- item1
- item2
"""
        )

        with open(main_file) as f:
            data = load(f, current_file=main_file)

        # The list should take precedence
        assert isinstance(data, list)
        assert data == ["item1", "item2"]


@pytest.mark.unit
class TestDocumentLevelIncludeWithSection:
    """Test document-level includes with section paths."""

    def test_document_include_section_on_non_dict(self, tmp_path):
        """Test error when document-level section path traverses non-dict."""
        include_file = tmp_path / "included.yaml"
        include_file.write_text(
            """
data:
  items:
    - one
    - two
"""
        )

        # Document-level include with section that traverses a list
        main_file = tmp_path / "main.yaml"
        main_file.write_text('!include "./included.yaml#data.items.key"\n\nname: app\n')

        with open(main_file) as f:
            with pytest.raises(yaml.YAMLError, match="is not a mapping"):
                load(f, current_file=main_file)

    def test_document_include_section_not_found(self, tmp_path):
        """Test error when document-level section path key not found."""
        include_file = tmp_path / "included.yaml"
        include_file.write_text(
            """
config:
  database:
    host: localhost
"""
        )

        # Document-level include with non-existent section
        main_file = tmp_path / "main.yaml"
        main_file.write_text('!include "./included.yaml#config.missing"\n\nname: app\n')

        with open(main_file) as f:
            with pytest.raises(yaml.YAMLError, match="not found"):
                load(f, current_file=main_file)

    def test_document_include_section_with_source_tracking(self, tmp_path):
        """Test document-level section include with source tracking."""
        include_file = tmp_path / "included.yaml"
        include_file.write_text(
            """
outer:
  inner:
    value: 42
    nested:
      deep: true
"""
        )

        # Document-level include with section and source tracking
        main_file = tmp_path / "main.yaml"
        main_file.write_text('!include "./included.yaml#outer.inner"\n\nname: app\n')

        with open(main_file) as f:
            data, source_map = load(f, current_file=main_file, track_sources=True)

        assert data["value"] == 42
        assert data["name"] == "app"
        assert source_map is not None


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


@pytest.mark.unit
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
# Deep Include Override Tests (!deep !include)
# =============================================================================


@pytest.mark.unit
class TestDeepIncludeOverride:
    """Test !deep !include for overlay pattern where include wins over document."""

    def test_deep_include_override_basic(self, tmp_path):
        """Test !deep !include? makes included values win over document values."""
        overlay_file = tmp_path / "overlay.yaml"
        overlay_file.write_text("""
config:
  key1: overlay_value
  nested:
    b: 20
    c: 3
""")
        main_content = f"""
config:
  key1: base_value
  key2: base_value
  nested:
    a: 1
    b: 2

<<: !deep !include? "{overlay_file}"
"""
        result = load(StringIO(main_content), current_file=tmp_path / "main.yaml")

        # overlay wins for key1
        assert result["config"]["key1"] == "overlay_value"
        # document-only key preserved
        assert result["config"]["key2"] == "base_value"
        # nested: overlay wins for b, document provides a, overlay adds c
        assert result["config"]["nested"]["a"] == 1
        assert result["config"]["nested"]["b"] == 20
        assert result["config"]["nested"]["c"] == 3

    def test_deep_include_override_missing_file(self, tmp_path):
        """Test !deep !include? returns empty for missing file."""
        main_content = """
config:
  key1: base_value

<<: !deep !include? "nonexistent.yaml"
"""
        result = load(StringIO(main_content), current_file=tmp_path / "main.yaml")
        # Document value preserved when include is missing
        assert result["config"]["key1"] == "base_value"

    def test_deep_include_required(self, tmp_path):
        """Test !deep !include (required) raises for missing file."""
        main_content = """
config:
  key1: base_value

<<: !deep !include "nonexistent.yaml"
"""
        with pytest.raises(yaml.YAMLError, match="Include file not found"):
            load(StringIO(main_content), current_file=tmp_path / "main.yaml")

    def test_deep_include_with_section(self, tmp_path):
        """Test !deep !include with section selector."""
        overlay_file = tmp_path / "overlay.yaml"
        overlay_file.write_text("""
overrides:
  config:
    key1: override_value
    nested:
      x: 10
""")
        main_content = f"""
config:
  key1: base_value
  nested:
    y: 20

<<: !deep !include "{overlay_file}#overrides"
"""
        result = load(StringIO(main_content), current_file=tmp_path / "main.yaml")

        # Override wins
        assert result["config"]["key1"] == "override_value"
        assert result["config"]["nested"]["x"] == 10
        assert result["config"]["nested"]["y"] == 20

    def test_deep_include_preserves_anchor_behavior(self, tmp_path):
        """Test that regular !deep *anchor still has document-wins semantics."""
        content = """
defaults: &defaults
  timeout: 30
  options:
    retries: 3

config:
  <<: !deep *defaults
  timeout: 60
  options:
    cache: true
"""
        result = load(StringIO(content))

        # Document wins for anchors (timeout overridden to 60)
        assert result["config"]["timeout"] == 60
        # Deep merge preserves anchor values, adds document values
        assert result["config"]["options"]["retries"] == 3
        assert result["config"]["options"]["cache"] is True

    def test_preprocessing_transforms_syntax(self):
        """Test that !deep !include is correctly preprocessed."""
        from appinfra.yaml.loader import preprocess_deep_tags

        content = '<<: !deep !include? "./overlay.yaml"'
        result = preprocess_deep_tags(content)
        assert result == '<<: !deep-include? "./overlay.yaml"'

        content2 = "<<: !deep !include './base.yaml'"
        result2 = preprocess_deep_tags(content2)
        assert result2 == "<<: !deep-include './base.yaml'"


# =============================================================================
# Reset Tag Tests
# =============================================================================


@pytest.mark.unit
class TestResetTag:
    """Tests for !reset tag that bypasses deep merge."""

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


@pytest.mark.unit
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
# Section Include Variable Resolution Tests
# =============================================================================


@pytest.mark.unit
class TestSectionIncludeVariableResolution:
    """Test variable interpolation in section includes.

    When using `!include './file.yaml#section'`, variables like `${sibling.key}`
    that reference other sections in the same source file should resolve before
    section extraction.
    """

    def test_core_case_sibling_variable_resolves(self, tmp_path):
        """Test ${sibling.key} resolves before section extraction."""
        # This is the main use case from the ticket
        pg_file = tmp_path / "pg.yaml"
        pg_file.write_text(
            """
pgserver:
  port: 7632
  user: postgres
dbs:
  main:
    url: "postgresql://${pgserver.user}:@127.0.0.1:${pgserver.port}/learn"
"""
        )

        app_file = tmp_path / "app.yaml"
        app_file.write_text(
            """
learn:
  db: !include './pg.yaml#dbs.main'
"""
        )

        with open(app_file) as f:
            data = load(f, current_file=app_file)

        # The URL should have the variables resolved
        assert (
            data["learn"]["db"]["url"] == "postgresql://postgres:@127.0.0.1:7632/learn"
        )

    def test_undefined_vars_pass_through(self, tmp_path):
        """Test undefined variables are passed through for Config._resolve() to handle."""
        include_file = tmp_path / "config.yaml"
        include_file.write_text(
            """
shared:
  base_url: "http://localhost"
section:
  url: "${shared.base_url}/api"
  token: "${ENV_TOKEN}"
"""
        )

        main_file = tmp_path / "main.yaml"
        main_file.write_text(
            """
data: !include './config.yaml#section'
"""
        )

        with open(main_file) as f:
            data = load(f, current_file=main_file)

        # Sibling reference should be resolved
        assert data["data"]["url"] == "http://localhost/api"
        # Undefined variable should be passed through
        assert data["data"]["token"] == "${ENV_TOKEN}"

    def test_nested_dict_variables_resolve(self, tmp_path):
        """Test variables in deeply nested structures resolve."""
        include_file = tmp_path / "config.yaml"
        include_file.write_text(
            """
defaults:
  timeout: 30
  retries: 3
services:
  api:
    connection:
      timeout: ${defaults.timeout}
      retries: ${defaults.retries}
      host: localhost
"""
        )

        main_file = tmp_path / "main.yaml"
        main_file.write_text(
            """
api: !include './config.yaml#services.api'
"""
        )

        with open(main_file) as f:
            data = load(f, current_file=main_file)

        assert data["api"]["connection"]["timeout"] == "30"
        assert data["api"]["connection"]["retries"] == "3"
        assert data["api"]["connection"]["host"] == "localhost"

    def test_list_variables_resolve(self, tmp_path):
        """Test variables in lists within sections resolve."""
        include_file = tmp_path / "config.yaml"
        include_file.write_text(
            """
hosts:
  primary: db-primary.local
  replica: db-replica.local
databases:
  cluster:
    nodes:
      - host: ${hosts.primary}
        role: primary
      - host: ${hosts.replica}
        role: replica
"""
        )

        main_file = tmp_path / "main.yaml"
        main_file.write_text(
            """
cluster: !include './config.yaml#databases.cluster'
"""
        )

        with open(main_file) as f:
            data = load(f, current_file=main_file)

        assert data["cluster"]["nodes"][0]["host"] == "db-primary.local"
        assert data["cluster"]["nodes"][0]["role"] == "primary"
        assert data["cluster"]["nodes"][1]["host"] == "db-replica.local"
        assert data["cluster"]["nodes"][1]["role"] == "replica"

    def test_document_level_section_include_resolves_vars(self, tmp_path):
        """Test document-level `!include './file.yaml#section'` resolves variables."""
        include_file = tmp_path / "base.yaml"
        include_file.write_text(
            """
common:
  version: "2.0"
production:
  app_version: "${common.version}"
  debug: false
"""
        )

        main_file = tmp_path / "main.yaml"
        main_file.write_text(
            """!include './base.yaml#production'

name: myapp
"""
        )

        with open(main_file) as f:
            data = load(f, current_file=main_file)

        assert data["app_version"] == "2.0"
        assert data["debug"] is False
        assert data["name"] == "myapp"

    def test_full_file_include_no_pre_resolution(self, tmp_path):
        """Test full file includes (no #section) don't pre-resolve variables.

        Full file includes should preserve ${} patterns for Config._resolve() to handle
        since the full context is available at that stage.
        """
        include_file = tmp_path / "config.yaml"
        include_file.write_text(
            """
shared:
  base_url: "http://localhost"
api:
  url: "${shared.base_url}/api"
"""
        )

        main_file = tmp_path / "main.yaml"
        main_file.write_text(
            """
config: !include './config.yaml'
"""
        )

        with open(main_file) as f:
            data = load(f, current_file=main_file)

        # For full file includes, the variable should remain unresolved
        # (Config._resolve() handles it later with full context)
        assert data["config"]["api"]["url"] == "${shared.base_url}/api"

    def test_circular_ref_single_pass_prevents_loop(self, tmp_path):
        """Test circular references don't cause infinite loops (single-pass resolution)."""
        include_file = tmp_path / "config.yaml"
        include_file.write_text(
            """
a:
  value: "${b.value}"
b:
  value: "${a.value}"
section:
  result: "${a.value}"
"""
        )

        main_file = tmp_path / "main.yaml"
        main_file.write_text(
            """
data: !include './config.yaml#section'
"""
        )

        with open(main_file) as f:
            data = load(f, current_file=main_file)

        # Single-pass resolution means ${a.value} resolves to "${b.value}" (a string)
        # This is expected behavior - no infinite loop
        assert data["data"]["result"] == "${b.value}"

    def test_self_ref_stays_unresolved(self, tmp_path):
        """Test self-referencing variable stays unresolved."""
        include_file = tmp_path / "config.yaml"
        include_file.write_text(
            """
section:
  host: "${section.host}"
  port: 8080
"""
        )

        main_file = tmp_path / "main.yaml"
        main_file.write_text(
            """
data: !include './config.yaml#section'
"""
        )

        with open(main_file) as f:
            data = load(f, current_file=main_file)

        # Self-reference can't be resolved (would need the value to compute itself)
        # Single-pass resolution means it stays as-is
        assert data["data"]["host"] == "${section.host}"
        assert data["data"]["port"] == 8080

    def test_multiple_vars_in_string(self, tmp_path):
        """Test multiple variables in a single string all resolve."""
        include_file = tmp_path / "config.yaml"
        include_file.write_text(
            """
server:
  protocol: https
  host: api.example.com
  port: 443
urls:
  main:
    base: "${server.protocol}://${server.host}:${server.port}"
"""
        )

        main_file = tmp_path / "main.yaml"
        main_file.write_text(
            """
urls: !include './config.yaml#urls.main'
"""
        )

        with open(main_file) as f:
            data = load(f, current_file=main_file)

        assert data["urls"]["base"] == "https://api.example.com:443"

    def test_non_string_values_preserved(self, tmp_path):
        """Test non-string values (int, bool, None) are preserved as-is."""
        include_file = tmp_path / "config.yaml"
        include_file.write_text(
            """
defaults:
  enabled: true
  count: 42
  nullable: null
section:
  enabled: ${defaults.enabled}
  count: ${defaults.count}
  nullable: ${defaults.nullable}
  raw_bool: true
  raw_int: 100
"""
        )

        main_file = tmp_path / "main.yaml"
        main_file.write_text(
            """
data: !include './config.yaml#section'
"""
        )

        with open(main_file) as f:
            data = load(f, current_file=main_file)

        # Variables are resolved to string representations
        assert data["data"]["enabled"] == "True"
        assert data["data"]["count"] == "42"
        assert data["data"]["nullable"] == "None"
        # Direct values remain their original types
        assert data["data"]["raw_bool"] is True
        assert data["data"]["raw_int"] == 100

    def test_deeply_nested_section_path(self, tmp_path):
        """Test variables resolve when extracting deeply nested sections."""
        include_file = tmp_path / "config.yaml"
        include_file.write_text(
            """
root:
  value: "root_value"
level1:
  level2:
    level3:
      data: "${root.value}"
"""
        )

        main_file = tmp_path / "main.yaml"
        main_file.write_text(
            """
extracted: !include './config.yaml#level1.level2.level3'
"""
        )

        with open(main_file) as f:
            data = load(f, current_file=main_file)

        assert data["extracted"]["data"] == "root_value"
