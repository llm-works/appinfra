# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for appinfra/cli/tools/cq/dead.py."""

import argparse
from pathlib import Path
from textwrap import dedent
from unittest.mock import MagicMock

import pytest

from appinfra.cli.tools.cq.common import EXIT_CODE_WARNING
from appinfra.cli.tools.cq.dead import (
    CheckDeadTool,
    DeadCodeAnalyzer,
    format_report,
    is_private,
)


def _write(tmp: Path, name: str, source: str) -> Path:
    path = tmp / name
    path.write_text(dedent(source), encoding="utf-8")
    return path


def _unused(tmp: Path, **sources: str) -> list[tuple[str, str]]:
    """Analyze the given files; return (kind, name) of each finding."""
    analyzer = DeadCodeAnalyzer()
    for name, source in sources.items():
        analyzer.add_file(_write(tmp, f"{name}.py", source))
    return [(d.kind, d.name) for d in analyzer.unused()]


@pytest.mark.unit
class TestIsPrivate:
    """Test is_private()."""

    @pytest.mark.parametrize("name", ["_x", "_helper", "__mangled", "_x1"])
    def test_private(self, name: str):
        assert is_private(name) is True

    @pytest.mark.parametrize(
        "name", ["x", "_", "__", "__init__", "_missing_", "public_"]
    )
    def test_not_private(self, name: str):
        assert is_private(name) is False


@pytest.mark.unit
class TestDeadCodeAnalyzer:
    """Test which definitions DeadCodeAnalyzer reports."""

    def test_reports_unused_private_function(self, tmp_path: Path):
        assert _unused(tmp_path, a="def _gone(): pass\n") == [("function", "_gone")]

    def test_ignores_public_function(self, tmp_path: Path):
        assert _unused(tmp_path, a="def public(): pass\n") == []

    def test_call_in_same_file_is_a_use(self, tmp_path: Path):
        src = "def _helper(): pass\ndef f():\n    _helper()\n"
        assert _unused(tmp_path, a=src) == []

    def test_import_from_other_file_is_a_use(self, tmp_path: Path):
        found = _unused(
            tmp_path, a="def _helper(): pass\n", b="from a import _helper\n"
        )
        assert found == []

    def test_string_literal_is_a_use(self, tmp_path: Path):
        src = """
            class C:
                def _handler(self): pass
            def f(c):
                return getattr(c, "_handler")
        """
        assert _unused(tmp_path, a=src) == []

    def test_reports_unused_method_and_class_attribute(self, tmp_path: Path):
        src = """
            class C:
                _limit = 3
                def _old(self): pass
        """
        found = _unused(tmp_path, a=src)
        assert found == [("class attribute", "_limit"), ("method", "_old")]

    def test_reports_instance_attribute_never_read(self, tmp_path: Path):
        src = """
            class C:
                def __init__(self):
                    self._kept = 1
                    self._read = 2
                def get(self):
                    return self._read
        """
        assert _unused(tmp_path, a=src) == [("instance attribute", "_kept")]

    def test_augmented_assignment_counts_as_read(self, tmp_path: Path):
        src = """
            class C:
                def __init__(self):
                    self._n = 0
                def bump(self):
                    self._n += 1
        """
        assert _unused(tmp_path, a=src) == []

    def test_reports_constant_inside_if_and_try(self, tmp_path: Path):
        src = """
            try:
                import json
                _HAS_JSON = True
            except ImportError:
                _HAS_JSON = False
            if True:
                _FLAG = 1
        """
        found = _unused(tmp_path, a=src)
        assert found == [("constant", "_HAS_JSON"), ("constant", "_FLAG")]

    def test_keep_directive_skips_definition(self, tmp_path: Path):
        src = "def _hook(): pass  # cq: keep called by the stdlib\n"
        assert _unused(tmp_path, a=src) == []

    def test_dunder_and_sunder_not_reported(self, tmp_path: Path):
        src = """
            class C:
                def __repr__(self): return ""
                def _missing_(self): pass
        """
        assert _unused(tmp_path, a=src) == []

    def test_unparsable_file_is_recorded(self, tmp_path: Path):
        analyzer = DeadCodeAnalyzer()
        path = _write(tmp_path, "bad.py", "def (:\n")
        analyzer.add_file(path)
        assert analyzer.unparsable == [path]
        assert analyzer.unused() == []


@pytest.mark.unit
class TestFormatReport:
    """Test format_report()."""

    def test_lists_findings_and_totals(self, tmp_path: Path):
        analyzer = DeadCodeAnalyzer()
        path = _write(tmp_path, "a.py", "def _gone(): pass\n")
        analyzer.add_file(path)

        report = format_report(analyzer.unused(), files_checked=1)

        assert f"{path}:1: function _gone" in report
        assert report.endswith("Files checked: 1\nViolations: 1")


def _make_tool(tmp_path: Path, strict: bool) -> CheckDeadTool:
    tool = CheckDeadTool(parent=None)
    tool._parsed_args = argparse.Namespace(
        dir=str(tmp_path), strict=strict, exclude=None
    )
    tool._logger = MagicMock()
    return tool


@pytest.mark.unit
class TestCheckDeadTool:
    """Test CheckDeadTool.run() exit codes."""

    def test_clean_tree_exits_zero(self, tmp_path: Path, capsys):
        _write(tmp_path, "a.py", "def public(): pass\n")
        assert _make_tool(tmp_path, strict=False).run() == 0
        assert "Violations: 0" in capsys.readouterr().out

    def test_findings_warn_in_report_mode(self, tmp_path: Path):
        _write(tmp_path, "a.py", "def _gone(): pass\n")
        assert _make_tool(tmp_path, strict=False).run() == EXIT_CODE_WARNING

    def test_findings_fail_in_strict_mode(self, tmp_path: Path):
        _write(tmp_path, "a.py", "def _gone(): pass\n")
        assert _make_tool(tmp_path, strict=True).run() == 1

    def test_unparsable_file_is_logged(self, tmp_path: Path):
        _write(tmp_path, "bad.py", "def (:\n")
        tool = _make_tool(tmp_path, strict=False)
        assert tool.run() == 0
        tool._logger.warning.assert_called()

    def test_args(self):
        parser = argparse.ArgumentParser()
        CheckDeadTool(parent=None).add_args(parser)
        args = parser.parse_args(["pkg", "--strict", "--exclude", "x/*"])
        assert (args.dir, args.strict, args.exclude) == ("pkg", True, ["x/*"])
