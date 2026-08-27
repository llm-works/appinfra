# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Version information sources.

This module provides different strategies for obtaining commit information
from installed packages, using a chain-of-responsibility pattern.
"""

from __future__ import annotations

import importlib.machinery
import importlib.metadata
import importlib.util
import json
import subprocess
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .info import PackageVersionInfo


class VersionSource(ABC):
    """
    Abstract base class for version information sources.

    Each source attempts to retrieve version and commit information
    for a package using a specific strategy.
    """

    @abstractmethod
    def get_info(self, package_name: str) -> PackageVersionInfo | None:
        """
        Attempt to get version info for a package.

        Args:
            package_name: The distribution name of the package

        Returns:
            PackageVersionInfo if successful, None if this source can't provide info
        """
        ...


class PEP610Source(VersionSource):
    """
    Get version info from PEP 610 direct_url.json.

    When pip installs from a VCS URL (e.g., pip install git+https://...),
    it creates a direct_url.json file in the package's dist-info directory:

    {
        "url": "https://github.com/org/repo",
        "vcs_info": {
            "vcs": "git",
            "commit_id": "abc123def456..."
        }
    }

    This is the most reliable source for packages installed from git URLs.
    """

    def get_info(self, package_name: str) -> PackageVersionInfo | None:
        """Read version info from PEP 610 direct_url.json."""
        from .info import PackageVersionInfo

        try:
            dist = importlib.metadata.distribution(package_name)
        except importlib.metadata.PackageNotFoundError:
            return None

        data = self._read_direct_url(dist)
        if not data:
            return None

        commit_full = self._extract_git_commit(data)
        if not commit_full:
            return None

        source_url = data.get("url")
        return PackageVersionInfo(
            name=package_name,
            version=dist.metadata["Version"] or "unknown",
            commit_full=commit_full,
            source_url=source_url if isinstance(source_url, str) else None,
            source_type=PackageVersionInfo.SOURCE_PIP_GIT,
        )

    def _read_direct_url(
        self, dist: importlib.metadata.Distribution
    ) -> dict[str, object] | None:
        """Read and parse direct_url.json from distribution."""
        try:
            direct_url_text = dist.read_text("direct_url.json")
        except FileNotFoundError:
            return None

        if not direct_url_text:
            return None

        try:
            result = json.loads(direct_url_text)
            return result if isinstance(result, dict) else None
        except json.JSONDecodeError:
            return None

    def _extract_git_commit(self, data: dict[str, object]) -> str | None:
        """Extract git commit from VCS info if present."""
        vcs_info = data.get("vcs_info")
        if not isinstance(vcs_info, dict) or vcs_info.get("vcs") != "git":
            return None
        commit_id = vcs_info.get("commit_id")
        return commit_id if isinstance(commit_id, str) else None


class BuildInfoSource(VersionSource):
    """
    Get version info from _build_info.py module.

    Packages can opt into build-time commit capture by adding appinfra
    to their build dependencies. The setuptools plugin generates a
    _build_info.py file with:

    COMMIT_HASH = "abc123def456..."
    COMMIT_SHORT = "abc123f"
    BUILD_TIME = "2025-12-01T10:30:00Z"
    """

    def get_info(self, package_name: str) -> PackageVersionInfo | None:
        """Read version info from _build_info.py module."""

        try:
            dist = importlib.metadata.distribution(package_name)
        except importlib.metadata.PackageNotFoundError:
            return None

        result = self._import_build_info_module(dist, package_name)
        if not result:
            return None

        build_info, spec = result
        commit_full = getattr(build_info, "COMMIT_HASH", None)
        if not commit_full:
            return None

        return self._create_version_info(
            package_name, dist, build_info, commit_full, spec
        )

    def _import_build_info_module(
        self, dist: importlib.metadata.Distribution, package_name: str
    ) -> tuple[object, importlib.machinery.ModuleSpec | None] | None:
        """Find and import the _build_info module."""
        top_level = self._get_top_level_name(dist, package_name)
        if not top_level:
            return None

        build_info_module = f"{top_level}._build_info"
        try:
            spec = importlib.util.find_spec(build_info_module)
            if spec is None:
                return None
            return importlib.import_module(build_info_module), spec
        except Exception:
            return None

    def _create_version_info(
        self,
        package_name: str,
        dist: importlib.metadata.Distribution,
        build_info: object,
        commit_full: str,
        spec: importlib.machinery.ModuleSpec | None,
    ) -> PackageVersionInfo:
        """Create PackageVersionInfo from build_info module attributes."""
        from .info import PackageVersionInfo

        commit_short = getattr(build_info, "COMMIT_SHORT", None)
        commit_message = getattr(build_info, "COMMIT_MESSAGE", "") or ""
        build_time = self._parse_build_time(getattr(build_info, "BUILD_TIME", None))
        build_modified = getattr(build_info, "MODIFIED", None)

        package_path = None
        if spec and spec.origin:
            package_path = Path(spec.origin).parent

        return PackageVersionInfo(
            name=package_name,
            version=dist.metadata["Version"] or "unknown",
            commit=commit_short,
            commit_full=commit_full,
            message=commit_message,
            source_type=PackageVersionInfo.SOURCE_BUILD_INFO,
            build_time=build_time,
            _package_path=package_path,
            _build_modified=build_modified,
        )

    def _parse_build_time(self, build_time_str: str | None) -> datetime | None:
        """Parse ISO format build time string."""
        if not build_time_str:
            return None
        try:
            return datetime.fromisoformat(build_time_str.replace("Z", "+00:00"))
        except ValueError:
            return None

    def _get_top_level_name(
        self, dist: importlib.metadata.Distribution, package_name: str
    ) -> str | None:
        """Get the top-level module name for a distribution."""
        try:
            top_level_text = dist.read_text("top_level.txt")
            if top_level_text:
                return top_level_text.strip().split("\n")[0].strip()
        except FileNotFoundError:
            pass
        return package_name.replace("-", "_")


class GitRuntimeSource(VersionSource):
    """
    Get version info by running git commands at runtime.

    This is a fallback for:
    - Editable installs (pip install -e .)
    - Development environments where PEP 610 data doesn't exist

    Runs `git rev-parse HEAD` in the package's source directory.
    """

    def __init__(self, check_dirty: bool = False):
        """
        Initialize the git runtime source.

        Args:
            check_dirty: If True, also check if the working tree is dirty.
                         This adds overhead as it runs `git status`.
        """
        self._check_dirty = check_dirty

    def get_info(self, package_name: str) -> PackageVersionInfo | None:
        """Get version info by running git commands."""
        from .info import PackageVersionInfo

        try:
            dist = importlib.metadata.distribution(package_name)
        except importlib.metadata.PackageNotFoundError:
            return None

        package_path = self._find_package_path(dist, package_name)
        if not package_path:
            return None

        git_root = self._find_git_root(package_path)
        if not git_root:
            return None

        git_info = self._get_git_info(git_root)
        if not git_info:
            return None

        commit_full, commit_message, commit_time = git_info
        return PackageVersionInfo(
            name=package_name,
            version=dist.metadata["Version"] or "unknown",
            commit_full=commit_full,
            message=commit_message,
            source_type=PackageVersionInfo.SOURCE_EDITABLE_GIT,
            build_time=commit_time,
            _package_path=package_path,
        )

    def _get_git_info(self, git_root: Path) -> tuple[str, str, datetime | None] | None:
        """Get commit hash, message, and timestamp from git."""
        commit_full = self._get_commit_hash(git_root)
        if not commit_full:
            return None
        return (
            commit_full,
            self._get_commit_message(git_root),
            self._get_commit_time(git_root),
        )

    def _find_package_path(
        self, dist: importlib.metadata.Distribution, package_name: str
    ) -> Path | None:
        """Find the filesystem path of a package."""
        # Try importing the package and getting __file__ (most reliable)
        top_level = package_name.replace("-", "_")
        try:
            spec = importlib.util.find_spec(top_level)
            if spec and spec.origin:
                return Path(spec.origin).resolve().parent
        except (ImportError, ModuleNotFoundError):
            pass

        # Fallback: try to get the package location from dist files
        try:
            files = dist.files
            if files:
                for file in files:
                    # Look for __init__.py or a .py file
                    if file.name == "__init__.py" or file.suffix == ".py":
                        located = Path(file.locate()).resolve()
                        if located.exists():
                            return located.parent
        except Exception:
            pass

        return None

    def _find_git_root(self, path: Path) -> Path | None:
        """Find the git root directory containing the given path."""
        current = path
        while current != current.parent:
            if (current / ".git").exists():
                return current
            current = current.parent
        return None

    def _get_commit_hash(self, git_root: Path) -> str | None:
        """Get the current commit hash from a git repository."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=git_root,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except (subprocess.SubprocessError, FileNotFoundError, OSError):
            # git not available or command failed
            pass
        return None

    def _get_commit_message(self, git_root: Path) -> str:
        """Get the current commit message from a git repository."""
        try:
            result = subprocess.run(
                ["git", "log", "-1", "--format=%s"],
                cwd=git_root,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except (subprocess.SubprocessError, FileNotFoundError, OSError):
            pass
        return ""

    def _get_commit_time(self, git_root: Path) -> datetime | None:
        """Get the current commit timestamp from a git repository."""
        try:
            result = subprocess.run(
                ["git", "log", "-1", "--format=%cI"],  # ISO 8601 format
                cwd=git_root,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                time_str = result.stdout.strip()
                return datetime.fromisoformat(time_str)
        except (subprocess.SubprocessError, FileNotFoundError, OSError, ValueError):
            pass
        return None
