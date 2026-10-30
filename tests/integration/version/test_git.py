# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for appinfra/version/git.py."""

import subprocess
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from appinfra.version.git import find_git_root, head_commit, is_modified, run_git


@pytest.mark.integration
class TestFindGitRoot:
    """Test find_git_root()."""

    def test_traverses_parents(self, tmp_path):
        (tmp_path / ".git").mkdir()
        nested = tmp_path / "a" / "b" / "c"
        nested.mkdir(parents=True)

        assert find_git_root(nested) == tmp_path.resolve()

    def test_none_without_git(self, tmp_path):
        assert find_git_root(tmp_path) is None


@pytest.mark.integration
class TestRunGit:
    """Test run_git()."""

    @patch("subprocess.run")
    def test_returns_stripped_stdout(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(returncode=0, stdout="output\n")

        assert run_git(tmp_path, "status") == "output"
        assert mock_run.call_args.args[0] == ["git", "status"]

    @patch("subprocess.run")
    def test_none_on_nonzero_exit(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(returncode=1)
        assert run_git(tmp_path, "status") is None

    @pytest.mark.parametrize(
        "error",
        [subprocess.SubprocessError("error"), FileNotFoundError("git not found")],
    )
    def test_none_when_git_cannot_run(self, tmp_path, error):
        with patch("subprocess.run", side_effect=error):
            assert run_git(tmp_path, "status") is None


@pytest.mark.integration
class TestIsModified:
    """Test is_modified()."""

    @pytest.mark.parametrize(("stdout", "expected"), [(" M a.py\n", True), ("", False)])
    @patch("subprocess.run")
    def test_reports_the_work_tree(self, mock_run, tmp_path, stdout, expected):
        mock_run.return_value = MagicMock(returncode=0, stdout=stdout)
        assert is_modified(tmp_path) is expected

    @patch("subprocess.run", side_effect=subprocess.SubprocessError("error"))
    def test_none_when_git_fails(self, mock_run, tmp_path):
        assert is_modified(tmp_path) is None


@pytest.mark.integration
class TestHeadCommit:
    """Test head_commit()."""

    @patch("appinfra.version.git.run_git")
    def test_hash_subject_and_time(self, mock_run_git, tmp_path):
        mock_run_git.side_effect = ["abc123", "Fix bug", "2025-12-01T10:30:00+00:00"]

        commit_full, message, commit_time = head_commit(tmp_path)

        assert (commit_full, message) == ("abc123", "Fix bug")
        assert commit_time == datetime.fromisoformat("2025-12-01T10:30:00+00:00")

    @patch("appinfra.version.git.run_git", return_value=None)
    def test_none_without_a_commit(self, mock_run_git, tmp_path):
        assert head_commit(tmp_path) is None

    @patch("appinfra.version.git.run_git")
    def test_missing_subject_and_bad_time(self, mock_run_git, tmp_path):
        mock_run_git.side_effect = ["abc123", None, "invalid"]
        assert head_commit(tmp_path) == ("abc123", "", None)
