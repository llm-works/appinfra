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


@pytest.mark.unit
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

    def test_modified_returns_none_without_git_repo(self, tmp_path):
        """Test modified returns None when not in git repo."""
        info = BuildInfo(
            commit="abc", commit_full="abc123", _source_path=tmp_path / "file.py"
        )
        assert info.modified is None

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


@pytest.mark.unit
class TestBuildInfoFromPath:
    """Test BuildInfo.from_path() method."""

    def test_from_path_with_missing_file(self, tmp_path):
        """Test from_path with missing file falls back to git."""
        # No git repo, so returns None
        result = BuildInfo.from_path(tmp_path / "_build_info.py")
        assert result is None

    def test_from_path_with_empty_stub(self, tmp_path):
        """Test from_path with empty stub falls back to git."""
        stub = tmp_path / "_build_info.py"
        stub.write_text('COMMIT_HASH = ""\nCOMMIT_SHORT = ""\n')

        result = BuildInfo.from_path(stub)
        # No git repo, so returns None
        assert result is None

    def test_from_path_with_valid_file(self, tmp_path):
        """Test from_path reads valid build info."""
        build_info = tmp_path / "_build_info.py"
        build_info.write_text(
            """
COMMIT_HASH = "abc123def456789012345678901234567890abcd"
COMMIT_SHORT = "abc123d"
COMMIT_MESSAGE = "Test commit"
BUILD_TIME = "2025-12-01T10:30:00Z"
"""
        )

        result = BuildInfo.from_path(build_info)

        assert result is not None
        assert result.commit == "abc123d"
        assert result.commit_full == "abc123def456789012345678901234567890abcd"
        assert result.message == "Test commit"
        assert result.build_time is not None

    def test_from_path_with_no_short_commit(self, tmp_path):
        """Test from_path derives short commit from full."""
        build_info = tmp_path / "_build_info.py"
        build_info.write_text(
            """
COMMIT_HASH = "abc123def456789012345678901234567890abcd"
COMMIT_SHORT = ""
"""
        )

        result = BuildInfo.from_path(build_info)

        assert result is not None
        assert result.commit == "abc123d"

    def test_from_path_with_invalid_build_time(self, tmp_path):
        """Test from_path handles invalid build time."""
        build_info = tmp_path / "_build_info.py"
        build_info.write_text(
            """
COMMIT_HASH = "abc123def456789012345678901234567890abcd"
COMMIT_SHORT = "abc123d"
BUILD_TIME = "invalid-time"
"""
        )

        result = BuildInfo.from_path(build_info)

        assert result is not None
        assert result.build_time is None


@pytest.mark.unit
class TestBuildInfoGitRuntime:
    """Test BuildInfo git runtime detection."""

    @patch.object(BuildInfo, "_run_git")
    def test_from_git_runtime_success(self, mock_run_git, tmp_path):
        """Test _from_git_runtime with successful git commands."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()

        mock_run_git.side_effect = [
            "abc123def456789012345678901234567890abcd",  # rev-parse HEAD
            "Test commit message",  # log --format=%s
            "2025-12-01T10:30:00+00:00",  # log --format=%cI
        ]

        result = BuildInfo._from_git_runtime(tmp_path)

        assert result is not None
        assert result.commit == "abc123d"
        assert result.commit_full == "abc123def456789012345678901234567890abcd"
        assert result.message == "Test commit message"
        assert result.build_time is not None

    def test_from_git_runtime_no_git_repo(self, tmp_path):
        """Test _from_git_runtime returns None without git repo."""
        result = BuildInfo._from_git_runtime(tmp_path)
        assert result is None

    @patch.object(BuildInfo, "_run_git")
    def test_from_git_runtime_git_fails(self, mock_run_git, tmp_path):
        """Test _from_git_runtime handles git failure."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()

        mock_run_git.return_value = None  # git command fails

        result = BuildInfo._from_git_runtime(tmp_path)
        assert result is None


