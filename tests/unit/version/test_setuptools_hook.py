# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for the setuptools hook's git helpers, with git mocked.
"""

import subprocess
from unittest.mock import MagicMock, patch

from appinfra.version.setuptools_hook import _get_git_info, _run_git

# =============================================================================
# Test _get_git_info
# =============================================================================


class TestRunGit:
    """Test _run_git helper function."""

    @patch("subprocess.run")
    def test_returns_stdout_on_success(self, mock_run):
        """Test returns stdout when git succeeds."""
        mock_run.return_value = MagicMock(returncode=0, stdout="output\n")

        result = _run_git("status")
        assert result == "output"

    @patch("subprocess.run")
    def test_returns_none_on_failure(self, mock_run):
        """Test returns None when git fails."""
        mock_run.return_value = MagicMock(returncode=1)

        result = _run_git("status")
        assert result is None

    @patch("subprocess.run")
    def test_handles_subprocess_error(self, mock_run):
        """Test handles subprocess errors."""
        mock_run.side_effect = subprocess.SubprocessError("error")

        result = _run_git("status")
        assert result is None


class TestGetGitInfo:
    """Test _get_git_info function."""

    @patch("appinfra.version.setuptools_hook._run_git")
    def test_returns_commit_info(self, mock_run_git):
        """Test returns commit hash, message, and dirty status."""

        def run_side_effect(*args):
            if "rev-parse" in args:
                return "abc123def456789012345678901234567890abcd"
            if "--format=%s" in args:
                return "Test commit"
            if "--porcelain" in args:
                return ""  # Clean repo
            return None

        mock_run_git.side_effect = run_side_effect

        result = _get_git_info()

        assert result is not None
        full, short, message, modified = result
        assert full == "abc123def456789012345678901234567890abcd"
        assert short == "abc123d"
        assert message == "Test commit"
        assert modified is False

    @patch("appinfra.version.setuptools_hook._run_git")
    def test_returns_none_on_git_failure(self, mock_run_git):
        """Test returns None when git fails."""
        mock_run_git.return_value = None

        result = _get_git_info()
        assert result is None

    @patch("appinfra.version.setuptools_hook._run_git")
    def test_detects_dirty_repo(self, mock_run_git):
        """Test detects modified working directory."""

        def run_side_effect(*args):
            if "rev-parse" in args:
                return "abc123def456789012345678901234567890abcd"
            if "--format=%s" in args:
                return "Test commit"
            if "--porcelain" in args:
                return " M file.py"  # Modified file
            return None

        mock_run_git.side_effect = run_side_effect

        result = _get_git_info()

        assert result is not None
        _, _, _, modified = result
        assert modified is True
