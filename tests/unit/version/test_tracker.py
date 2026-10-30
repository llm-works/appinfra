# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for PackageVersionTracker.

Tests the main version tracking interface including:
- Package tracking
- Source chain resolution
- Output formatting
"""

from unittest.mock import patch

import pytest

from appinfra.version.info import PackageVersionInfo
from appinfra.version.sources import VersionSource
from appinfra.version.tracker import PackageVersionTracker

# =============================================================================
# Mock Source for Testing
# =============================================================================


class MockSource(VersionSource):
    """Mock version source for testing."""

    def __init__(self, packages: dict[str, PackageVersionInfo | None]):
        self._packages = packages

    def get_info(self, package_name: str) -> PackageVersionInfo | None:
        return self._packages.get(package_name)


# =============================================================================
# Test PackageVersionTracker Initialization
# =============================================================================


@pytest.mark.unit
class TestPackageVersionTrackerInit:
    """Test PackageVersionTracker initialization."""

    def test_default_initialization(self):
        """Test default initialization creates standard sources."""
        tracker = PackageVersionTracker()

        assert len(tracker._sources) == 3
        assert len(tracker) == 0

    def test_custom_sources(self):
        """Test initialization with custom sources."""
        mock_source = MockSource({})
        tracker = PackageVersionTracker(sources=[mock_source])

        assert len(tracker._sources) == 1
        assert tracker._sources[0] is mock_source


# =============================================================================
# Test Package Tracking
# =============================================================================


@pytest.mark.unit
class TestPackageTracking:
    """Test package tracking functionality."""

    def test_track_single_package(self):
        """Test tracking a single package."""
        info = PackageVersionInfo(
            name="mylib",
            version="1.0.0",
            commit="abc123f",
            commit_full="abc123f" + "0" * 33,
        )
        source = MockSource({"mylib": info})
        tracker = PackageVersionTracker(sources=[source])

        tracker.track("mylib")

        assert len(tracker) == 1
        assert "mylib" in tracker
        assert tracker.get_info("mylib") == info

    def test_track_multiple_packages(self):
        """Test tracking multiple packages."""
        info1 = PackageVersionInfo(name="lib1", version="1.0.0")
        info2 = PackageVersionInfo(name="lib2", version="2.0.0")
        source = MockSource({"lib1": info1, "lib2": info2})
        tracker = PackageVersionTracker(sources=[source])

        tracker.track("lib1", "lib2")

        assert len(tracker) == 2
        assert "lib1" in tracker
        assert "lib2" in tracker

    def test_track_returns_self(self):
        """Test track() returns self for chaining."""
        source = MockSource({})
        tracker = PackageVersionTracker(sources=[source])

        result = tracker.track("pkg")

        assert result is tracker

    def test_track_ignores_unresolvable_packages(self):
        """Test tracking ignores packages that can't be resolved."""
        source = MockSource(
            {"exists": PackageVersionInfo(name="exists", version="1.0")}
        )
        tracker = PackageVersionTracker(sources=[source])

        tracker.track("exists", "missing")

        assert len(tracker) == 1
        assert "exists" in tracker
        assert "missing" not in tracker

    def test_get_info_returns_none_for_untracked(self):
        """Test get_info returns None for untracked packages."""
        tracker = PackageVersionTracker(sources=[MockSource({})])
        assert tracker.get_info("untracked") is None

    def test_get_all_returns_copy(self):
        """Test get_all returns a copy of tracked packages."""
        info = PackageVersionInfo(name="pkg", version="1.0.0")
        source = MockSource({"pkg": info})
        tracker = PackageVersionTracker(sources=[source])
        tracker.track("pkg")

        result = tracker.get_all()
        result["new"] = PackageVersionInfo(name="new", version="2.0.0")

        assert "new" not in tracker


# =============================================================================
# Test Source Chain Resolution
# =============================================================================


@pytest.mark.unit
class TestSourceChainResolution:
    """Test source chain resolution behavior."""

    def test_first_source_wins(self):
        """Test first source that returns info wins."""
        info1 = PackageVersionInfo(name="pkg", version="1.0.0", source_type="first")
        info2 = PackageVersionInfo(name="pkg", version="1.0.0", source_type="second")

        source1 = MockSource({"pkg": info1})
        source2 = MockSource({"pkg": info2})
        tracker = PackageVersionTracker(sources=[source1, source2])

        tracker.track("pkg")

        assert tracker.get_info("pkg").source_type == "first"

    def test_falls_through_to_next_source(self):
        """Test falls through when first source returns None."""
        info = PackageVersionInfo(name="pkg", version="1.0.0", source_type="second")

        source1 = MockSource({"pkg": None})
        source2 = MockSource({"pkg": info})
        tracker = PackageVersionTracker(sources=[source1, source2])

        tracker.track("pkg")

        assert tracker.get_info("pkg").source_type == "second"

    @patch("importlib.metadata.distribution")
    def test_creates_basic_info_when_no_source_matches(self, mock_dist):
        """Test creates basic info when no source returns commit info."""
        mock_dist.return_value.metadata = {"Version": "1.0.0"}

        tracker = PackageVersionTracker(sources=[MockSource({})])
        tracker.track("pip")

        info = tracker.get_info("pip")
        assert info is not None
        assert info.version == "1.0.0"
        assert info.source_type == PackageVersionInfo.SOURCE_PIP


