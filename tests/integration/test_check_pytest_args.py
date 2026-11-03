# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""APPINFRA_PYTEST_ARGS reaches the test runs of check.sh (make check)."""

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CHECK_SH = REPO / "appinfra" / "scripts" / "check.sh"

_CONFTEST = '''"""Options for the tests."""

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    """Add --x-marker and --x-value."""
    parser.addoption("--x-marker", action="store_true")
    parser.addoption("--x-value")


def pytest_configure(config: pytest.Config) -> None:
    """Register the unit marker."""
    config.addinivalue_line("markers", "unit: unit tests")
'''

_TEST = '''"""A test that passes only when pytest was given --x-marker."""

import pytest


@pytest.mark.unit
def test_option_given(request: pytest.FixtureRequest) -> None:
    """The option reached pytest."""
    assert request.config.getoption("--x-marker")
'''

_TEST_VALUE = '''"""A test that passes only when pytest was given --x-value with a | in it."""

import pytest


@pytest.mark.unit
def test_value_whole(request: pytest.FixtureRequest) -> None:
    """The value reached pytest whole."""
    assert request.config.getoption("--x-value") == "a|b"
'''


def _check(
    project: Path, settings: dict[str, str], test: str = _TEST
) -> subprocess.CompletedProcess[str]:
    """Run check.sh over a package and one scratch test, with the given settings.

    The environment drops the settings a surrounding make check exports.
    """
    (project / "pkg").mkdir()
    (project / "pkg" / "__init__.py").write_text('"""A package for the check."""\n')
    (project / "tests").mkdir()
    (project / "tests" / "conftest.py").write_text(_CONFTEST)
    (project / "tests" / "test_option.py").write_text(test)
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("INFRA_", "APPINFRA_", "_APPINFRA_", "MAKE", "PYTEST_"))
    }
    env |= {
        "PYTHON": sys.executable,
        "PYTHONPATH": str(REPO),
        "APPINFRA_DEV_PROJECT_ROOT": str(project),
        "APPINFRA_DEV_PKG_NAME": "pkg",
        "APPINFRA_DEV_DOCSTRING_THRESHOLD": "0",
        "APPINFRA_PYTEST_COVERAGE_THRESHOLD": "0",
        **settings,
    }
    return subprocess.run(
        ["bash", str(CHECK_SH)],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )


def test_args_reach_the_test_runs(tmp_path: Path) -> None:
    result = _check(tmp_path, {"APPINFRA_PYTEST_ARGS": "--x-marker"})
    assert result.returncode == 0, result.stdout + result.stderr


def test_an_arg_with_a_pipe_reaches_the_test_runs_whole(tmp_path: Path) -> None:
    """check.sh keeps each run in a |-separated record; the args must not be split there."""
    result = _check(tmp_path, {"APPINFRA_PYTEST_ARGS": "--x-value='a|b'"}, _TEST_VALUE)
    assert result.returncode == 0, result.stdout + result.stderr


def test_a_worker_option_is_an_error(tmp_path: Path) -> None:
    """check.sh sets its own worker counts: after -n 1, -n 2 would end the serial run."""
    result = _check(tmp_path, {"APPINFRA_PYTEST_ARGS": "--x-marker -n 2"})
    assert result.returncode == 2, result.stdout + result.stderr
    assert "make check sets its own worker counts" in result.stderr, result.stderr
    # make check reads no APPINFRA_PYTEST_WORKERS: naming it would send the user nowhere
    assert "APPINFRA_PYTEST_WORKERS" not in result.stderr, result.stderr


def test_without_the_args_the_test_fails(tmp_path: Path) -> None:
    """The control: the scratch test does depend on the option."""
    result = _check(tmp_path, {})
    assert result.returncode != 0
