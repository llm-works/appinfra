# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for the git runtime version source that locate package files and git repos on disk.
"""

from unittest.mock import MagicMock, patch

import pytest

from appinfra.version.info import PackageVersionInfo
from appinfra.version.sources import GitRuntimeSource


class TestGitRuntimeSource:
    """Test GitRuntimeSource for editable installs."""

    @pytest.mark.unit
    def test_returns_none_for_missing_package(self):
        """Test returns None for non-existent package."""
        source = GitRuntimeSource()
        result = source.get_info("nonexistent-package-xyz-123")
        assert result is None

    @pytest.mark.unit
    @patch("importlib.util.find_spec")
    @patch("importlib.metadata.distribution")
    def test_returns_none_without_package_path(self, mock_dist, mock_find_spec):
        """Test returns None when package path cannot be found."""
        mock_dist.return_value.metadata = {"Version": "1.0.0"}
        mock_dist.return_value.files = None
        mock_find_spec.return_value = None

        source = GitRuntimeSource()
        result = source.get_info("mypackage")
        assert result is None

    @patch("subprocess.run")
    @patch("importlib.util.find_spec")
    @patch("importlib.metadata.distribution")
    def test_returns_none_without_git_repo(
        self, mock_dist, mock_find_spec, mock_run, tmp_path
    ):
        """Test returns None when not in git repo."""
        mock_dist.return_value.metadata = {"Version": "1.0.0"}
        mock_dist.return_value.files = None
        mock_find_spec.return_value = MagicMock(origin=str(tmp_path / "__init__.py"))

        source = GitRuntimeSource()
        result = source.get_info("mypackage")
        assert result is None

    @patch("subprocess.run")
    @patch("importlib.util.find_spec")
    @patch("importlib.metadata.distribution")
    def test_successful_git_detection(
        self, mock_dist, mock_find_spec, mock_run, tmp_path
    ):
        """Test successful git info detection."""
        # Create fake git repo
        git_dir = tmp_path / ".git"
        git_dir.mkdir()

        mock_dist.return_value.metadata = {"Version": "1.2.0"}
        mock_dist.return_value.files = None
        mock_find_spec.return_value = MagicMock(origin=str(tmp_path / "__init__.py"))

        # Mock git commands
        def run_side_effect(args, **kwargs):
            if "rev-parse" in args:
                return MagicMock(
                    returncode=0,
                    stdout="abc123def456789012345678901234567890abcd\n",
                )
            if "--format=%s" in args:
                return MagicMock(returncode=0, stdout="Test commit\n")
            if "--format=%cI" in args:
                return MagicMock(returncode=0, stdout="2025-12-01T10:30:00+00:00\n")
            return MagicMock(returncode=1)

        mock_run.side_effect = run_side_effect

        source = GitRuntimeSource()
        result = source.get_info("mypackage")

        assert result is not None
        assert result.name == "mypackage"
        assert result.version == "1.2.0"
        assert result.commit == "abc123d"
        assert result.commit_full == "abc123def456789012345678901234567890abcd"
        assert result.message == "Test commit"
        assert result.source_type == PackageVersionInfo.SOURCE_EDITABLE_GIT

    @patch("subprocess.run")
    @patch("importlib.util.find_spec")
    @patch("importlib.metadata.distribution")
    def test_handles_git_command_failure(
        self, mock_dist, mock_find_spec, mock_run, tmp_path
    ):
        """Test handles git command failure gracefully."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()

        mock_dist.return_value.metadata = {"Version": "1.0.0"}
        mock_dist.return_value.files = None
        mock_find_spec.return_value = MagicMock(origin=str(tmp_path / "__init__.py"))
        mock_run.return_value = MagicMock(returncode=1)

        source = GitRuntimeSource()
        result = source.get_info("mypackage")
        assert result is None


class TestGitRuntimeSourceFindPackagePath:
    """Test GitRuntimeSource._find_package_path()."""

    @patch("importlib.util.find_spec")
    @patch("importlib.metadata.distribution")
    def test_find_spec_import_error(self, mock_dist, mock_find_spec, tmp_path):
        """Test handles ImportError from find_spec."""
        mock_dist.return_value.metadata = {"Version": "1.0.0"}
        mock_dist.return_value.files = None
        mock_find_spec.side_effect = ImportError("cannot import")

        source = GitRuntimeSource()
        result = source._find_package_path(mock_dist.return_value, "mypackage")

        assert result is None

    @patch("importlib.util.find_spec")
    @patch("importlib.metadata.distribution")
    def test_fallback_to_dist_files(self, mock_dist, mock_find_spec, tmp_path):
        """Test falls back to dist.files when find_spec fails."""
        mock_find_spec.return_value = None

        # Create a mock file object
        init_file = tmp_path / "mypackage" / "__init__.py"
        init_file.parent.mkdir()
        init_file.touch()

        mock_file = MagicMock()
        mock_file.name = "__init__.py"
        mock_file.suffix = ".py"
        mock_file.locate.return_value = init_file

        mock_dist.return_value.metadata = {"Version": "1.0.0"}
        mock_dist.return_value.files = [mock_file]

        source = GitRuntimeSource()
        result = source._find_package_path(mock_dist.return_value, "mypackage")

        assert result is not None
        assert result == init_file.parent
