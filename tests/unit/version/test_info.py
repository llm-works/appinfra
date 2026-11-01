# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for version info dataclasses.

Tests BuildInfo and PackageVersionInfo dataclasses including:
- Dataclass initialization and properties
- Message truncation
- Modified detection
- Runtime git fallback
"""

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from appinfra.version.info import BuildInfo, PackageVersionInfo

# =============================================================================
# Test BuildInfo
# =============================================================================


class TestBuildInfo:
    """Test BuildInfo dataclass."""

    def test_basic_initialization(self):
        """Test basic BuildInfo creation."""
        info = BuildInfo(
            commit="abc123f",
            commit_full="abc123f0123456789abcdef0123456789abcdef01",
        )
        assert info.commit == "abc123f"
        assert info.commit_full == "abc123f0123456789abcdef0123456789abcdef01"
        assert info.message == ""
        assert info.build_time is None
        assert info._source_path is None

    def test_full_initialization(self):
        """Test BuildInfo with all fields."""
        build_time = datetime(2025, 12, 1, 10, 30, 0)
        source_path = Path("/app/mypackage")

        info = BuildInfo(
            commit="abc123f",
            commit_full="abc123f0123456789abcdef0123456789abcdef01",
            message="Fix critical bug",
            build_time=build_time,
            _source_path=source_path,
        )

        assert info.commit == "abc123f"
        assert info.message == "Fix critical bug"
        assert info.build_time == build_time
        assert info._source_path == source_path

    def test_message_short_under_limit(self):
        """Test message_short with short message."""
        info = BuildInfo(commit="abc", commit_full="abc123", message="Short msg")
        assert info.message_short == "Short msg"

    def test_message_short_at_limit(self):
        """Test message_short at exactly 20 chars."""
        info = BuildInfo(commit="abc", commit_full="abc123", message="A" * 20)
        assert info.message_short == "A" * 20

    def test_message_short_over_limit(self):
        """Test message_short truncates long messages."""
        info = BuildInfo(commit="abc", commit_full="abc123", message="A" * 30)
        assert info.message_short == "A" * 20 + "..."

    def test_modified_returns_none_without_source_path(self):
        """Test modified returns None when no source path."""
        info = BuildInfo(commit="abc", commit_full="abc123")
        assert info.modified is None

    @pytest.mark.integration
    def test_modified_returns_none_without_git_repo(self, tmp_path):
        """Test modified returns None when not in git repo."""
        info = BuildInfo(
            commit="abc", commit_full="abc123", _source_path=tmp_path / "file.py"
        )
        assert info.modified is None

    @pytest.mark.integration
    @patch("subprocess.run")
    def test_modified_returns_true_when_dirty(self, mock_run, tmp_path):
        """Test modified returns True when repo has changes."""
        # Create fake git directory
        git_dir = tmp_path / ".git"
        git_dir.mkdir()

        mock_run.return_value = MagicMock(returncode=0, stdout="M file.py\n")

        info = BuildInfo(
            commit="abc", commit_full="abc123", _source_path=tmp_path / "subdir"
        )
        assert info.modified is True

    @pytest.mark.integration
    @patch("subprocess.run")
    def test_modified_returns_false_when_clean(self, mock_run, tmp_path):
        """Test modified returns False when repo is clean."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()

        mock_run.return_value = MagicMock(returncode=0, stdout="")

        info = BuildInfo(
            commit="abc", commit_full="abc123", _source_path=tmp_path / "subdir"
        )
        assert info.modified is False


# =============================================================================
# Test PackageVersionInfo
# =============================================================================


