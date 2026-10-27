# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for appinfra/cli/tools/cq/dup.py."""

import argparse
import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from appinfra.cli.tools.cq.common import EXIT_CODE_WARNING
from appinfra.cli.tools.cq.dup import (
    Block,
    CheckDupTool,
    format_report,
    module_paths,
    parse_groups,
    pylint_command,
)

# A body long enough to pass the default 8-line threshold
_BODY = "\n".join(f"    total = total + {i}" for i in range(12))


def _r0801(*locations: str) -> dict:
    text = "Similar lines in 2 files\n" + "\n".join(locations) + "\n    code\n"
    return {"symbol": "duplicate-code", "message": text}


@pytest.mark.unit
class TestParsing:
    """Test pylint output parsing."""

    def test_module_paths_maps_dotted_suffixes(self):
        f = Path("pkg/sub/mod.py")
        paths = module_paths([f])
        assert paths["pkg.sub.mod"] == f
        assert paths["sub.mod"] == f

    def test_parse_groups_resolves_modules_and_lines(self):
        files = [Path("pkg/a.py"), Path("pkg/b.py")]
        output = json.dumps({"messages": [_r0801("==pkg.a:[9:20]", "==pkg.b:[0:11]")]})

        groups = parse_groups(output, module_paths(files))

        assert groups == [[Block("pkg/a.py", 10, 20), Block("pkg/b.py", 1, 11)]]

    def test_parse_groups_keeps_unknown_module_name(self):
        output = json.dumps({"messages": [_r0801("==other.mod:[0:9]")]})
        assert parse_groups(output, {}) == [[Block("other.mod", 1, 9)]]

    def test_parse_groups_skips_other_messages(self):
        output = json.dumps({"messages": [{"symbol": "unused-import", "message": "x"}]})
        assert parse_groups(output, {}) == []


@pytest.mark.unit
class TestFormatReport:
    """Test format_report()."""

    def test_counts_smallest_copy_per_extra_copy(self):
        groups = [[Block("a.py", 1, 10), Block("b.py", 1, 12)]]

        report = format_report(groups, files_checked=2)

        assert "  a.py:1-10 (10 lines)" in report
        assert "  b.py:1-12 (12 lines)" in report
        assert report.endswith("Files checked: 2\nDuplicated lines: 10\nViolations: 1")

    def test_no_groups(self):
        report = format_report([], files_checked=3)
        assert report == "Files checked: 3\nDuplicated lines: 0\nViolations: 0"


def _make_tool(tmp_path: Path, strict: bool = False) -> CheckDupTool:
    tool = CheckDupTool(parent=None)
    tool._parsed_args = argparse.Namespace(
        dir=str(tmp_path), min_lines=8, strict=strict, exclude=None
    )
    tool._logger = MagicMock()
    return tool


@pytest.mark.unit
class TestCheckDupTool:
    """Test CheckDupTool.run() against pylint."""

    def test_reports_duplicate_across_files(self, tmp_path: Path, capsys):
        for name in ("a", "b"):
            (tmp_path / f"{name}.py").write_text(
                f"def {name}(total):\n{_BODY}\n    return total\n"
            )

        assert _make_tool(tmp_path).run() == EXIT_CODE_WARNING
        out = capsys.readouterr().out
        assert "duplicate block in 2 places:" in out
        assert "Violations: 1" in out

    def test_strict_mode_fails(self, tmp_path: Path):
        for name in ("a", "b"):
            (tmp_path / f"{name}.py").write_text(
                f"def {name}(total):\n{_BODY}\n    return total\n"
            )
        assert _make_tool(tmp_path, strict=True).run() == 1

    def test_clean_tree_exits_zero(self, tmp_path: Path):
        (tmp_path / "a.py").write_text("x = 1\n")
        assert _make_tool(tmp_path).run() == 0

    def test_no_files_exits_zero(self, tmp_path: Path):
        tool = _make_tool(tmp_path)
        assert tool.run() == 0
        tool._logger.warning.assert_called()

    def test_pylint_failure_exits_one(self, tmp_path: Path):
        (tmp_path / "a.py").write_text("x = 1\n")
        failed = subprocess.CompletedProcess([], 1, stdout="", stderr="No module")
        tool = _make_tool(tmp_path)
        with patch("appinfra.cli.tools.cq.dup.subprocess.run", return_value=failed):
            assert tool.run() == 1
        tool._logger.warning.assert_called()

    def test_command_passes_threshold_and_files(self):
        cmd = pylint_command([Path("a.py")], 6)
        assert "--min-similarity-lines=6" in cmd
        assert cmd[-1] == "a.py"

    def test_args(self):
        parser = argparse.ArgumentParser()
        CheckDupTool(parent=None).add_args(parser)
        args = parser.parse_args(["pkg", "--min-lines", "5", "--strict"])
        assert (args.dir, args.min_lines, args.strict) == ("pkg", 5, True)
