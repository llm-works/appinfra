"""Internal utilities for YAML processing."""

from pathlib import Path


def _file_exists(path: Path) -> bool:
    """
    Check if a file exists without raising exceptions.

    Args:
        path: Path to check

    Returns:
        True if file exists and is accessible, False otherwise
    """
    try:
        return path.exists()
    except (PermissionError, OSError):
        return False
