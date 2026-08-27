# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for appinfra/cli/tools/check_spdx.py."""

import argparse
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from appinfra.cli.tools.check_spdx import (
    DEFAULT_PATTERNS,
    EXCLUDE_PATTERNS,
    HEADER_SCAN_LINES,
    REQUIRED_MARKERS,
    CheckSpdxTool,
    _filter_source_files,
    _print_offenders,
    apply_header_to_text,
    apply_headers,
    build_header,
    collect_offenders,
    derive_package_name,
    missing_markers,
    tracked_source_files,
)

VALID_HEADER = build_header("appinfra", 2026)


@pytest.mark.unit
class TestMissingMarkers:
    """Test missing_markers() logic."""

    def _write(self, tmp: Path, content: str) -> Path:
        p = tmp / "sample.py"
        p.write_text(content, encoding="utf-8")
        return p

    def test_full_header_returns_empty(self, tmp_path: Path):
        p = self._write(tmp_path, VALID_HEADER + '"""x."""\n')
        assert missing_markers(p) == []

    def test_missing_both_markers(self, tmp_path: Path):
        p = self._write(tmp_path, '"""no header at all."""\n')
        assert set(missing_markers(p)) == set(REQUIRED_MARKERS)

    def test_missing_only_copyright(self, tmp_path: Path):
        p = self._write(tmp_path, "# SPDX-License-Identifier: Apache-2.0\n\nx = 1\n")
        assert missing_markers(p) == ["SPDX-FileCopyrightText:"]

    def test_header_past_scan_window_counts_as_missing(self, tmp_path: Path):
        padding = "\n" * (HEADER_SCAN_LINES + 2)
        p = self._write(tmp_path, padding + VALID_HEADER)
        assert set(missing_markers(p)) == set(REQUIRED_MARKERS)

    def test_shebang_then_header_passes(self, tmp_path: Path):
        p = self._write(tmp_path, "#!/usr/bin/env python3\n" + VALID_HEADER)
        assert missing_markers(p) == []

    def test_read_error_surfaces_as_marker(self, tmp_path: Path):
        p = tmp_path / "nonexistent.py"
        missing = missing_markers(p)
        assert missing and missing[0].startswith("read error:")


@pytest.mark.unit
class TestCollectOffenders:
    """Test collect_offenders() aggregation."""

    def test_all_pass(self, tmp_path: Path):
        good_a = tmp_path / "a.py"
        good_a.write_text(VALID_HEADER + "x = 1\n", encoding="utf-8")
        good_b = tmp_path / "b.py"
        good_b.write_text(VALID_HEADER + "y = 2\n", encoding="utf-8")
        assert collect_offenders([good_a, good_b]) == []

    def test_mixed(self, tmp_path: Path):
        good = tmp_path / "ok.py"
        good.write_text(VALID_HEADER + "x = 1\n", encoding="utf-8")
        bad = tmp_path / "bad.py"
        bad.write_text("no header\n", encoding="utf-8")
        offenders = collect_offenders([good, bad])
        assert len(offenders) == 1
        assert offenders[0][0] == bad


@pytest.mark.unit
class TestBuildHeader:
    """Test build_header() shape."""

    def test_contains_both_markers(self):
        header = build_header("foo", 2026)
        assert "SPDX-License-Identifier: Apache-2.0" in header
        assert "SPDX-FileCopyrightText: Copyright 2026 The foo Authors" in header

    def test_ends_with_blank_line(self):
        header = build_header("foo", 2026)
        assert header.endswith("\n\n")

    def test_package_and_year_interpolated(self):
        header = build_header("llm-gent", 2027)
        assert "The llm-gent Authors" in header
        assert "Copyright 2027" in header


@pytest.mark.unit
class TestApplyHeaderToText:
    """Test apply_header_to_text() text transformation."""

    def test_no_shebang(self):
        header = build_header("foo", 2026)
        result = apply_header_to_text("x = 1\n", header)
        assert result == header + "x = 1\n"

    def test_shebang_preserved_with_blank_separator(self):
        header = build_header("foo", 2026)
        result = apply_header_to_text("#!/usr/bin/env python3\nx = 1\n", header)
        # Shebang → blank line → SPDX header → blank → content
        lines = result.splitlines()
        assert lines[0] == "#!/usr/bin/env python3"
        assert lines[1] == ""
        assert lines[2] == "# SPDX-License-Identifier: Apache-2.0"

    def test_dedupes_leading_blank(self):
        header = build_header("foo", 2026)
        result = apply_header_to_text("\nx = 1\n", header)
        assert result == header + "x = 1\n"

    def test_shebang_existing_blank_not_doubled(self):
        header = build_header("foo", 2026)
        result = apply_header_to_text("#!/usr/bin/env python3\n\nx = 1\n", header)
        # File already had a blank after shebang; still exactly one blank
        # between shebang and SPDX, not two.
        assert result == "#!/usr/bin/env python3\n\n" + header + "x = 1\n"


