# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for appinfra/cli/tools/cq/spdx.py."""

import argparse
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from appinfra.cli.tools.cq.spdx import (
    COPYRIGHT_MARKER,
    DEFAULT_LICENSE,
    DEFAULT_PATTERNS,
    EXCLUDE_PATTERNS,
    HEADER_SCAN_LINES,
    LICENSE_MARKER,
    CheckSpdxTool,
    _filter_source_files,
    _missing,
    _print_conflicts,
    _print_offenders,
    apply_header_to_text,
    apply_headers,
    build_header,
    check_license,
    collect_offenders,
    derive_license,
    derive_package_name,
    missing_markers,
    tracked_source_files,
)

LICENSE = "Apache-2.0"
VALID_HEADER = build_header("appinfra", 2026, LICENSE)
REQUIRED_MARKERS = {f"{LICENSE_MARKER} {LICENSE}", COPYRIGHT_MARKER}


@pytest.mark.integration
class TestMissingMarkers:
    """Test missing_markers() logic."""

    def _write(self, tmp: Path, content: str) -> Path:
        p = tmp / "sample.py"
        p.write_text(content, encoding="utf-8")
        return p

    def test_full_header_returns_empty(self, tmp_path: Path):
        p = self._write(tmp_path, VALID_HEADER + '"""x."""\n')
        assert missing_markers(p, LICENSE) == []

    def test_missing_both_markers(self, tmp_path: Path):
        p = self._write(tmp_path, '"""no header at all."""\n')
        assert set(missing_markers(p, LICENSE)) == REQUIRED_MARKERS

    def test_missing_only_copyright(self, tmp_path: Path):
        p = self._write(tmp_path, "# SPDX-License-Identifier: Apache-2.0\n\nx = 1\n")
        assert missing_markers(p, LICENSE) == ["SPDX-FileCopyrightText:"]

    def test_header_past_scan_window_counts_as_missing(self, tmp_path: Path):
        padding = "\n" * (HEADER_SCAN_LINES + 2)
        p = self._write(tmp_path, padding + VALID_HEADER)
        assert set(missing_markers(p, LICENSE)) == REQUIRED_MARKERS

    def test_shebang_then_header_passes(self, tmp_path: Path):
        p = self._write(tmp_path, "#!/usr/bin/env python3\n" + VALID_HEADER)
        assert missing_markers(p, LICENSE) == []

    def test_read_error_surfaces_as_marker(self, tmp_path: Path):
        p = tmp_path / "nonexistent.py"
        missing = missing_markers(p, LICENSE)
        assert missing and missing[0].startswith("read error:")

    def test_header_of_another_license_misses_the_license_marker(self, tmp_path: Path):
        p = self._write(tmp_path, VALID_HEADER + "x = 1\n")
        assert missing_markers(p, "MIT") == [f"{LICENSE_MARKER} MIT"]


@pytest.mark.integration
class TestCollectOffenders:
    """Test collect_offenders() aggregation."""

    def test_all_pass(self, tmp_path: Path):
        good_a = tmp_path / "a.py"
        good_a.write_text(VALID_HEADER + "x = 1\n", encoding="utf-8")
        good_b = tmp_path / "b.py"
        good_b.write_text(VALID_HEADER + "y = 2\n", encoding="utf-8")
        assert collect_offenders([good_a, good_b], LICENSE) == []

    def test_mixed(self, tmp_path: Path):
        good = tmp_path / "ok.py"
        good.write_text(VALID_HEADER + "x = 1\n", encoding="utf-8")
        bad = tmp_path / "bad.py"
        bad.write_text("no header\n", encoding="utf-8")
        offenders = collect_offenders([good, bad], LICENSE)
        assert len(offenders) == 1
        assert offenders[0][0] == bad


@pytest.mark.unit
class TestBuildHeader:
    """Test build_header() shape."""

    def test_contains_both_markers(self):
        header = build_header("foo", 2026, LICENSE)
        assert "SPDX-License-Identifier: Apache-2.0" in header
        assert "SPDX-FileCopyrightText: Copyright 2026 The foo Authors" in header

    def test_ends_with_blank_line(self):
        header = build_header("foo", 2026, LICENSE)
        assert header.endswith("\n\n")

    def test_package_and_year_interpolated(self):
        header = build_header("llm-gent", 2027, LICENSE)
        assert "The llm-gent Authors" in header
        assert "Copyright 2027" in header

    def test_license_interpolated(self):
        header = build_header("docs", 2026, "MIT OR Apache-2.0")
        assert header.startswith("# SPDX-License-Identifier: MIT OR Apache-2.0\n")