# =============================================================================
# Test Output Formatting
# =============================================================================


@pytest.mark.unit
class TestFormatForLog:
    """Test format_for_log() output."""

    def test_empty_tracker(self):
        """Test format_for_log with no tracked packages."""
        tracker = PackageVersionTracker(sources=[MockSource({})])
        assert tracker.format_for_log() == ""

    def test_single_package(self):
        """Test format_for_log with single package."""
        info = PackageVersionInfo(name="mylib", version="1.0.0", commit="abc123f")
        tracker = PackageVersionTracker(sources=[MockSource({"mylib": info})])
        tracker.track("mylib")

        result = tracker.format_for_log()
        assert result == "mylib=1.0.0@abc123f"

    def test_multiple_packages_sorted(self):
        """Test format_for_log sorts packages alphabetically."""
        info1 = PackageVersionInfo(name="zlib", version="1.0.0", commit="aaa")
        info2 = PackageVersionInfo(name="alib", version="2.0.0", commit="bbb")
        tracker = PackageVersionTracker(
            sources=[MockSource({"zlib": info1, "alib": info2})]
        )
        tracker.track("zlib", "alib")

        result = tracker.format_for_log()
        assert result == "alib=2.0.0@bbb zlib=1.0.0@aaa"


@pytest.mark.unit
class TestFormatForVersion:
    """Test format_for_version() output."""

    def test_empty_tracker(self):
        """Test format_for_version with no tracked packages."""
        tracker = PackageVersionTracker(sources=[MockSource({})])
        result = tracker.format_for_version("myapp", "1.0.0")
        assert result == "myapp 1.0.0"

    def test_with_tracked_packages(self):
        """Test format_for_version with tracked packages."""
        info = PackageVersionInfo(
            name="mylib",
            version="1.2.0",
            commit="abc123f",
            source_url="git+https://github.com/org/mylib",
        )
        tracker = PackageVersionTracker(sources=[MockSource({"mylib": info})])
        tracker.track("mylib")

        result = tracker.format_for_version("myapp", "1.0.0")

        assert "myapp 1.0.0" in result
        assert "Tracked packages:" in result
        assert "mylib" in result
        assert "1.2.0" in result
        assert "abc123f" in result
        assert "git+https://github.com/org/mylib" in result

    def test_aligns_columns(self):
        """Test format_for_version aligns columns."""
        info1 = PackageVersionInfo(name="short", version="1.0.0")
        info2 = PackageVersionInfo(name="verylongname", version="2.0.0")
        tracker = PackageVersionTracker(
            sources=[MockSource({"short": info1, "verylongname": info2})]
        )
        tracker.track("short", "verylongname")

        result = tracker.format_for_version("app", "1.0")
        lines = result.split("\n")

        # Both package lines should have same column alignment
        pkg_lines = [
            line for line in lines if "short" in line or "verylongname" in line
        ]
        assert len(pkg_lines) == 2


# =============================================================================
# Test Dunder Methods
# =============================================================================


@pytest.mark.unit
class TestDunderMethods:
    """Test __len__ and __contains__ methods."""

    def test_len_empty(self):
        """Test __len__ with empty tracker."""
        tracker = PackageVersionTracker(sources=[MockSource({})])
        assert len(tracker) == 0

    def test_len_with_packages(self):
        """Test __len__ with tracked packages."""
        info = PackageVersionInfo(name="pkg", version="1.0.0")
        tracker = PackageVersionTracker(sources=[MockSource({"pkg": info})])
        tracker.track("pkg")
        assert len(tracker) == 1

    def test_contains_tracked(self):
        """Test __contains__ returns True for tracked packages."""
        info = PackageVersionInfo(name="pkg", version="1.0.0")
        tracker = PackageVersionTracker(sources=[MockSource({"pkg": info})])
        tracker.track("pkg")
        assert "pkg" in tracker

    def test_contains_untracked(self):
        """Test __contains__ returns False for untracked packages."""
        tracker = PackageVersionTracker(sources=[MockSource({})])
        assert "pkg" not in tracker
