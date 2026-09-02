# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Internal utilities for YAML processing."""

from pathlib import Path


def _file_exists(path: Path) -> bool:
    """
    Check if a file exists, letting permission/access errors propagate.

    Args:
        path: Path to check

    Returns:
        True if file exists, False if file not found.

    Raises:
        PermissionError: If parent directory is not accessible.
        OSError: For other filesystem errors.
    """
    # path.exists() returns False for missing files and raises for access errors
    # Don't catch exceptions - let PermissionError etc propagate as real problems
    return path.exists()


def _normalize_allowed_paths(
    entries: list[Path | str] | None,
) -> frozenset[Path]:
    """Normalize an `allowed_paths` list into the resolved set the loader
    checks membership against.

    Each entry is expanded (~) and resolved to an absolute path. `None` and
    empty list both become the empty set — no bypass entries.
    """
    if not entries:
        return frozenset()
    return frozenset(Path(str(e)).expanduser().resolve() for e in entries)
