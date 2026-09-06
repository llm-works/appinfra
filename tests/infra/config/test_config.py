# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Comprehensive tests for the configuration management module.

Tests the Config class functionality including:
- YAML loading and parsing
- Variable substitution (${var} syntax)
- Environment variable overrides
- Relative path resolution
- File size validation
- Type conversion
- Nested value access
"""

import os
from pathlib import Path
from unittest.mock import Mock

import pytest

from appinfra.config import MAX_CONFIG_SIZE_BYTES, Config, ConfigFile, ConfigSpec
from appinfra.config.config import (
    _check_file_size,
    _preserve_config_attributes,
    _restore_config_attributes,
)
from appinfra.errors import UndeclaredConfigPathError

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def temp_yaml_file(tmp_path):
    """Create a temporary YAML config file."""
    config_file = tmp_path / "config.yaml"
    content = """
app:
  name: test_app
  version: 1.0.0
  debug: false

database:
  host: localhost
  port: 5432
  name: testdb

logging:
  level: info
  format: json
"""
    config_file.write_text(content)
    return str(config_file)


@pytest.fixture
def temp_yaml_with_substitution(tmp_path):
    """Create a YAML file with variable substitution."""
    config_file = tmp_path / "config.yaml"
    content = """
database:
  host: localhost
  port: 5432
  name: testdb
  url: postgresql://${database.host}:${database.port}/${database.name}

api:
  endpoint: http://${database.host}/api
"""
    config_file.write_text(content)
    return str(config_file)


@pytest.fixture
def temp_yaml_with_paths(tmp_path):
    """Create a YAML file with paths using !path tag."""
    config_file = tmp_path / "config.yaml"
    content = """
files:
  data: !path ./data/file.txt
  logs: !path ../logs/app.log
  absolute: /var/log/app.log
  url: http://example.com/path
  no_tag: ./unresolved/path.txt
"""
    config_file.write_text(content)
    return str(config_file)


# clean_env fixture is in tests/conftest.py


# =============================================================================
# Test Config Initialization
# =============================================================================


@pytest.mark.unit
@pytest.mark.usefixtures("clean_env")
class TestConfigInitialization:
    """Test Config class initialization."""

    def test_init_with_valid_yaml(self, temp_yaml_file):
        """Test initialization with valid YAML file."""
        config = Config(temp_yaml_file)
        assert config.app.name == "test_app"
        assert config.app.version == "1.0.0"
        assert config.database.host == "localhost"
        assert config.database.port == 5432

    def test_init_with_nonexistent_file(self, tmp_path):
        """Test initialization with nonexistent file raises error."""
        nonexistent = tmp_path / "nonexistent.yaml"
        with pytest.raises(FileNotFoundError):
            Config(str(nonexistent))

    def test_init_stores_configuration_attributes(self, temp_yaml_file):
        """Test that initialization stores configuration attributes."""
        config = Config(
            temp_yaml_file,
            enable_env_overrides=False,
            env_prefix="MYAPP_",
            merge_strategy="merge",
        )
        assert config._enable_env_overrides is False
        assert config._env_prefix == "MYAPP_"
        assert config._merge_strategy == "merge"

    def test_init_default_attributes(self, temp_yaml_file):
        """Test that default attributes are set correctly."""
        config = Config(temp_yaml_file)
        assert config._enable_env_overrides is True
        assert config._env_prefix == "INFRA_"
        assert config._merge_strategy == "replace"

    def test_init_with_malformed_yaml(self, tmp_path):
        """Test initialization with malformed YAML raises error."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("invalid: yaml: content: ::::")
        with pytest.raises(Exception):  # yaml.YAMLError or similar
            Config(str(config_file))

    def test_init_with_empty_file(self, tmp_path):
        """Test initialization with empty YAML file."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("")
        # Empty YAML returns None which causes TypeError
        with pytest.raises(TypeError):
            Config(str(config_file))


# =============================================================================
# Test Variable Substitution
# =============================================================================


@pytest.mark.unit
@pytest.mark.usefixtures("clean_env")
class TestVariableSubstitution:
    """Test ${variable} substitution in configuration values."""

    def test_simple_variable_substitution(self, temp_yaml_with_substitution):
        """Test basic variable substitution."""
        config = Config(temp_yaml_with_substitution)
        assert config.database.url == "postgresql://localhost:5432/testdb"

    def test_nested_variable_substitution(self, temp_yaml_with_substitution):
        """Test variable substitution with nested paths."""
        config = Config(temp_yaml_with_substitution)
        assert config.api.endpoint == "http://localhost/api"

    def test_multiple_substitutions_in_string(self, tmp_path):
        """Test multiple variable substitutions in single string."""
        config_file = tmp_path / "config.yaml"
        content = """
server:
  host: example.com
  port: 8080
  protocol: https
  url: ${server.protocol}://${server.host}:${server.port}/api
"""
        config_file.write_text(content)
        config = Config(str(config_file))
        assert config.server.url == "https://example.com:8080/api"

    def test_substitution_with_nonexistent_variable(self, tmp_path):
        """Test substitution with undefined variable raises error."""
        config_file = tmp_path / "config.yaml"
        content = """
app:
  url: http://${undefined.variable}/path
"""
        config_file.write_text(content)
        # Undefined variables raise DotDictPathNotFoundError
        from appinfra.dot_dict import DotDictPathNotFoundError

        with pytest.raises(DotDictPathNotFoundError):
            Config(str(config_file))

    def test_no_substitution_in_non_string_values(self, tmp_path):
        """Test that substitution only applies to strings."""
        config_file = tmp_path / "config.yaml"
        content = """
values:
  number: 123
  boolean: true
  list: [1, 2, 3]
