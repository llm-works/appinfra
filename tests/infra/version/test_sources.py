# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for version information sources.

Tests the chain-of-responsibility pattern for version detection:
- PEP610Source (direct_url.json)
- BuildInfoSource (_build_info.py)
- GitRuntimeSource (git commands)
"""

import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from appinfra.version.info import PackageVersionInfo
from appinfra.version.sources import (
    BuildInfoSource,
    GitRuntimeSource,
    PEP610Source,
    VersionSource,
)

# =============================================================================
# Test VersionSource ABC
# =============================================================================


@pytest.mark.unit
class TestVersionSourceABC:
    """Test VersionSource abstract base class."""

    def test_cannot_instantiate_directly(self):
        """Test VersionSource cannot be instantiated."""
        with pytest.raises(TypeError):
            VersionSource()


# =============================================================================
# Test PEP610Source
# =============================================================================


@pytest.mark.unit
class TestPEP610Source:
    """Test PEP610Source for pip git+ installs."""

    def test_returns_none_for_missing_package(self):
        """Test returns None for non-existent package."""
        source = PEP610Source()
        result = source.get_info("nonexistent-package-xyz-123")
        assert result is None

    @patch("importlib.metadata.distribution")
    def test_returns_none_without_direct_url(self, mock_dist):
        """Test returns None when direct_url.json is missing."""
        mock_dist.return_value.read_text.side_effect = FileNotFoundError()
        mock_dist.return_value.metadata = {"Version": "1.0.0"}

        source = PEP610Source()
        result = source.get_info("mypackage")
        assert result is None

    @patch("importlib.metadata.distribution")
    def test_returns_none_for_empty_direct_url(self, mock_dist):
        """Test returns None when direct_url.json is empty."""
        mock_dist.return_value.read_text.return_value = ""
        mock_dist.return_value.metadata = {"Version": "1.0.0"}

        source = PEP610Source()
        result = source.get_info("mypackage")
        assert result is None

    @patch("importlib.metadata.distribution")
    def test_returns_none_for_missing_commit_id(self, mock_dist):
        """Test returns None when commit_id is missing."""
        mock_dist.return_value.read_text.return_value = json.dumps(
            {"url": "https://example.com", "vcs_info": {"vcs": "git"}}
        )
        mock_dist.return_value.metadata = {"Version": "1.0.0"}

        source = PEP610Source()
        result = source.get_info("mypackage")
        assert result is None

    @patch("importlib.metadata.distribution")
    def test_returns_none_for_non_git_vcs(self, mock_dist):
        """Test returns None for non-git VCS."""
        mock_dist.return_value.read_text.return_value = json.dumps(
            {
                "url": "https://example.com",
                "vcs_info": {"vcs": "hg", "commit_id": "abc"},
            }
        )
        mock_dist.return_value.metadata = {"Version": "1.0.0"}

        source = PEP610Source()
        result = source.get_info("mypackage")
        assert result is None

    @patch("importlib.metadata.distribution")
    def test_returns_none_without_vcs_info(self, mock_dist):
        """Test returns None when vcs_info is missing."""
        mock_dist.return_value.read_text.return_value = json.dumps(
            {"url": "https://example.com"}
        )
        mock_dist.return_value.metadata = {"Version": "1.0.0"}

        source = PEP610Source()
        result = source.get_info("mypackage")
        assert result is None

    @patch("importlib.metadata.distribution")
    def test_parses_valid_git_install(self, mock_dist):
        """Test successfully parses pip install git+... package."""
        mock_dist.return_value.read_text.return_value = json.dumps(
            {
                "url": "https://github.com/org/repo",
                "vcs_info": {
                    "vcs": "git",
                    "commit_id": "abc123def456789012345678901234567890abcd",
                },
            }
        )
        mock_dist.return_value.metadata = {"Version": "1.2.0"}

        source = PEP610Source()
        result = source.get_info("mypackage")

        assert result is not None
        assert result.name == "mypackage"
        assert result.version == "1.2.0"
        assert result.commit_full == "abc123def456789012345678901234567890abcd"
        assert result.source_url == "https://github.com/org/repo"
        assert result.source_type == PackageVersionInfo.SOURCE_PIP_GIT

    @patch("importlib.metadata.distribution")
    def test_handles_invalid_json(self, mock_dist):
        """Test handles invalid JSON in direct_url.json."""
        mock_dist.return_value.read_text.return_value = "not valid json"
        mock_dist.return_value.metadata = {"Version": "1.0.0"}

        source = PEP610Source()
        result = source.get_info("mypackage")
        assert result is None


# =============================================================================
# Test BuildInfoSource
# =============================================================================


@pytest.mark.unit
class TestBuildInfoSource:
    """Test BuildInfoSource for _build_info.py detection."""

    def test_returns_none_for_missing_package(self):
        """Test returns None for non-existent package."""
        source = BuildInfoSource()
        result = source.get_info("nonexistent-package-xyz-123")
        assert result is None

    @patch("importlib.util.find_spec")
    @patch("importlib.metadata.distribution")
    def test_returns_none_without_build_info_module(self, mock_dist, mock_find_spec):
        """Test returns None when _build_info module is missing."""
        mock_dist.return_value.read_text.side_effect = FileNotFoundError()
        mock_dist.return_value.metadata = {"Version": "1.0.0"}
        mock_find_spec.return_value = None

        source = BuildInfoSource()
        result = source.get_info("mypackage")
        assert result is None

    @patch("importlib.import_module")
    @patch("importlib.util.find_spec")
    @patch("importlib.metadata.distribution")
    def test_returns_none_for_empty_commit_hash(
        self, mock_dist, mock_find_spec, mock_import
    ):
        """Test returns None when COMMIT_HASH is empty."""
        mock_dist.return_value.read_text.side_effect = FileNotFoundError()
        mock_dist.return_value.metadata = {"Version": "1.0.0"}
        mock_find_spec.return_value = MagicMock(origin="/path/to/_build_info.py")
        mock_import.return_value = MagicMock(COMMIT_HASH="")

        source = BuildInfoSource()
        result = source.get_info("mypackage")
        assert result is None

    @patch("importlib.import_module")
    @patch("importlib.util.find_spec")
    @patch("importlib.metadata.distribution")
    def test_parses_valid_build_info(self, mock_dist, mock_find_spec, mock_import):
        """Test successfully parses _build_info.py module."""
        mock_dist.return_value.read_text.side_effect = FileNotFoundError()
        mock_dist.return_value.metadata = {"Version": "1.2.0"}
        mock_find_spec.return_value = MagicMock(origin="/path/pkg/_build_info.py")

        build_info_module = MagicMock()
        build_info_module.COMMIT_HASH = "abc123def456789012345678901234567890abcd"
        build_info_module.COMMIT_SHORT = "abc123d"
        build_info_module.COMMIT_MESSAGE = "Fix bug"
        build_info_module.BUILD_TIME = "2025-12-01T10:30:00Z"
        mock_import.return_value = build_info_module

        source = BuildInfoSource()
        result = source.get_info("mypackage")

        assert result is not None
        assert result.name == "mypackage"
        assert result.version == "1.2.0"
        assert result.commit == "abc123d"
        assert result.commit_full == "abc123def456789012345678901234567890abcd"
        assert result.message == "Fix bug"
        assert result.source_type == PackageVersionInfo.SOURCE_BUILD_INFO
        assert result.build_time is not None

    @patch("importlib.import_module")
    @patch("importlib.util.find_spec")
    @patch("importlib.metadata.distribution")
    def test_handles_import_exception(self, mock_dist, mock_find_spec, mock_import):
        """Test handles import exception gracefully."""
        mock_dist.return_value.read_text.side_effect = FileNotFoundError()
        mock_dist.return_value.metadata = {"Version": "1.0.0"}
        mock_find_spec.return_value = MagicMock(origin="/path/to/_build_info.py")
        mock_import.side_effect = ImportError("broken import")

        source = BuildInfoSource()
        result = source.get_info("mypackage")
        assert result is None


@pytest.mark.unit
class TestBuildInfoSourceTopLevel:
    """Test BuildInfoSource._get_top_level_name()."""

    @patch("importlib.metadata.distribution")
    def test_reads_top_level_txt(self, mock_dist):
        """Test reads top_level.txt when available."""
        mock_dist.return_value.read_text.return_value = "mypackage\n"

        source = BuildInfoSource()
        result = source._get_top_level_name(mock_dist.return_value, "my-package")

        assert result == "mypackage"

    @patch("importlib.metadata.distribution")
    def test_normalizes_package_name(self, mock_dist):
        """Test normalizes package name when top_level.txt is missing."""
        mock_dist.return_value.read_text.side_effect = FileNotFoundError()

        source = BuildInfoSource()
        result = source._get_top_level_name(mock_dist.return_value, "my-package")

        assert result == "my_package"


@pytest.mark.unit
class TestBuildInfoSourceParseBuildTime:
    """Test BuildInfoSource._parse_build_time()."""

    def test_parse_empty_string(self):
        """Test returns None for empty string."""
        source = BuildInfoSource()
        result = source._parse_build_time("")
        assert result is None

    def test_parse_none(self):
        """Test returns None for None."""
        source = BuildInfoSource()
        result = source._parse_build_time(None)
        assert result is None

    def test_parse_invalid_format(self):
        """Test returns None for invalid format."""
        source = BuildInfoSource()
        result = source._parse_build_time("not-a-date")
        assert result is None

    def test_parse_valid_format(self):
        """Test parses valid ISO format."""
        source = BuildInfoSource()
        result = source._parse_build_time("2025-12-01T10:30:00Z")
        assert result is not None


# =============================================================================
# Test GitRuntimeSource
# =============================================================================


@pytest.mark.unit
class TestGitRuntimeSource:
    """Test GitRuntimeSource for editable installs."""

    def test_returns_none_for_missing_package(self):
        """Test returns None for non-existent package."""
        source = GitRuntimeSource()
        result = source.get_info("nonexistent-package-xyz-123")
        assert result is None

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
            elif "--format=%s" in args:
                return MagicMock(returncode=0, stdout="Test commit\n")
            elif "--format=%cI" in args:
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


@pytest.mark.unit
class TestGitRuntimeSourceHelpers:
    """Test GitRuntimeSource helper methods."""

    def test_find_git_root_finds_git_dir(self, tmp_path):
        """Test _find_git_root finds .git directory."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        subdir = tmp_path / "subdir" / "nested"
        subdir.mkdir(parents=True)

        source = GitRuntimeSource()
        result = source._find_git_root(subdir)

        assert result == tmp_path

    def test_find_git_root_returns_none_without_git(self, tmp_path):
        """Test _find_git_root returns None without .git."""
        source = GitRuntimeSource()
        result = source._find_git_root(tmp_path)
        assert result is None

    @patch("subprocess.run")
    def test_get_commit_hash_success(self, mock_run, tmp_path):
        """Test _get_commit_hash returns hash on success."""
        mock_run.return_value = MagicMock(returncode=0, stdout="abc123def456\n")

        source = GitRuntimeSource()
        result = source._get_commit_hash(tmp_path)

        assert result == "abc123def456"

    @patch("subprocess.run")
    def test_get_commit_hash_failure(self, mock_run, tmp_path):
        """Test _get_commit_hash returns None on failure."""
        mock_run.return_value = MagicMock(returncode=1)

        source = GitRuntimeSource()
        result = source._get_commit_hash(tmp_path)

        assert result is None

    @patch("subprocess.run")
    def test_get_commit_hash_exception(self, mock_run, tmp_path):
        """Test _get_commit_hash handles exception."""
        import subprocess

        mock_run.side_effect = subprocess.SubprocessError("error")

        source = GitRuntimeSource()
        result = source._get_commit_hash(tmp_path)

        assert result is None

    @patch("subprocess.run")
    def test_get_commit_message_success(self, mock_run, tmp_path):
        """Test _get_commit_message returns message."""
        mock_run.return_value = MagicMock(returncode=0, stdout="Fix bug\n")

        source = GitRuntimeSource()
        result = source._get_commit_message(tmp_path)

        assert result == "Fix bug"

    @patch("subprocess.run")
    def test_get_commit_message_exception(self, mock_run, tmp_path):
        """Test _get_commit_message handles exception."""
        import subprocess

        mock_run.side_effect = subprocess.SubprocessError("error")

        source = GitRuntimeSource()
        result = source._get_commit_message(tmp_path)

        assert result == ""

    @patch("subprocess.run")
    def test_get_commit_time_success(self, mock_run, tmp_path):
        """Test _get_commit_time parses timestamp."""
        mock_run.return_value = MagicMock(
            returncode=0, stdout="2025-12-01T10:30:00+00:00\n"
        )

        source = GitRuntimeSource()
        result = source._get_commit_time(tmp_path)

        assert result is not None
        assert isinstance(result, datetime)

    @patch("subprocess.run")
    def test_get_commit_time_invalid_format(self, mock_run, tmp_path):
        """Test _get_commit_time handles invalid format."""
        mock_run.return_value = MagicMock(returncode=0, stdout="invalid\n")

        source = GitRuntimeSource()
        result = source._get_commit_time(tmp_path)

        assert result is None


@pytest.mark.unit
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
