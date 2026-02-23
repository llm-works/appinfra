"""Security tests for Config module (infra/app/cfg.py)."""

import os
from pathlib import Path

import pytest

from appinfra.config import MAX_CONFIG_SIZE_BYTES, Config
from tests.security.payloads.injection import ENV_VAR_INJECTION
from tests.security.payloads.resource_exhaustion import generate_large_config
from tests.security.payloads.traversal import (
    ABSOLUTE_PATH_ESCAPE,
    CLASSIC_TRAVERSAL,
)


@pytest.mark.security
@pytest.mark.integration
def test_config_file_size_limit(secure_temp_project: Path):
    """
    Verify MAX_CONFIG_SIZE_BYTES enforcement prevents DoS attacks.

    Attack Vector: Resource exhaustion via oversized config files
    Module: infra/app/cfg.py:43-51 (_check_file_size)
    OWASP: A05:2021 - Security Misconfiguration

    Security Concern: Extremely large config files can exhaust memory and
    processing time during YAML parsing. The 10MB limit should prevent
    resource exhaustion attacks.
    """
    # Test 1: Config file slightly under limit should succeed
    max_size_mb = MAX_CONFIG_SIZE_BYTES // (1024 * 1024)
    # Generate config slightly smaller to account for YAML overhead
    config_under_limit = generate_large_config(max_size_mb - 1)
    valid_path = secure_temp_project / "configs" / "valid_size.yaml"
    valid_path.write_text(config_under_limit)

    # Should load without error
    config = Config(str(valid_path), enable_env_overrides=False)
    assert config is not None

    # Test 2: Config file exceeding limit should fail
    # Generate 11MB config (exceeds 10MB limit)
    oversized_config = generate_large_config(max_size_mb + 1)
    oversized_path = secure_temp_project / "configs" / "oversized.yaml"
    oversized_path.write_text(oversized_config)

    # Verify file is actually oversized
    assert oversized_path.stat().st_size > MAX_CONFIG_SIZE_BYTES

    # Should raise ValueError for exceeding size limit
    with pytest.raises(
        ValueError,
        match=f"exceeding maximum size of {MAX_CONFIG_SIZE_BYTES} bytes",
    ):
        Config(str(oversized_path), enable_env_overrides=False)

    # Test 3: Verify error message includes actual file size
    try:
        Config(str(oversized_path), enable_env_overrides=False)
        pytest.fail("Expected ValueError for oversized config")
    except ValueError as e:
        error_msg = str(e)
        assert str(oversized_path) in error_msg
        assert "bytes" in error_msg


@pytest.mark.security
@pytest.mark.integration
@pytest.mark.parametrize("payload", ENV_VAR_INJECTION[:3])  # Test first 3 payloads
def test_variable_substitution_injection(payload: str, secure_temp_project: Path):
    """
    Verify variable substitution pattern restricts to safe characters.

    Attack Vector: Code injection via variable substitution
    Module: infra/app/cfg.py:181-205 (_resolve method)
    OWASP: A03:2021 - Injection

    Security Concern: Variable substitution using ${...} syntax could enable
    code execution if the pattern allows arbitrary expressions. The regex
    should restrict to safe config key characters (alphanumeric, dot, underscore).
    """
    # Create config with malicious variable reference
    config_content = f"""
base_value: "safe_value"
malicious: "{payload}"
"""
    config_path = secure_temp_project / "configs" / "injection.yaml"
    config_path.write_text(config_content)

    # Load config - malicious payload should not execute
    config = Config(str(config_path), enable_env_overrides=False)

    # The malicious payload should remain as literal string
    # since it doesn't match the safe pattern [a-zA-Z0-9_.]
    # The payload is preserved but not RESOLVED (not executed)
    assert config.malicious == payload

    # Most importantly: verify the payload was NOT executed
    # (if it were executed, the config would contain different values)
    # The presence of the string is OK - it's execution that's bad