@pytest.mark.unit
class TestLicenseMatching:
    """The license line must declare exactly the expected expression."""

    def _head(self, license_line: str) -> list[str]:
        return [f"# {LICENSE_MARKER} {license_line}", f"# {COPYRIGHT_MARKER} x"]

    def test_exact_expression_matches(self):
        assert _missing(self._head("MIT"), "MIT") == []

    def test_whitespace_around_the_expression_is_ignored(self):
        assert _missing(self._head("  MIT  "), "MIT") == []

    @pytest.mark.parametrize(
        ("declared", "expected"),
        [
            ("MIT-0", "MIT"),
            ("Apache-2.0 WITH LLVM-exception", "Apache-2.0"),
            ("Apache-2.0", "MIT"),
            ("MIT OR Apache-2.0", "MIT"),
        ],
    )
    def test_other_expressions_do_not_match(self, declared: str, expected: str):
        assert _missing(self._head(declared), expected) == [
            f"{LICENSE_MARKER} {expected}"
        ]


@pytest.mark.unit
class TestCheckLicense:
    """check_license() accepts one-line expressions only."""

    def test_strips_and_returns(self):
        assert check_license("  MIT ", "--license") == "MIT"

    @pytest.mark.parametrize("value", ["", "   ", "MIT\nx", "MIT\r", None, 3])
    def test_rejects_what_cannot_go_in_a_header(self, value: object):
        with pytest.raises(ValueError, match="--license"):
            check_license(value, "--license")


@pytest.mark.unit
class TestApplyHeaderToText:
    """Test apply_header_to_text() text transformation."""

    def test_no_shebang(self):
        header = build_header("foo", 2026, LICENSE)
        result = apply_header_to_text("x = 1\n", header)
        assert result == header + "x = 1\n"

    def test_shebang_preserved_with_blank_separator(self):
        header = build_header("foo", 2026, LICENSE)
        result = apply_header_to_text("#!/usr/bin/env python3\nx = 1\n", header)
        # Shebang → blank line → SPDX header → blank → content
        lines = result.splitlines()
        assert lines[0] == "#!/usr/bin/env python3"
        assert lines[1] == ""
        assert lines[2] == "# SPDX-License-Identifier: Apache-2.0"

    def test_dedupes_leading_blank(self):
        header = build_header("foo", 2026, LICENSE)
        result = apply_header_to_text("\nx = 1\n", header)
        assert result == header + "x = 1\n"

    def test_shebang_existing_blank_not_doubled(self):
        header = build_header("foo", 2026, LICENSE)
        result = apply_header_to_text("#!/usr/bin/env python3\n\nx = 1\n", header)
        # File already had a blank after shebang; still exactly one blank
        # between shebang and SPDX, not two.
        assert result == "#!/usr/bin/env python3\n\n" + header + "x = 1\n"


@pytest.mark.integration
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


def _pyproject(tmp: Path, body: str) -> Path:
    """Write a pyproject.toml with ``body`` under tmp; return tmp."""
    (tmp / "pyproject.toml").write_text(body, encoding="utf-8")
    return tmp


@pytest.mark.integration
class TestDeriveLicense:
    """derive_license() reads the PEP 639 [project] license expression."""

    def test_reads_the_expression(self, tmp_path: Path):
        root = _pyproject(tmp_path, '[project]\nname = "d"\nlicense = "MIT"\n')
        assert derive_license(cwd=root) == "MIT"

    def test_compound_expression_kept_whole(self, tmp_path: Path):
        root = _pyproject(tmp_path, '[project]\nlicense = "MIT OR Apache-2.0"\n')
        assert derive_license(cwd=root) == "MIT OR Apache-2.0"

    def test_missing_field_falls_back(self, tmp_path: Path):
        root = _pyproject(tmp_path, '[project]\nname = "d"\n')
        assert derive_license(cwd=root) == DEFAULT_LICENSE == "Apache-2.0"

    def test_missing_project_table_falls_back(self, tmp_path: Path):
        root = _pyproject(tmp_path, "[tool.x]\ny = 1\n")
        assert derive_license(cwd=root) == DEFAULT_LICENSE

    def test_missing_file_falls_back(self, tmp_path: Path):
        assert derive_license(cwd=tmp_path) == DEFAULT_LICENSE

    def test_file_gone_before_it_is_opened_falls_back(
        self, tmp_path: Path, monkeypatch
    ):
        """Only a missing file means the default; there is no check-then-open window."""
        root = _pyproject(tmp_path, '[project]\nlicense = "MIT"\n')

        def vanished(*args: object, **kwargs: object) -> None:
            raise FileNotFoundError("removed")

        monkeypatch.setattr(Path, "open", vanished)
        assert derive_license(cwd=root) == DEFAULT_LICENSE

    def test_unreadable_file_raises(self, tmp_path: Path, monkeypatch):
        """An unreadable pyproject.toml is an error, not a reason to assume Apache-2.0."""
        root = _pyproject(tmp_path, '[project]\nlicense = "MIT"\n')

        def denied(*args: object, **kwargs: object) -> None:
            raise PermissionError("denied")

        monkeypatch.setattr(Path, "open", denied)
        with pytest.raises(PermissionError):
            derive_license(cwd=root)

    @pytest.mark.parametrize(
        "body",
        [
            '[project]\nlicense = {text = "MIT"}\n',
            '[project]\nlicense = {file = "LICENSE"}\n',
            '[project]\nlicense = ""\n',
            "[project]\nlicense = 3\n",
            "[project\n",
        ],
        ids=["text-table", "file-table", "empty", "number", "bad-toml"],
    )
    def test_unusable_value_raises(self, tmp_path: Path, body: str):
        with pytest.raises(ValueError):
            derive_license(cwd=_pyproject(tmp_path, body))


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


