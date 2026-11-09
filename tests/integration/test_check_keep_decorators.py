# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""The settings check.sh (make check) and Makefile.dev's cq targets pass to cq: nothing in
APPINFRA_DEV_CQ_DEAD_KEEP_DECORATORS or APPINFRA_DEV_CQ_EXCLUDE runs in a shell."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
CHECK_SH = REPO / "appinfra" / "scripts" / "check.sh"
MAKE_DIR = REPO / "appinfra" / "scripts" / "make"


def _env(settings: dict[str, str]) -> dict[str, str]:
    """The test environment with the given settings, for a project of one package, pkg.

    It drops the settings a surrounding make check exports, and puts this checkout first on the
    path, so the CLI under test is the source tree's.
    """
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("INFRA_", "APPINFRA_", "_APPINFRA_", "MAKE"))
    }
    return {
        **env,
        "PYTHON": sys.executable,
        "PYTHONPATH": str(REPO),
        "APPINFRA_DEV_PKG_NAME": "pkg",
        **settings,
    }


def _check(project: Path, settings: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run check.sh over a one-module package with the given settings.

    The package passes every check that runs before the code quality check, so a setting
    reaches cq_tool's eval unless check.sh stops it.
    """
    package = project / "pkg"
    package.mkdir(exist_ok=True)
    (package / "__init__.py").write_text('"""A package for the check."""\n')
    env = _env(
        {
            "APPINFRA_DEV_PROJECT_ROOT": str(project),
            "APPINFRA_DEV_DOCSTRING_THRESHOLD": "0",
            **settings,
        }
    )
    return subprocess.run(
        ["bash", str(CHECK_SH), "--skip-tests"],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


# Each setting check.sh puts in a command, with a value that would break the command
@pytest.mark.parametrize(
    ("name", "value", "what"),
    [
        (
            "APPINFRA_DEV_CQ_DEAD_KEEP_DECORATORS",
            "a$(date>{marker})",
            "decorator names",
        ),
        ("APPINFRA_DEV_CQ_DEAD_KEEP_DECORATORS", "a`date>{marker}`", "decorator names"),
        ("APPINFRA_DEV_CQ_DEAD_KEEP_DECORATORS", "*", "decorator names"),
        ("APPINFRA_DEV_PKG_NAME", "pkg;touch {marker}", "a package name"),
        ("APPINFRA_DEV_CQ_LINT_SELECT", "C90;touch {marker}", "ruff rule codes"),
        ("APPINFRA_DEV_DOCSTRING_THRESHOLD", "0;touch {marker}", "a percent"),
        ("APPINFRA_PYTEST_BOUND_SUITES", "e2e;touch {marker}", "a list of suites"),
        ("APPINFRA_PYTEST_COVERAGE_THRESHOLD", "150", "a percent"),
    ],
)
def test_a_bad_setting_stops_check_sh_and_runs_nothing(
    tmp_path: Path, name: str, value: str, what: str
) -> None:
    marker = tmp_path / "ran"
    value = value.format(marker=marker)
    result = _check(tmp_path, {name: value})

    assert result.returncode == 2
    assert f"{name}={value} is not" in result.stderr and what in result.stderr
    assert not marker.exists()


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("APPINFRA_DEV_PKG_NAME", "my-pkg"),
        ("APPINFRA_PYTEST_COVERAGE_THRESHOLD", "150"),
        ("APPINFRA_DEV_DOCSTRING_THRESHOLD", "high"),
        ("APPINFRA_DEV_CQ_DEAD_KEEP_DECORATORS", "*"),
        ("APPINFRA_DEV_CQ_LINT_SELECT", "C90, SIM"),
        ("APPINFRA_PYTEST_BOUND_SUITES", "e2e smoke"),
    ],
)
def test_a_bad_setting_stops_check_sh_before_any_command(
    tmp_path: Path, name: str, value: str
) -> None:
    """Every setting is checked before check.sh runs its first command (the interpreter)."""
    marker = tmp_path / "ran"
    python = tmp_path / "python"
    python.write_text(f"#!/bin/sh\ntouch '{marker}'\nexec '{sys.executable}' \"$@\"\n")
    python.chmod(0o755)
    result = _check(tmp_path, {"PYTHON": str(python), name: value})

    assert result.returncode == 2, result.stdout + result.stderr
    assert f"{name}={value} is not" in result.stderr
    assert not marker.exists()


# An exclude pattern is any text, so it passes to cq as it is: the second pattern is a real one
# that must still exclude its file
@pytest.mark.parametrize("value", ["a$(date>{marker})", "a`date>{marker}`", 'a"b'])
def test_an_exclude_pattern_reaches_cq_as_written(tmp_path: Path, value: str) -> None:
    marker = tmp_path / "ran"
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "skipped.py").write_text(
        '"""Dead code the pattern excludes."""\n\n\ndef _gone() -> None:\n    pass\n'
    )
    pattern = value.format(marker=marker)
    settings = {
        "APPINFRA_DEV_CQ_EXCLUDE": f"{pattern} *skipped.py",
        "APPINFRA_DEV_CQ_DEAD": "strict",
    }
    result = _check(tmp_path, settings)

    assert not marker.exists()
    assert result.returncode == 0, result.stdout + result.stderr


def _make_cq_dead(
    project: Path, settings: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    """Run make cq.dead over a one-module package with the given settings."""
    package = project / "pkg"
    package.mkdir(exist_ok=True)
    (package / "__init__.py").write_text('"""A package for the check."""\n')
    (project / "Makefile").write_text(
        f"include {MAKE_DIR / 'Makefile.config'}\ninclude {MAKE_DIR / 'Makefile.dev'}\n"
    )
    return subprocess.run(
        ["make", "--no-print-directory", "cq.dead"],
        cwd=project,
        env=_env(settings),
        capture_output=True,
        text=True,
        timeout=120,
    )


# A $(...) in the setting is a make reference, expanded by make itself; the shell's own syntax
# is what must not run, a quote included
@pytest.mark.parametrize("value", ["a`date>{marker}`", "a'`date>{marker}`'"])
def test_a_non_name_fails_make_cq_dead_and_runs_nothing(
    tmp_path: Path, value: str
) -> None:
    marker = tmp_path / "ran"
    setting = {"APPINFRA_DEV_CQ_DEAD_KEEP_DECORATORS": value.format(marker=marker)}
    result = _make_cq_dead(tmp_path, setting)

    assert result.returncode != 0
    assert "not a dotted decorator name" in result.stderr
    assert not marker.exists()


# make itself refuses a '$' in the environment (Makefile.config); the shell's other syntax must
# reach cq as written
@pytest.mark.parametrize("value", ["a`date>{marker}`", "a'`date>{marker}`'", 'a"b'])
def test_an_exclude_pattern_reaches_make_cq_dead_as_written(
    tmp_path: Path, value: str
) -> None:
    marker = tmp_path / "ran"
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "skipped.py").write_text(
        '"""Dead code the pattern excludes."""\n\n\ndef _gone() -> None:\n    pass\n'
    )
    pattern = value.format(marker=marker)
    result = _make_cq_dead(
        tmp_path, {"APPINFRA_DEV_CQ_EXCLUDE": f"{pattern} *skipped.py"}
    )

    assert not marker.exists()
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Violations: 0" in result.stdout  # skipped.py was excluded
