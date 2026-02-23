"""Security tests for YAML module (infra/yaml.py)."""

from pathlib import Path

import pytest
import yaml

from appinfra.yaml import Loader
from tests.security.payloads.injection import YAML_CODE_EXECUTION
from tests.security.payloads.resource_exhaustion import (
    BILLION_LAUGHS_YAML,
    generate_circular_includes,
    generate_deep_yaml_includes,
)
from tests.security.payloads.traversal import (
    ABSOLUTE_PATH_ESCAPE,
    CLASSIC_TRAVERSAL,
    NULL_BYTE_BYPASS,
)


@pytest.mark.security
@pytest.mark.unit
@pytest.mark.parametrize("payload", YAML_CODE_EXECUTION)
def test_yaml_code_execution_blocked(payload: str):
    """
    Verify SafeLoader prevents arbitrary code execution via YAML tags.

    Attack Vector: Code execution via !!python/object tags
    Module: infra/yaml.py:36 (uses yaml.SafeLoader)
    OWASP: A03:2021 - Injection

    Security Concern: YAML parsing with unsafe loaders can execute arbitrary
    Python code via tags like !!python/object/apply. This test verifies that
    the Loader class extends SafeLoader which blocks code execution.
    """
    # Attempt to load malicious YAML
    try:
        yaml.load(payload, Loader=Loader)
        pytest.fail(f"Code execution payload should have been blocked: {payload}")
    except yaml.constructor.ConstructorError as e:
        # SafeLoader raises ConstructorError for dangerous tags
        assert "could not determine a constructor" in str(e).lower()
    except yaml.YAMLError:
        # Other YAML errors are also acceptable (malformed payload)
        pass


@pytest.mark.security
@pytest.mark.integration
@pytest.mark.parametrize("traversal_path", CLASSIC_TRAVERSAL + ABSOLUTE_PATH_ESCAPE)
def test_yaml_include_path_traversal(
    traversal_path: str, secure_temp_project: Path, write_yaml_files
):
    """
    Verify project_root enforcement prevents path traversal in includes.

    Attack Vector: Path traversal via !include directives
    Module: infra/yaml.py:293-303 (project_root validation)
    OWASP: A01:2021 - Broken Access Control

    Security Concern: Attackers could use path traversal in !include directives
    to read arbitrary files outside the project directory. The project_root
    parameter should enforce boundary restrictions.
    """
    # Create a config with malicious include
    malicious_config = f"data: !include {traversal_path}\n"
    config_path = secure_temp_project / "configs" / "malicious.yaml"
    config_path.write_text(malicious_config)

    # Attempt to load with project_root protection
    with open(config_path) as f:
        loader = Loader(
            f,
            current_file=config_path,
            project_root=secure_temp_project,
        )

        with pytest.raises(yaml.YAMLError, match="(outside project root|not found)"):
            loader.get_single_data()


@pytest.mark.security
@pytest.mark.integration
@pytest.mark.expected_skip  # Skips on Windows (no /etc/passwd)
def test_yaml_include_symlink_attack(secure_temp_project: Path):
    """
    Verify symlink resolution respects project_root boundary.

    Attack Vector: Symlink-based path traversal
    Module: infra/yaml.py:298 (relative_to check on resolved path)
    OWASP: A01:2021 - Broken Access Control

    Security Concern: Attackers could create symlinks pointing outside
    project_root, then include them. The .resolve() call should detect
    this and raise an error.
    """
    # Create a symlink pointing outside project (to /etc/passwd)
    symlink_path = secure_temp_project / "configs" / "symlink_attack.yaml"
    target_path = Path("/etc/passwd")

    # Skip test if /etc/passwd doesn't exist (e.g., Windows)
    if not target_path.exists():
        pytest.skip("/etc/passwd not available on this platform")

    try:
        symlink_path.symlink_to(target_path)
    except OSError:
        pytest.skip("Cannot create symlinks (insufficient permissions)")

    # Create config that includes the symlink
    config_content = "data: !include symlink_attack.yaml\n"
    config_path = secure_temp_project / "configs" / "config.yaml"
    config_path.write_text(config_content)

    # Attempt to load - should fail because symlink points outside project_root
    with open(config_path) as f:
        loader = Loader(
            f,
            current_file=config_path,
            project_root=secure_temp_project,
        )

        with pytest.raises(yaml.YAMLError, match="outside project root"):
            loader.get_single_data()