"""
        config_file.write_text(content)
        config = Config(str(config_file))
        assert config.values.number == 123
        assert config.values.boolean is True
        assert config.values.list == [1, 2, 3]


# =============================================================================
# Test Security
# =============================================================================


@pytest.mark.unit
@pytest.mark.usefixtures("clean_env")
class TestSecurity:
    """Test security fixes and protections."""

    def test_redos_prevention_malicious_pattern(self, tmp_path):
        """Test that malicious ReDoS patterns are rejected (don't match)."""
        import time

        config_file = tmp_path / "config.yaml"
        # Malicious pattern with many opening braces that could cause exponential backtracking
        # With the old regex (.*?), this would cause catastrophic backtracking
        # With the new regex ([a-zA-Z0-9_.]+), this simply won't match
        content = """
app:
  name: myapp
  # This malicious pattern should not cause ReDoS
  url: ${{{{{{{{{{{{{{{{{{{{{{{{{{{{{{{{{{{{{
"""
        config_file.write_text(content)

        start = time.time()
        config = Config(str(config_file))
        elapsed = time.time() - start

        # Should complete quickly (well under 1 second)
        assert elapsed < 1.0, f"ReDoS vulnerability detected: took {elapsed}s"

        # The malicious pattern should not be substituted (stays as-is)
        assert "${" in config.app.url

    def test_variable_substitution_restricts_to_valid_names(self, tmp_path):
        """Test that variable substitution only works with valid names."""
        config_file = tmp_path / "config.yaml"
        content = """
app:
  name: myapp
  valid: ${app.name}
  # Invalid characters in variable name (spaces, special chars)
  invalid1: ${app name}
  invalid2: ${app-name}
  invalid3: ${app@name}
"""
        config_file.write_text(content)
        config = Config(str(config_file))

        # Valid variable name should be substituted
        assert config.app.valid == "myapp"

        # Invalid variable names should not be substituted (stay as-is)
        assert "${app name}" in config.app.invalid1
        assert "${app-name}" in config.app.invalid2
        assert "${app@name}" in config.app.invalid3

    def test_variable_substitution_accepts_dots_and_underscores(self, tmp_path):
        """Test that dots and underscores are allowed in variable names."""
        config_file = tmp_path / "config.yaml"
        content = """
db_config:
  host: localhost
  port: 5432
app:
  # Should support dots for nested paths
  url1: http://${db_config.host}:${db_config.port}
  # Should support underscores in section names
  url2: ${db_config.host}
"""
        config_file.write_text(content)
        config = Config(str(config_file))

        assert config.app.url1 == "http://localhost:5432"
        assert config.app.url2 == "localhost"


# =============================================================================
# Test Environment Variable Overrides
# =============================================================================


@pytest.mark.unit
class TestEnvironmentOverrides:
    """Test environment variable override functionality."""

    def test_env_override_disabled(self, temp_yaml_file, clean_env):
        """Test that env overrides can be disabled."""
        os.environ["INFRA_LOGGING_LEVEL"] = "debug"
        config = Config(temp_yaml_file, enable_env_overrides=False)
        assert config.logging.level == "info"  # Original value, not debug

    def test_env_override_enabled(self, temp_yaml_file, clean_env):
        """Test that env overrides work when enabled."""
        os.environ["INFRA_LOGGING_LEVEL"] = "debug"
        config = Config(temp_yaml_file, enable_env_overrides=True)
        assert config.logging.level == "debug"

    def test_env_override_string_value(self, temp_yaml_file, clean_env):
        """Test environment override for string values."""
        os.environ["INFRA_APP_NAME"] = "overridden_app"
        config = Config(temp_yaml_file)
        assert config.app.name == "overridden_app"

    def test_env_override_boolean_true(self, temp_yaml_file, clean_env):
        """Test environment override for boolean true."""
        os.environ["INFRA_APP_DEBUG"] = "true"
        config = Config(temp_yaml_file)
        assert config.app.debug is True

    def test_env_override_boolean_false(self, temp_yaml_file, clean_env):
        """Test environment override for boolean false."""
        os.environ["INFRA_APP_DEBUG"] = "false"
        config = Config(temp_yaml_file)
        assert config.app.debug is False

    def test_env_override_integer_value(self, temp_yaml_file, clean_env):
        """Test environment override for integer values."""
        os.environ["INFRA_DATABASE_PORT"] = "3306"
        config = Config(temp_yaml_file)
        assert config.database.port == 3306
        assert isinstance(config.database.port, int)

    def test_env_override_float_value(self, tmp_path, clean_env):
        """Test environment override for float values."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("metrics:\n  threshold: 0.5")
        os.environ["INFRA_METRICS_THRESHOLD"] = "0.95"
        config = Config(str(config_file))
        assert config.metrics.threshold == 0.95
        assert isinstance(config.metrics.threshold, float)

    def test_env_override_list_value(self, tmp_path, clean_env):
        """Test environment override for list values."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("servers:\n  hosts: [localhost]")
        os.environ["INFRA_SERVERS_HOSTS"] = "host1,host2,host3"
        config = Config(str(config_file))
        assert config.servers.hosts == ["host1", "host2", "host3"]

    def test_env_override_list_with_mixed_types(self, tmp_path, clean_env):
        """Test environment override for list with mixed types."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("data:\n  values: []")
        os.environ["INFRA_DATA_VALUES"] = "text,123,true,3.14"
        config = Config(str(config_file))
        # Each element converted to its proper type
        assert config.data.values == ["text", 123, True, 3.14]

    def test_env_override_list_single_value_wraps(self, tmp_path, clean_env):
        """Single-value override against a declared list wraps to one-element list."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("cluster:\n  endpoints: ['http://localhost']\n")
        os.environ["INFRA_CLUSTER_ENDPOINTS"] = "http://prod"
        config = Config(str(config_file))
        assert config.cluster.endpoints == ["http://prod"]

    def test_env_override_list_empty_default_wraps(self, tmp_path, clean_env):
        """Empty-list default still anchors the type for single-value override."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("hosts: []\n")
        os.environ["INFRA_HOSTS"] = "alice"
        config = Config(str(config_file))
        assert config.hosts == ["alice"]

    def test_env_override_list_numeric_wraps(self, tmp_path, clean_env):
        """Numeric scalar override against numeric list wraps."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("ports: [1, 2]\n")
        os.environ["INFRA_PORTS"] = "5"
        config = Config(str(config_file))
        assert config.ports == [5]

    def test_env_override_list_null_clears(self, tmp_path, clean_env):
        """Null override against a declared list clears it, does not produce [None]."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("hosts: ['a', 'b']\n")
        os.environ["INFRA_HOSTS"] = "null"
        config = Config(str(config_file))
        assert config.hosts is None

    def test_env_override_list_empty_string_clears(self, tmp_path, clean_env):
        """Empty-string override against a declared list clears it."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("hosts: ['a', 'b']\n")
        os.environ["INFRA_HOSTS"] = ""
        config = Config(str(config_file))
        assert config.hosts is None

    def test_env_override_list_hyphenated_key_wraps(self, tmp_path, clean_env):
        """Yaml-peek works against hyphenated keys with underscore env var."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("web-auth:\n  staging-users: ['x']\n")
        os.environ["INFRA_WEB_AUTH_STAGING_USERS"] = "alice"
        config = Config(str(config_file))
        assert config["web-auth"]["staging-users"] == ["alice"]

    def test_env_override_null_value(self, tmp_path, clean_env):
        """Test environment override for null values."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("optional:\n  value: something")
        os.environ["INFRA_OPTIONAL_VALUE"] = "null"
        config = Config(str(config_file))
        assert config.optional.value is None

    def test_env_override_none_value(self, tmp_path, clean_env):
        """Test environment override with 'none' string."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("optional:\n  value: something")
        os.environ["INFRA_OPTIONAL_VALUE"] = "none"
        config = Config(str(config_file))
        assert config.optional.value is None

    def test_env_override_empty_string(self, tmp_path, clean_env):
        """Test environment override with empty string."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("optional:\n  value: something")
        os.environ["INFRA_OPTIONAL_VALUE"] = ""
        config = Config(str(config_file))
        assert config.optional.value is None

    def test_env_override_nested_path(self, temp_yaml_file, clean_env):
        """Test environment override for deeply nested values."""
        os.environ["INFRA_DATABASE_HOST"] = "remote.example.com"
        config = Config(temp_yaml_file)
        assert config.database.host == "remote.example.com"

    def test_env_override_undeclared_path_raises(self, temp_yaml_file, clean_env):
        """Override on an undeclared yaml path raises UndeclaredConfigPathError."""
        os.environ["INFRA_NEW_SECTION_NEW_KEY"] = "new_value"
        with pytest.raises(UndeclaredConfigPathError) as exc_info:
            Config(temp_yaml_file)
        assert exc_info.value.env_name == "INFRA_NEW_SECTION_NEW_KEY"
        assert exc_info.value.path == ["new", "section", "new", "key"]

    def test_appinfra_tooling_env_vars_skipped(self, temp_yaml_file, clean_env):
        """Vars in APPINFRA_TOOLING_ENV_VARS bypass Config override matching.

        Without this skip, shell-script vars like INFRA_DEV_PKG_NAME would
        raise UndeclaredConfigPathError because they have no yaml field.
        """
        os.environ["INFRA_DEV_PKG_NAME"] = "appinfra"
        os.environ["INFRA_CHECK_PYTEST_SUITE"] = "unit"
        # Config load must not raise even though these paths are undeclared.
        config = Config(temp_yaml_file)
        # And they must not have been quietly written into the config tree.
        assert not config.has("dev.pkg.name")
        assert not config.has("check.pytest.suite")

    def test_env_override_preserves_existing_structure(self, temp_yaml_file, clean_env):
        """Test that env overrides don't destroy existing structure."""
        os.environ["INFRA_LOGGING_LEVEL"] = "debug"
        config = Config(temp_yaml_file)
        # Override applied
        assert config.logging.level == "debug"
        # Other values preserved
        assert config.logging.format == "json"

    def test_custom_env_prefix(self, temp_yaml_file, clean_env):
        """Test custom environment variable prefix."""
        os.environ["MYAPP_LOGGING_LEVEL"] = "debug"
        os.environ["INFRA_LOGGING_LEVEL"] = "warning"  # Should be ignored
        config = Config(temp_yaml_file, env_prefix="MYAPP_")
        assert config.logging.level == "debug"

    def test_get_env_overrides_returns_applied_overrides(
        self, temp_yaml_file, clean_env
    ):
        """Test get_env_overrides returns all applied overrides."""
        os.environ["INFRA_LOGGING_LEVEL"] = "debug"
        os.environ["INFRA_DATABASE_PORT"] = "3306"
        config = Config(temp_yaml_file)
        overrides = config.get_env_overrides()
        assert "logging.level" in overrides
        assert "database.port" in overrides
        assert overrides["logging.level"] == "debug"
        assert overrides["database.port"] == 3306

    def test_get_env_overrides_when_disabled(self, temp_yaml_file, clean_env):
        """Test get_env_overrides returns empty dict when disabled."""
        os.environ["INFRA_LOGGING_LEVEL"] = "debug"
        config = Config(temp_yaml_file, enable_env_overrides=False)
        overrides = config.get_env_overrides()
        assert overrides == {}

    def test_env_override_hyphenated_key(self, tmp_path, clean_env):
        """Test environment override for hyphenated YAML keys."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("services:\n  web-server:\n    port: 3000")
        os.environ["INFRA_SERVICES_WEB_SERVER_PORT"] = "8080"
        config = Config(str(config_file))
        assert config.services["web-server"].port == 8080

    def test_env_override_multiple_hyphens(self, tmp_path, clean_env):
        """Test environment override for keys with multiple hyphens."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("database:\n  primary-db-pool:\n    size: 10")
        os.environ["INFRA_DATABASE_PRIMARY_DB_POOL_SIZE"] = "50"
        config = Config(str(config_file))
        assert config.database["primary-db-pool"].size == 50

    def test_env_override_nested_hyphenated_keys(self, tmp_path, clean_env):
        """Test environment override for nested hyphenated keys."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("app-config:\n  cache-settings:\n    ttl: 300")
        os.environ["INFRA_APP_CONFIG_CACHE_SETTINGS_TTL"] = "600"
        config = Config(str(config_file))
        assert config["app-config"]["cache-settings"].ttl == 600

    def test_env_override_undeclared_hyphenated_path_raises(self, tmp_path, clean_env):
        """Undeclared hyphenated paths also raise."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("app:\n  name: test")
        os.environ["INFRA_NEW_SECTION_API_SERVER_PORT"] = "9000"
        with pytest.raises(UndeclaredConfigPathError):
            Config(str(config_file))

    def test_env_override_exact_match_preferred(self, tmp_path, clean_env):
        """Test that exact matches are preferred over normalized matches."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "services:\n  web_server:\n    port: 3000\n  web-server:\n    port: 4000"
        )
        os.environ["INFRA_SERVICES_WEB_SERVER_PORT"] = "8080"
        config = Config(str(config_file))
        # Should match web_server exactly, not web-server
        assert config.services.web_server.port == 8080
        # web-server should remain unchanged
        assert config.services["web-server"].port == 4000

    def test_env_override_mixed_hyphens_underscores(self, tmp_path, clean_env):
        """Test environment override with mixed hyphens and underscores in keys."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("api:\n  rate-limit_config:\n    max_requests: 100")
        os.environ["INFRA_API_RATE_LIMIT_CONFIG_MAX_REQUESTS"] = "500"
        config = Config(str(config_file))
        assert config.api["rate-limit_config"].max_requests == 500

    def test_env_override_nest_under_scalar_raises(self, tmp_path, clean_env):
        """Cannot traverse into a scalar yaml field — raise."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text('services:\n  web-server: "http://localhost"\n')
        os.environ["INFRA_SERVICES_WEB_SERVER_PORT"] = "8080"
        with pytest.raises(UndeclaredConfigPathError):
            Config(str(config_file))

    def test_env_override_scalar_value_direct(self, tmp_path, clean_env):
        """Test that env override can directly replace a scalar value."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text('services:\n  web-server: "http://localhost"\n')
        os.environ["INFRA_SERVICES_WEB_SERVER"] = "https://example.com"
        config = Config(str(config_file))
        # Direct replacement works
        assert config.services["web-server"] == "https://example.com"

    def test_env_override_nest_under_list_raises(self, tmp_path, clean_env):
        """Cannot traverse into a list yaml field — raise."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("services:\n  web-servers:\n    - host1\n    - host2\n")
        os.environ["INFRA_SERVICES_WEB_SERVERS_PRIMARY_HOST"] = "host1"
        with pytest.raises(UndeclaredConfigPathError):
            Config(str(config_file))

    def test_env_override_list_value_direct(self, tmp_path, clean_env):
        """Test that env override can directly replace a list value."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("services:\n  web-servers:\n    - host1\n    - host2\n")
        os.environ["INFRA_SERVICES_WEB_SERVERS"] = "host1,host2,host3"
        config = Config(str(config_file))
        # Direct list replacement works
        assert config.services["web-servers"] == ["host1", "host2", "host3"]

    def test_env_override_nest_under_null_raises(self, tmp_path, clean_env):
        """Cannot traverse into a null yaml field — raise."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("services:\n  web-server: null\n")
        os.environ["INFRA_SERVICES_WEB_SERVER_PORT"] = "8080"
        with pytest.raises(UndeclaredConfigPathError):
            Config(str(config_file))

    def test_env_override_null_value_direct(self, tmp_path, clean_env):
        """Test that env override can directly set a null value to non-null."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("services:\n  web-server: null\n")
        os.environ["INFRA_SERVICES_WEB_SERVER"] = "enabled"
        config = Config(str(config_file))
        # Direct replacement works
        assert config.services["web-server"] == "enabled"

    def test_env_override_ambiguous_key_exact_match(self, tmp_path, clean_env):
        """Test that exact matches win in ambiguous scenarios."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "services:\n  web_server:\n    port: 3000\n  web:\n    server-port: 4000\n"
        )
        os.environ["INFRA_SERVICES_WEB_SERVER_PORT"] = "8080"
        config = Config(str(config_file))
        # Should match web_server.port exactly
        assert config.services.web_server.port == 8080
        # Other keys unchanged
        assert config.services.web["server-port"] == 4000

    def test_env_override_ambiguous_key_hyphenated(self, tmp_path, clean_env):
        """Test hyphenated match when exact underscore doesn't exist."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "services:\n  web-server:\n    port: 3000\n  web:\n    server-port: 4000\n"
        )
        os.environ["INFRA_SERVICES_WEB_SERVER_PORT"] = "8080"
        config = Config(str(config_file))
        # Should match web-server.port (hyphenated)
        assert config.services["web-server"].port == 8080
        # Other keys unchanged
        assert config.services.web["server-port"] == 4000

    def test_env_override_backward_compat_underscores(self, tmp_path, clean_env):
        """Test backward compatibility with existing underscore keys."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("db:\n  connection_pool:\n    size: 10\n    timeout: 30")
        os.environ["INFRA_DB_CONNECTION_POOL_SIZE"] = "50"
        os.environ["INFRA_DB_CONNECTION_POOL_TIMEOUT"] = "60"
        config = Config(str(config_file))
        # Existing underscore keys still work
        assert config.db.connection_pool.size == 50
        assert config.db.connection_pool.timeout == 60

    def test_env_override_undeclared_nested_path_raises(self, tmp_path, clean_env):
        """Override that would create a new nested subtree raises."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("logging:\n  level: info\n")
        os.environ["INFRA_LOGGING_EXTRA_NESTED_VALUE"] = "test"
        with pytest.raises(UndeclaredConfigPathError):
            Config(str(config_file))


