"""
Tests for build_info CLI tool.

Tests the git commit info generator used by git hooks and CI/CD.
"""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from appinfra.version.build_info import _run_git, generate, get_git_commit, main

# =============================================================================
# Test _run_git
# =============================================================================


@pytest.mark.unit
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

    @patch("subprocess.run")
    def test_handles_file_not_found(self, mock_run):
        """Test handles missing git command."""
        mock_run.side_effect = FileNotFoundError("git not found")

        result = _run_git("status")
        assert result is None


# =============================================================================
# Test get_git_commit
# =============================================================================


@pytest.mark.unit
class TestGetGitCommit:
    """Test get_git_commit function."""

    @patch("appinfra.version.build_info._run_git")
    def test_returns_commit_info(self, mock_run_git):
        """Test returns commit hash, message, and dirty status."""

        def side_effect(*args):
            if "rev-parse" in args:
                return "abc123def456789012345678901234567890abcd"
            elif "--format=%s" in args:
                return "Test commit message"
            elif "--porcelain" in args:
                return " M file.py"
            return None

        mock_run_git.side_effect = side_effect

        result = get_git_commit()

        assert result is not None
        full, short, message, modified = result
        assert full == "abc123def456789012345678901234567890abcd"
        assert short == "abc123d"
        assert message == "Test commit message"
        assert modified is True

    @patch("appinfra.version.build_info._run_git")
    def test_returns_none_on_git_failure(self, mock_run_git):
        """Test returns None when git command fails."""
        mock_run_git.return_value = None

        result = get_git_commit()
        assert result is None

    @patch("appinfra.version.build_info._run_git")
    def test_handles_empty_commit_message(self, mock_run_git):
        """Test handles empty commit message."""

        def side_effect(*args):
            if "rev-parse" in args:
                return "abc123"
            elif "--format=%s" in args:
                return None  # message command fails
            elif "--porcelain" in args:
                return ""
            return None

        mock_run_git.side_effect = side_effect

        result = get_git_commit()
        assert result is not None
        _, _, message, modified = result
        assert message == ""
        assert modified is False

    @patch("appinfra.version.build_info._run_git")
    def test_clean_working_tree(self, mock_run_git):
        """Test modified is False when working tree is clean."""

        def side_effect(*args):
            if "rev-parse" in args:
                return "abc123"
            elif "--format=%s" in args:
                return "Clean commit"
            elif "--porcelain" in args:
                return ""
            return None

        mock_run_git.side_effect = side_effect

        result = get_git_commit()
        assert result is not None
        _, _, _, modified = result
        assert modified is False


# =============================================================================
# Test generate
# =============================================================================


@pytest.mark.unit
class TestGenerate:
    """Test generate function."""

    @patch("appinfra.version.build_info.get_git_commit")
    def test_generates_build_info_file(self, mock_get_commit, tmp_path):
        """Test generates _build_info.py file."""
        mock_get_commit.return_value = (
            "abc123def456789012345678901234567890abcd",
            "abc123d",
            "Test commit",
            True,
        )

        result = generate(tmp_path)

        assert result is True
        build_info = tmp_path / "_build_info.py"
        assert build_info.exists()
        content = build_info.read_text()
        assert 'COMMIT_HASH = "abc123def456789012345678901234567890abcd"' in content
        assert 'COMMIT_SHORT = "abc123d"' in content
        assert 'COMMIT_MESSAGE = "Test commit"' in content
        assert "BUILD_TIME" in content
        assert "MODIFIED = True" in content

    @patch("appinfra.version.build_info.get_git_commit")
    def test_returns_false_without_git(self, mock_get_commit, tmp_path):
        """Test returns False when not in git repo."""
        mock_get_commit.return_value = None

        result = generate(tmp_path)
        assert result is False

    @patch("appinfra.version.build_info.get_git_commit")
    def test_escapes_quotes_in_message(self, mock_get_commit, tmp_path):
        """Test escapes quotes in commit message."""
        mock_get_commit.return_value = (
            "abc123def456789012345678901234567890abcd",
            "abc123d",
            'Fix "bug" in code',
            False,
        )

        generate(tmp_path)

        content = (tmp_path / "_build_info.py").read_text()
        assert 'COMMIT_MESSAGE = "Fix \\"bug\\" in code"' in content

    @patch("appinfra.version.build_info.get_git_commit")
    def test_escapes_backslashes_in_message(self, mock_get_commit, tmp_path):
        """Test escapes backslashes in commit message."""
        mock_get_commit.return_value = (
            "abc123def456789012345678901234567890abcd",
            "abc123d",
            "Fix path\\to\\file",
            False,
        )

        generate(tmp_path)

        content = (tmp_path / "_build_info.py").read_text()
        assert 'COMMIT_MESSAGE = "Fix path\\\\to\\\\file"' in content


# =============================================================================
# Test main
# =============================================================================


@pytest.mark.unit
class TestMain:
    """Test main CLI entry point."""

    @patch("sys.argv", ["build_info"])
    def test_no_args_returns_1(self, capsys):
        """Test returns 1 with no arguments."""
        result = main()
        assert result == 1
        captured = capsys.readouterr()
        assert "Usage:" in captured.out

    @patch("sys.argv", ["build_info", "/nonexistent/path"])
    def test_invalid_path_returns_1(self, capsys):
        """Test returns 1 with invalid path."""
        result = main()
        assert result == 1
        captured = capsys.readouterr()
        assert "Not a directory" in captured.err

    @patch("appinfra.version.build_info.generate")
    @patch("sys.argv", ["build_info", "."])
    def test_success_returns_0(self, mock_generate):
        """Test returns 0 on success."""
        mock_generate.return_value = True
        result = main()
        assert result == 0

    @patch("appinfra.version.build_info.generate")
    @patch("sys.argv", ["build_info", "."])
    def test_failure_returns_1(self, mock_generate):
        """Test returns 1 on generate failure."""
        mock_generate.return_value = False
        result = main()
        assert result == 1