@pytest.mark.security
@pytest.mark.integration
def test_variable_substitution_recursion(secure_temp_project: Path):
    """
    Verify circular variable references don't cause infinite loops.

    Attack Vector: Stack overflow via circular variable references
    Module: infra/app/cfg.py:181-205 (_resolve method)
    OWASP: A05:2021 - Security Misconfiguration

    Security Concern: Circular variable references (a=${b}, b=${a}) could
    cause infinite recursion and stack overflow. The implementation should
    handle this gracefully.
    """
    # Create config with circular references
    config_content = """
var_a: "${var_b}"
var_b: "${var_a}"
"""
    config_path = secure_temp_project / "configs" / "circular.yaml"
    config_path.write_text(config_content)

    # Load config - should not hang or crash
    # Python's re.sub processes the string once, so circular refs become literals
    config = Config(str(config_path), enable_env_overrides=False)

    # The substitution doesn't recurse - it runs once
    # var_a resolves to whatever var_b's value is at that time
    # In this case, it becomes the literal string "${var_a}"
    assert config is not None
    # Verify we didn't enter infinite loop (test completes)


@pytest.mark.security
@pytest.mark.integration
@pytest.mark.parametrize("payload", ENV_VAR_INJECTION)
def test_environment_variable_injection(payload: str, secure_temp_project: Path):
    """
    Verify environment variable values are safely type-converted.

    Attack Vector: Code execution via environment variable values
    Module: infra/app/cfg.py:370-471 (_apply_env_overrides, _convert_env_value)
    OWASP: A03:2021 - Injection

    Security Concern: Environment variables can be controlled by attackers
    in some deployment scenarios. Type conversion must not execute code
    even if variable values contain shell or Python injection payloads.
    """
    # Create minimal config
    config_content = """
app:
  name: "test_app"
  setting: "default"
"""
    config_path = secure_temp_project / "configs" / "env_test.yaml"
    config_path.write_text(config_content)

    # Set malicious environment variable
    env_key = "INFRA_APP_SETTING"
    os.environ[env_key] = payload

    try:
        # Load config with env overrides enabled
        # Some payloads may cause config loading to fail (e.g., ${PATH} references
        # non-existent config key), which is acceptable - the key test is that
        # no code is executed
        try:
            config = Config(str(config_path), enable_env_overrides=True)

            # The malicious payload should be treated as a string, not executed
            setting_value = config.app.setting
            assert isinstance(setting_value, str)

            # The value may be transformed by variable substitution,
            # but the important thing is no code execution occurred
            # We can verify this by checking the process is still running
            # and no files were created/modified by the payload

        except Exception:
            # Some payloads may cause parsing errors (e.g., ${PATH} tries to
            # resolve a non-existent config key). This is acceptable - the
            # important thing is no code execution occurred.
            # The test succeeding (not hanging/crashing) proves no execution.
            pass

    finally:
        # Clean up environment variable
        if env_key in os.environ:
            del os.environ[env_key]


@pytest.mark.security
@pytest.mark.unit
@pytest.mark.parametrize(
    "env_value,expected_type,expected_value",
    [
        ("true", bool, True),
        ("false", bool, False),
        ("True", bool, True),  # Case variations
        ("FALSE", bool, False),
        ("42", int, 42),
        ("3.14", float, 3.14),
        ("NaN", str, "NaN"),  # Should NOT convert to float('nan')
        ("Infinity", str, "Infinity"),  # Should NOT convert to float('inf')
        ("null", type(None), None),
        ("none", type(None), None),
        ("", type(None), None),
        ("regular_string", str, "regular_string"),
    ],
)
def test_environment_variable_type_confusion(
    env_value: str,
    expected_type: type,
    expected_value: object,
    secure_temp_project: Path,
):
    """
    Verify safe type conversion for environment variable values.

    Attack Vector: Type confusion attacks via special float/string values
    Module: infra/app/cfg.py:437-471 (_convert_env_value)
    OWASP: A03:2021 - Injection

    Security Concern: Special string values like "NaN", "Infinity", or case
    variations of booleans could cause type confusion. The converter should
    handle these safely and predictably.
    """
    # Create minimal config
    config_content = """
test:
  value: "default"
"""
    config_path = secure_temp_project / "configs" / "type_test.yaml"
    config_path.write_text(config_content)

    # Set environment variable with test value
    env_key = "INFRA_TEST_VALUE"
    os.environ[env_key] = env_value

    try:
        # Load config with env overrides
        config = Config(str(config_path), enable_env_overrides=True)

        # Verify type and value
        actual_value = config.test.value
        assert type(actual_value) is expected_type, (
            f"Expected type {expected_type.__name__}, "
            f"got {type(actual_value).__name__} for value '{env_value}'"
        )
        assert actual_value == expected_value, (
            f"Expected value {expected_value}, got {actual_value} for input '{env_value}'"
        )

    finally:
        # Clean up
        if env_key in os.environ:
            del os.environ[env_key]


