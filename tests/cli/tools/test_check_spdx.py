# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for appinfra/cli/tools/check_spdx.py."""

from pathlib import Path

import pytest

from appinfra.cli.tools.check_spdx import (
    DEFAULT_PATTERNS,
    EXCLUDE_PATTERNS,
    HEADER_SCAN_LINES,
    REQUIRED_MARKERS,
    apply_header_to_text,
    build_header,
    collect_offenders,
    derive_package_name,
    missing_markers,
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
        p = self._write(
            tmp_path, "# SPDX-License-Identifier: Apache-2.0\n\nx = 1\n"
        )
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
