# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Report tests that run long, with the stack of every thread.

When INFRA_PYTEST_HANG_DUMP_SECONDS is above 0, a test still running (setup, call or teardown)
after that many seconds gets one report written to stderr, past pytest's output capture:

    === test running >120s: tests/test_server.py::test_shutdown ===
    Thread 140234 (MainThread):
      File ".../tests/test_server.py", line 88, in test_shutdown
      ...

and, if it ends (not if an interrupt unwinds it), a closing line:
``=== test done after 131.4s: tests/test_server.py::test_shutdown ===``. A report without one
is a test that never finished.

The report neither stops nor fails the test. The stacks are read with the GIL held
(sys._current_frames), so a busy test is not disturbed; pytest's faulthandler_timeout reads
them from a C watchdog thread instead and can crash the process it dumps. A test stuck in C
code that holds the GIL gets no report.

check.sh puts this file's directory on PYTHONPATH, loads the plugin with ``-p pytest_hang``,
sets the variable, and turns the report's first line and the closing line into a row below its
checklist.
The file lives outside the appinfra package and imports nothing from it: ``-p`` imports a
plugin before pytest-cov starts measuring, and importing anything under ``appinfra.`` would run
the package's ``__init__`` early and leave its module-level lines unmeasured.
"""

from __future__ import annotations

import os
import sys
import threading
import time
import traceback
from collections.abc import Generator

import pytest

ENV_VAR = "INFRA_PYTEST_HANG_DUMP_SECONDS"

_seconds_key = pytest.StashKey[float]()
_fd_key = pytest.StashKey[int]()
_reported_key = pytest.StashKey[bool]()
# one writer at a time, so a report and a closing line never interleave
_write_lock = threading.Lock()


def pytest_configure(config: pytest.Config) -> None:
    """Read the threshold and keep a copy of stderr that output capture does not replace."""
    seconds = float(os.environ.get(ENV_VAR) or 0)
    config.stash[_seconds_key] = seconds
    if seconds > 0:
        config.stash[_fd_key] = os.dup(_stderr_fileno())


def pytest_unconfigure(config: pytest.Config) -> None:
    """Close the stderr copy."""
    if _fd_key in config.stash:
        os.close(config.stash[_fd_key])
        del config.stash[_fd_key]


@pytest.hookimpl(wrapper=True)
def pytest_runtest_protocol(item: pytest.Item) -> Generator[None, object, object]:
    """Time the test's setup, call and teardown; report once if they outlast the threshold."""
    seconds = item.config.stash.get(_seconds_key, 0.0)
    if seconds <= 0:
        return (yield)
    start = time.monotonic()
    timer = threading.Timer(seconds, _report, (item, seconds))
    timer.daemon = True
    timer.start()
    try:
        result = yield
    finally:
        timer.cancel()
        timer.join()  # a report being written finishes before the closing line
    # Only a test that ended gets the closing line. One unwinding from an interrupt (a SIGTERM
    # handler raising KeyboardInterrupt, say) did not, and must still read as running.
    if item.stash.get(_reported_key, False):
        took = time.monotonic() - start
        _write(item.config, f"\n=== test done after {took:.1f}s: {item.nodeid} ===\n")
    return result


def _report(item: pytest.Item, seconds: float) -> None:
    """Write the report: the test's node id, then the stack of every other thread."""
    names = {thread.ident: thread.name for thread in threading.enumerate()}
    # leading newline: pytest's progress output leaves the line open
    lines = [f"\n=== test running >{seconds:g}s: {item.nodeid} ===\n"]
    for ident, frame in sys._current_frames().items():
        if ident == threading.get_ident():
            continue  # the timer thread writing this report
        lines.append(f"Thread {ident} ({names.get(ident, '?')}):\n")
        lines.extend(traceback.format_stack(frame))
    lines.append("\n")
    _write(item.config, "".join(lines))
    item.stash[_reported_key] = True


def _write(config: pytest.Config, text: str) -> None:
    """Write text to the stderr copy, all of it, one writer at a time."""
    data = text.encode(errors="replace")
    fd = config.stash[_fd_key]
    with _write_lock:
        while data:
            data = data[os.write(fd, data) :]


def _stderr_fileno() -> int:
    """
    Return the file descriptor of the real stderr.

    pytest-xdist replaces sys.stderr in its workers with an object that has no usable file
    descriptor; sys.__stderr__ is the inherited one (pytest's faulthandler plugin does the same).
    """
    try:
        fileno = sys.stderr.fileno()
        if fileno != -1:
            return fileno
    except (AttributeError, ValueError):
        pass
    assert sys.__stderr__ is not None
    return sys.__stderr__.fileno()
