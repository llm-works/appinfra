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
