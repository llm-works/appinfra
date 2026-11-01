# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""appinfra_suite_markers in appinfra/scripts/_settings.sh: the suites check.sh finds tests for.
A suite neither named by a marker nor given a directory under tests/ is reported as "no tests"
without running pytest."""

import subprocess
from pathlib import Path

SETTINGS_SH = (
    Path(__file__).resolve().parents[2] / "appinfra" / "scripts" / "_settings.sh"
)


def _suites(project: Path, *args: str) -> set[str]:
    result = subprocess.run(
        ["bash", "-c", f'. "{SETTINGS_SH}"; appinfra_suite_markers "$@"', "_", *args],
        cwd=project,
        capture_output=True,
        text=True,
        check=True,
    )
    return set(result.stdout.split())


def _write(path: Path, source: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source)


def test_a_marker_named_in_a_test_file_is_found(tmp_path: Path) -> None:
    _write(
        tmp_path / "tests" / "test_a.py",
        "import pytest\n\n\n@pytest.mark.security\ndef test_a():\n    pass\n",
    )
    assert "security" in _suites(tmp_path)


def test_a_suite_directory_is_found_without_markers(tmp_path: Path) -> None:
    _write(
        tmp_path / "tests" / "performance" / "test_p.py", "def test_p():\n    pass\n"
    )
    assert "performance" in _suites(tmp_path)


def test_a_suite_with_neither_is_not_found(tmp_path: Path) -> None:
    _write(tmp_path / "tests" / "unit" / "test_u.py", "def test_u():\n    pass\n")
    assert "performance" not in _suites(tmp_path)


def test_markers_in_the_performance_directory_are_found(tmp_path: Path) -> None:
    _write(
        tmp_path / "bench" / "test_b.py",
        "import pytest\n\n\n@pytest.mark.performance\ndef test_b():\n    pass\n",
    )
    _write(tmp_path / "tests" / "unit" / "test_u.py", "def test_u():\n    pass\n")
    assert "performance" in _suites(tmp_path, "bench")
