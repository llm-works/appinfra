#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Print ``COVERAGE_CORE=sysmon`` when coverage.py can measure the run with sys.monitoring, for
check.sh and the test.coverage targets.

sys.monitoring (Python 3.12+) measures much faster than coverage.py's default tracer, but:

- it does not run coverage plugins: coverage.py keeps it and only warns that they are
  unsupported, so their data is lost
- before Python 3.14 it cannot measure branches: coverage.py falls back to its default tracer
  with a warning
- it does not record dynamic contexts (``dynamic_context`` in the settings, pytest-cov's
  ``--cov-context``): coverage.py falls back, or keeps it and warns that the context data may
  be incomplete
- it does not support greenlet, eventlet or gevent concurrency: coverage.py falls back with a
  warning

Under pytest's ``filterwarnings = error`` any of these warnings fails the run. Where sys.monitoring can
measure the run, this prints the setting; otherwise nothing, and coverage.py keeps its default
tracer. The coverage settings are the project's own, read as pytest-cov reads them: the file
``--cov-config`` names, else the one coverage.py finds from the current directory. The pytest
arguments are those in APPINFRA_PYTEST_ARGS and PYTEST_ADDOPTS.
"""

from __future__ import annotations

import os
import shlex
import sys

from coverage import Coverage
from coverage.config import CoverageConfig


def sysmon_usable(
    config: CoverageConfig, python: tuple[int, int], pytest_args: list[str]
) -> bool:
    """True when sys.monitoring can measure what *config* and *pytest_args* ask for."""
    branch = config.branch or "--cov-branch" in pytest_args
    if branch and python < (3, 14):
        return False
    contexts = bool(config.dynamic_context) or any(
        arg.startswith("--cov-context") for arg in pytest_args
    )
    # The concurrency libraries coverage.py's own core selection rejects sysmon for
    greenlets = any(c in config.concurrency for c in ("greenlet", "eventlet", "gevent"))
    return python >= (3, 12) and not (config.plugins or contexts or greenlets)


def _pytest_args() -> list[str]:
    """The pytest arguments the run takes from the environment."""
    args: list[str] = []
    # pytest puts PYTEST_ADDOPTS before the command line, which APPINFRA_PYTEST_ARGS joins
    for name in ("PYTEST_ADDOPTS", "APPINFRA_PYTEST_ARGS"):
        value = os.environ.get(name, "")
        try:
            args += shlex.split(value)
        except ValueError:
            # Unbalanced quotes: the words are enough to find the options
            args += value.split()
    return args


def _config_file(pytest_args: list[str]) -> str | bool:
    """The coverage config file pytest-cov reads: the last --cov-config, else True, which
    has coverage.py search for it as usual."""
    path: str | bool = True
    for i, arg in enumerate(pytest_args):
        if arg == "--cov-config" and i + 1 < len(pytest_args):
            path = pytest_args[i + 1]
        elif arg.startswith("--cov-config="):
            path = arg.split("=", 1)[1]
    return path


def main() -> int:
    python = (sys.version_info.major, sys.version_info.minor)
    pytest_args = _pytest_args()
    config = Coverage(config_file=_config_file(pytest_args)).config
    if sysmon_usable(config, python, pytest_args):
        print("COVERAGE_CORE=sysmon")
    return 0


if __name__ == "__main__":
    sys.exit(main())
