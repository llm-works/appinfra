#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Version Tracking Demo

Demonstrates the commit hash tracking framework that displays git commit
information for installed packages at startup and via --version.

Features shown:
1. Tracking specific packages explicitly
2. Startup logging of package versions
3. Enhanced --version output with commit hashes

Run with:
    python version_tracking_demo.py --help
    python version_tracking_demo.py --version
    python version_tracking_demo.py info
    python version_tracking_demo.py list
"""

import sys
from pathlib import Path

# Add parent directory to path for running examples directly
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from appinfra.app import AppBuilder
from appinfra.app.tools.base import Tool, ToolConfig
from appinfra.version import PackageVersionTracker


class InfoTool(Tool):
    """Display detailed version information for tracked packages."""

    def __init__(self, tracker: PackageVersionTracker) -> None:
        config = ToolConfig(
            name="info",
            aliases=["i"],
            help_text="Show detailed version info for all tracked packages",
        )
        super().__init__(config=config)
        self._tracker = tracker

    def run(self, **kwargs) -> int:
        """Display version info."""
        self.lg.info("Tracked Package Information")
        self.lg.info("-" * 40)

        for name, info in sorted(self._tracker.get_all().items()):
            self.lg.info(f"Package: {name}")
            self.lg.info(f"  Version:     {info.version}")
            self.lg.info(f"  Commit:      {info.commit or 'N/A'}")
            self.lg.info(f"  Commit Full: {info.commit_full or 'N/A'}")
            self.lg.info(f"  Source Type: {info.source_type}")
            self.lg.info(f"  Source URL:  {info.source_url or 'N/A'}")
            if info.build_time:
                self.lg.info(f"  Build Time:  {info.build_time}")
            self.lg.info("")

        return 0


class ListTool(Tool):
    """List all tracked packages in compact format."""

    def __init__(self, tracker: PackageVersionTracker) -> None:
        config = ToolConfig(
            name="list",
            aliases=["ls"],
            help_text="List tracked packages in compact format",
        )
        super().__init__(config=config)
        self._tracker = tracker

    def run(self, **kwargs) -> int:
        """List packages."""
        print("\nTracked Packages:")
        print("-" * 60)

        for name, info in sorted(self._tracker.get_all().items()):
            commit_str = f"@ {info.commit}" if info.commit else ""
            print(f"  {name:<20} {info.version:<10} {commit_str}")

        print(f"\nTotal: {len(self._tracker)} packages")
        return 0


def main() -> int:
    """Build and run the demo application."""
    # Create a tracker to share with tools (for displaying package info)
    tracker = PackageVersionTracker()
    tracker.track("appinfra")

    # Path to appinfra's _build_info.py (relative to repo root)
    build_info_path = (
        Path(__file__).parent.parent.parent.parent / "appinfra" / "_build_info.py"
    )

    # Build the application with version tracking
    app = (
        AppBuilder("version-demo")
        .with_description("Demonstrates commit hash tracking for packages")
        .version.with_semver("1.0.0")
        .with_build_info(build_info_path)  # This repo's commit
        .with_package("appinfra")  # Track appinfra package
        .done()
        .tools.with_tool(InfoTool(tracker))
        .with_tool(ListTool(tracker))
        .done()
        .with_standard_args(log_level=True, quiet=True)
        .build()
    )

    return app.main()


if __name__ == "__main__":
    sys.exit(main())
