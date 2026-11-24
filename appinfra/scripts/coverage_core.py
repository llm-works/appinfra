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

Under pytest's ``filterwarnings = error`` any of these warnings fails the run. Where sys.monitoring can
measure the run, this prints the setting; otherwise nothing, and coverage.py keeps its default
tracer. The coverage settings are the project's own, read from the current directory as
coverage.py reads them, plus the pytest arguments in APPINFRA_PYTEST_ARGS.
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
    return python >= (3, 12) and not config.plugins and not contexts


def _pytest_args() -> list[str]:
    value = os.environ.get("APPINFRA_PYTEST_ARGS", "")
    try:
        return shlex.split(value)
    except ValueError:  # unbalanced quotes: the words are enough to find the options
        return value.split()


def main() -> int:
    python = (sys.version_info.major, sys.version_info.minor)
    if sysmon_usable(Coverage().config, python, _pytest_args()):
        print("COVERAGE_CORE=sysmon")
    return 0


if __name__ == "__main__":
    sys.exit(main())
