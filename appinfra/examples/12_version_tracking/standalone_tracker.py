#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Standalone Version Tracker Example

Shows how to use PackageVersionTracker directly without the full
AppBuilder framework. Useful for libraries or simple scripts that
want to track package versions.

Run with:
    python standalone_tracker.py
"""

import sys
from pathlib import Path

# Add parent directory to path for running examples directly
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from appinfra.version import PackageVersionTracker


def _print_package_info(tracker: PackageVersionTracker) -> None:
    """Print detailed package information."""
    print("\n2. Package information:")
    print("-" * 60)
    for name, info in sorted(tracker.get_all().items()):
        commit_display = info.commit if info.commit else "(no commit info)"
        print(f"   {name:<15} {info.version:<12} {commit_display}")
        print(f"      Source: {info.source_type}")


def _print_formats(tracker: PackageVersionTracker) -> None:
    """Print log and version formats."""
    print("\n3. Log format (compact):")
    print(f"   {tracker.format_for_log()}")

    print("\n4. Version format (detailed):")
    version_output = tracker.format_for_version("myapp", "2.0.0")
    for line in version_output.split("\n"):
        print(f"   {line}")


def main() -> None:
    """Demonstrate standalone version tracking."""
    print("=" * 60)
    print("Standalone Package Version Tracker Demo")
    print("=" * 60)

    tracker = PackageVersionTracker()

    print("\n1. Tracking specific packages...")
    tracker.track("appinfra", "pip", "setuptools")
    print(f"   Tracked {len(tracker)} packages")

    _print_package_info(tracker)
    _print_formats(tracker)

    print("\n" + "=" * 60)
    print("Demo complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
