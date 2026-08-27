# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Custom setup.py to generate _build_info.py during build.

Works alongside pyproject.toml - pyproject.toml provides the configuration,
this script just adds the build-time code generation hook.

The setuptools entry point (finalize_distribution_options) doesn't work for
a package's own build because entry points are loaded from already-installed
packages. This setup.py uses cmdclass to run the hook during our own build.
"""

import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py

_BUILD_INFO_TEMPLATE = '''\
"""Build information - auto-generated during install, do not edit."""

# Populated by setuptools hook during pip install or CI/CD build
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
            cwd=Path(__file__).parent,
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
        print(
            "appinfra: git info not available, skipping _build_info.py", file=sys.stderr
        )
        return False

    commit_full, commit_short, commit_message, modified = git_info
    build_time = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    escaped_message = commit_message.replace("\\", "\\\\").replace('"', '\\"')

    content = _BUILD_INFO_TEMPLATE.format(
        commit_full=commit_full,
        commit_short=commit_short,
        commit_message=escaped_message,
        build_time=build_time,
        modified=modified,
    )

    build_info_path = package_dir / "_build_info.py"
    build_info_path.write_text(content)
    print(f"appinfra: generated _build_info.py ({commit_short})", file=sys.stderr)
    return True


class BuildPyWithBuildInfo(build_py):
    """Custom build_py that generates _build_info.py in the build directory."""

    def run(self):
        """Run normal build, then generate build info in build directory."""
        # First, run the normal build (copies files to build_lib)
        super().run()

        # Then generate _build_info.py in the build directory
        # This way we don't modify the source files
        if self.build_lib:
            build_package_dir = Path(self.build_lib) / "appinfra"
            if build_package_dir.is_dir():
                _generate_build_info(build_package_dir)


setup(cmdclass={"build_py": BuildPyWithBuildInfo})