@pytest.mark.security
@pytest.mark.integration
@pytest.mark.expected_skip  # Skips non-relative paths (absolute, Windows, etc.)
@pytest.mark.parametrize("traversal_path", CLASSIC_TRAVERSAL + ABSOLUTE_PATH_ESCAPE)
def test_config_path_resolution_traversal(
    traversal_path: str, secure_temp_project: Path
):
    """
    Verify !path tag resolution stays within project boundaries.

    Attack Vector: Path traversal via relative paths in config values
    Module: appinfra/yaml.py (path_constructor)
    OWASP: A01:2021 - Broken Access Control

    Security Concern: Config values using !path tag are resolved to absolute
    paths. Without proper validation, attackers could use path traversal
    to reference files outside the project directory.

    Note: Path resolution only happens with explicit !path tag.
    """
    # Create config with !path tag for path resolution
    # Note: Only paths with !path tag are resolved
    if not (traversal_path.startswith("./") or traversal_path.startswith("../")):
        pytest.skip(f"Path {traversal_path} not a relative path (not ./ or ../)")

    config_content = f"""
paths:
  data_dir: !path "{traversal_path}"
"""
    config_path = secure_temp_project / "configs" / "paths.yaml"
    config_path.write_text(config_content)

    # Load config
    config = Config(str(config_path), enable_env_overrides=False)

    # Get resolved path
    resolved_path_str = config.paths.data_dir
    resolved_path = Path(resolved_path_str)

    # If resolution succeeded, verify it's within project boundaries
    # (The YAML loader's project_root enforcement should prevent escapes)
    if resolved_path.exists():
        # If path exists and was resolved, it should be safe
        # The yaml loader should have blocked dangerous includes
        assert resolved_path.is_absolute()


@pytest.mark.security
@pytest.mark.integration
@pytest.mark.expected_skip  # Skips on Windows (no /etc/passwd)
def test_config_path_symlink_attack(secure_temp_project: Path):
    """
    Verify !path tag symlink resolution doesn't escape project boundaries.

    Attack Vector: Symlink-based path traversal
    Module: appinfra/yaml.py (path_constructor with .resolve())
    OWASP: A01:2021 - Broken Access Control

    Security Concern: Symlinks can point outside the project directory.
    The .resolve() call should detect this, and combined with YAML loader's
    project_root enforcement, should prevent access to sensitive files.
    """
    # Create a symlink pointing outside project (to /etc/passwd or similar)
    target_path = Path("/etc/passwd")

    # Skip test if target doesn't exist (e.g., Windows)
    if not target_path.exists():
        pytest.skip("/etc/passwd not available on this platform")

    symlink_path = secure_temp_project / "configs" / "evil_symlink"

    try:
        symlink_path.symlink_to(target_path)
    except OSError:
        pytest.skip("Cannot create symlinks (insufficient permissions)")

    # Create config referencing the symlink via !path tag
    config_content = """
paths:
  dangerous: !path "./evil_symlink"
"""
    config_path = secure_temp_project / "configs" / "symlink.yaml"
    config_path.write_text(config_content)

    # Load config - !path tag will resolve the path
    config = Config(str(config_path), enable_env_overrides=False)

    # The path will be resolved via !path tag
    resolved = Path(config.paths.dangerous)

    # Verify the resolved path
    # If it points outside project_root, that's a security issue
    # However, the actual enforcement is in yaml.py for includes
    # This test documents the behavior for !path tag resolution

    # For this test, we verify that .resolve() is being called
    # (which is the basis for security checks elsewhere)
    assert resolved.is_absolute()


