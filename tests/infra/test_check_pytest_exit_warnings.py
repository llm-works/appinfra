# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for appinfra/scripts/check_pytest/pytest_exit_warnings.py, the plugin check.sh loads.

check.sh asks the plugin for the mode line, and check_warnings.py reads what it makes print at
exit, so both are pinned here.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

PLUGIN_DIR = (
    Path(__file__).resolve().parents[2] / "appinfra" / "scripts" / "check_pytest"
)

# After pytest has removed its warning filters: an exit handler calls a deprecated API, and a
# file kept open in a module global is finalized. A Python finalizer's own warning would not
# do as the second case: late in shutdown, Python 3.14 drops it.
_EXIT_WARNING_TEST = """
import atexit
import warnings

def _close_old_api():
    warnings.warn("old api used at exit", DeprecationWarning, stacklevel=1)

_KEEP = []

def test_leaves_work_for_exit():
    _KEEP.append(open(__file__))
    atexit.register(_close_old_api)
"""

_DEPRECATION = "DeprecationWarning: old api used at exit"
_AT_EXIT = ("ResourceWarning: unclosed file", _DEPRECATION)


@pytest.fixture
def run_inner(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch):
    """Run the inner test in a subprocess, under the given filterwarnings."""
    pythonpath = os.environ.get("PYTHONPATH")
    monkeypatch.setenv("PYTHONPATH", f"{PLUGIN_DIR}{os.pathsep}{pythonpath or ''}")
    monkeypatch.delenv("PYTHONWARNINGS", raising=False)
    pytester.makepyfile(test_inner=_EXIT_WARNING_TEST)

    def run(filterwarnings: str, *args: str) -> pytest.RunResult:
        pytester.makeini(
            "[pytest]\n"
            "asyncio_default_fixture_loop_scope = function\n"
            f"filterwarnings = {filterwarnings}\n"
        )
        return pytester.runpytest_subprocess("-q", "-p", "no:cacheprovider", *args)

    return run


@pytest.mark.unit
@pytest.mark.parametrize("filterwarnings", ["error", "default"])
@pytest.mark.parametrize("workers", [[], ["-n", "2"]], ids=["in-process", "xdist"])
def test_every_warning_at_exit_is_printed(
    run_inner, filterwarnings: str, workers: list[str]
) -> None:
    """Any category, from the main process or an xdist worker, whatever the filters."""
    result = run_inner(filterwarnings, "-p", "pytest_exit_warnings", *workers)

    result.assert_outcomes(passed=1)
    err = result.stderr.str()
    for warning in _AT_EXIT:
        assert warning in err


@pytest.mark.unit
def test_exit_deprecation_is_silent_without_the_plugin(run_inner) -> None:
    """At exit Python's default filters apply, which ignore a DeprecationWarning outside
    __main__: the plugin is what shows it. (An unclosed file is no control: Python 3.14 reports
    it whatever the filters.)"""
    result = run_inner("error")

    result.assert_outcomes(passed=1)
    assert _DEPRECATION not in result.stderr.str()


@pytest.mark.unit
@pytest.mark.parametrize(
    ("filterwarnings", "mode"),
    [
        ("error", "strict"),
        ("\n    error\n    ignore::UserWarning", "strict"),
        ("error::DeprecationWarning", "warn"),
        ("default", "warn"),
    ],
    ids=["error", "error-among-others", "error-for-one-category", "no-error"],
)
def test_mode_line_follows_filterwarnings(
    run_inner, filterwarnings: str, mode: str
) -> None:
    """A bare "error" makes every warning an error, so one at exit is one too."""
    result = run_inner(filterwarnings, "-p", "pytest_exit_warnings", "-n", "2")

    err = result.stderr.str()
    assert err.count("=== exit warnings: ") == 1  # the controller only, not each worker
    assert f"=== exit warnings: {mode} ===" in err
