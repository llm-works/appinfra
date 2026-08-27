# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Package version tracker.

This module provides the main interface for tracking version and commit
information across multiple packages.
"""

from __future__ import annotations

import importlib.metadata
from typing import TYPE_CHECKING

from .info import PackageVersionInfo
from .sources import BuildInfoSource, GitRuntimeSource, PEP610Source, VersionSource

if TYPE_CHECKING:
    pass


class PackageVersionTracker:
    """
    Track version information for multiple packages.

    Uses a chain of sources (PEP 610 first, then build info, then git runtime)
    to find commit information for each tracked package.

    Example:
        tracker = PackageVersionTracker()
        tracker.track("mylib", "otherlib")
        for name, info in tracker.get_all().items():
            print(f"{name}: {info.version} @ {info.commit}")
    """

    def __init__(self, sources: list[VersionSource] | None = None):
        """
        Initialize the tracker.

        Args:
            sources: Custom list of version sources. If None, uses default
                     chain: PEP610Source -> BuildInfoSource -> GitRuntimeSource
        """
        self._sources: list[VersionSource] = sources or [
            PEP610Source(),
            BuildInfoSource(),
            GitRuntimeSource(),
        ]
        self._tracked: dict[str, PackageVersionInfo] = {}

    def track(self, *package_names: str) -> PackageVersionTracker:
        """
        Add packages to track.

        Args:
            *package_names: Distribution names of packages to track

        Returns:
            Self for method chaining
        """
        for name in package_names:
            info = self._resolve_version(name)
            if info:
                self._tracked[name] = info
        return self

    def get_info(self, package_name: str) -> PackageVersionInfo | None:
        """
        Get version info for a specific package.

        Args:
            package_name: The distribution name of the package

        Returns:
            PackageVersionInfo if tracked, None otherwise
        """
        return self._tracked.get(package_name)

    def get_all(self) -> dict[str, PackageVersionInfo]:
        """
        Get all tracked package info.

        Returns:
            Dictionary mapping package names to their version info
        """
        return self._tracked.copy()

    def format_for_log(self) -> str:
        """
        Format version info for startup logging.

        Returns a compact single-line format suitable for log messages:
        "mylib=1.2.0@abc123f otherlib=2.0.0@def456a"
        """
        if not self._tracked:
            return ""

        parts = [info.format_short() for info in self._tracked.values()]
        return " ".join(sorted(parts))

    def format_for_version(self, app_name: str, app_version: str) -> str:
        """
        Format version info for --version output.

        Args:
            app_name: The application name
            app_version: The application version string

        Returns:
            Multi-line formatted string for display
        """
        lines = [f"{app_name} {app_version}"]

        if self._tracked:
            lines.append("")
            lines.append("Tracked packages:")

            # Calculate column widths for alignment
            max_name_len = max(len(name) for name in self._tracked)
            max_ver_len = max(len(info.version) for info in self._tracked.values())

            for name in sorted(self._tracked):
                info = self._tracked[name]
                line = f"  {name:<{max_name_len}}  {info.version:<{max_ver_len}}"
                if info.commit:
                    line += f" @ {info.commit}"
                if info.source_url:
                    line += f" ({info.source_url})"
                lines.append(line)

        return "\n".join(lines)

    def _resolve_version(self, package_name: str) -> PackageVersionInfo | None:
        """
        Resolve version info for a package using the source chain.

        Tries each source in order until one returns valid info.
        """
        for source in self._sources:
            info = source.get_info(package_name)
            if info:
                return info

        # No source found commit info, create basic version info
        try:
            dist = importlib.metadata.distribution(package_name)
            return PackageVersionInfo(
                name=package_name,
                version=dist.metadata["Version"] or "unknown",
                source_type=PackageVersionInfo.SOURCE_PIP,
            )
        except importlib.metadata.PackageNotFoundError:
            return None

    def __len__(self) -> int:
        """Return the number of tracked packages."""
        return len(self._tracked)

    def __contains__(self, package_name: str) -> bool:
        """Check if a package is being tracked."""
        return package_name in self._tracked
