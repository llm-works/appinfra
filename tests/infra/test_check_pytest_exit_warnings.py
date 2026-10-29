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

# Objects kept in a module global past the test are finalized at interpreter exit, after pytest
# has removed its warning filters: an open file (ResourceWarning) and one whose finalizer warns
# with another category
_EXIT_WARNING_TEST = """
import warnings

class _WarnsAtExit:
    def __del__(self):
        warnings.warn("old api used at exit", DeprecationWarning, stacklevel=1)

_KEEP = []

def test_leaves_objects_for_exit():
    _KEEP.extend([open(__file__), _WarnsAtExit()])
"""

_AT_EXIT = (
    "ResourceWarning: unclosed file",
    "DeprecationWarning: old api used at exit",
)


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
def test_exit_warnings_are_silent_without_the_plugin(run_inner) -> None:
    """Under an error filter, Python's default filters apply at exit: the plugin shows them."""
    result = run_inner("error")

    result.assert_outcomes(passed=1)
    err = result.stderr.str()
    for warning in _AT_EXIT:
        assert warning not in err


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
