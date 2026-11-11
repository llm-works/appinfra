# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""check.sh (make check) and the warnings mode: whether a passing check's warnings fail it
(strict, the project's pytest filterwarnings has a bare "error") or only warn.

No check needs the mode until it has passed with warnings in its log. A pytest check finds it
in its own log, from pytest_exit_warnings; any other check asks pytest for it then, so a run
whose checks have no warnings never starts a pytest run just to read the configuration.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.helpers.check_sh import FIXTURE_WORKERS

REPO = Path(__file__).resolve().parents[2]
CHECK_SH = REPO / "appinfra" / "scripts" / "check.sh"

_CONFTEST = '"""Suites."""\n\npytest_plugins = ["appinfra.pytest_suites"]\n'
_PLAIN_TEST = '"""A test."""\n\n\ndef test_plain():\n    """Passes."""\n'
# A deprecated call at interpreter exit, after pytest has removed its warning filters
_EXIT_WARNING_TEST = (
    '"""A test leaving a warning for interpreter exit."""\n\n'
    "import atexit\nimport warnings\n\n\n"
    "def _late():\n"
    '    warnings.warn("old api", DeprecationWarning, stacklevel=1)\n\n\n'
    "def test_leaves_work_for_exit():\n"
    '    """Registers the late call."""\n'
    "    atexit.register(_late)\n"
)
# ruff warns about linter settings at the top level of [tool.ruff], and still exits 0
_RUFF_TOP_LEVEL = '[tool.ruff]\nselect = ["E"]\n\n'


def _check(
    project: Path,
    filterwarnings: str,
    test: str = _PLAIN_TEST,
    pyproject: str = "",
    args: tuple[str, ...] = (),
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    """Run check.sh over a package and one unit test; return the run and the interpreter
    command lines it ran, recorded by a wrapper given as PYTHON.

    The environment drops the settings a surrounding make check exports.
    """
    (project / "pkg").mkdir()
    (project / "pkg" / "__init__.py").write_text('"""A package for the check."""\n')
    (project / "tests" / "unit").mkdir(parents=True)
    (project / "tests" / "conftest.py").write_text(_CONFTEST)
    (project / "tests" / "unit" / "test_unit.py").write_text(test)
    # Set as appinfra sets it: unset, pytest-asyncio warns at configure, an error in strict mode
    (project / "pyproject.toml").write_text(
        f"{pyproject}[tool.pytest.ini_options]\nfilterwarnings = [{filterwarnings!r}]\n"
        'asyncio_default_fixture_loop_scope = "function"\n'
    )
    calls = project / "calls.log"
    python = project / "python"
    python.write_text(
        f'#!/bin/sh\nprintf "%s\\n" "$*" >> "{calls}"\nexec "{sys.executable}" "$@"\n'
    )
    python.chmod(0o755)
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("INFRA_", "APPINFRA_", "_APPINFRA_", "MAKE", "PYTEST_"))
    }
    env |= FIXTURE_WORKERS | {
        "PYTHON": str(python),
        "PYTHONPATH": str(REPO),
        "APPINFRA_DEV_PROJECT_ROOT": str(project),
        "APPINFRA_DEV_PKG_NAME": "pkg",
        "APPINFRA_DEV_DOCSTRING_THRESHOLD": "0",
        "APPINFRA_PYTEST_COVERAGE_THRESHOLD": "0",
    }
    result = subprocess.run(
        ["bash", str(CHECK_SH), *args],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    return result, calls.read_text().splitlines() if calls.exists() else []


def _probes(calls: list[str]) -> list[str]:
    """The pytest runs that only read the configuration for the mode."""
    return [c for c in calls if "--collect-only" in c and "--ignore-glob" in c]


def test_a_run_without_warnings_reads_no_mode(tmp_path: Path) -> None:
    result, calls = _check(tmp_path, "error")
    assert result.returncode == 0, result.stdout + result.stderr
    assert _probes(calls) == [], _probes(calls)


def test_a_test_check_takes_the_mode_from_its_own_run(tmp_path: Path) -> None:
    """The exit warning fails the unit tests in strict mode without a run of its own."""
    result, calls = _check(tmp_path, "error", test=_EXIT_WARNING_TEST)
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "filterwarnings makes every warning an error" in output, output
    assert _probes(calls) == [], _probes(calls)


# The display of make check, and the plain text of check.ci
_MODES = pytest.mark.parametrize(
    "args", [(), ("--raw", "--summary")], ids=["display", "raw"]
)


@pytest.mark.parametrize(
    ("args", "failure"),
    [
        # The display gives the failure's reason below the checklist
        ((), "1 warning: filterwarnings makes every warning an error"),
        # Raw mode puts the warnings on the failure line itself
        (("--raw", "--summary"), "Formatting check failed (1 warnings)"),
    ],
    ids=["display", "raw"],
)
def test_a_tool_warning_fails_its_check_in_strict_mode(
    tmp_path: Path, args: tuple[str, ...], failure: str
) -> None:
    result, calls = _check(tmp_path, "error", pyproject=_RUFF_TOP_LEVEL, args=args)
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert failure in output, output
    assert _probes(calls), "the mode was read without asking pytest"


@_MODES
def test_a_tool_warning_only_warns_in_warn_mode(
    tmp_path: Path, args: tuple[str, ...]
) -> None:
    result, _ = _check(tmp_path, "default", pyproject=_RUFF_TOP_LEVEL, args=args)
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "filterwarnings makes every warning an error" not in output, output
    assert "warning" in output, output