# =============================================================================
# Test Path Resolution
# =============================================================================


@pytest.mark.unit
@pytest.mark.usefixtures("clean_env")
class TestPathResolution:
    """Test path resolution via !path YAML tag."""

    def test_path_tag_resolves_relative_paths(self, temp_yaml_with_paths):
        """Test that !path tag resolves relative paths to absolute."""
        config = Config(temp_yaml_with_paths)
        # Paths with !path tag should be resolved to absolute
        assert Path(config.files.data).is_absolute()
        assert Path(config.files.logs).is_absolute()
        # Absolute paths should remain unchanged
        assert config.files.absolute == "/var/log/app.log"
        # URLs should remain unchanged
        assert config.files.url == "http://example.com/path"
        # Paths without !path tag should NOT be resolved
        assert config.files.no_tag == "./unresolved/path.txt"

    def test_path_tag_with_dot_slash(self, tmp_path):
        """Test !path resolution of ./ paths."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("file: !path ./relative/path.txt")
        config = Config(str(config_file))
        expected = str((tmp_path / "relative" / "path.txt").resolve())
        assert config.file == expected

    def test_path_tag_with_dot_dot_slash(self, tmp_path):
        """Test !path resolution of ../ paths."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("file: !path ../parent/path.txt")
        config = Config(str(config_file))
        expected = str((tmp_path.parent / "parent" / "path.txt").resolve())
        assert config.file == expected

    def test_path_tag_expands_tilde(self, tmp_path):
        """Test that !path expands tilde to home directory."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("cache: !path ~/.cache/myapp")
        config = Config(str(config_file))
        expected = str(Path("~/.cache/myapp").expanduser())
        assert config.cache == expected

    def test_path_tag_absolute_path_unchanged(self, tmp_path):
        """Test that !path with absolute paths returns them unchanged."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("file: !path /absolute/path.txt")
        config = Config(str(config_file))
        assert config.file == "/absolute/path.txt"

    def test_no_automatic_path_resolution(self, tmp_path):
        """Test that paths without !path tag are NOT resolved."""
        config_file = tmp_path / "config.yaml"
        content = """
paths:
  relative_dot: ./data/file.txt
  relative_dotdot: ../logs/app.log
  tilde: ~/.config/app
  plain: some/value
"""
        config_file.write_text(content)
        config = Config(str(config_file))
        # All paths without !path tag should remain as-is
        assert config.paths.relative_dot == "./data/file.txt"
        assert config.paths.relative_dotdot == "../logs/app.log"
        assert config.paths.tilde == "~/.config/app"
        assert config.paths.plain == "some/value"

    def test_urls_unchanged(self, tmp_path):
        """Test that URLs are not affected by !path tag or otherwise."""
        config_file = tmp_path / "config.yaml"
        content = """
urls:
  http: http://example.com/path
  https: https://example.com/path
  file: file:///absolute/path
  postgres: postgresql://localhost:5432/db
"""
        config_file.write_text(content)
        config = Config(str(config_file))
        # All URLs should remain unchanged
        assert config.urls.http == "http://example.com/path"
        assert config.urls.https == "https://example.com/path"
        assert config.urls.file == "file:///absolute/path"
        assert config.urls.postgres == "postgresql://localhost:5432/db"


