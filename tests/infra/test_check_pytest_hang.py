# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for appinfra/scripts/check_pytest/pytest_hang.py, the plugin check.sh loads.

check.sh parses the report's first line and the closing line, so their format is pinned here.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

PLUGIN_DIR = (
    Path(__file__).resolve().parents[2] / "appinfra" / "scripts" / "check_pytest"
)

_SLOW_TEST = """
import time

def test_slow():
    time.sleep(1.0)

def test_fast():
    pass
"""


@pytest.fixture
def run_with_plugin(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch):
    """Run the inner tests in a subprocess with the plugin importable and loaded."""
    pythonpath = os.environ.get("PYTHONPATH")
    monkeypatch.setenv("PYTHONPATH", f"{PLUGIN_DIR}{os.pathsep}{pythonpath or ''}")
    pytester.makepyfile(test_inner=_SLOW_TEST)

    def run(seconds: str | None) -> pytest.RunResult:
        if seconds is None:
            monkeypatch.delenv("INFRA_PYTEST_HANG_DUMP_SECONDS", raising=False)
        else:
            monkeypatch.setenv("INFRA_PYTEST_HANG_DUMP_SECONDS", seconds)
        return pytester.runpytest_subprocess(
            "-p", "pytest_hang", "-q", "-p", "no:cacheprovider"
        )

    return run


@pytest.mark.unit
def test_long_test_gets_a_report_with_stacks_and_a_closing_line(
    run_with_plugin,
) -> None:
    result = run_with_plugin("0.3")

    result.assert_outcomes(passed=2)
    err = result.stderr.str()
    assert "=== test running >0.3s: test_inner.py::test_slow ===" in err
    assert ", in test_slow\n" in err  # the test's own frame is in the stacks
    assert "=== test done after " in err
    assert "s: test_inner.py::test_slow ===" in err
    assert "test_fast" not in err  # a test under the threshold gets nothing


@pytest.mark.unit
def test_report_starts_on_its_own_line(run_with_plugin) -> None:
    """pytest's progress output leaves the line open; the report must not continue it."""
    result = run_with_plugin("0.3")

    lines = result.stderr.lines + result.stdout.lines
    assert any(line.startswith("=== test running >0.3s: ") for line in lines)


@pytest.mark.unit
def test_nothing_without_the_variable(run_with_plugin) -> None:
    for seconds in (None, "0"):
        result = run_with_plugin(seconds)

        result.assert_outcomes(passed=2)
        assert "=== test" not in result.stderr.str()