@pytest.mark.security
@pytest.mark.integration
def test_yaml_include_depth_bomb(secure_temp_project: Path):
    """
    Verify max_include_depth limit prevents stack exhaustion.

    Attack Vector: Deeply nested includes to exhaust stack
    Module: infra/yaml.py:321-326 (max_include_depth check)
    OWASP: A05:2021 - Security Misconfiguration

    Security Concern: Deeply nested includes (11+ levels) could cause stack
    overflow. The max_include_depth parameter (default 10) should prevent this.
    """
    # Generate deeply nested include structure (12 files = 11 includes, exceeds default limit of 10)
    configs_dir = secure_temp_project / "configs"
    files = generate_deep_yaml_includes(depth=12, base_dir=configs_dir)

    # Write all files
    for file_path, content in files.items():
        Path(file_path).write_text(content)

    # Attempt to load the entry point (level_0.yaml)
    entry_file = configs_dir / "level_0.yaml"
    with open(entry_file) as f:
        loader = Loader(
            f,
            current_file=entry_file,
            project_root=secure_temp_project,
        )

        with pytest.raises(yaml.YAMLError, match="Include depth exceeds maximum"):
            loader.get_single_data()


@pytest.mark.security
@pytest.mark.integration
def test_yaml_billion_laughs_attack(secure_temp_project: Path):
    """
    Verify SafeLoader prevents YAML bomb (billion laughs) attacks.

    Attack Vector: Exponential entity expansion
    Module: infra/yaml.py:36 (SafeLoader prevents anchors/aliases expansion bomb)
    OWASP: A05:2021 - Security Misconfiguration

    Security Concern: YAML anchors and aliases can be used to create
    exponentially expanding data structures (billion laughs attack),
    exhausting memory. SafeLoader should handle this safely.
    """
    config_path = secure_temp_project / "configs" / "bomb.yaml"
    config_path.write_text(BILLION_LAUGHS_YAML)

    # Load the billion laughs YAML
    # SafeLoader will expand this, but it should not cause catastrophic memory issues
    # because Python's YAML implementation has safeguards
    with open(config_path) as f:
        loader = Loader(f, current_file=config_path)

        # This should complete without hanging or OOM
        # If it takes more than a few seconds, the test will timeout
        data = loader.get_single_data()

        # The structure will be expanded, but should be finite
        assert data is not None


@pytest.mark.security
@pytest.mark.integration
def test_yaml_circular_include_detection(secure_temp_project: Path):
    """
    Verify circular include detection prevents infinite loops.

    Attack Vector: Circular includes (A includes B, B includes A)
    Module: infra/yaml.py:283-287 (circular include check)
    OWASP: A05:2021 - Security Misconfiguration

    Security Concern: Circular includes could cause infinite loops and
    stack overflow. The include_chain tracking should detect and prevent this.
    """
    # Generate circular includes
    configs_dir = secure_temp_project / "configs"
    circular_files = generate_circular_includes(configs_dir)

    # Write circular files
    for file_path, content in circular_files.items():
        Path(file_path).write_text(content)

    # Attempt to load circular_a.yaml
    entry_file = configs_dir / "circular_a.yaml"
    with open(entry_file) as f:
        loader = Loader(
            f,
            current_file=entry_file,
            project_root=secure_temp_project,
        )

        with pytest.raises(yaml.YAMLError, match="Circular include detected"):
            loader.get_single_data()


@pytest.mark.security
@pytest.mark.unit
@pytest.mark.parametrize("payload", NULL_BYTE_BYPASS)
def test_yaml_null_byte_in_include_path(payload: str, secure_temp_project: Path):
    """
    Verify null bytes in include paths don't bypass validation.

    Attack Vector: Null byte injection in file paths
    Module: infra/yaml.py:293-303 (path validation)
    OWASP: A03:2021 - Injection

    Security Concern: Null bytes (\\x00) can truncate strings in some contexts,
    potentially bypassing path validation. Ensure include path handling is safe.
    """
    # Create config with null byte in include path
    malicious_config = f"data: !include {payload}\n"
    config_path = secure_temp_project / "configs" / "nullbyte.yaml"
    config_path.write_text(malicious_config)

    # Attempt to load - should fail (null byte rejected by YAML reader)
    with open(config_path) as f:
        with pytest.raises(
            (yaml.YAMLError, yaml.reader.ReaderError, ValueError, OSError)
        ):
            # Various possible errors depending on how null byte is handled:
            # - yaml.reader.ReaderError: Null byte rejected by YAML reader during parsing (most common)
            # - YAMLError: Include file not found
            # - ValueError: Invalid path
            # - OSError: Path contains null byte
            loader = Loader(
                f,
                current_file=config_path,
                project_root=secure_temp_project,
            )
            loader.get_single_data()
