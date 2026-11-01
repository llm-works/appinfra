# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for setuptools hook.

Tests the setuptools finalize hook for generating _build_info.py during install.
"""

from unittest.mock import MagicMock, patch

from appinfra.version.setuptools_hook import (
    _generate_build_info,
    finalize_hook,
)

# =============================================================================
# Test _generate_build_info
# =============================================================================


class TestGenerateBuildInfo:
    """Test _generate_build_info function."""

    @patch("appinfra.version.setuptools_hook._get_git_info")
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
        assert "MODIFIED = False" in content

    @patch("appinfra.version.setuptools_hook._get_git_info")
    def test_returns_false_without_git(self, mock_get_info, tmp_path):
        """Test returns False when git info unavailable."""
        mock_get_info.return_value = None

        result = _generate_build_info(tmp_path)
        assert result is False

    @patch("appinfra.version.setuptools_hook._get_git_info")
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


# =============================================================================
# Test finalize_hook
# =============================================================================


class TestFinalizeHook:
    """Test finalize_hook function."""

    @patch("appinfra.version.setuptools_hook._generate_build_info")
    @patch("pathlib.Path.cwd")
    def test_generates_in_appinfra_dir(self, mock_cwd, mock_generate, tmp_path):
        """Test generates build info in appinfra directory."""
        # Create appinfra package structure
        appinfra_dir = tmp_path / "appinfra"
        appinfra_dir.mkdir()
        (appinfra_dir / "__init__.py").touch()

        mock_cwd.return_value = tmp_path
        mock_generate.return_value = True

        finalize_hook(MagicMock())

        mock_generate.assert_called_once_with(appinfra_dir)

    @patch("appinfra.version.setuptools_hook._generate_build_info")
    @patch("pathlib.Path.cwd")
    def test_generates_in_src_layout(self, mock_cwd, mock_generate, tmp_path):
        """Test generates build info in src/appinfra directory."""
        # Create src/appinfra package structure
        src_dir = tmp_path / "src" / "appinfra"
        src_dir.mkdir(parents=True)
        (src_dir / "__init__.py").touch()

        mock_cwd.return_value = tmp_path
        mock_generate.return_value = True

        finalize_hook(MagicMock())

        mock_generate.assert_called_once_with(src_dir)

    @patch("appinfra.version.setuptools_hook._generate_build_info")
    @patch("pathlib.Path.cwd")
    def test_skips_when_no_appinfra_dir(self, mock_cwd, mock_generate, tmp_path):
        """Test skips gracefully when appinfra not found."""
        mock_cwd.return_value = tmp_path

        # Should not raise, just skip
        finalize_hook(MagicMock())

        mock_generate.assert_not_called()

    @patch("appinfra.version.setuptools_hook._generate_build_info")
    @patch("pathlib.Path.cwd")
    def test_handles_generate_failure(self, mock_cwd, mock_generate, tmp_path, capsys):
        """Test handles generate failure gracefully."""
        appinfra_dir = tmp_path / "appinfra"
        appinfra_dir.mkdir()
        (appinfra_dir / "__init__.py").touch()

        mock_cwd.return_value = tmp_path
        mock_generate.return_value = False

        # Should not raise
        finalize_hook(MagicMock())

        # No output expected when generation fails silently
        captured = capsys.readouterr()
        assert "generated" not in captured.err