# =============================================================================
# Test File Validation
# =============================================================================


@pytest.mark.unit
@pytest.mark.usefixtures("clean_env")
class TestFileValidation:
    """Test file size validation and error handling."""

    def test_file_size_within_limit(self, temp_yaml_file):
        """Test that normal-sized files load successfully."""
        config = Config(temp_yaml_file)
        assert config.app.name == "test_app"

    def test_file_size_exceeds_limit(self, tmp_path):
        """Test that oversized files are rejected."""
        config_file = tmp_path / "huge_config.yaml"
        # Create a file larger than MAX_CONFIG_SIZE_BYTES
        large_content = "x: " + ("a" * (MAX_CONFIG_SIZE_BYTES + 1000))
        config_file.write_text(large_content)

        with pytest.raises(ValueError, match="exceeding maximum size"):
            Config(str(config_file))

    def test_check_file_size_helper_accepts_valid(self, temp_yaml_file):
        """Test _check_file_size helper with valid file."""
        # Should not raise
        _check_file_size(temp_yaml_file)

    def test_check_file_size_helper_rejects_large(self, tmp_path):
        """Test _check_file_size helper rejects large files."""
        config_file = tmp_path / "huge.yaml"
        large_content = "x" * (MAX_CONFIG_SIZE_BYTES + 1)
        config_file.write_text(large_content)

        with pytest.raises(ValueError, match="exceeding maximum size"):
            _check_file_size(str(config_file))


# =============================================================================
# Test Type Conversion
# =============================================================================


@pytest.mark.unit
class TestTypeConversion:
    """Test environment variable type conversion."""

    def test_convert_boolean_true_lowercase(self, tmp_path, clean_env):
        """Test conversion of 'true' string to boolean."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("flag: false")
        os.environ["INFRA_FLAG"] = "true"
        config = Config(str(config_file))
        assert config.flag is True

    def test_convert_boolean_false_lowercase(self, tmp_path, clean_env):
        """Test conversion of 'false' string to boolean."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("flag: true")
        os.environ["INFRA_FLAG"] = "false"
        config = Config(str(config_file))
        assert config.flag is False

    def test_convert_integer(self, tmp_path, clean_env):
        """Test conversion of integer strings."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("port: 0")
        os.environ["INFRA_PORT"] = "8080"
        config = Config(str(config_file))
        assert config.port == 8080
        assert type(config.port) is int

    def test_convert_negative_integer(self, tmp_path, clean_env):
        """Test conversion of negative integers."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("offset: 0")
        os.environ["INFRA_OFFSET"] = "-100"
        config = Config(str(config_file))
        assert config.offset == -100

    def test_convert_float(self, tmp_path, clean_env):
        """Test conversion of float strings."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("ratio: 0.0")
        os.environ["INFRA_RATIO"] = "3.14159"
        config = Config(str(config_file))
        assert config.ratio == 3.14159
        assert type(config.ratio) is float

    def test_convert_string_remains_string(self, tmp_path, clean_env):
        """Test that plain strings remain as strings."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("name: original")
        os.environ["INFRA_NAME"] = "new_name"
        config = Config(str(config_file))
        assert config.name == "new_name"
        assert type(config.name) is str

    def test_convert_comma_list(self, tmp_path, clean_env):
        """Test conversion of comma-separated values to list."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("items: []")
        os.environ["INFRA_ITEMS"] = "item1,item2,item3"
        config = Config(str(config_file))
        assert config.items == ["item1", "item2", "item3"]

    def test_convert_mixed_type_list(self, tmp_path, clean_env):
        """Test list with mixed types."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("mixed: []")
        os.environ["INFRA_MIXED"] = "text,42,true,3.14,false"
        config = Config(str(config_file))
        assert config.mixed == ["text", 42, True, 3.14, False]


# =============================================================================
# Test Helper Functions
# =============================================================================


@pytest.mark.unit
class TestHelperFunctions:
    """Test module-level helper functions."""

    def test_preserve_config_attributes(self):
        """Test preserving config attributes."""
        mock_config = Mock()
        mock_config._enable_env_overrides = False
        mock_config._env_prefix = "TEST_"
        mock_config._merge_strategy = "merge"
        mock_config._allowed_paths = ["~/.myapp.yaml"]
        mock_config._project_root_override = Path("/pkg")

        attrs = _preserve_config_attributes(mock_config)

        assert attrs["enable_env_overrides"] is False
        assert attrs["env_prefix"] == "TEST_"
        assert attrs["merge_strategy"] == "merge"
        assert attrs["allowed_paths"] == ["~/.myapp.yaml"]
        assert attrs["project_root_override"] == Path("/pkg")

    def test_preserve_config_attributes_with_defaults(self):
        """Test preserving config attributes with missing attributes."""
        mock_config = Mock(spec=[])  # Empty spec - no attributes

        attrs = _preserve_config_attributes(mock_config)

        # Should return defaults
        assert attrs["enable_env_overrides"] is True
        assert attrs["env_prefix"] == "INFRA_"
        assert attrs["merge_strategy"] == "replace"
        assert attrs["allowed_paths"] is None
        assert attrs["project_root_override"] is None

    def test_restore_config_attributes(self):
        """Test restoring config attributes."""
        mock_config = Mock()
        attrs = {
            "enable_env_overrides": False,
            "env_prefix": "CUSTOM_",
            "merge_strategy": "deep",
            "allowed_paths": ["~/.myapp.yaml"],
            "project_root_override": Path("/pkg"),
        }

        _restore_config_attributes(mock_config, attrs)

        assert mock_config._enable_env_overrides is False
        assert mock_config._env_prefix == "CUSTOM_"
        assert mock_config._merge_strategy == "deep"
        assert mock_config._allowed_paths == ["~/.myapp.yaml"]
        assert mock_config._project_root_override == Path("/pkg")


# =============================================================================
# Test Validation
# =============================================================================


