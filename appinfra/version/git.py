# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Git queries shared by the version sources.

Each query returns None when git is missing, the command fails or times out, so a caller
falls back to reporting no commit information.
"""

from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path

_TIMEOUT_SECONDS = 5


def find_git_root(path: Path) -> Path | None:
    """Return the nearest directory at or above path that holds a .git entry."""
    current = path.resolve()
    while current != current.parent:
        if (current / ".git").exists():
            return current
        current = current.parent
    return None


def run_git(git_root: Path, *args: str) -> str | None:
    """Run git with args in git_root; return its stripped stdout, or None on failure."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=git_root,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def is_modified(git_root: Path) -> bool | None:
    """True if the work tree has uncommitted changes; None if git cannot tell."""
    status = run_git(git_root, "status", "--porcelain")
    return None if status is None else bool(status)


def head_commit(git_root: Path) -> tuple[str, str, datetime | None] | None:
    """Return HEAD's full hash, subject and commit time; None if there is no commit."""
    commit_full = run_git(git_root, "rev-parse", "HEAD")
    if not commit_full:
        return None
    message = run_git(git_root, "log", "-1", "--format=%s") or ""
    return commit_full, message, _commit_time(git_root)


def _commit_time(git_root: Path) -> datetime | None:
    """Return HEAD's commit time, or None if git or the timestamp fails."""
    time_str = run_git(git_root, "log", "-1", "--format=%cI")
    if not time_str:
        return None
    try:
        return datetime.fromisoformat(time_str)
    except ValueError:
        return None