@pytest.mark.integration
class TestApplyHeaders:
    """Test apply_headers() pure function."""

    def test_skips_when_all_have_headers(self, tmp_path: Path):
        p = tmp_path / "a.py"
        p.write_text(VALID_HEADER + "x = 1\n", encoding="utf-8")
        result = apply_headers([p], VALID_HEADER, LICENSE, dry_run=False)
        assert (result.modified, result.skipped, result.error) == (0, 1, None)

    def test_applies_to_missing(self, tmp_path: Path):
        p = tmp_path / "a.py"
        p.write_text("x = 1\n", encoding="utf-8")
        result = apply_headers([p], VALID_HEADER, LICENSE, dry_run=False)
        assert (result.modified, result.skipped, result.error) == (1, 0, None)
        assert p.read_text().startswith(VALID_HEADER)

    def test_dry_run_does_not_write(self, tmp_path: Path):
        p = tmp_path / "a.py"
        original = "x = 1\n"
        p.write_text(original, encoding="utf-8")
        result = apply_headers([p], VALID_HEADER, LICENSE, dry_run=True)
        assert (result.modified, result.error) == (1, None)
        assert p.read_text() == original

    def test_read_error_returns_path(self, tmp_path: Path):
        missing = tmp_path / "nonexistent.py"
        result = apply_headers([missing], VALID_HEADER, LICENSE, dry_run=False)
        assert result.error == missing

    def test_write_error_returns_path(self, tmp_path: Path, monkeypatch):
        p = tmp_path / "a.py"
        p.write_text("x = 1\n", encoding="utf-8")

        def refuse(*args: object, **kwargs: object) -> None:
            raise PermissionError("read-only")

        monkeypatch.setattr(Path, "write_text", refuse)
        result = apply_headers([p], VALID_HEADER, LICENSE, dry_run=False)
        assert (result.modified, result.error) == (0, p)

    def test_header_of_another_license_is_left_alone(self, tmp_path: Path):
        """Prepending would give the file two license lines; it is reported instead."""
        apache = tmp_path / "copied.py"
        apache.write_text(VALID_HEADER + "x = 1\n", encoding="utf-8")
        bare = tmp_path / "new.py"
        bare.write_text("y = 2\n", encoding="utf-8")
        mit_header = build_header("docs", 2026, "MIT")
        result = apply_headers([apache, bare], mit_header, "MIT", dry_run=False)
        assert result.conflicts == [apache]
        assert result.modified == 1
        assert apache.read_text() == VALID_HEADER + "x = 1\n"
        assert bare.read_text().startswith(mit_header)


