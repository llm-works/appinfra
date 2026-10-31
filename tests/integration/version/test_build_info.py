# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for the build_info CLI tool that write _build_info.py files.
"""

from unittest.mock import patch

from appinfra.version.build_info import generate

# =============================================================================
# Test generate
# =============================================================================


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