@pytest.mark.unit
class TestBuildInfoRunGit:
    """Test BuildInfo._run_git static method."""

    @patch("subprocess.run")
    def test_run_git_success(self, mock_run, tmp_path):
        """Test _run_git returns output on success."""
        mock_run.return_value = MagicMock(returncode=0, stdout="output\n")

        result = BuildInfo._run_git(tmp_path, ["status"])
        assert result == "output"

    @patch("subprocess.run")
    def test_run_git_failure(self, mock_run, tmp_path):
        """Test _run_git returns None on failure."""
        mock_run.return_value = MagicMock(returncode=1)

        result = BuildInfo._run_git(tmp_path, ["status"])
        assert result is None

    @patch("subprocess.run")
    def test_run_git_exception(self, mock_run, tmp_path):
        """Test _run_git handles exceptions."""
        import subprocess

        mock_run.side_effect = subprocess.SubprocessError("error")

        result = BuildInfo._run_git(tmp_path, ["status"])
        assert result is None

    @patch("subprocess.run")
    def test_run_git_file_not_found(self, mock_run, tmp_path):
        """Test _run_git handles missing git command."""
        mock_run.side_effect = FileNotFoundError("git not found")

        result = BuildInfo._run_git(tmp_path, ["status"])
        assert result is None


@pytest.mark.unit
class TestBuildInfoCheckGitModified:
    """Test BuildInfo._check_git_modified method."""

    @patch("subprocess.run")
    def test_check_git_modified_exception(self, mock_run, tmp_path):
        """Test _check_git_modified handles exceptions."""
        import subprocess

        mock_run.side_effect = subprocess.SubprocessError("error")

        info = BuildInfo(
            commit="abc", commit_full="abc123", _source_path=tmp_path / "file.py"
        )
        result = info._check_git_modified(tmp_path)
        assert result is None


@pytest.mark.unit
class TestBuildInfoFromPathException:
    """Test BuildInfo.from_path exception handling."""

    def test_from_path_with_invalid_python(self, tmp_path):
        """Test from_path falls back to git when file has invalid Python."""
        build_info = tmp_path / "_build_info.py"
        build_info.write_text("this is not valid python {{{")

        result = BuildInfo.from_path(build_info)
        # Falls back to git runtime, which returns None (no git repo)
        assert result is None


# =============================================================================
# Test PackageVersionInfo
# =============================================================================


@pytest.mark.unit
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


@pytest.mark.unit
class TestPackageVersionInfoSourceTypes:
    """Test PackageVersionInfo source type constants."""

    def test_source_types_exist(self):
        """Test all source type constants are defined."""
        assert PackageVersionInfo.SOURCE_PIP_GIT == "pip-git"
        assert PackageVersionInfo.SOURCE_BUILD_INFO == "build-info"
        assert PackageVersionInfo.SOURCE_EDITABLE_GIT == "editable-git"
        assert PackageVersionInfo.SOURCE_PIP == "pip"
        assert PackageVersionInfo.SOURCE_UNKNOWN == "unknown"


@pytest.mark.unit
class TestPackageVersionInfoModifiedEdgeCases:
    """Test PackageVersionInfo modified detection edge cases."""

    def test_modified_no_git_root(self, tmp_path):
        """Test modified returns None when no git root found."""
        info = PackageVersionInfo(
            name="pkg",
            version="1.0.0",
            source_type=PackageVersionInfo.SOURCE_EDITABLE_GIT,
            _package_path=tmp_path,
        )
        # No .git directory, so _find_git_root returns None
        assert info.modified is None

    def test_find_git_root_traverses_parents(self, tmp_path):
        """Test _find_git_root traverses parent directories."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        nested = tmp_path / "a" / "b" / "c"
        nested.mkdir(parents=True)

        info = PackageVersionInfo(
            name="pkg",
            version="1.0.0",
            source_type=PackageVersionInfo.SOURCE_EDITABLE_GIT,
            _package_path=nested,
        )
        result = info._find_git_root(nested)
        assert result == tmp_path

    def test_find_git_root_no_git(self, tmp_path):
        """Test _find_git_root returns None without .git."""
        info = PackageVersionInfo(name="pkg", version="1.0.0")
        result = info._find_git_root(tmp_path)
        assert result is None

    @patch("subprocess.run")
    def test_check_git_modified_exception(self, mock_run, tmp_path):
        """Test _check_git_modified handles subprocess exception."""
        import subprocess

        mock_run.side_effect = subprocess.SubprocessError("error")

        info = PackageVersionInfo(name="pkg", version="1.0.0")
        result = info._check_git_modified(tmp_path)
        assert result is None

    def test_message_short_exact_limit(self):
        """Test message_short at exactly 20 chars returns unchanged."""
        info = PackageVersionInfo(name="pkg", version="1.0.0", message="A" * 20)
        assert info.message_short == "A" * 20
        assert "..." not in info.message_short

    def test_message_short_under_limit(self):
        """Test message_short under 20 chars returns unchanged."""
        info = PackageVersionInfo(name="pkg", version="1.0.0", message="Short")
        assert info.message_short == "Short"