@pytest.mark.unit
class TestPrintOffenders:
    """Test _print_offenders() stderr output."""

    @pytest.mark.integration
    def test_prints_offender_list_to_stderr(self, capsys, tmp_path: Path):
        p = tmp_path / "bad.py"
        _print_offenders([(p, ["SPDX-License-Identifier: Apache-2.0"])], LICENSE)
        captured = capsys.readouterr()
        assert "FAIL: 1 source file(s)" in captured.err
        assert str(p) in captured.err
        assert "SPDX-License-Identifier" in captured.err
        assert "appinfra cq spdx --fix" in captured.err

    def test_empty_offenders_still_prints_header(self, capsys):
        _print_offenders([], LICENSE)
        captured = capsys.readouterr()
        assert "FAIL: 0 source file(s)" in captured.err

    def test_example_header_carries_the_license(self, capsys):
        _print_offenders([], "MIT")
        assert "    # SPDX-License-Identifier: MIT\n" in capsys.readouterr().err

    def test_conflicts_listed_with_the_expected_license(self, capsys):
        _print_conflicts([Path("copied.py")], "MIT")
        err = capsys.readouterr().err
        assert "1 source file(s) declare a license other than MIT" in err
        assert "  copied.py" in err


@pytest.mark.unit
class TestTrackedSourceFiles:
    """Test tracked_source_files() with mocked git subprocess."""

    def test_shells_out_and_filters(self, monkeypatch):
        result = MagicMock()
        result.stdout = "foo.py\nbar.sh\nREADME.md\nMakefile\n"
        monkeypatch.setattr(
            "appinfra.cli.tools.cq.spdx.subprocess.run",
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
            [
                "--fix",
                "--dry-run",
                "--package",
                "foo",
                "--year",
                "2026",
                "--license",
                "MIT",
            ]
        )
        assert args.fix is True
        assert args.dry_run is True
        assert args.package == "foo"
        assert args.year == 2026
        assert args.license == "MIT"

    def test_add_args_defaults(self):
        tool = CheckSpdxTool(parent=None)
        parser = argparse.ArgumentParser()
        tool.add_args(parser)
        args = parser.parse_args([])
        assert args.fix is False
        assert args.dry_run is False
        assert args.package is None
        assert args.year is None
        assert args.license is None

    def test_invalid_license_flag_is_refused(self):
        tool = _make_tool(license="MIT\n# injected")
        assert tool._license() is None
        tool._logger.warning.assert_called_once()

    def test_license_flag_wins(self):
        assert _make_tool(license="MIT")._license() == "MIT"


def _make_tool(**arg_overrides) -> CheckSpdxTool:
    """Build a CheckSpdxTool with mocked lg and args namespace."""
    defaults = {
        "fix": False,
        "dry_run": False,
        "package": None,
        "year": None,
        "license": None,
    }
    defaults.update(arg_overrides)
    tool = CheckSpdxTool(parent=None)
    tool._parsed_args = argparse.Namespace(**defaults)
    tool._logger = MagicMock()
    return tool


