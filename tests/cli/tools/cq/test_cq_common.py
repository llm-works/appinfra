# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for appinfra/cli/tools/cq/common.py."""

from pathlib import Path
from unittest.mock import Mock

import pytest

from appinfra.cli.tools.cq.common import collect_python_files, should_exclude


@pytest.mark.unit
class TestShouldExclude:
    """Test should_exclude()."""

    def test_excludes_test_directory(self):
        assert should_exclude(Path("/project/tests/test_foo.py"), [], False) is True

    def test_excludes_test_prefix(self):
        assert should_exclude(Path("/project/test_foo.py"), [], False) is True

    def test_includes_test_files_when_flag_set(self):
        assert should_exclude(Path("/project/tests/test_foo.py"), [], True) is False

    def test_excludes_custom_patterns(self):
        assert should_exclude(Path("/project/vendor/lib.py"), ["vendor/*"], False)

    def test_excludes_hidden_and_cache_dirs(self):
        assert should_exclude(Path("/project/.venv/lib.py"), [], False) is True
        assert should_exclude(Path("/project/__pycache__/a.py"), [], False) is True

    def test_includes_regular_files(self):
        assert should_exclude(Path("/project/infra/app.py"), [], False) is False

    def test_current_dir_prefix_is_not_hidden(self):
        assert should_exclude(Path("./app.py"), [], False) is False


@pytest.mark.unit
class TestCollectPythonFiles:
    """Test collect_python_files()."""

    def test_collects_files_in_directory(self, tmp_path: Path):
        (tmp_path / "file1.py").touch()
        (tmp_path / "file2.py").touch()
        (tmp_path / "readme.txt").touch()

        files = collect_python_files(Mock(), [str(tmp_path)], [], False)

        assert [f.name for f in files] == ["file1.py", "file2.py"]

    def test_excludes_test_files_by_default(self, tmp_path: Path):
        (tmp_path / "app.py").touch()
        (tmp_path / "test_app.py").touch()

        files = collect_python_files(Mock(), [str(tmp_path)], [], False)

        assert [f.name for f in files] == ["app.py"]

    def test_includes_test_files_when_flag_set(self, tmp_path: Path):
        (tmp_path / "app.py").touch()
        (tmp_path / "test_app.py").touch()

        files = collect_python_files(Mock(), [str(tmp_path)], [], True)

        assert len(files) == 2

    def test_handles_nonexistent_path(self):
        lg = Mock()

        files = collect_python_files(lg, ["/nonexistent/path"], [], False)

        assert files == []
        lg.warning.assert_called()

    def test_collects_single_file(self, tmp_path: Path):
        path = tmp_path / "one.py"
        path.touch()

        files = collect_python_files(Mock(), [str(path)], [], False)

        assert files == [path]

    def test_skips_single_non_python_file(self, tmp_path: Path):
        path = tmp_path / "one.txt"
        path.touch()

        assert collect_python_files(Mock(), [str(path)], [], False) == []