class TestPackageVersionInfo:
    """Test PackageVersionInfo dataclass."""

    def test_basic_initialization(self):
        """Test basic PackageVersionInfo creation."""
        info = PackageVersionInfo(name="mypackage", version="1.0.0")

        assert info.name == "mypackage"
        assert info.version == "1.0.0"
        assert info.commit is None
        assert info.commit_full is None
        assert info.has_commit is False

    def test_with_commit_info(self):
        """Test PackageVersionInfo with commit info."""
        info = PackageVersionInfo(
            name="mypackage",
            version="1.0.0",
            commit="abc123f",
            commit_full="abc123f0123456789abcdef0123456789abcdef01",
            message="Fix bug",
            source_type=PackageVersionInfo.SOURCE_BUILD_INFO,
        )

        assert info.has_commit is True
        assert info.commit == "abc123f"
        assert info.source_type == "build-info"

    def test_post_init_derives_short_from_full(self):
        """Test __post_init__ derives short commit from full."""
        info = PackageVersionInfo(
            name="pkg",
            version="1.0.0",
            commit_full="abc123f0123456789abcdef0123456789abcdef01",
        )

        assert info.commit == "abc123f"

    def test_post_init_handles_40_char_short_commit(self):
        """Test __post_init__ handles 40-char commit in short field."""
        # Exactly 40 characters (standard git full hash length)
        full_hash = "abc123f" + "0" * 33  # 7 + 33 = 40
        info = PackageVersionInfo(
            name="pkg",
            version="1.0.0",
            commit=full_hash,
        )

        assert info.commit == "abc123f"
        assert info.commit_full == full_hash

    def test_message_short_truncates(self):
        """Test message_short truncates long messages."""
        info = PackageVersionInfo(name="pkg", version="1.0.0", message="A" * 30)
        assert info.message_short == "A" * 20 + "..."

    def test_format_short_with_commit(self):
        """Test format_short with commit."""
        info = PackageVersionInfo(name="mylib", version="1.2.0", commit="abc123f")
        assert info.format_short() == "mylib=1.2.0@abc123f"

    def test_format_short_without_commit(self):
        """Test format_short without commit."""
        info = PackageVersionInfo(name="mylib", version="1.2.0")
        assert info.format_short() == "mylib=1.2.0"

    def test_format_long_full(self):
        """Test format_long with all fields."""
        info = PackageVersionInfo(
            name="mylib",
            version="1.2.0",
            commit="abc123f",
            source_url="git+https://github.com/org/mylib",
        )
        result = info.format_long()
        assert "mylib" in result
        assert "1.2.0" in result
        assert "abc123f" in result
        assert "git+https://github.com/org/mylib" in result

    def test_modified_returns_none_for_pip_install(self):
        """Test modified returns None for regular pip installs."""
        info = PackageVersionInfo(
            name="pkg",
            version="1.0.0",
            source_type=PackageVersionInfo.SOURCE_PIP,
        )
        assert info.modified is None

    def test_modified_returns_none_without_package_path(self):
        """Test modified returns None without package path."""
        info = PackageVersionInfo(
            name="pkg",
            version="1.0.0",
            source_type=PackageVersionInfo.SOURCE_EDITABLE_GIT,
        )
        assert info.modified is None

    @pytest.mark.integration
    @patch("subprocess.run")
    def test_modified_detects_changes(self, mock_run, tmp_path):
        """Test modified detects uncommitted changes."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()

        mock_run.return_value = MagicMock(returncode=0, stdout="M file.py\n")

        info = PackageVersionInfo(
            name="pkg",
            version="1.0.0",
            source_type=PackageVersionInfo.SOURCE_EDITABLE_GIT,
            _package_path=tmp_path,
        )
        assert info.modified is True


class TestPackageVersionInfoSourceTypes:
    """Test PackageVersionInfo source type constants."""

    def test_source_types_exist(self):
        """Test all source type constants are defined."""
        assert PackageVersionInfo.SOURCE_PIP_GIT == "pip-git"
        assert PackageVersionInfo.SOURCE_BUILD_INFO == "build-info"
        assert PackageVersionInfo.SOURCE_EDITABLE_GIT == "editable-git"
        assert PackageVersionInfo.SOURCE_PIP == "pip"
        assert PackageVersionInfo.SOURCE_UNKNOWN == "unknown"


class TestPackageVersionInfoModifiedEdgeCases:
    """Test PackageVersionInfo modified detection edge cases."""

    @pytest.mark.integration
    def test_modified_no_git_root(self, tmp_path):
        """Test modified returns None when no git root found."""
        info = PackageVersionInfo(
            name="pkg",
            version="1.0.0",
            source_type=PackageVersionInfo.SOURCE_EDITABLE_GIT,
            _package_path=tmp_path,
        )
        # No .git directory, so find_git_root returns None
        assert info.modified is None

    def test_message_short_exact_limit(self):
        """Test message_short at exactly 20 chars returns unchanged."""
        info = PackageVersionInfo(name="pkg", version="1.0.0", message="A" * 20)
        assert info.message_short == "A" * 20
        assert "..." not in info.message_short

    def test_message_short_under_limit(self):
        """Test message_short under 20 chars returns unchanged."""
        info = PackageVersionInfo(name="pkg", version="1.0.0", message="Short")
        assert info.message_short == "Short"
