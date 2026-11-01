# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""File selection, exit codes and the keep directive shared by the cq checks."""

import io
import re
import tokenize
from pathlib import Path

from ....log import Logger

# Exit code for "warnings but ok" - findings in non-strict mode
EXIT_CODE_WARNING = 42

# Marks a finding as intended, followed by the reason: "# cq: keep <reason>"
KEEP_DIRECTIVE = re.compile(r"#\s*cq:\s*keep\b", re.IGNORECASE)


def read_source(path: Path) -> str:
    """Read a Python file with its declared encoding, as the interpreter and pylint do."""
    with tokenize.open(path) as f:
        return f.read()


def keep_lines(source: str) -> set[int]:
    """Return the numbers of the lines whose comment carries the keep directive.

    Only comments count: the directive's text inside a string literal does not.
    """
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (SyntaxError, tokenize.TokenError):
        return set()
    return {
        token.start[0]
        for token in tokens
        if token.type == tokenize.COMMENT and KEEP_DIRECTIVE.search(token.string)
    }


def has_keep(kept: set[int], first_line: int, last_line: int) -> bool:
    """True if a line in first_line..last_line (1-based, inclusive) is in kept."""
    return any(first_line <= line <= last_line for line in kept)


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
    # Exclude hidden directories and default exclude dirs
    # Note: skip "." (current dir) to allow "./file.py" paths
    for part in file_path.parts:
        if (part != "." and part.startswith(".")) or part in DEFAULT_EXCLUDE_DIRS:
            return True

    # Exclude test files by default; matching components also covers relative tests/x.py
    if not include_tests and (
        "test" in file_path.parts
        or "tests" in file_path.parts
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
            # Judge each file below the scan root, keeping the root's own name: the directories
            # above the root (a checkout under tests/ or a hidden directory) must not exclude it
            python_files.extend(
                py_file
                for py_file in sorted(path.rglob("*.py"))
                if not should_exclude(
                    Path(path.name) / py_file.relative_to(path),
                    exclude_patterns,
                    include_tests,
                )
            )

    return python_files
