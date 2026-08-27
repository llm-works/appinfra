# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Custom argparse actions for version display.

This module provides argparse actions that enhance --version output
with tracked package commit information.
"""

from __future__ import annotations

import argparse
import sys
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .info import BuildInfo
    from .tracker import PackageVersionTracker


class VersionWithTrackerAction(argparse.Action):
    """
    Custom argparse action for --version that includes tracked packages.

    Unlike the built-in 'version' action, this displays both the app
    version and commit information for all tracked packages.

    Example output:
        myapp 1.0.0 (abc123f)

        Tracked packages:
          mylib 1.2.0 (abc123f) (git+https://github.com/org/mylib)
          otherlib 2.0.0 (def456a)

    Usage:
        tracker = PackageVersionTracker()
        tracker.track("mylib")

        parser.add_argument(
            "--version",
            action=VersionWithTrackerAction,
            app_name="myapp",
            app_version="1.0.0",
            tracker=tracker,
            build_info=build_info,  # optional
        )
    """

    def __init__(
        self,
        option_strings: list[str],
        dest: str = argparse.SUPPRESS,
        default: Any = argparse.SUPPRESS,
        app_name: str = "app",
        app_version: str = "0.0.0",
        tracker: PackageVersionTracker | None = None,
        build_info: BuildInfo | None = None,
        **kwargs: Any,
    ):
        """
        Initialize the version action.

        Args:
            option_strings: Command-line option strings (e.g., ["--version"])
            dest: Destination attribute name (suppressed by default)
            default: Default value (suppressed by default)
            app_name: Application name to display
            app_version: Application version string
            tracker: PackageVersionTracker with tracked packages
            build_info: BuildInfo with app's own commit information
            **kwargs: Additional argparse.Action arguments
        """
        super().__init__(
            option_strings=option_strings,
            dest=dest,
            default=default,
            nargs=0,
            **kwargs,
        )
        self.app_name = app_name
        self.app_version = app_version
        self.tracker = tracker
        self.build_info = build_info

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: Any,
        option_string: str | None = None,
    ) -> None:
        """Display version information and exit."""
        version_str = self._format_version()
        print(version_str, file=sys.stdout)
        parser.exit()

    def _format_version(self) -> str:
        """Format version string with app info and tracked packages."""
        # Format app version line (with commit if available)
        app_line = self._format_app_line()

        # Add tracked packages if available
        if self.tracker and len(self.tracker) > 0:
            tracked_lines = self._format_tracked_packages()
            return f"{app_line}\n\n{tracked_lines}"

        return app_line

    def _format_app_line(self) -> str:
        """Format the main application version line."""
        if self.build_info and self.build_info.commit:
            dirty = "*" if self.build_info.modified else ""
            return (
                f"{self.app_name} {self.app_version} ({self.build_info.commit}{dirty})"
            )
        return f"{self.app_name} {self.app_version}"

    def _format_tracked_packages(self) -> str:
        """Format tracked packages section."""
        assert self.tracker is not None
        lines = ["Tracked packages:"]
        tracked = self.tracker.get_all()

        for name in sorted(tracked):
            info = tracked[name]
            line = f"  {name} {info.version}"
            if info.commit:
                line += f" ({info.commit})"
            if info.source_url:
                line += f" ({info.source_url})"
            lines.append(line)

        return "\n".join(lines)