@pytest.mark.unit
@pytest.mark.usefixtures("clean_env")
class TestValidation:
    """Test configuration validation."""

    def test_validate_with_simple_config(self, tmp_path):
        """Test validation with simple config."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("app:\n  name: test")
        config = Config(str(config_file))
        # Validation may return True, False, or validated object depending on pydantic availability
        result = config.validate(raise_on_error=False)
        # Should not raise and should return something
        assert result is not None or result is False

    def test_validate_returns_result(self, tmp_path):
        """Test validation returns a result."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("simple: value")
        config = Config(str(config_file))
        # Validation should return something (True, False, or validated object)
        result = config.validate(raise_on_error=False)
        # Just verify it doesn't crash
        assert result is not None or result is False or result is True


# =============================================================================
# Test Source File Tracking
# =============================================================================


@pytest.mark.unit
@pytest.mark.usefixtures("clean_env")
class TestSourceFileTracking:
    """Test get_source_files() functionality for config file tracking."""

    def test_get_source_files_returns_main_file(self, tmp_path):
        """Test get_source_files returns the main config file."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("app:\n  name: test")
        config = Config(str(config_file))

        source_files = config.get_source_files()

        assert config_file.resolve() in source_files
        assert len(source_files) == 1

    def test_get_source_files_includes_included_files(self, tmp_path):
        """Test get_source_files includes files loaded via !include."""
        # Create included file
        db_file = tmp_path / "database.yaml"
        db_file.write_text("host: localhost\nport: 5432")

        # Create main config with include
        main_file = tmp_path / "config.yaml"
        main_file.write_text('database: !include "./database.yaml"\napp:\n  name: test')

        config = Config(str(main_file))
        source_files = config.get_source_files()

        assert main_file.resolve() in source_files
        assert db_file.resolve() in source_files
        assert len(source_files) == 2

    def test_get_source_files_includes_nested_includes(self, tmp_path):
        """Test get_source_files includes nested includes."""
        # Create nested include chain: main -> logging -> handlers
        handlers_file = tmp_path / "handlers.yaml"
        handlers_file.write_text("console:\n  level: INFO")

        logging_file = tmp_path / "logging.yaml"
        logging_file.write_text('level: DEBUG\nhandlers: !include "./handlers.yaml"')

        main_file = tmp_path / "config.yaml"
        main_file.write_text('logging: !include "./logging.yaml"\napp: test')

        config = Config(str(main_file))
        source_files = config.get_source_files()

        assert main_file.resolve() in source_files
        assert logging_file.resolve() in source_files
        assert handlers_file.resolve() in source_files
        assert len(source_files) == 3

    def test_get_source_files_with_document_level_include(self, tmp_path):
        """Test get_source_files works with document-level includes."""
        # Create base config
        base_file = tmp_path / "base.yaml"
        base_file.write_text("shared:\n  setting: value")

        # Create main config with document-level include
        main_file = tmp_path / "config.yaml"
        main_file.write_text('!include "./base.yaml"\n\napp:\n  name: test')

        config = Config(str(main_file))
        source_files = config.get_source_files()

        assert main_file.resolve() in source_files
        assert base_file.resolve() in source_files

    def test_get_source_files_returns_set(self, tmp_path):
        """Test get_source_files returns a set type."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("app: test")
        config = Config(str(config_file))

        source_files = config.get_source_files()

        assert isinstance(source_files, set)


# =============================================================================
# Test Integration Scenarios
# =============================================================================


@pytest.mark.integration
@pytest.mark.usefixtures("clean_env")
class TestIntegrationScenarios:
    """Test real-world configuration scenarios."""

    def test_config_reload_preserves_attributes(self, temp_yaml_file, tmp_path):
        """Test that reloading config preserves attributes."""
        # Create initial config with custom attributes
        config = Config(temp_yaml_file, enable_env_overrides=False, env_prefix="TEST_")

        # Verify initial attributes
        assert config._enable_env_overrides is False
        assert config._env_prefix == "TEST_"

        # Create a new config file
        new_file = tmp_path / "new_config.yaml"
        new_file.write_text("new:\n  value: 123")

        # Reload config
        config._load(str(new_file))

        # Attributes should be preserved
        assert config._enable_env_overrides is False
        assert config._env_prefix == "TEST_"

        # New values should be loaded
        assert config.new.value == 123

    def test_substitution_not_recursive(self, tmp_path):
        """Test that variable substitution is not recursive."""
        config_file = tmp_path / "config.yaml"
        content = """
env: production
region: us-west
tier: web

cluster: ${env}-${region}-${tier}
endpoint: https://${cluster}.example.com
"""
        config_file.write_text(content)
        config = Config(str(config_file))

        # First level substitution works
        assert config.cluster == "production-us-west-web"
        # When ${cluster} is substituted, it becomes "${env}-${region}-${tier}"
        # but those variables are not recursively resolved
        # This is a limitation - substitution is not recursive
        assert config.endpoint == "https://${env}-${region}-${tier}.example.com"

    def test_env_overrides_with_substitution(self, tmp_path, clean_env):
        """Test environment overrides work with variable substitution."""
        config_file = tmp_path / "config.yaml"
        content = """
database:
  host: localhost
  port: 5432
  url: postgresql://${database.host}:${database.port}/db
"""
        config_file.write_text(content)
        os.environ["INFRA_DATABASE_HOST"] = "remote.example.com"
        config = Config(str(config_file))

        # Env override should be applied before substitution
        assert config.database.host == "remote.example.com"
        assert config.database.url == "postgresql://remote.example.com:5432/db"

    def test_nested_list_and_dict_structures(self, tmp_path):
        """Test handling of complex nested structures."""
        config_file = tmp_path / "config.yaml"
        content = """
servers:
  - name: web1
    host: web1.example.com
    ports: [80, 443]
  - name: web2
    host: web2.example.com
    ports: [80, 443]

database:
  replicas:
    primary:
      host: db-primary.example.com
      port: 5432
    secondary:
      host: db-secondary.example.com
      port: 5432
"""
        config_file.write_text(content)
        config = Config(str(config_file))

        assert len(config.servers) == 2
        assert config.servers[0].name == "web1"
        assert config.servers[0].ports == [80, 443]
        assert config.database.replicas.primary.host == "db-primary.example.com"

    def test_path_tag_in_nested_structures(self, tmp_path):
        """Test !path tag works in nested lists and dicts."""
        config_file = tmp_path / "config.yaml"
        content = """
files:
  configs:
    - !path ./config1.yaml
    - !path ./config2.yaml
  logs:
    primary: !path ./logs/primary.log
    secondary: !path ./logs/secondary.log
  unresolved:
    - ./no_tag1.yaml
    - ./no_tag2.yaml
"""
        config_file.write_text(content)
        config = Config(str(config_file))

        # List paths with !path should be resolved
        assert Path(config.files.configs[0]).is_absolute()
        assert Path(config.files.configs[1]).is_absolute()

        # Nested dict paths with !path should be resolved
        assert Path(config.files.logs.primary).is_absolute()
        assert Path(config.files.logs.secondary).is_absolute()

        # List paths without !path should NOT be resolved
        assert config.files.unresolved[0] == "./no_tag1.yaml"
        assert config.files.unresolved[1] == "./no_tag2.yaml"


# =============================================================================
# Test Edge Cases
# =============================================================================


