# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Show the warnings raised at interpreter exit, which pytest's warning filters never see.

pytest applies its filterwarnings only while it runs. An object still alive when the
interpreter exits (an unclosed file, socket or database connection held by a module global or a
cache, an object whose finalizer calls a deprecated API) is finalized after pytest is done,
under Python's default filters, which ignore ResourceWarning and DeprecationWarning, so its
warning goes nowhere. At exit, in the main process and in every pytest-xdist worker, this
plugin makes every warning print once per location, so it reaches stderr:

    sys:1: ResourceWarning: unclosed file <_io.TextIOWrapper name='...' ...>
    .../pool.py:42: DeprecationWarning: ...

An exception a finalizer raises at exit ("Exception ignored in: ...") prints without help.

The main process also writes one line saying whether the project's filterwarnings has a bare
"error", which makes every warning an error:

    === exit warnings: strict ===     (or: warn)

check.sh asks for that line once, from a run that only configures, and loads the plugin into
its pytest checks with ``-p pytest_exit_warnings`` (this file's directory on PYTHONPATH);
check_warnings.py then finds the warnings in each check's log. Interpreters the tests start are
left alone. Like pytest_hang, the file imports nothing from appinfra, so loading it early does
not run the package's ``__init__`` before pytest-cov measures it.
"""

from __future__ import annotations

import atexit
import os
import sys
import warnings

import pytest


def pytest_unconfigure(config: pytest.Config) -> None:
    """Make every warning print at exit; the main process also reports the mode."""
    # At exit, not now: pytest restores its own filters in a cleanup after unconfigure.
    # atexit callbacks run after that and before the interpreter finalizes module globals.
    atexit.register(warnings.simplefilter, "default")
    # An xdist worker has workerinput; the controller, which reports, does not
    if not hasattr(config, "workerinput"):
        mode = "strict" if _warnings_are_errors(config) else "warn"
        _write_stderr(f"\n=== exit warnings: {mode} ===\n")


def _warnings_are_errors(config: pytest.Config) -> bool:
    """True when filterwarnings (ini or -W) has a bare "error" entry."""
    entries = [*config.getini("filterwarnings"), *(config.option.pythonwarnings or [])]
    return any(entry.strip() == "error" for entry in entries)


def _write_stderr(text: str) -> None:
    """Write to the real stderr; output capture may still hold sys.stderr."""
    assert sys.__stderr__ is not None
    data = text.encode(errors="replace")
    fd = sys.__stderr__.fileno()
    while data:
        data = data[os.write(fd, data) :]