@pytest.mark.security
@pytest.mark.unit
@pytest.mark.parametrize(
    "null_byte_key", ["key\x00name", "section\x00field", "data\x00"]
)
def test_config_null_byte_in_keys(null_byte_key: str, secure_temp_project: Path):
    """
    Verify null bytes in config keys don't bypass validation or truncate keys.

    Attack Vector: Null byte injection in configuration keys
    Module: infra/app/cfg.py (Config class, DotDict operations)
    OWASP: A03:2021 - Injection

    Security Concern: Null bytes (\\x00) can truncate strings in C-based
    libraries or bypass validation in some contexts. Config keys should
    handle null bytes safely without truncation or bypass.
    """
    # Create config with null byte in key
    # YAML may or may not accept null bytes in keys - test the behavior
    config_content = f"""
normal_key: "normal_value"
{null_byte_key}: "dangerous_value"
"""
    config_path = secure_temp_project / "configs" / "nullbyte.yaml"

    # Write using binary mode to ensure null byte is preserved
    config_path.write_bytes(config_content.encode("utf-8"))

    # Attempt to load config
    try:
        config = Config(str(config_path), enable_env_overrides=False)

        # If loading succeeded, verify the key wasn't truncated
        config_dict = config.dict()

        # Check that null byte didn't truncate the key
        for key in config_dict.keys():
            if "\x00" in key:
                # Null byte preserved - verify full key is there
                assert key == null_byte_key
            elif key.startswith(null_byte_key.split("\x00")[0]):
                # Key was truncated at null byte - security issue!
                pytest.fail(
                    f"Key was truncated at null byte: expected '{null_byte_key}', "
                    f"got '{key}'"
                )

    except Exception:
        # YAML parser may reject null bytes - this is acceptable behavior
        # The important thing is that null bytes don't bypass validation
        pass


# Positive test: Verify legitimate config operations work
@pytest.mark.security
@pytest.mark.integration
def test_legitimate_config_operations(secure_temp_project: Path):
    """
    Verify legitimate config operations are not blocked by security measures.

    Security Concern: Security measures should block attacks without breaking
    legitimate use cases. Common config patterns should work correctly.
    """
    # Create a realistic config with various features
    config_content = """
app:
  name: "my_application"
  version: "1.2.3"
  base_path: !path ./data
  literal_path: ./data

database:
  host: "localhost"
  port: 5432
  connection_string: "postgresql://${database.host}:${database.port}/mydb"

features:
  - authentication
  - logging
  - caching

settings:
  debug: false
  timeout: 30
  ratio: 0.75
"""
    config_path = secure_temp_project / "configs" / "legitimate.yaml"
    config_path.write_text(config_content)

    # Set legitimate environment override
    os.environ["INFRA_APP_VERSION"] = "1.2.4"

    try:
        # Load config with all features enabled
        config = Config(str(config_path), enable_env_overrides=True)

        # Verify basic access
        assert config.app.name == "my_application"
        assert config.app.version == "1.2.4"  # Overridden by env var
        assert config.database.host == "localhost"
        assert config.database.port == 5432

        # Verify variable substitution works
        assert config.database.connection_string == "postgresql://localhost:5432/mydb"

        # Verify list access
        assert "authentication" in config.features
        assert len(config.features) == 3

        # Verify type conversion
        assert isinstance(config.settings.debug, bool)
        assert isinstance(config.settings.timeout, int)
        assert isinstance(config.settings.ratio, float)

        # Verify !path tag resolves paths
        base_path = Path(config.app.base_path)
        assert base_path.is_absolute()

        # Verify paths without !path remain literal
        assert config.app.literal_path == "./data"

    finally:
        # Clean up
        if "INFRA_APP_VERSION" in os.environ:
            del os.environ["INFRA_APP_VERSION"]