@pytest.mark.integration
class TestCheckSpdxToolMethods:
    """Test CheckSpdxTool instance methods (args + lg injected directly)."""

    def test_apply_headers_to_files_success(self, tmp_path: Path):
        p = tmp_path / "a.py"
        p.write_text("x = 1\n", encoding="utf-8")
        tool = _make_tool(dry_run=True)
        result = tool._apply_headers_to_files([p], VALID_HEADER, LICENSE)
        assert result is not None
        assert (result.modified, result.skipped) == (1, 0)

    def test_apply_headers_to_files_read_error(self, tmp_path: Path):
        missing = tmp_path / "nonexistent.py"
        tool = _make_tool()
        assert tool._apply_headers_to_files([missing], VALID_HEADER, LICENSE) is None
        tool._logger.warning.assert_called_once()

    def test_run_check_returns_0_when_clean(self, tmp_path: Path):
        p = tmp_path / "a.py"
        p.write_text(VALID_HEADER + "x = 1\n", encoding="utf-8")
        tool = _make_tool()
        assert tool._run_check([p], LICENSE) == 0

    def test_run_check_returns_1_when_missing(self, tmp_path: Path, capsys):
        p = tmp_path / "bad.py"
        p.write_text("no header\n", encoding="utf-8")
        tool = _make_tool()
        assert tool._run_check([p], LICENSE) == 1

    def test_run_fix_returns_0(self, tmp_path: Path):
        p = tmp_path / "a.py"
        p.write_text("x = 1\n", encoding="utf-8")
        tool = _make_tool(dry_run=True, package="foo", year=2026)
        assert tool._run_fix([p], LICENSE) == 0

    def test_run_fix_returns_1_on_another_license(self, tmp_path: Path, capsys):
        p = tmp_path / "copied.py"
        p.write_text(VALID_HEADER + "x = 1\n", encoding="utf-8")
        tool = _make_tool(package="docs", year=2026)
        assert tool._run_fix([p], "MIT") == 1
        assert "declare a license other than MIT" in capsys.readouterr().err
        assert p.read_text() == VALID_HEADER + "x = 1\n"

    def test_run_fix_returns_1_when_pyproject_missing(
        self, tmp_path: Path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        tool = _make_tool()
        assert tool._run_fix([], LICENSE) == 1
        tool._logger.warning.assert_called()

    def test_run_fix_returns_1_when_pyproject_is_not_toml(
        self, tmp_path: Path, monkeypatch
    ):
        """A malformed pyproject.toml is reported, not raised, when the name is needed."""
        _pyproject(tmp_path, "[project\n")
        monkeypatch.chdir(tmp_path)
        tool = _make_tool(fix=True, license="MIT")
        assert tool._run_fix([], "MIT") == 1
        tool._logger.warning.assert_called_once()

    def test_run_dispatches_to_fix(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = MagicMock()
        result.stdout = ""
        monkeypatch.setattr(
            "appinfra.cli.tools.cq.spdx.subprocess.run",
            lambda *a, **kw: result,
        )
        tool = _make_tool(fix=True, dry_run=True, package="foo", year=2026)
        assert tool.run() == 0

    def test_run_dispatches_to_check(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = MagicMock()
        result.stdout = ""
        monkeypatch.setattr(
            "appinfra.cli.tools.cq.spdx.subprocess.run",
            lambda *a, **kw: result,
        )
        tool = _make_tool(fix=False)
        assert tool.run() == 0


def _project(tmp: Path, license_line: str, files: dict[str, str], monkeypatch) -> None:
    """Make tmp a project: pyproject.toml, the given files, git ls-files listing them."""
    _pyproject(tmp, f'[project]\nname = "proj"\n{license_line}')
    for name, text in files.items():
        (tmp / name).write_text(text, encoding="utf-8")
    listing = MagicMock()
    listing.stdout = "\n".join(files)
    monkeypatch.setattr(
        "appinfra.cli.tools.cq.spdx.subprocess.run", lambda *a, **kw: listing
    )
    monkeypatch.chdir(tmp)


@pytest.mark.integration
class TestProjectLicense:
    """run() checks and writes the license the project's pyproject.toml declares."""

    def test_mit_project_passes_with_mit_headers(self, tmp_path: Path, monkeypatch):
        mit = build_header("proj", 2026, "MIT")
        _project(tmp_path, 'license = "MIT"\n', {"a.py": mit + "x = 1\n"}, monkeypatch)
        assert _make_tool().run() == 0

    def test_mit_project_fails_on_an_apache_header(
        self, tmp_path: Path, monkeypatch, capsys
    ):
        files = {"a.py": VALID_HEADER + "x = 1\n"}
        _project(tmp_path, 'license = "MIT"\n', files, monkeypatch)
        assert _make_tool().run() == 1
        assert "SPDX-License-Identifier: MIT" in capsys.readouterr().err

    def test_project_without_license_keeps_apache(self, tmp_path: Path, monkeypatch):
        _project(tmp_path, "", {"a.py": VALID_HEADER + "x = 1\n"}, monkeypatch)
        assert _make_tool().run() == 0

    def test_fix_writes_the_project_license(self, tmp_path: Path, monkeypatch):
        _project(tmp_path, 'license = "MIT"\n', {"a.py": "x = 1\n"}, monkeypatch)
        assert _make_tool(fix=True, year=2026).run() == 0
        assert (tmp_path / "a.py").read_text() == build_header(
            "proj", 2026, "MIT"
        ) + "x = 1\n"

    def test_license_flag_overrides_pyproject(self, tmp_path: Path, monkeypatch):
        mit = build_header("proj", 2026, "MIT")
        files = {"a.py": mit + "x = 1\n"}
        _project(tmp_path, 'license = "Apache-2.0"\n', files, monkeypatch)
        assert _make_tool(license="MIT").run() == 0

    def test_table_license_stops_the_check(self, tmp_path: Path, monkeypatch):
        _project(tmp_path, 'license = {text = "MIT"}\n', {}, monkeypatch)
        tool = _make_tool()
        assert tool.run() == 1
        tool._logger.warning.assert_called_once()

    def test_unreadable_pyproject_stops_the_check(self, tmp_path: Path, monkeypatch):
        """Reported and exit 1, not a traceback."""
        _project(tmp_path, 'license = "MIT"\n', {}, monkeypatch)

        def denied(*args: object, **kwargs: object) -> None:
            raise PermissionError("denied")

        monkeypatch.setattr(Path, "open", denied)
        tool = _make_tool()
        assert tool.run() == 1
        tool._logger.warning.assert_called_once()
