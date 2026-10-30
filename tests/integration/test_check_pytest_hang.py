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
            monkeypatch.delenv("APPINFRA_PYTEST_HANG_DUMP_SECONDS", raising=False)
        else:
            monkeypatch.setenv("APPINFRA_PYTEST_HANG_DUMP_SECONDS", seconds)
        return pytester.runpytest_subprocess(
            "-p", "pytest_hang", "-q", "-p", "no:cacheprovider"
        )

    return run


@pytest.mark.integration
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


@pytest.mark.integration
def test_report_starts_on_its_own_line(run_with_plugin) -> None:
    """pytest's progress output leaves the line open; the report must not continue it."""
    result = run_with_plugin("0.3")

    lines = result.stderr.lines + result.stdout.lines
    assert any(line.startswith("=== test running >0.3s: ") for line in lines)


_THREAD_TESTS = """
import threading

stop = threading.Event()

def test_leaves_a_thread():
    threading.Thread(target=stop.wait, args=(30.0,), name="lingerer").start()

def test_leaves_a_daemon():
    threading.Thread(target=stop.wait, args=(30.0,), name="daemonic", daemon=True).start()

def test_joins_its_thread():
    thread = threading.Thread(target=lambda: None, name="joined")
    thread.start()
    thread.join()

def test_stops_its_thread_in_a_cleanup(request):
    done = threading.Event()
    thread = threading.Thread(target=done.wait, args=(30.0,), name="cleaned-up")
    thread.start()

    def stop():
        done.set()
        thread.join()

    request.config.add_cleanup(stop)
"""

# Releases the inner threads only after pytest_hang has reported them. Cleanups run last-
# registered first; registered from a tryfirst pytest_configure, before the plugin's, this one
# runs after the report, so the threads are alive when it looks, however slow the machine, and
# the inner run does not wait out their timeout
_RELEASE_THREADS = """
import sys

import pytest

def _release():
    module = sys.modules.get("test_inner")
    if module is not None:
        module.stop.set()

@pytest.hookimpl(tryfirst=True)
def pytest_configure(config):
    config.add_cleanup(_release)
"""


@pytest.mark.integration
def test_thread_left_running_is_reported_with_its_test(
    run_with_plugin, pytester: pytest.Pytester
) -> None:
    pytester.makepyfile(test_inner=_THREAD_TESTS)
    pytester.makeconftest(_RELEASE_THREADS)
    result = run_with_plugin("60")

    result.assert_outcomes(passed=4)
    err = result.stderr.str()
    assert "=== thread left running by test_inner.py::test_leaves_a_thread ===" in err
    assert "(lingerer):\n" in err  # the thread follows, then its own stack
    assert ", in wait\n" in err
    assert "daemonic" not in err  # a daemon thread does not hold up the exit
    assert "joined" not in err  # nor does one that ended
    assert "cleaned-up" not in err  # nor one a config cleanup stops before the report


@pytest.mark.integration
def test_nothing_without_the_variable(run_with_plugin) -> None:
    for seconds in (None, "0"):
        result = run_with_plugin(seconds)

        result.assert_outcomes(passed=2)
        assert "=== test" not in result.stderr.str()
