# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

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

        # PermissionError is also valid - it means the path traversal was blocked
        # at the filesystem level (e.g., /root/.ssh/id_rsa is not accessible)
        with pytest.raises((yaml.YAMLError, PermissionError)) as excinfo:
            loader.get_single_data()

        # Validate that YAMLError contains include/traversal-related message
        if isinstance(excinfo.value, yaml.YAMLError):
            error_msg = str(excinfo.value).lower()
            assert any(
                indicator in error_msg
                for indicator in [
                    "include",
                    "cannot find",
                    "not found",
                    "outside project",
                ]
            ), f"Expected include/traversal error, got: {excinfo.value}"


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


@pytest.mark.security
@pytest.mark.integration
def test_allowed_paths_does_not_broaden_beyond_listed_entries(
    secure_temp_project: Path, tmp_path: Path
):
    """
    Verify allowed_paths bypasses project_root ONLY for the explicit entries
    it names — allowlisting one file does not silently permit siblings.

    Attack Vector: Assumption that an opt-in for one overlay unlocks a
    directory or a wider surface.
    Module: appinfra/yaml/loader.py (_check_project_root_security)
    OWASP: A01:2021 - Broken Access Control

    Security Concern: The caller opts into a specific overlay path (e.g.
    ~/.myapp.yaml). If the guard treated the allowlist as a prefix or
    directory grant, an attacker could reach adjacent files by name. This
    test pins the bypass at exact-path membership.
    """
    outside = tmp_path / "outside_home"
    outside.mkdir()
    (outside / "allowed.yaml").write_text("ok: true\n")
    (outside / "sibling.yaml").write_text("leaked: true\n")

    config_path = secure_temp_project / "main.yaml"
    config_path.write_text(f'data: !include "{outside}/sibling.yaml"\n')

    with open(config_path) as f:
        loader = Loader(
            f,
            current_file=config_path,
            project_root=secure_temp_project,
            allowed_paths=[str(outside / "allowed.yaml")],
        )
        with pytest.raises(yaml.YAMLError, match="is not authorized"):
            loader.get_single_data()


@pytest.mark.security
@pytest.mark.integration
def test_config_outside_project_marker_bounds_to_config_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """
    Config auto-derives project_root even when the config file lives outside
    any project tree with an etc/*.yaml marker. The derivation must resolve
    to a bounded directory, not the filesystem root.

    Attack Vector: Absolute-path include reaching beyond the intended
    boundary when a Config caller relies on the auto-derived project_root.
    Module: appinfra/config/config.py (_get_project_root_from_config)
    OWASP: A01:2021 - Broken Access Control
    """
    fake_home = tmp_path / "home"
    (fake_home / ".ssh").mkdir(parents=True)
    (fake_home / ".ssh" / "id_rsa").write_text("PRIV")
    monkeypatch.setenv("HOME", str(fake_home))

    base_dir = tmp_path / "loose_config"
    base_dir.mkdir()
    config_path = base_dir / "base.yaml"
    config_path.write_text(f'stolen: !include "{fake_home}/.ssh/id_rsa"\n')

    from appinfra.config.config import Config

    with pytest.raises(yaml.YAMLError, match="is not authorized"):
        Config(str(config_path), allowed_paths=["~/.does-not-match.yaml"])


@pytest.mark.security
@pytest.mark.integration
def test_load_file_no_project_root_denies_unlisted_absolute(tmp_path: Path):
    """
    load_file(project_root=None, allowed_paths=[...]) treats the allowlist
    as authoritative for absolute includes: only exact-match entries are
    permitted; every other absolute path is denied.

    Attack Vector: Unlisted absolute include when allowed_paths is set as
    the sole authorization surface.
    Module: appinfra/yaml/loader.py (_check_project_root_security)
    OWASP: A01:2021 - Broken Access Control
    """
    from appinfra.yaml import load_file

    allowed = tmp_path / "allowed.yaml"
    allowed.write_text("ok: true\n")
    denied = tmp_path / "denied.yaml"
    denied.write_text("leaked: true\n")

    base = tmp_path / "base.yaml"
    base.write_text(f'x: !include "{denied}"\n')
    with pytest.raises(yaml.YAMLError, match="is not authorized"):
        load_file(str(base), project_root=None, allowed_paths=[str(allowed)])

    base.write_text(f'x: !include "{allowed}"\n')
    result = load_file(str(base), project_root=None, allowed_paths=[str(allowed)])
    assert result == {"x": {"ok": True}}


@pytest.mark.security
@pytest.mark.integration
def test_relative_include_permitted_without_project_root(tmp_path: Path):
    """
    Relative includes are permitted when project_root is not set — the
    YAML author owns their own file layout. Verify a plain relative
    sibling include still resolves.
    """
    from appinfra.yaml import load_file

    (tmp_path / "sibling.yaml").write_text("ok: true\n")
    base = tmp_path / "base.yaml"
    base.write_text('x: !include "./sibling.yaml"\n')

    result = load_file(str(base), project_root=None)
    assert result == {"x": {"ok": True}}


@pytest.mark.security
@pytest.mark.integration
def test_relative_include_bounded_by_project_root_when_set(tmp_path: Path):
    """
    Regression guard: when project_root is set, a relative include using
    `..` escape resolves outside project_root and is denied.
    """
    from appinfra.yaml import load_file

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "leaked.yaml").write_text("leaked: true\n")

    project = tmp_path / "project"
    project.mkdir()
    base = project / "base.yaml"
    base.write_text('x: !include "../outside/leaked.yaml"\n')

    with pytest.raises(yaml.YAMLError, match="outside project root"):
        load_file(str(base), project_root=project)


@pytest.mark.security
@pytest.mark.integration
def test_absolute_inside_project_root_with_allowed_paths_set(tmp_path: Path):
    """
    Regression guard: an absolute include that resolves inside project_root
    is permitted even when allowed_paths is set for other files. The
    authorization contract is "in allowed_paths OR inside project_root".

    Attack Vector: Inadvertent denial when allowed_paths inadvertently
    disables the project_root fallback for absolute includes.
    Module: appinfra/yaml/loader.py (_authorize_absolute_include)
    OWASP: A01:2021 - Broken Access Control (false positive variant)
    """
    from appinfra.yaml import load_file

    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "child.yaml").write_text("ok: true\n")
    main = proj / "main.yaml"
    main.write_text(f'x: !include "{proj}/child.yaml"\n')

    result = load_file(str(main), project_root=proj, allowed_paths=["~/.other.yaml"])
    assert result == {"x": {"ok": True}}