@pytest.mark.unit
@pytest.mark.usefixtures("clean_env")
class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_config_file(self, tmp_path):
        """Test empty configuration file raises TypeError."""
        config_file = tmp_path / "empty.yaml"
        config_file.write_text("")
        # Empty YAML returns None which causes TypeError
        with pytest.raises(TypeError):
            Config(str(config_file))

    def test_config_with_only_comments(self, tmp_path):
        """Test config file with only comments raises TypeError."""
        config_file = tmp_path / "comments.yaml"
        content = """
# This is a comment
# Another comment
"""
        config_file.write_text(content)
        # Comments-only YAML returns None which causes TypeError
        with pytest.raises(TypeError):
            Config(str(config_file))

    def test_config_with_unicode(self, tmp_path):
        """Test config with unicode characters."""
        config_file = tmp_path / "unicode.yaml"
        content = """
message: "Hello 世界 🌍"
name: "José García"
"""
        config_file.write_text(content)
        config = Config(str(config_file))
        assert config.message == "Hello 世界 🌍"
        assert config.name == "José García"

    def test_very_deep_nesting(self, tmp_path):
        """Test very deeply nested configuration."""
        config_file = tmp_path / "deep.yaml"
        content = """
a:
  b:
    c:
      d:
        e:
          f:
            g:
              value: deep
"""
        config_file.write_text(content)
        config = Config(str(config_file))
        assert config.a.b.c.d.e.f.g.value == "deep"

    def test_env_override_very_deep_nesting(self, tmp_path, clean_env):
        """Test env override for very deeply nested path."""
        config_file = tmp_path / "deep.yaml"
        config_file.write_text("a:\n  b:\n    c: original")
        os.environ["INFRA_A_B_C"] = "overridden"
        config = Config(str(config_file))
        assert config.a.b.c == "overridden"

    def test_numeric_string_not_converted_in_yaml(self, tmp_path):
        """Test that numeric strings in YAML remain strings."""
        config_file = tmp_path / "strings.yaml"
        content = """
version: "1.0.0"
code: "00123"
"""
        config_file.write_text(content)
        config = Config(str(config_file))
        assert config.version == "1.0.0"
        assert config.code == "00123"

    def test_special_yaml_values(self, tmp_path):
        """Test YAML special values (null, true, false)."""
        config_file = tmp_path / "special.yaml"
        content = """
null_value: null
true_value: true
false_value: false
yes_value: yes
no_value: no
"""
        config_file.write_text(content)
        config = Config(str(config_file))
        assert config.null_value is None
        assert config.true_value is True
        assert config.false_value is False
        assert config.yes_value is True
        assert config.no_value is False


@pytest.mark.unit
@pytest.mark.usefixtures("clean_env")
class TestConfigErrors:
    """Test configuration error handling."""

    def test_invalid_yaml_raises_error(self, tmp_path):
        """Test that invalid YAML raises YAMLError."""
        import yaml

        config_file = tmp_path / "invalid.yaml"
        # Invalid YAML: unmatched brackets
        config_file.write_text("invalid: yaml: content: [")

        with pytest.raises(yaml.YAMLError):
            Config(str(config_file))

    def test_file_not_found_raises_error(self, tmp_path):
        """Test that missing config file raises FileNotFoundError."""
        missing_file = tmp_path / "nonexistent.yaml"

        with pytest.raises(FileNotFoundError):
            Config(str(missing_file))

    def test_yaml_with_invalid_substitution(self, tmp_path):
        """Test YAML with reference to nonexistent key."""
        from appinfra.dot_dict import DotDictPathNotFoundError

        config_file = tmp_path / "config.yaml"
        content = """
database:
  host: localhost
  # Reference to nonexistent key should cause error during substitution
  url: postgresql://${nonexistent.key}:5432/db
"""
        config_file.write_text(content)

        # Should raise DotDictPathNotFoundError when trying to substitute ${nonexistent.key}
        with pytest.raises(DotDictPathNotFoundError):
            Config(str(config_file))


# =============================================================================
# Test Config.reload()
# =============================================================================


@pytest.mark.unit
@pytest.mark.usefixtures("clean_env")
class TestConfigReload:
    """Test Config.reload() method."""

    def test_reload_reloads_from_disk(self, tmp_path):
        """Test reload() re-reads the config file."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("value: original")

        config = Config(str(config_file))
        assert config.value == "original"

        # Modify the file
        config_file.write_text("value: updated")

        # Reload should pick up the change
        config.reload()
        assert config.value == "updated"

    def test_reload_returns_self(self, tmp_path):
        """Test reload() returns self for chaining."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("value: test")

        config = Config(str(config_file))
        result = config.reload()

        assert result is config

    def test_reload_raises_without_config_path(self):
        """Test reload() raises RuntimeError if config wasn't loaded from file."""
        from appinfra.dot_dict import DotDict

        # Create a Config-like object without _config_path
        # Note: This is an edge case - normally Config always has _config_path
        config = Config.__new__(Config)
        DotDict.__init__(config)  # Initialize as empty DotDict

        with pytest.raises(RuntimeError, match="not loaded from a file"):
            config.reload()

    def test_reload_preserves_config_options(self, tmp_path):
        """Test reload() preserves enable_env_overrides, env_prefix, etc."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("value: original")

        config = Config(
            str(config_file),
            enable_env_overrides=False,
            env_prefix="CUSTOM_",
        )

        config_file.write_text("value: updated")
        config.reload()

        # Options should be preserved
        assert config._enable_env_overrides is False
        assert config._env_prefix == "CUSTOM_"
        # Value should be updated
        assert config.value == "updated"

    def test_reload_chain_with_get(self, tmp_path):
        """Test reload() can be chained with get()."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("database:\n  host: localhost")

        config = Config(str(config_file))
        config_file.write_text("database:\n  host: remotehost")

        # Chain reload with get
        host = config.reload().get("database.host")
        assert host == "remotehost"


# =============================================================================
# Test Config Integration with DotDict
# =============================================================================


@pytest.mark.usefixtures("clean_env")
class TestConfigDotDictIntegration:
    """Test Config compatibility with DotDict dict subclass changes."""

    def test_config_with_deeply_nested_structure(self, tmp_path):
        """Test Config initialization with deeply nested YAML structures."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            """
level1:
  level2:
    level3:
      level4:
        value: deep
      sibling: shallow
"""
        )
        config = Config(str(config_file))
        assert config.level1.level2.level3.level4.value == "deep"
        assert config.level1.level2.level3.sibling == "shallow"

    def test_config_with_dict_method_name_keys(self, tmp_path):
        """Test Config with YAML keys that match dict method names."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            """
data:
  keys: value1
  values: value2
  items: value3
  copy: value4
"""
        )
        config = Config(str(config_file))
        # Should access data, not methods
        assert config.data.keys == "value1"
        assert config.data.values == "value2"
        assert config.data.items == "value3"
        assert config.data.copy == "value4"

    def test_config_reload_with_nested_structure(self, tmp_path):
        """Test Config reload works correctly with nested structures."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("app:\n  server:\n    port: 3000\n    host: localhost")

        config = Config(str(config_file))
        assert config.app.server.port == 3000

        config_file.write_text("app:\n  server:\n    port: 8080\n    host: remotehost")
        config.reload()

        assert config.app.server.port == 8080
        assert config.app.server.host == "remotehost"

    def test_config_with_mixed_hyphen_underscore_keys(self, tmp_path):
        """Test Config handles mixed hyphen/underscore keys correctly."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            """
services:
  web-server:
    port: 3000
  db_pool:
    size: 10
  cache-config_v2:
    ttl: 300
"""
        )
        config = Config(str(config_file))
        assert config.services["web-server"].port == 3000
        assert config.services.db_pool.size == 10
        assert config.services["cache-config_v2"].ttl == 300

    def test_config_reload_preserves_nested_dotdict_structure(self, tmp_path):
        """Test Config reload correctly rebuilds nested DotDict structures."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            """
app:
  server:
    config:
      port: 3000
      host: localhost
"""
        )

        config = Config(str(config_file))
        assert config.app.server.config.port == 3000

        # Change file with different structure
        config_file.write_text(
            """
app:
  server:
    config:
      port: 8080
      host: remotehost
      timeout: 30
