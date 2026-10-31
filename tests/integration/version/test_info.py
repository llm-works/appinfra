# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for BuildInfo that read build info files and probe directories for git.
"""

from unittest.mock import patch

from appinfra.version.info import BuildInfo


class TestBuildInfoFromPath:
    """Test BuildInfo.from_path() method."""

    def test_from_path_with_missing_file(self, tmp_path):
        """Test from_path with missing file falls back to git."""
        # No git repo, so returns None
        result = BuildInfo.from_path(tmp_path / "_build_info.py")
        assert result is None

    def test_from_path_with_empty_stub(self, tmp_path):
        """Test from_path with empty stub falls back to git."""
        stub = tmp_path / "_build_info.py"
        stub.write_text('COMMIT_HASH = ""\nCOMMIT_SHORT = ""\n')

        result = BuildInfo.from_path(stub)
        # No git repo, so returns None
        assert result is None

    def test_from_path_with_valid_file(self, tmp_path):
        """Test from_path reads valid build info."""
        build_info = tmp_path / "_build_info.py"
        build_info.write_text(
            """
COMMIT_HASH = "abc123def456789012345678901234567890abcd"
COMMIT_SHORT = "abc123d"
COMMIT_MESSAGE = "Test commit"
BUILD_TIME = "2025-12-01T10:30:00Z"
"""
        )

        result = BuildInfo.from_path(build_info)

        assert result is not None
        assert result.commit == "abc123d"
        assert result.commit_full == "abc123def456789012345678901234567890abcd"
        assert result.message == "Test commit"
        assert result.build_time is not None

    def test_from_path_with_no_short_commit(self, tmp_path):
        """Test from_path derives short commit from full."""
        build_info = tmp_path / "_build_info.py"
        build_info.write_text(
            """
COMMIT_HASH = "abc123def456789012345678901234567890abcd"
COMMIT_SHORT = ""
"""
        )

        result = BuildInfo.from_path(build_info)

        assert result is not None
        assert result.commit == "abc123d"

    def test_from_path_with_invalid_build_time(self, tmp_path):
        """Test from_path handles invalid build time."""
        build_info = tmp_path / "_build_info.py"
        build_info.write_text(
            """
COMMIT_HASH = "abc123def456789012345678901234567890abcd"
COMMIT_SHORT = "abc123d"
BUILD_TIME = "invalid-time"
"""
        )

        result = BuildInfo.from_path(build_info)

        assert result is not None
        assert result.build_time is None


class TestBuildInfoGitRuntime:
    """Test BuildInfo git runtime detection."""

    @patch("appinfra.version.git.run_git")
    def test_from_git_runtime_success(self, mock_run_git, tmp_path):
        """Test _from_git_runtime with successful git commands."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()

        mock_run_git.side_effect = [
            "abc123def456789012345678901234567890abcd",  # rev-parse HEAD
            "Test commit message",  # log --format=%s
            "2025-12-01T10:30:00+00:00",  # log --format=%cI
        ]

        result = BuildInfo._from_git_runtime(tmp_path)

        assert result is not None
        assert result.commit == "abc123d"
        assert result.commit_full == "abc123def456789012345678901234567890abcd"
        assert result.message == "Test commit message"
        assert result.build_time is not None

    def test_from_git_runtime_no_git_repo(self, tmp_path):
        """Test _from_git_runtime returns None without git repo."""
        result = BuildInfo._from_git_runtime(tmp_path)
        assert result is None

    @patch("appinfra.version.git.run_git")
    def test_from_git_runtime_git_fails(self, mock_run_git, tmp_path):
        """Test _from_git_runtime handles git failure."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()

        mock_run_git.return_value = None  # git command fails

        result = BuildInfo._from_git_runtime(tmp_path)
        assert result is None


class TestBuildInfoFromPathException:
    """Test BuildInfo.from_path exception handling."""

    def test_from_path_with_invalid_python(self, tmp_path):
        """Test from_path falls back to git when file has invalid Python."""
        build_info = tmp_path / "_build_info.py"
        build_info.write_text("this is not valid python {{{")

        result = BuildInfo.from_path(build_info)
        # Falls back to git runtime, which returns None (no git repo)
        assert result is None
