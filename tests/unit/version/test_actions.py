# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for version argparse actions.

Tests the custom argparse action for enhanced --version output.
"""

import argparse
from unittest.mock import MagicMock

import pytest

from appinfra.version.actions import VersionWithTrackerAction

# =============================================================================
# Test VersionWithTrackerAction
# =============================================================================


@pytest.mark.unit
class TestVersionWithTrackerAction:
    """Test VersionWithTrackerAction argparse action."""

    def test_init_defaults(self):
        """Test action initializes with defaults."""
        action = VersionWithTrackerAction(
            option_strings=["--version"],
        )

        assert action.app_name == "app"
        assert action.app_version == "0.0.0"
        assert action.tracker is None

    def test_init_with_values(self):
        """Test action initializes with provided values."""
        tracker = MagicMock()
        build_info = MagicMock()
        action = VersionWithTrackerAction(
            option_strings=["--version"],
            app_name="myapp",
            app_version="1.2.3",
            tracker=tracker,
            build_info=build_info,
        )

        assert action.app_name == "myapp"
        assert action.app_version == "1.2.3"
        assert action.tracker is tracker
        assert action.build_info is build_info

    def test_call_without_tracker(self, capsys):
        """Test action output without tracker."""
        parser = argparse.ArgumentParser()
        action = VersionWithTrackerAction(
            option_strings=["--version"],
            app_name="myapp",
            app_version="1.0.0",
        )

        with pytest.raises(SystemExit):
            action(parser, argparse.Namespace(), None)

        captured = capsys.readouterr()
        assert "myapp 1.0.0" in captured.out

    def test_call_with_empty_tracker(self, capsys):
        """Test action output with empty tracker."""
        parser = argparse.ArgumentParser()
        tracker = MagicMock()
        tracker.__len__ = MagicMock(return_value=0)

        action = VersionWithTrackerAction(
            option_strings=["--version"],
            app_name="myapp",
            app_version="1.0.0",
            tracker=tracker,
        )

        with pytest.raises(SystemExit):
            action(parser, argparse.Namespace(), None)

        captured = capsys.readouterr()
        assert "myapp 1.0.0" in captured.out

    def test_call_with_tracked_packages(self, capsys):
        """Test action output with tracked packages."""
        parser = argparse.ArgumentParser()

        # Create mock package info
        mock_info = MagicMock()
        mock_info.version = "1.2.0"
        mock_info.commit = "abc123f"
        mock_info.source_url = None

        # Create a mock tracker
        tracker = MagicMock()
        tracker.__len__ = MagicMock(return_value=1)
        tracker.get_all.return_value = {"mylib": mock_info}

        action = VersionWithTrackerAction(
            option_strings=["--version"],
            app_name="myapp",
            app_version="1.0.0",
            tracker=tracker,
        )

        with pytest.raises(SystemExit):
            action(parser, argparse.Namespace(), None)

        captured = capsys.readouterr()
        assert "myapp 1.0.0" in captured.out
        assert "Tracked packages:" in captured.out
        assert "mylib" in captured.out
        assert "1.2.0" in captured.out
        assert "abc123f" in captured.out

    def test_call_with_build_info(self, capsys):
        """Test action output with build_info shows commit hash."""
        parser = argparse.ArgumentParser()

        build_info = MagicMock()
        build_info.commit = "abc123f"
        build_info.modified = False

        action = VersionWithTrackerAction(
            option_strings=["--version"],
            app_name="myapp",
            app_version="1.0.0",
            build_info=build_info,
        )

        with pytest.raises(SystemExit):
            action(parser, argparse.Namespace(), None)

        captured = capsys.readouterr()
        assert "myapp 1.0.0 (abc123f)" in captured.out

    def test_call_with_build_info_modified(self, capsys):
        """Test action output with modified build shows asterisk."""
        parser = argparse.ArgumentParser()

        build_info = MagicMock()
        build_info.commit = "abc123f"
        build_info.modified = True

        action = VersionWithTrackerAction(
            option_strings=["--version"],
            app_name="myapp",
            app_version="1.0.0",
            build_info=build_info,
        )

        with pytest.raises(SystemExit):
            action(parser, argparse.Namespace(), None)

        captured = capsys.readouterr()
        assert "myapp 1.0.0 (abc123f*)" in captured.out

    def test_call_with_build_info_no_commit(self, capsys):
        """Test action output with build_info but no commit."""
        parser = argparse.ArgumentParser()

        build_info = MagicMock()
        build_info.commit = None

        action = VersionWithTrackerAction(
            option_strings=["--version"],
            app_name="myapp",
            app_version="1.0.0",
            build_info=build_info,
        )

        with pytest.raises(SystemExit):
            action(parser, argparse.Namespace(), None)

        captured = capsys.readouterr()
        assert "myapp 1.0.0" in captured.out
        assert "(" not in captured.out

    def test_call_with_build_info_and_tracker(self, capsys):
        """Test action output with both build_info and tracked packages."""
        parser = argparse.ArgumentParser()

        build_info = MagicMock()
        build_info.commit = "abc123f"
        build_info.modified = False

        mock_info = MagicMock()
        mock_info.version = "2.0.0"
        mock_info.commit = "def456a"
        mock_info.source_url = None

        tracker = MagicMock()
        tracker.__len__ = MagicMock(return_value=1)
        tracker.get_all.return_value = {"otherlib": mock_info}

        action = VersionWithTrackerAction(
            option_strings=["--version"],
            app_name="myapp",
            app_version="1.0.0",
            build_info=build_info,
            tracker=tracker,
        )

        with pytest.raises(SystemExit):
            action(parser, argparse.Namespace(), None)

        captured = capsys.readouterr()
        assert "myapp 1.0.0 (abc123f)" in captured.out
        assert "Tracked packages:" in captured.out
        assert "otherlib" in captured.out
        assert "def456a" in captured.out

    def test_call_with_source_url(self, capsys):
        """Test action output includes source_url when present."""
        parser = argparse.ArgumentParser()

        mock_info = MagicMock()
        mock_info.version = "1.2.0"
        mock_info.commit = "abc123f"
        mock_info.source_url = "git+https://github.com/org/mylib"

        tracker = MagicMock()
        tracker.__len__ = MagicMock(return_value=1)
        tracker.get_all.return_value = {"mylib": mock_info}

        action = VersionWithTrackerAction(
            option_strings=["--version"],
            app_name="myapp",
            app_version="1.0.0",
            tracker=tracker,
        )

        with pytest.raises(SystemExit):
            action(parser, argparse.Namespace(), None)

        captured = capsys.readouterr()
        assert (
            "mylib 1.2.0 (abc123f) (git+https://github.com/org/mylib)" in captured.out
        )

    def test_integrated_with_argparse(self, capsys):
        """Test action works when integrated with argparse."""
        parser = argparse.ArgumentParser(prog="testapp")
        parser.add_argument(
            "--version",
            action=VersionWithTrackerAction,
            app_name="testapp",
            app_version="2.0.0",
        )

        with pytest.raises(SystemExit):
            parser.parse_args(["--version"])

        captured = capsys.readouterr()
        assert "testapp 2.0.0" in captured.out
