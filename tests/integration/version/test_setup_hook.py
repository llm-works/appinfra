# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for the setup_hook module that write _build_info.py files.
"""

from unittest.mock import patch

from appinfra.version.setup_hook import _generate_build_info

# =============================================================================
# Test _generate_build_info
# =============================================================================


class TestGenerateBuildInfo:
    """Test _generate_build_info function."""

    @patch("appinfra.version.setup_hook._get_git_info")
    def test_generates_file(self, mock_get_info, tmp_path):
        """Test generates _build_info.py file."""
        mock_get_info.return_value = (
            "abc123def456789012345678901234567890abcd",
            "abc123d",
            "Test commit",
            False,  # modified
        )

        result = _generate_build_info(tmp_path)

        assert result is True
        build_info = tmp_path / "_build_info.py"
        assert build_info.exists()
        content = build_info.read_text()
        assert 'COMMIT_HASH = "abc123def456789012345678901234567890abcd"' in content
        assert 'COMMIT_SHORT = "abc123d"' in content
        assert 'COMMIT_MESSAGE = "Test commit"' in content
        assert "MODIFIED = False" in content
        assert "BUILD_TIME" in content

    @patch("appinfra.version.setup_hook._get_git_info")
    def test_returns_false_without_git(self, mock_get_info, tmp_path, capsys):
        """Test returns False when git info unavailable."""
        mock_get_info.return_value = None

        result = _generate_build_info(tmp_path)

        assert result is False
        captured = capsys.readouterr()
        assert "git info not available" in captured.err

    @patch("appinfra.version.setup_hook._get_git_info")
    def test_escapes_quotes_in_message(self, mock_get_info, tmp_path):
        """Test escapes quotes in commit message."""
        mock_get_info.return_value = (
            "abc123def456789012345678901234567890abcd",
            "abc123d",
            'Fix "bug"',
            True,  # modified
        )

        _generate_build_info(tmp_path)

        content = (tmp_path / "_build_info.py").read_text()
        assert 'COMMIT_MESSAGE = "Fix \\"bug\\""' in content
        assert "MODIFIED = True" in content

    @patch("appinfra.version.setup_hook._get_git_info")
    def test_escapes_backslashes_in_message(self, mock_get_info, tmp_path):
        """Test escapes backslashes in commit message."""
        mock_get_info.return_value = (
            "abc123def456789012345678901234567890abcd",
            "abc123d",
            "Fix path\\to\\file",
            False,
        )

        _generate_build_info(tmp_path)

        content = (tmp_path / "_build_info.py").read_text()
        assert 'COMMIT_MESSAGE = "Fix path\\\\to\\\\file"' in content

    @patch("appinfra.version.setup_hook._get_git_info")
    def test_prints_success_message(self, mock_get_info, tmp_path, capsys):
        """Test prints success message with short commit."""
        mock_get_info.return_value = (
            "abc123def456789012345678901234567890abcd",
            "abc123d",
            "Test commit",
            False,
        )

        _generate_build_info(tmp_path)

        captured = capsys.readouterr()
        assert "generated _build_info.py" in captured.err
        assert "abc123d" in captured.err

    @patch("appinfra.version.setup_hook._get_git_info")
    def test_passes_cwd_to_get_git_info(self, mock_get_info, tmp_path):
        """Test passes cwd parameter to _get_git_info."""
        mock_get_info.return_value = None
        src_dir = tmp_path / "src"
        src_dir.mkdir()

        _generate_build_info(tmp_path, cwd=src_dir)

        mock_get_info.assert_called_once_with(src_dir)
