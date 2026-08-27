# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Reusable setup.py hook for build-time version tracking.

Two approaches are available:

1. **Standalone setup.py (recommended)** - Works with PEP 517 build isolation:

    # Generate with CLI:
    appinfra version init-hook mypackage --output setup.py

    # Or programmatically:
    from appinfra.version.setup_hook import generate_standalone_setup
    print(generate_standalone_setup("mypackage"))

2. **Import-based** - Requires appinfra installed in build environment:

    # setup.py
    from appinfra.version.setup_hook import make_build_py_class
    from setuptools import setup

    setup(cmdclass={"build_py": make_build_py_class("mypackage")})

    Note: This approach fails with standard `pip install .` due to build isolation.
    Use `pip install --no-build-isolation .` or the standalone approach instead.

Both approaches write to the build directory (not source), keeping the repo clean.
Source should contain a stub _build_info.py with empty values.
"""

import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

_BUILD_INFO_TEMPLATE = '''\
"""Build information - auto-generated during install, do not edit."""

COMMIT_HASH = "{commit_full}"
COMMIT_SHORT = "{commit_short}"
COMMIT_MESSAGE = "{commit_message}"
BUILD_TIME = "{build_time}"
MODIFIED = {modified}
'''

_STUB_TEMPLATE = '''\
"""Build information - auto-generated during install, do not edit."""

# Stub values - populated during pip install by setup.py hook
COMMIT_HASH = ""
COMMIT_SHORT = ""
COMMIT_MESSAGE = ""
BUILD_TIME = ""
MODIFIED = None
'''


def _run_git(*args: str, cwd: Path | None = None) -> str | None:
    """Run git command and return stdout, or None on failure."""
    try:
        result = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=cwd,
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return None


def _get_git_info(cwd: Path | None = None) -> tuple[str, str, str, bool] | None:
    """Get current git commit hash, message, and dirty status."""
    full = _run_git("rev-parse", "HEAD", cwd=cwd)
    if not full:
        return None

    short = full[:7]
    message = _run_git("log", "-1", "--format=%s", cwd=cwd) or ""
    status = _run_git("status", "--porcelain", cwd=cwd)
    modified = bool(status) if status is not None else False

    return full, short, message, modified


def _generate_build_info(package_dir: Path, cwd: Path | None = None) -> bool:
    """Generate _build_info.py in the given package directory."""
    git_info = _get_git_info(cwd)
    if not git_info:
        print(
            "appinfra: git info not available, skipping _build_info.py",
            file=sys.stderr,
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


def make_build_py_class(package_name: str) -> type:
    """
    Create a custom build_py class that generates _build_info.py during build.

    This writes to the build directory (not source), so the source repo
    stays clean with stub values.

    Args:
        package_name: Name of the package directory (e.g., "mypackage")

    Returns:
        A build_py subclass to use in setup(cmdclass={"build_py": ...})

    Example:
        from appinfra.version.setup_hook import make_build_py_class
        from setuptools import setup

        setup(cmdclass={"build_py": make_build_py_class("mypackage")})
    """
    from setuptools.command.build_py import build_py

    class BuildPyWithBuildInfo(build_py):
        """Custom build_py that generates _build_info.py in the build directory."""

        def run(self) -> None:
            """Run normal build, then generate build info in build directory."""
            # First, run the normal build (copies files to build_lib)
            super().run()

            # Then generate _build_info.py in the build directory
            # This way we don't modify the source files
            if self.build_lib:
                build_package_dir = Path(self.build_lib) / package_name
                if build_package_dir.is_dir():
                    _generate_build_info(build_package_dir)

    return BuildPyWithBuildInfo


def get_stub_content() -> str:
    """
    Get the content for a stub _build_info.py file.

    Use this to create the initial stub file in your package:

        from appinfra.version.setup_hook import get_stub_content
        print(get_stub_content())

    Or via CLI:
        python -c "from appinfra.version.setup_hook import get_stub_content; print(get_stub_content())"
    """
    return _STUB_TEMPLATE


# =============================================================================
# Standalone setup.py generation (works with PEP 517 build isolation)
# =============================================================================

_STANDALONE_SETUP_TEMPLATE = '''\
"""
Setup script with build-time version tracking.

Generated by: appinfra version init-hook
This file is self-contained - no appinfra imports needed at build time.

The build hook automatically populates _build_info.py with git commit info
during `pip install`, writing to the build directory (not source).
"""
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py

PACKAGE_NAME = "{package_name}"


def _run_git(*args):
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


def _get_git_info():
    """Get current git commit hash, message, and dirty status."""
    full = _run_git("rev-parse", "HEAD")
    if not full:
        return None
    short = full[:7]
    message = _run_git("log", "-1", "--format=%s") or ""
    status = _run_git("status", "--porcelain")
    modified = bool(status) if status is not None else False
    return full, short, message, modified


def _generate_build_info(package_dir):
    """Generate _build_info.py in the given package directory."""
    git_info = _get_git_info()
    if not git_info:
        print("build-hook: git info not available, skipping _build_info.py", file=sys.stderr)
        return False

    commit_full, commit_short, commit_message, modified = git_info
    build_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Escape special characters in commit message
    escaped_message = commit_message.replace("\\\\", "\\\\\\\\").replace(\'"\', \'\\\\"\')

    content = f\'\'\'"""Build information - auto-generated during install, do not edit."""

COMMIT_HASH = "{{commit_full}}"
COMMIT_SHORT = "{{commit_short}}"
COMMIT_MESSAGE = "{{escaped_message}}"
BUILD_TIME = "{{build_time}}"
MODIFIED = {{modified}}
\'\'\'

    build_info_path = package_dir / "_build_info.py"
    build_info_path.write_text(content)
    print(f"build-hook: generated _build_info.py ({{commit_short}})", file=sys.stderr)
    return True


class BuildPyWithBuildInfo(build_py):
    """Custom build_py that generates _build_info.py in the build directory."""

    def run(self):
        """Run normal build, then generate build info in build directory."""
        super().run()
        if self.build_lib:
            build_package_dir = Path(self.build_lib) / PACKAGE_NAME
            if build_package_dir.is_dir():
                _generate_build_info(build_package_dir)


setup(cmdclass={{"build_py": BuildPyWithBuildInfo}})
'''


def generate_standalone_setup(package_name: str) -> str:
    """
    Generate a self-contained setup.py with build-time version tracking.

    The generated setup.py has NO appinfra imports - it's fully standalone
    and works with PEP 517 build isolation (standard `pip install .`).

    Args:
        package_name: Name of the package directory (e.g., "mypackage")

    Returns:
        Complete setup.py content as a string

    Example:
        # Generate and write to file
        content = generate_standalone_setup("mypackage")
        Path("setup.py").write_text(content)

        # Or use CLI:
        # appinfra version init-hook mypackage --output setup.py
    """
    return _STANDALONE_SETUP_TEMPLATE.format(package_name=package_name)