"""
        )

        # Reload should rebuild nested structure correctly
        config.reload()
        assert config.app.server.config.port == 8080
        assert config.app.server.config.host == "remotehost"
        assert config.app.server.config.timeout == 30


@pytest.mark.unit
class TestEnvOverrideSubstitution:
    """Env overrides must reach `${var}` references inside strings.

    Regression: the YAML loader's include-time substitution pre-rendered
    `${pgserver.host}` with raw YAML values *before* Config applied env
    overrides, so URLs like `postgres://${pgserver.host}/db` kept the
    pre-override value even when `INFRA_PGSERVER_HOST` was set.
    appinfra.yaml._include now checks INFRA_* env vars first.
    """

    def test_env_override_substitutes_into_url(self, tmp_path, clean_env):
        """${var} in a URL string picks up the env-overridden value."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "pgserver:\n"
            "  host: 127.0.0.1\n"
            "  port: 25432\n"
            "  user: postgres\n"
            "  pass: ''\n"
            "dbs:\n"
            "  unittest:\n"
            '    url: "postgresql://${pgserver.user}:${pgserver.pass}'
            '@${pgserver.host}:${pgserver.port}/infra_test"\n'
        )
        os.environ["INFRA_PGSERVER_HOST"] = "postgres"
        os.environ["INFRA_PGSERVER_PORT"] = "5432"
        config = Config(str(config_file))
        assert config.pgserver.host == "postgres"
        assert config.pgserver.port == 5432
        assert (
            config.dbs.unittest.url == "postgresql://postgres:@postgres:5432/infra_test"
        )

    def test_env_override_substitutes_across_include(self, tmp_path, clean_env):
        """${var} resolved at !include time also picks up env overrides."""
        included = tmp_path / "pg.yaml"
        included.write_text(
            "pgserver:\n"
            "  host: 127.0.0.1\n"
            "  port: 25432\n"
            "dbs:\n"
            "  unittest:\n"
            '    url: "postgresql://${pgserver.host}:${pgserver.port}/db"\n'
        )
        main = tmp_path / "infra.yaml"
        main.write_text(
            "pgserver: !include pg.yaml#pgserver\ndbs: !include pg.yaml#dbs\n"
        )
        os.environ["INFRA_PGSERVER_HOST"] = "postgres"
        os.environ["INFRA_PGSERVER_PORT"] = "5432"
        config = Config(str(main))
        assert config.dbs.unittest.url == "postgresql://postgres:5432/db"

    def test_no_env_override_uses_yaml_values(self, tmp_path, clean_env):
        """Without env overrides set, substitution uses YAML values as before."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "pgserver:\n"
            "  host: 127.0.0.1\n"
            "  port: 25432\n"
            "dbs:\n"
            "  unittest:\n"
            '    url: "postgresql://${pgserver.host}:${pgserver.port}/db"\n'
        )
        config = Config(str(config_file))
        assert config.dbs.unittest.url == "postgresql://127.0.0.1:25432/db"

    def test_env_override_multi_underscore_resolves_via_canonical_alias(
        self, tmp_path, clean_env
    ):
        """A multi-segment env var (`INFRA_DB_CONNECTION_POOL_SIZE`) reaches a
        `${db.connection_pool.size}` reference inside an included section.

        Without the canonical alias, `_collect_env_overrides_for_yaml` only
        emits `db.connection.pool.size` (every `_` becomes `.`); the
        include-time substitute then misses the override and renders the
        included string with the raw YAML value (10), so the env override
        cannot land at all — `Config._resolve` already sees a baked literal.
        """
        included = tmp_path / "db.yaml"
        included.write_text(
            "db:\n"
            "  connection_pool:\n"
            "    size: 10\n"
            "  summary:\n"
            '    size_str: "size=${db.connection_pool.size}"\n'
        )
        main = tmp_path / "main.yaml"
        main.write_text("db: !include db.yaml#db\n")
        os.environ["INFRA_DB_CONNECTION_POOL_SIZE"] = "42"
        config = Config(str(main))
        assert config.db.connection_pool.size == 42
        assert config.db.summary.size_str == "size=42"

    def test_env_overrides_disabled_does_not_reach_include_substitution(
        self, tmp_path, clean_env
    ):
        """`enable_env_overrides=False` cleanly suppresses env at BOTH the
        leaf-key override pass and the include-time `${var}` substitution.

        Config achieves this by not passing an `env_overrides` dict to
        yaml.load() — the YAML loader is pure local-context substitution
        unless the caller explicitly opts in.
        """
        included = tmp_path / "pg.yaml"
        included.write_text(
            "pgserver:\n"
            "  host: 127.0.0.1\n"
            "dbs:\n"
            "  unittest:\n"
            '    url: "postgres://${pgserver.host}/db"\n'
        )
        main = tmp_path / "main.yaml"
        main.write_text(
            "pgserver: !include pg.yaml#pgserver\ndbs: !include pg.yaml#dbs\n"
        )
        os.environ["INFRA_PGSERVER_HOST"] = "postgres"
        config = Config(str(main), enable_env_overrides=False)
        assert config.pgserver.host == "127.0.0.1"
        assert config.dbs.unittest.url == "postgres://127.0.0.1/db"


class TestConfigAllowedPaths:
    """Config-level integration for the allowed_paths per-path allowlist."""

    def test_default_blocks_home_include(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        proj = tmp_path / "proj" / "etc"
        home.mkdir(parents=True)
        proj.mkdir(parents=True)
        monkeypatch.setenv("HOME", str(home))
        (home / ".overrides.yaml").write_text("db:\n  port: 9999\n")
        cfg_file = proj / "config.yaml"
        cfg_file.write_text('db:\n  port: 5432\nextra: !include "~/.overrides.yaml"\n')

        import yaml as _yaml

        with pytest.raises(_yaml.YAMLError, match="outside project root"):
            Config(str(cfg_file), enable_env_overrides=False)

    def test_allowlist_enables_named_overlay(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        proj = tmp_path / "proj" / "etc"
        home.mkdir(parents=True)
        proj.mkdir(parents=True)
        monkeypatch.setenv("HOME", str(home))
        (home / ".overrides.yaml").write_text("db:\n  port: 9999\n")
        cfg_file = proj / "config.yaml"
        cfg_file.write_text(
            "db:\n  port: 5432\n  host: localhost\n"
            '<<: !deep !include? "~/.overrides.yaml"\n'
        )

        cfg = Config(
            str(cfg_file),
            enable_env_overrides=False,
            allowed_paths=["~/.overrides.yaml"],
        )
        assert cfg.db.port == 9999
        assert cfg.db.host == "localhost"

    def test_allowlist_does_not_unlock_siblings(self, tmp_path, monkeypatch):
        """One allowlisted overlay does NOT permit reads of other home files."""
        home = tmp_path / "home"
        proj = tmp_path / "proj" / "etc"
        home.mkdir(parents=True)
        proj.mkdir(parents=True)
        monkeypatch.setenv("HOME", str(home))
        (home / ".overrides.yaml").write_text("v: 1\n")
        (home / ".other.yaml").write_text("present: true\n")
        cfg_file = proj / "config.yaml"
        cfg_file.write_text('extra: !include "~/.other.yaml"\n')

        import yaml as _yaml

        with pytest.raises(_yaml.YAMLError, match="is not authorized"):
            Config(
                str(cfg_file),
                enable_env_overrides=False,
                allowed_paths=["~/.overrides.yaml"],
            )

    def test_reload_preserves_allowlist(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        proj = tmp_path / "proj" / "etc"
        home.mkdir(parents=True)
        proj.mkdir(parents=True)
        monkeypatch.setenv("HOME", str(home))
        (home / ".overrides.yaml").write_text("v: 1\n")
        cfg_file = proj / "config.yaml"
        cfg_file.write_text('overlay: !include? "~/.overrides.yaml"\n')

        cfg = Config(
            str(cfg_file),
            enable_env_overrides=False,
            allowed_paths=["~/.overrides.yaml"],
        )
        assert cfg.overlay.v == 1
        (home / ".overrides.yaml").write_text("v: 2\n")
        cfg.reload()
        assert cfg.overlay.v == 2


@pytest.mark.unit
class TestConfigProjectRootOverride:
    """Config-level integration for the project_root override.

    Covers the overlay-loads-bundled-base pattern from the v1 config
    protocol: a user overlay under $XDG_CONFIG_HOME `!include`s a base
    config shipped inside a package's etc/ directory, and the base's own
    sibling includes must resolve against the package install directory —
    which the auto-derived project_root cannot reach.
    """

    def _make_bundled_base(self, tmp_path):
        pkg_root = tmp_path / "pkg"
        etc = pkg_root / "etc"
        etc.mkdir(parents=True)
        (etc / "models.yaml").write_text("model: gpt\n")
        (etc / "base.yaml").write_text("app: base\nmodels: !include './models.yaml'\n")
        return pkg_root, etc / "base.yaml"

    def _make_overlay(self, tmp_path, base_path):
        overlay_dir = tmp_path / "xdg" / "myorg"
        overlay_dir.mkdir(parents=True)
        overlay = overlay_dir / "myapp.yaml"
        overlay.write_text(f'!include "{base_path}"\napp: overlay\n')
        return overlay

    def test_default_derivation_rejects_bundled_base_siblings(self, tmp_path):
        """Without an override, sibling relative includes in the base are
        rejected — this is the failure mode `project_root` fixes."""
        _, base = self._make_bundled_base(tmp_path)
        overlay = self._make_overlay(tmp_path, base)

        import yaml as _yaml

        with pytest.raises(_yaml.YAMLError, match="outside project root"):
            Config(
                str(overlay),
                enable_env_overrides=False,
                allowed_paths=[str(base)],
            )

    def test_override_authorizes_base_and_relative_siblings(self, tmp_path):
        """`project_root=<pkg root>` authorizes the base's absolute include
        AND the base's own relative sibling includes in one call."""
        pkg_root, base = self._make_bundled_base(tmp_path)
        overlay = self._make_overlay(tmp_path, base)

        cfg = Config(
            str(overlay),
            enable_env_overrides=False,
            project_root=pkg_root,
        )
        assert cfg.app == "overlay"
        assert cfg.models.model == "gpt"

    def test_override_wins_over_auto_derivation(self, tmp_path):
        """When project_root is set, auto-derivation is skipped even if the
        entry file has an etc/*.yaml marker ancestor."""
        pkg_root, base = self._make_bundled_base(tmp_path)
        # Overlay lives INSIDE an unrelated project root with its own etc/
        other_root = tmp_path / "other"
        other_etc = other_root / "etc"
        other_etc.mkdir(parents=True)
        (other_etc / "marker.yaml").write_text("marker: true\n")
        overlay = other_etc / "myapp.yaml"
        overlay.write_text(f'!include "{base}"\napp: overlay\n')

        # Auto-derivation would pick `other_root` (has etc/marker.yaml),
        # which does not contain the base — the include would fail. The
        # override redirects the boundary to `pkg_root` instead.
        cfg = Config(
            str(overlay),
            enable_env_overrides=False,
            project_root=pkg_root,
        )
        assert cfg.models.model == "gpt"

    def test_none_preserves_auto_derivation(self, tmp_path):
        """`project_root=None` (the default) leaves auto-derivation in
        place — same behavior as before this parameter existed."""
        pkg_root, base = self._make_bundled_base(tmp_path)
        # Load the base directly from inside the package: auto-derivation
        # finds pkg_root (has etc/*.yaml) and the sibling include resolves.
        cfg = Config(str(base), enable_env_overrides=False)
        assert cfg.app == "base"
        assert cfg.models.model == "gpt"

    def test_empty_string_preserves_auto_derivation(self, tmp_path):
        """Empty string falls back to auto-derivation, same as None.

        Guards against `os.environ.get("VAR", "")` accidentally setting
        the security boundary to cwd via `Path("").resolve()`.
        """
        pkg_root, base = self._make_bundled_base(tmp_path)
        cfg = Config(str(base), enable_env_overrides=False, project_root="")
        assert cfg.app == "base"
        assert cfg.models.model == "gpt"

    def test_override_string_path_is_expanded(self, tmp_path, monkeypatch):
        """String paths are `~`-expanded and resolved, matching the
        allowed_paths normalization contract."""
        pkg_root, base = self._make_bundled_base(tmp_path)
        overlay = self._make_overlay(tmp_path, base)
        # Move pkg under a fake home so `~/pkg` resolves to it.
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        target = fake_home / "pkg"
        pkg_root.rename(target)
        # Rewrite the overlay so its !include points at the new base path.
        overlay.write_text(f'!include "{target / "etc" / "base.yaml"}"\napp: overlay\n')
        monkeypatch.setenv("HOME", str(fake_home))

        cfg = Config(
            str(overlay),
            enable_env_overrides=False,
            project_root="~/pkg",
        )
        assert cfg.models.model == "gpt"

    def test_reload_preserves_override(self, tmp_path):
        """Reload keeps the project_root override — same discipline as
        allowed_paths (preserved via _preserve_config_attributes)."""
        pkg_root, base = self._make_bundled_base(tmp_path)
        overlay = self._make_overlay(tmp_path, base)

        cfg = Config(
            str(overlay),
            enable_env_overrides=False,
            project_root=pkg_root,
        )
        assert cfg.models.model == "gpt"

        (pkg_root / "etc" / "models.yaml").write_text("model: gpt-5\n")
        cfg.reload()
        assert cfg.models.model == "gpt-5"


