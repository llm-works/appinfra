# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Security test fixtures and configuration."""

from collections.abc import Generator
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest


@pytest.fixture(autouse=True)
def isolate_security_tests(monkeypatch, tmp_path):
    """
    Automatically run all security tests in isolated temp directory.

    This prevents security test payloads from creating directories
    in the project root (e.g., 'file:', '..;' from path traversal tests).

    The fixture uses pytest's tmp_path which creates directories in
    /tmp/pytest-of-$USER/pytest-current/ with automatic cleanup.
    """
    # Change to temp directory for test execution
    monkeypatch.chdir(tmp_path)
    yield tmp_path
    # monkeypatch automatically restores original directory


@pytest.fixture
def secure_temp_project() -> Generator[Path, None, None]:
    """
    Provides isolated temporary directory for security tests.

    This fixture creates a temporary project structure with subdirectories
    for configs and includes, ensuring tests don't affect the real filesystem.

    Yields:
        Path: Root directory of temporary project
    """
    with TemporaryDirectory(prefix="infra-security-test-", dir="/tmp") as tmpdir:
        project_root = Path(tmpdir)
        (project_root / "configs").mkdir()
        (project_root / "includes").mkdir()
        (project_root / "logs").mkdir()
        yield project_root


@pytest.fixture
def malicious_yaml_loader(secure_temp_project: Path):
    """
    YAML loader configured for security testing with project_root protection.

    Args:
        secure_temp_project: Temporary project directory

    Returns:
        YAMLConfigLoader: Loader instance with project_root set
    """
    from appinfra.yaml import YAMLConfigLoader

    return YAMLConfigLoader(project_root=secure_temp_project)


@pytest.fixture
def yaml_loader_no_root():
    """
    YAML loader WITHOUT project_root protection (for testing vulnerabilities).

    Returns:
        YAMLConfigLoader: Loader instance without project_root restriction
    """
    from appinfra.yaml import YAMLConfigLoader

    return YAMLConfigLoader(project_root=None)


@pytest.fixture(params=["unix", "windows"])
def platform_mock(request, monkeypatch):
    """
    Parametrized fixture to test behavior on both Unix and Windows platforms.

    Args:
        request: Pytest request object with param (unix/windows)
        monkeypatch: Pytest monkeypatch fixture

    Returns:
        str: Platform name ('unix' or 'windows')
    """
    platform_name = request.param

    if platform_name == "windows":
        # Mock platform to appear as Windows
        monkeypatch.setattr("sys.platform", "win32")
    else:
        # Mock platform to appear as Unix/Linux
        monkeypatch.setattr("sys.platform", "linux")

    return platform_name


@pytest.fixture
def mock_tool_registry():
    """
    Provides a fresh ToolRegistry instance for testing.

    Returns:
        ToolRegistry: New registry instance
    """
    from appinfra.app.tools.registry import ToolRegistry

    return ToolRegistry()


@pytest.fixture
def sample_yaml_content() -> dict[str, str]:
    """
    Provides sample YAML file contents for testing.

    Returns:
        Dictionary mapping filenames to their YAML content
    """
    return {
        "config.yaml": "app:\n  name: 'test-app'\n  version: '1.0.0'\n",
        "database.yaml": "database:\n  host: 'localhost'\n  port: 5432\n",
        "safe_include.yaml": "!include database.yaml\n",
    }


@pytest.fixture
def write_yaml_files(secure_temp_project: Path, sample_yaml_content: dict[str, str]):
    """
    Helper fixture to write YAML files to temporary project.

    Args:
        secure_temp_project: Temporary project directory
        sample_yaml_content: Dictionary of filename -> content

    Returns:
        Callable that writes files and returns their paths
    """

    def _write_files(files: dict[str, str] | None = None) -> dict[str, Path]:
        """Write YAML files and return their paths."""
        if files is None:
            files = sample_yaml_content

        written_paths = {}
        for filename, content in files.items():
            file_path = secure_temp_project / "configs" / filename
            file_path.write_text(content)
            written_paths[filename] = file_path

        return written_paths

    return _write_files
