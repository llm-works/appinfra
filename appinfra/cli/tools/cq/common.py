# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""File selection and exit codes shared by the cq checks."""

from pathlib import Path

from ....log import Logger

# Exit code for "warnings but ok" - findings in non-strict mode
EXIT_CODE_WARNING = 42

# Default directories to exclude (build artifacts, caches, virtual envs)
# These are matched against individual path components
DEFAULT_EXCLUDE_DIRS = [
    "__pycache__",
]


def should_exclude(file_path: Path, patterns: list[str], include_tests: bool) -> bool:
    """
    Check if file should be excluded.

    Args:
        file_path: Path to check
        patterns: Exclusion patterns (Path.match syntax)
        include_tests: Whether to include test files

    Returns:
        True if file should be excluded
    """
    file_str = str(file_path)

    # Exclude hidden directories and default exclude dirs
    # Note: skip "." (current dir) to allow "./file.py" paths
    for part in file_path.parts:
        if (part != "." and part.startswith(".")) or part in DEFAULT_EXCLUDE_DIRS:
            return True

    # Exclude test files by default
    if not include_tests and (
        "/test/" in file_str
        or "/tests/" in file_str
        or file_path.name.startswith("test_")
        or file_path.name.endswith("_test.py")
    ):
        return True

    return any(file_path.match(pattern) for pattern in patterns)


def collect_python_files(
    lg: Logger, paths: list[str], exclude_patterns: list[str], include_tests: bool
) -> list[Path]:
    """
    Collect the .py files under the given paths.

    Args:
        lg: Logger for paths that do not exist
        paths: List of file or directory paths
        exclude_patterns: Patterns to exclude
        include_tests: Whether to include test files

    Returns:
        List of Python file paths
    """
    python_files = []

    for path_str in paths:
        path = Path(path_str)

        if not path.exists():
            lg.warning("path does not exist", extra={"path": path})
            continue

        if path.is_file():
            if path.suffix == ".py" and not should_exclude(
                path, exclude_patterns, include_tests
            ):
                python_files.append(path)
        elif path.is_dir():
            python_files.extend(
                py_file
                for py_file in sorted(path.rglob("*.py"))
                if not should_exclude(py_file, exclude_patterns, include_tests)
            )

    return python_files