@pytest.mark.unit
class TestDerivePackageName:
    """Test derive_package_name() pyproject.toml parsing."""

    def test_reads_project_name(self, tmp_path: Path):
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "mypkg"\nversion = "1.0"\n',
            encoding="utf-8",
        )
        assert derive_package_name(cwd=tmp_path) == "mypkg"

    def test_missing_file_raises(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            derive_package_name(cwd=tmp_path)

    def test_missing_name_field_raises(self, tmp_path: Path):
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nversion = "1.0"\n', encoding="utf-8"
        )
        with pytest.raises(KeyError):
            derive_package_name(cwd=tmp_path)


@pytest.mark.unit
class TestFilePatterns:
    """Test DEFAULT_PATTERNS and EXCLUDE_PATTERNS coverage."""

    def test_python_patterns(self):
        assert "*.py" in DEFAULT_PATTERNS
        assert "*.pyi" in DEFAULT_PATTERNS

    def test_shell_patterns(self):
        assert "*.sh" in DEFAULT_PATTERNS

    def test_makefile_patterns(self):
        assert "Makefile" in DEFAULT_PATTERNS
        assert "Makefile.*" in DEFAULT_PATTERNS

    def test_dockerfile_pattern(self):
        assert "Dockerfile" in DEFAULT_PATTERNS

    def test_in_templates_excluded(self):
        assert "*.in" in EXCLUDE_PATTERNS


@pytest.mark.unit
class TestFilterSourceFiles:
    """Test _filter_source_files() pattern matching."""

    def test_python_matched(self):
        result = _filter_source_files(["foo.py", "sub/bar.py", "baz.txt"])
        assert Path("foo.py") in result
        assert Path("sub/bar.py") in result
        assert Path("baz.txt") not in result

    def test_shell_and_pyi_matched(self):
        result = _filter_source_files(["scripts/run.sh", "types.pyi"])
        assert Path("scripts/run.sh") in result
        assert Path("types.pyi") in result

    def test_makefile_nested_matched(self):
        result = _filter_source_files(["Makefile", "scripts/Makefile.dev"])
        assert Path("Makefile") in result
        assert Path("scripts/Makefile.dev") in result

    def test_dockerfile_nested_matched(self):
        result = _filter_source_files(["Dockerfile", "sub/Dockerfile"])
        assert Path("Dockerfile") in result
        assert Path("sub/Dockerfile") in result

    def test_in_templates_excluded(self):
        result = _filter_source_files(
            ["Makefile.dev", "scaffold/Makefile.framework.in"]
        )
        assert Path("Makefile.dev") in result
        assert Path("scaffold/Makefile.framework.in") not in result

    def test_empty_lines_skipped(self):
        result = _filter_source_files(["foo.py", "", "bar.py"])
        assert len(result) == 2

    def test_no_matches_returns_empty(self):
        result = _filter_source_files(["README.md", "config.yaml"])
        assert result == []


@pytest.mark.unit
class TestApplyHeaders:
    """Test apply_headers() pure function."""

    def test_skips_when_all_have_headers(self, tmp_path: Path):
        p = tmp_path / "a.py"
        p.write_text(VALID_HEADER + "x = 1\n", encoding="utf-8")
        modified, skipped, err = apply_headers([p], VALID_HEADER, dry_run=False)
        assert modified == 0
        assert skipped == 1
        assert err is None

    def test_applies_to_missing(self, tmp_path: Path):
        p = tmp_path / "a.py"
        p.write_text("x = 1\n", encoding="utf-8")
        modified, skipped, err = apply_headers([p], VALID_HEADER, dry_run=False)
        assert modified == 1
        assert skipped == 0
        assert err is None
        assert p.read_text().startswith(VALID_HEADER)

    def test_dry_run_does_not_write(self, tmp_path: Path):
        p = tmp_path / "a.py"
        original = "x = 1\n"
        p.write_text(original, encoding="utf-8")
        modified, skipped, err = apply_headers([p], VALID_HEADER, dry_run=True)
        assert modified == 1
        assert err is None
        assert p.read_text() == original

    def test_read_error_returns_path(self, tmp_path: Path):
        missing = tmp_path / "nonexistent.py"
        modified, skipped, err = apply_headers([missing], VALID_HEADER, dry_run=False)
        assert err == missing


@pytest.mark.unit
class TestPrintOffenders:
    """Test _print_offenders() stderr output."""

    def test_prints_offender_list_to_stderr(self, capsys, tmp_path: Path):
        p = tmp_path / "bad.py"
        _print_offenders([(p, ["SPDX-License-Identifier: Apache-2.0"])])
        captured = capsys.readouterr()
        assert "FAIL: 1 source file(s)" in captured.err
        assert str(p) in captured.err
        assert "SPDX-License-Identifier" in captured.err
        assert "appinfra cq spdx --fix" in captured.err

    def test_empty_offenders_still_prints_header(self, capsys):
        _print_offenders([])
        captured = capsys.readouterr()
        assert "FAIL: 0 source file(s)" in captured.err


