# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Build info generator for git hooks.

Run this before commit to update _build_info.py in a package:

    python -m appinfra.version.build_info mypackage/

Or from a git pre-commit hook:

    #!/bin/sh
    python -m appinfra.version.build_info mypackage/
    git add mypackage/_build_info.py
"""

import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

_TEMPLATE = '''\
"""Build information - auto-generated, do not edit."""

COMMIT_HASH = "{commit_full}"
COMMIT_SHORT = "{commit_short}"
COMMIT_MESSAGE = "{commit_message}"
BUILD_TIME = "{build_time}"
MODIFIED = {modified}
'''


def _run_git(*args: str) -> str | None:
    """Run a git command and return stripped stdout, or None on failure."""
    try:
        result = subprocess.run(
            ["git", *args], capture_output=True, text=True, timeout=5
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return None


def get_git_commit() -> tuple[str, str, str, bool] | None:
    """Get current git commit hash, message, and dirty status."""
    full = _run_git("rev-parse", "HEAD")
    if not full:
        return None

    short = full[:7]
    message = _run_git("log", "-1", "--format=%s") or ""
    status = _run_git("status", "--porcelain")
    modified = bool(status) if status is not None else False

    return full, short, message, modified


def generate(package_dir: Path) -> bool:
    """
    Generate _build_info.py in the given package directory.

    Args:
        package_dir: Path to the package directory

    Returns:
        True if successful, False otherwise
    """
    commit = get_git_commit()
    if not commit:
        print("Not in a git repo or no commits", file=sys.stderr)
        return False

    commit_full, commit_short, commit_message, modified = commit
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
    print(f"Generated {build_info_path}")
    return True


def main() -> int:
    """CLI entry point."""
    if len(sys.argv) < 2:
        print("Usage: python -m appinfra.version.build_info <package_dir>")
        return 1

    package_dir = Path(sys.argv[1])
    if not package_dir.is_dir():
        print(f"Not a directory: {package_dir}", file=sys.stderr)
        return 1

    return 0 if generate(package_dir) else 1


if __name__ == "__main__":
    sys.exit(main())
