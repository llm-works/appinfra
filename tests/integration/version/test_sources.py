# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for the git runtime version source that locate package files on disk.
"""

from unittest.mock import MagicMock, patch

from appinfra.version.sources import GitRuntimeSource


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