@pytest.mark.unit
class TestTrackedSourceFiles:
    """Test tracked_source_files() with mocked git subprocess."""

    def test_shells_out_and_filters(self, monkeypatch):
        result = MagicMock()
        result.stdout = "foo.py\nbar.sh\nREADME.md\nMakefile\n"
        monkeypatch.setattr(
            "appinfra.cli.tools.check_spdx.subprocess.run",
            lambda *a, **kw: result,
        )
        files = tracked_source_files()
        assert Path("foo.py") in files
        assert Path("bar.sh") in files
        assert Path("Makefile") in files
        assert Path("README.md") not in files


@pytest.mark.unit
class TestCheckSpdxToolConstruction:
    """Test CheckSpdxTool argparse wiring."""

    def test_init_registers_name_and_aliases(self):
        tool = CheckSpdxTool(parent=None)
        assert tool.config.name == "check-spdx"
        assert "spdx" in tool.config.aliases

    def test_add_args_registers_all_flags(self):
        tool = CheckSpdxTool(parent=None)
        parser = argparse.ArgumentParser()
        tool.add_args(parser)
        args = parser.parse_args(
            ["--fix", "--dry-run", "--package", "foo", "--year", "2026"]
        )
        assert args.fix is True
        assert args.dry_run is True
        assert args.package == "foo"
        assert args.year == 2026

    def test_add_args_defaults(self):
        tool = CheckSpdxTool(parent=None)
        parser = argparse.ArgumentParser()
        tool.add_args(parser)
        args = parser.parse_args([])
        assert args.fix is False
        assert args.dry_run is False
        assert args.package is None
        assert args.year is None


def _make_tool(**arg_overrides) -> CheckSpdxTool:
    """Build a CheckSpdxTool with mocked lg and args namespace."""
    defaults = {"fix": False, "dry_run": False, "package": None, "year": None}
    defaults.update(arg_overrides)
    tool = CheckSpdxTool(parent=None)
    tool._parsed_args = argparse.Namespace(**defaults)
    tool._logger = MagicMock()
    return tool


@pytest.mark.unit
class TestCheckSpdxToolMethods:
    """Test CheckSpdxTool instance methods (args + lg injected directly)."""

    def test_apply_headers_to_files_success(self, tmp_path: Path):
        p = tmp_path / "a.py"
        p.write_text("x = 1\n", encoding="utf-8")
        tool = _make_tool(dry_run=True)
        assert tool._apply_headers_to_files([p], VALID_HEADER) == (1, 0)

    def test_apply_headers_to_files_read_error(self, tmp_path: Path):
        missing = tmp_path / "nonexistent.py"
        tool = _make_tool()
        assert tool._apply_headers_to_files([missing], VALID_HEADER) is None
        tool._logger.warning.assert_called_once()

    def test_run_check_returns_0_when_clean(self, tmp_path: Path):
        p = tmp_path / "a.py"
        p.write_text(VALID_HEADER + "x = 1\n", encoding="utf-8")
        tool = _make_tool()
        assert tool._run_check([p]) == 0

    def test_run_check_returns_1_when_missing(self, tmp_path: Path, capsys):
        p = tmp_path / "bad.py"
        p.write_text("no header\n", encoding="utf-8")
        tool = _make_tool()
        assert tool._run_check([p]) == 1

    def test_run_fix_returns_0(self, tmp_path: Path):
        p = tmp_path / "a.py"
        p.write_text("x = 1\n", encoding="utf-8")
        tool = _make_tool(dry_run=True, package="foo", year=2026)
        assert tool._run_fix([p]) == 0

    def test_run_fix_returns_1_when_pyproject_missing(
        self, tmp_path: Path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        tool = _make_tool()
        assert tool._run_fix([]) == 1
        tool._logger.warning.assert_called()

    def test_run_dispatches_to_fix(self, tmp_path: Path, monkeypatch):
        result = MagicMock()
        result.stdout = ""
        monkeypatch.setattr(
            "appinfra.cli.tools.check_spdx.subprocess.run",
            lambda *a, **kw: result,
        )
        tool = _make_tool(fix=True, dry_run=True, package="foo", year=2026)
        assert tool.run() == 0

    def test_run_dispatches_to_check(self, tmp_path: Path, monkeypatch):
        result = MagicMock()
        result.stdout = ""
        monkeypatch.setattr(
            "appinfra.cli.tools.check_spdx.subprocess.run",
            lambda *a, **kw: result,
        )
        tool = _make_tool(fix=False)
        assert tool.run() == 0
