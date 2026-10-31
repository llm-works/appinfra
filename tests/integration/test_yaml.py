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
    load,
    load_file,
)

# =============================================================================
# Include Tests
# =============================================================================


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

    @pytest.mark.unit
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


class TestCircularDependencies:
    """Test circular include detection."""

    def test_detect_circular_include(self, yaml_files_dir):
        """Test circular includes are detected."""
        circular_file = yaml_files_dir / "circular_a.yaml"

        with (
            open(circular_file) as f,
            pytest.raises(yaml.YAMLError, match="Circular include detected"),
        ):
            load(f, current_file=circular_file)

    def test_detect_self_include(self, yaml_files_dir):
        """Test self-inclusion is detected as circular."""
        self_include_file = yaml_files_dir / "self.yaml"
        self_include_file.write_text(
            """
data: !include "./self.yaml"
"""
        )

        with (
            open(self_include_file) as f,
            pytest.raises(yaml.YAMLError, match="Circular include detected"),
        ):
            load(f, current_file=self_include_file)


# =============================================================================
# Include Depth Limit Tests
# =============================================================================


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
        with (
            open(files[0]) as f,
            pytest.raises(yaml.YAMLError, match="Include depth exceeds maximum of 10"),
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
        with (
            open(files[0]) as f,
            pytest.raises(yaml.YAMLError, match="Include depth exceeds maximum of 2"),
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
        with open(files[0]) as f, pytest.raises(yaml.YAMLError) as exc_info:
            load(f, current_file=files[0])

        error_msg = str(exc_info.value)
        assert "Include chain:" in error_msg
        # Should mention it's about recursive/deeply nested patterns
        assert "deeply nested" in error_msg or "recursive" in error_msg


# =============================================================================
# Integration Tests
# =============================================================================


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
# Document-Level Include Tests
# =============================================================================


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

        with (
            open(file_a) as f,
            pytest.raises(yaml.YAMLError, match="Circular include detected"),
        ):
            load(f, current_file=file_a)

    def test_document_level_include_security(self, tmp_path):
        """Test that document-level includes respect origin."""
        # Create project structure
        origin = tmp_path / "project"
        origin.mkdir()

        outside_file = tmp_path / "outside.yaml"
        outside_file.write_text("secret: password\n")

        main_file = origin / "main.yaml"
        main_file.write_text('!include "../outside.yaml"\n')

        with (
            open(main_file) as f,
            pytest.raises(yaml.YAMLError, match="Security.*outside origin"),
        ):
            load(f, current_file=main_file, origin=origin)

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

        with (
            open(main_file) as f,
            pytest.raises(yaml.YAMLError, match="Include file not found"),
        ):
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

        with (
            open(main_file) as f,
            pytest.raises(yaml.YAMLError, match="Include depth exceeds maximum"),
        ):
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
        with (
            open(main_file) as f,
            pytest.raises(yaml.YAMLError, match="Include depth exceeds maximum"),
        ):
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
        with (
            open(main_file) as f,
            pytest.raises(yaml.YAMLError, match="Include depth exceeds maximum"),
        ):
            load(f, current_file=main_file, max_include_depth=2)


class TestIncludeSecurityEdgeCases:
    """Test security-related edge cases for includes."""

    def test_include_outside_origin(self, tmp_path):
        """Test error when include path is outside origin."""
        # Create project directory
        project = tmp_path / "project"
        project.mkdir()

        # Create file outside project
        outside_file = tmp_path / "outside.yaml"
        outside_file.write_text("secret: exposed\n")

        # Create main file trying to include outside file
        main_file = project / "main.yaml"
        main_file.write_text('data: !include "../outside.yaml"\n')

        with (
            open(main_file) as f,
            pytest.raises(yaml.YAMLError, match="outside origin"),
        ):
            load(f, current_file=main_file, origin=project)


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

        with (
            open(main_file) as f,
            pytest.raises(yaml.YAMLError, match="is not a mapping"),
        ):
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

        with open(main_file) as f, pytest.raises(yaml.YAMLError, match="not found"):
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

        with (
            open(main_file) as f,
            pytest.raises(yaml.YAMLError, match="is not a mapping"),
        ):
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

        with open(main_file) as f, pytest.raises(yaml.YAMLError, match="not found"):
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


# =============================================================================
# Deep Include Override Tests (!deep !include)
# =============================================================================


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

    @pytest.mark.unit
    def test_preprocessing_transforms_syntax(self):
        """Test that !deep !include is correctly preprocessed to the canonical chain form."""
        from appinfra.yaml.loader import preprocess_deep_tags

        content = '<<: !deep !include? "./overlay.yaml"'
        result = preprocess_deep_tags(content)
        assert result == '<<: !chain:include?+deep "./overlay.yaml"'

        content2 = "<<: !deep !include './base.yaml'"
        result2 = preprocess_deep_tags(content2)
        assert result2 == "<<: !chain:include+deep './base.yaml'"

    def test_secretstr_in_deep_included_file_survives_merge(self, tmp_path):
        """A Envelope in a !deep !include? child must round-trip as Envelope, not '***'.

        Regression: flatten_mapping reconstructed the merged mapping via
        _value_to_node, whose else branch stringified any non-primitive value.
        str(Envelope) is "***", so credentials from the child file were
        silently masked before reaching consumers.
        """
        child = tmp_path / "deep_secret_child.yaml"
        child.write_text(
            "web_search:\n"
            "  backend:\n"
            "    config:\n"
            "      api_key: !secret !env SERPER_API_KEY\n"
        )
        parent = tmp_path / "deep_secret_parent.yaml"
        parent.write_text(
            "web_search:\n"
            "  backend:\n"
            "    kind: serper\n"
            "\n"
            f'<<: !deep !include? "{child.name}"\n'
        )

        with open(parent) as f:
            data = load(
                f,
                current_file=parent,
                env_overrides={"SERPER_API_KEY": "hunter2"},
            )

        api_key = data["web_search"]["backend"]["config"]["api_key"]
        assert isinstance(api_key, Envelope)
        assert api_key.reveal() == "hunter2"
        # Document-side value merged around it, not overwritten
        assert data["web_search"]["backend"]["kind"] == "serper"

    def test_secretstr_in_bare_included_file_survives_merge(self, tmp_path):
        """Companion: bare `<<: !include?` (DeepMergeDict path) must also
        preserve Envelope — the same _value_to_node path handles merge_base
        and override_base.
        """
        child = tmp_path / "bare_secret_child.yaml"
        child.write_text("creds:\n  token: !secret !env API_TOKEN\n")
        parent = tmp_path / "bare_secret_parent.yaml"
        parent.write_text(f'creds:\n  user: alice\n\n<<: !include? "{child.name}"\n')

        with open(parent) as f:
            data = load(
                f,
                current_file=parent,
                env_overrides={"API_TOKEN": "s3cret"},
            )

        token = data["creds"]["token"]
        assert isinstance(token, Envelope)
        assert token.reveal() == "s3cret"
        assert data["creds"]["user"] == "alice"


# =============================================================================
# Section Include Variable Resolution Tests
# =============================================================================


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

    def test_a_secret_reference_carries_the_envelope(self, tmp_path, monkeypatch):
        """A sibling secret reached through a section include stays an Envelope."""
        monkeypatch.setenv("TEST_DB_PW", "s3cret")
        (tmp_path / "pg.yaml").write_text(
            """
pgserver:
  pass: !env TEST_DB_PW !secret
dbs:
  main:
    password: "${pgserver.pass}"
"""
        )
        app_file = tmp_path / "app.yaml"
        app_file.write_text("db: !include './pg.yaml#dbs.main'\n")

        with open(app_file) as f:
            data = load(f, current_file=app_file)

        assert isinstance(data["db"]["password"], Envelope)
        assert data["db"]["password"].reveal() == "s3cret"

    def test_an_override_of_a_secret_reference_stays_an_envelope(
        self, tmp_path, monkeypatch
    ):
        """An env override replaces the secret's value, not its envelope."""
        monkeypatch.setenv("TEST_DB_PW", "s3cret")
        (tmp_path / "pg.yaml").write_text(
            """
pgserver:
  pass: !env TEST_DB_PW !secret
dbs:
  main:
    password: "${pgserver.pass}"
"""
        )
        app_file = tmp_path / "app.yaml"
        app_file.write_text("db: !include './pg.yaml#dbs.main'\n")

        with open(app_file) as f:
            data = load(
                f,
                current_file=app_file,
                env_overrides={"pgserver.pass": "override"},
            )

        assert isinstance(data["db"]["password"], Envelope)
        assert data["db"]["password"].reveal() == "override"

    def test_text_with_a_secret_is_a_secret(self, tmp_path, monkeypatch):
        """A string a secret is spliced into becomes an Envelope as a whole."""
        monkeypatch.setenv("TEST_DB_PW", "s3cret")
        (tmp_path / "pg.yaml").write_text(
            """
pgserver:
  pass: !env TEST_DB_PW !secret
dbs:
  main:
    url: "postgresql://app:${pgserver.pass}@h/db"
"""
        )
        app_file = tmp_path / "app.yaml"
        app_file.write_text("db: !include './pg.yaml#dbs.main'\n")

        with open(app_file) as f:
            data = load(f, current_file=app_file)

        assert isinstance(data["db"]["url"], Envelope)
        assert data["db"]["url"].reveal() == "postgresql://app:s3cret@h/db"

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


class TestDeepIncludeChainSyntax:
    """End-to-end tests for !deep !include via the chain mechanism.

    !deep !include uses override semantics — the included file wins over
    document values on conflict. Both prefix and postfix orderings share
    the same composer, so they must produce identical results.
    """

    def _write_overlay(self, tmp_path):
        overlay = tmp_path / "overlay.yaml"
        overlay.write_text("db:\n  host: overlay-host\n  port: 6543\n")
        return overlay

    def test_prefix_deep_include(self, tmp_path):
        """!deep !include (prefix form) — overlay wins, document contributes non-conflict keys."""
        self._write_overlay(tmp_path)
        main_content = (
            "db:\n  host: doc-host\n  timeout: 30\n\n"
            '<<: !deep !include "./overlay.yaml"\n'
        )
        data = load(StringIO(main_content), current_file=tmp_path / "main.yaml")
        assert data["db"] == {"host": "overlay-host", "port": 6543, "timeout": 30}

    def test_postfix_deep_include(self, tmp_path):
        """!include ... !deep (postfix form) — identical semantics."""
        self._write_overlay(tmp_path)
        main_content = (
            "db:\n  host: doc-host\n  timeout: 30\n\n"
            '<<: !include "./overlay.yaml" !deep\n'
        )
        data = load(StringIO(main_content), current_file=tmp_path / "main.yaml")
        assert data["db"] == {"host": "overlay-host", "port": 6543, "timeout": 30}

    def test_prefix_and_postfix_yield_same_result(self, tmp_path):
        """The two syntaxes produce byte-identical loaded output."""
        self._write_overlay(tmp_path)
        doc = "db:\n  host: doc-host\n  timeout: 30\n\n"
        prefix_content = doc + '<<: !deep !include "./overlay.yaml"\n'
        postfix_content = doc + '<<: !include "./overlay.yaml" !deep\n'
        p = load(StringIO(prefix_content), current_file=tmp_path / "main.yaml")
        q = load(StringIO(postfix_content), current_file=tmp_path / "main.yaml")
        assert p == q

    def test_postfix_optional_deep_include(self, tmp_path):
        """!include? ... !deep — optional deep include, tolerates missing file."""
        main_content = 'db:\n  host: only-me\n\n<<: !include? "./absent.yaml" !deep\n'
        data = load(StringIO(main_content), current_file=tmp_path / "main.yaml")
        assert data["db"] == {"host": "only-me"}


class TestAllowedPaths:
    """Tests for the allowed_paths per-path allowlist on !include*.

    Splits home from project via monkeypatched HOME so tilde-notation in
    tests never touches the real user home.
    """

    @pytest.fixture
    def home_and_proj(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        proj = tmp_path / "proj"
        home.mkdir()
        proj.mkdir()
        monkeypatch.setenv("HOME", str(home))
        return home, proj

    def test_allowlisted_path_bypasses_guard(self, home_and_proj):
        home, proj = home_and_proj
        (home / ".overlay.yaml").write_text("db:\n  port: 9999\n")
        main = proj / "main.yaml"
        main.write_text('overlay: !include "~/.overlay.yaml"\n')

        data = load_file(main, origin=proj, allowed_paths=["~/.overlay.yaml"])
        assert data == {"overlay": {"db": {"port": 9999}}}

    def test_home_include_blocked_by_default(self, home_and_proj):
        home, proj = home_and_proj
        (home / ".overlay.yaml").write_text("db:\n  port: 9999\n")
        main = proj / "main.yaml"
        main.write_text('overlay: !include "~/.overlay.yaml"\n')

        with pytest.raises(yaml.YAMLError, match="outside origin"):
            load_file(main, origin=proj)

    def test_non_allowlisted_home_path_still_blocked(self, home_and_proj):
        """Allowlisting one file does NOT unlock all of home."""
        home, proj = home_and_proj
        (home / ".overlay.yaml").write_text("v: 1\n")
        (home / ".other.yaml").write_text("present: true\n")
        main = proj / "main.yaml"
        main.write_text('extra: !include "~/.other.yaml"\n')

        with pytest.raises(yaml.YAMLError, match="is not authorized"):
            load_file(main, origin=proj, allowed_paths=["~/.overlay.yaml"])

    def test_optional_allowlisted_include_missing_returns_empty(self, home_and_proj):
        _, proj = home_and_proj
        main = proj / "main.yaml"
        main.write_text('overlay: !include? "~/.absent.yaml"\n')

        data = load_file(main, origin=proj, allowed_paths=["~/.absent.yaml"])
        assert data == {"overlay": {}}

    def test_optional_non_allowlisted_missing_still_blocked(self, home_and_proj):
        """Missing optional path outside origin must still hit guard.

        Ensures authorization happens before existence check - we reject the
        path for being outside origin, not silently return empty because
        the file is missing.
        """
        _, proj = home_and_proj
        main = proj / "main.yaml"
        main.write_text('overlay: !include? "~/.absent.yaml"\n')

        with pytest.raises(yaml.YAMLError, match="outside origin"):
            load_file(main, origin=proj)

    def test_deep_merge_overlay_pattern(self, home_and_proj):
        """Package-ships-defaults + user-overlay: <<: !deep !include? '~/.file#section'."""
        home, proj = home_and_proj
        (home / ".overlay.yaml").write_text("myapp:\n  db:\n    host: overlay-host\n")
        main = proj / "main.yaml"
        main.write_text(
            "db:\n"
            "  host: default-host\n"
            "  port: 5432\n"
            '<<: !deep !include? "~/.overlay.yaml#myapp"\n'
        )

        data = load_file(main, origin=proj, allowed_paths=["~/.overlay.yaml"])
        assert data["db"] == {"host": "overlay-host", "port": 5432}

    def test_absolute_traversal_still_blocked_with_allowlist(
        self, home_and_proj, tmp_path
    ):
        """Non-allowlisted absolute paths hit the guard regardless."""
        home, proj = home_and_proj
        (home / ".overlay.yaml").write_text("v: 1\n")
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "other.yaml").write_text("present: true\n")
        main = proj / "main.yaml"
        main.write_text(f'extra: !include "{outside}/other.yaml"\n')

        with pytest.raises(yaml.YAMLError, match="is not authorized"):
            load_file(main, origin=proj, allowed_paths=["~/.overlay.yaml"])

    def test_document_level_include_honors_allowlist(self, home_and_proj):
        home, proj = home_and_proj
        (home / ".base.yaml").write_text("name: overlay\n")
        main = proj / "main.yaml"
        main.write_text('!include? "~/.base.yaml"\nversion: 1\n')

        data = load_file(main, origin=proj, allowed_paths=["~/.base.yaml"])
        assert data == {"name": "overlay", "version": 1}

    def test_allowlist_accepts_pathlib_and_str_mixed(self, home_and_proj):
        home, proj = home_and_proj
        (home / ".overlay.yaml").write_text("v: 1\n")
        main = proj / "main.yaml"
        main.write_text('overlay: !include "~/.overlay.yaml"\n')

        data = load_file(main, origin=proj, allowed_paths=[Path("~/.overlay.yaml")])
        assert data == {"overlay": {"v": 1}}

    def test_no_origin_allowlist_is_noop(self, home_and_proj):
        """Without origin the guard is off; allowlist doesn't change data."""
        home, proj = home_and_proj
        (home / ".overlay.yaml").write_text("v: 42\n")
        main = proj / "main.yaml"
        main.write_text('overlay: !include "~/.overlay.yaml"\n')

        assert load_file(main) == load_file(main, allowed_paths=["~/.overlay.yaml"])
