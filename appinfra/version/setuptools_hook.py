# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Setuptools hook to generate _build_info.py during pip install.

This hook runs during the build process and populates _build_info.py
with the current git commit information.

Registered as entry point in pyproject.toml:
    [project.entry-points."setuptools.finalize_distribution_options"]
    appinfra = "appinfra.version.setuptools_hook:finalize_hook"
"""

from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from setuptools import Distribution

_TEMPLATE = '''\
"""Build information - auto-generated during install, do not edit."""

COMMIT_HASH = "{commit_full}"
COMMIT_SHORT = "{commit_short}"
COMMIT_MESSAGE = "{commit_message}"
BUILD_TIME = "{build_time}"
MODIFIED = {modified}
'''


def _run_git(*args: str) -> str | None:
    """Run git command and return stdout, or None on failure."""
    try:
        result = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return None


def _get_git_info() -> tuple[str, str, str, bool] | None:
    """Get current git commit hash, message, and dirty status."""
    full = _run_git("rev-parse", "HEAD")
    if not full:
        return None

    short = full[:7]
    message = _run_git("log", "-1", "--format=%s") or ""
    status = _run_git("status", "--porcelain")
    modified = bool(status) if status is not None else False

    return full, short, message, modified


def _generate_build_info(package_dir: Path) -> bool:
    """Generate _build_info.py in the given package directory."""
    git_info = _get_git_info()
    if not git_info:
        return False

    commit_full, commit_short, commit_message, modified = git_info
    build_time = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Escape message for Python string
    escaped_message = commit_message.replace("\\", "\\\\").replace('"', '\\"')

    content = _TEMPLATE.format(
        commit_full=commit_full,
        commit_short=commit_short,
        commit_message=escaped_message,
        build_time=build_time,
        modified=modified,
    )

    build_info_path = package_dir / "_build_info.py"
    build_info_path.write_text(content)
    return True


def finalize_hook(dist: Distribution) -> None:
    """
    Setuptools hook to generate _build_info.py during build.

    This runs during 'pip install' or 'python -m build'.
    """
    # Find the appinfra package directory
    # This hook runs from the source directory during build
    source_dir = Path.cwd()

    # Look for appinfra package in common locations
    for candidate in [
        source_dir / "appinfra",
        source_dir / "src" / "appinfra",
    ]:
        if candidate.is_dir() and (candidate / "__init__.py").exists():
            if _generate_build_info(candidate):
                print(
                    f"appinfra: generated _build_info.py in {candidate}",
                    file=sys.stderr,
                )
            return

    # If we can't find it, that's OK - might be installed differently
    pass