@pytest.fixture
def clean_xdg_env(monkeypatch):
    """Ensure no XDG_* or INFRA_* env vars leak in from the host."""
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("XDG_CONFIG_DIRS", raising=False)
    # CI sets INFRA_* vars that would fail against minimal test configs
    for key in list(os.environ):
        if key.startswith("INFRA_"):
            monkeypatch.delenv(key, raising=False)


def _bundled(
    tmp_path: Path, package: str = "mypkg", body: str = "app: bundled\n"
) -> Path:
    """Write a packaged base config at tmp_path/<package>/etc/<package>.yaml."""
    etc = tmp_path / package / "etc"
    etc.mkdir(parents=True)
    base = etc / f"{package}.yaml"
    base.write_text(body)
    return base


@pytest.mark.unit
class TestConfigFromConfigFile:
    """``Config`` accepts a ``ConfigFile`` as its source.

    The located file carries its own include-authorization root, so the
    two-step ``ConfigSpec.resolve()`` then ``Config(...)`` needs no other
    argument to agree with the resolver.
    """

    def test_loads_from_config_file(self, tmp_path, clean_xdg_env):
        base = _bundled(tmp_path)
        cfg = Config(ConfigFile(base, base.parent, 6))
        assert cfg.app == "bundled"

    def test_config_file_supplies_project_root(self, tmp_path, clean_xdg_env):
        """An overlay outside the base's directory loads under the base's root."""
        base = _bundled(tmp_path)
        overlay = tmp_path / "xdg" / "myorg" / "mypkg.yaml"
        overlay.parent.mkdir(parents=True)
        overlay.write_text(f"!include {base}\nextra: 1\n")
        cfg = Config(ConfigFile(overlay, base.parent, 5))
        assert cfg.app == "bundled"
        assert cfg.extra == 1

    def test_rejects_project_root_alongside_config_file(self, tmp_path):
        base = _bundled(tmp_path)
        with pytest.raises(ValueError, match="do not pass both"):
            Config(ConfigFile(base, base.parent, 6), project_root=tmp_path)

    def test_accepts_path_object(self, tmp_path, clean_xdg_env):
        base = _bundled(tmp_path)
        assert Config(base).app == "bundled"

    def test_end_to_end_bundled_base(self, tmp_path, clean_xdg_env, monkeypatch):
        """No overrides, no XDG overlay, no project-local: the bundled base loads."""
        base = _bundled(tmp_path)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "empty_xdg"))
        neutral = tmp_path / "neutral"
        neutral.mkdir()
        monkeypatch.chdir(neutral)
        cfg = Config(ConfigSpec("myorg", "mypkg", path=base).resolve())
        assert cfg.app == "bundled"

    def test_end_to_end_xdg_overlay_wins(self, tmp_path, clean_xdg_env, monkeypatch):
        base = _bundled(tmp_path)
        xdg_home = tmp_path / "xdg"
        (xdg_home / "myorg").mkdir(parents=True)
        (xdg_home / "myorg" / "mypkg.yaml").write_text("app: overlay\n")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg_home))
        neutral = tmp_path / "neutral"
        neutral.mkdir()
        monkeypatch.chdir(neutral)
        cfg = Config(ConfigSpec("myorg", "mypkg", path=base).resolve())
        assert cfg.app == "overlay"

    def test_end_to_end_etc_dir_override(self, tmp_path, clean_xdg_env, monkeypatch):
        base = _bundled(tmp_path)
        user_etc = tmp_path / "user_etc"
        user_etc.mkdir()
        (user_etc / "mypkg.yaml").write_text("app: user\n")
        monkeypatch.chdir(tmp_path)
        spec = ConfigSpec("myorg", "mypkg", path=base)
        assert Config(spec.resolve(etc_dir=str(user_etc))).app == "user"

    def test_missing_base_raises_at_load(self, tmp_path, clean_xdg_env, monkeypatch):
        """Resolution never probes the packaged base; the load raises instead."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "empty_xdg"))
        neutral = tmp_path / "neutral"
        neutral.mkdir()
        monkeypatch.chdir(neutral)
        spec = ConfigSpec("myorg", "missing", path=tmp_path / "etc" / "missing.yaml")
        with pytest.raises(FileNotFoundError):
            Config(spec.resolve())
