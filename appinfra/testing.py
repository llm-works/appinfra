# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Generic pytest utilities for appinfra-based projects.

This module provides pytest markers and hooks for common testing patterns.
Use as a pytest plugin by adding to your conftest.py:

    pytest_plugins = ["appinfra.testing"]

Markers:
    expected_skip: Mark tests where skipping is expected/acceptable.
        These skips won't appear in check.sh warning summaries.

Fixtures:
    destroy_test_loggers (autouse): destroys the loggers a test created with
        LoggerFactory and left registered, so the next test can create the same names.

Example:
    @pytest.mark.expected_skip
    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only test")
    def test_windows_paths():
        ...
"""

from __future__ import annotations

from collections.abc import Generator
from typing import TYPE_CHECKING

import pytest

from .log import LoggerFactory

if TYPE_CHECKING:
    from _pytest.config import Config
    from _pytest.nodes import Item
    from _pytest.reports import TestReport
    from _pytest.runner import CallInfo


# Prefix added to skip reasons for expected skips (filtered by check.sh)
EXPECTED_SKIP_PREFIX = "[expected] "


def pytest_configure(config: Config) -> None:
    """Register custom markers."""
    config.addinivalue_line(
        "markers",
        "expected_skip: Mark test where skipping is expected/acceptable. "
        "These skips won't appear in check.sh warning summaries.",
    )


@pytest.fixture(autouse=True)
def destroy_test_loggers() -> Generator[None, None, None]:
    """
    Destroy the loggers a test created with LoggerFactory and left registered.

    LoggerFactory.create() raises for a name this process already holds, so a logger
    one test leaves behind fails the next test in the same process that creates the
    same name. Loggers that existed before the test (session or module fixtures) stay.
    """
    before = LoggerFactory.names()
    yield
    for name in LoggerFactory.names() - before:
        # destroying a parent already removed the loggers derived from it
        LoggerFactory.destroy_if_exists(name)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    item: Item, call: CallInfo
) -> Generator[None, TestReport, TestReport]:
    """
    Modify skip reason for tests marked with expected_skip.

    When a test with the expected_skip marker is skipped, this hook prefixes
    the skip reason with '[expected] ' so that check.sh can filter it out
    of the warning summary.
    """
    report: TestReport = yield

    # Process skipped tests in call or setup phase (not teardown - rare and typically fixture failures)
    if report.skipped and call.when in ("call", "setup"):
        if item.get_closest_marker("expected_skip"):
            _prefix_skip_reason(report)

    return report


def _prefix_skip_reason(report: TestReport) -> None:
    """Add [expected] prefix to a skip report's reason."""
    # report.longrepr is a tuple: (file, line, reason)
    if isinstance(report.longrepr, tuple) and len(report.longrepr) == 3:
        file_path, line, reason = report.longrepr
        if not reason.startswith(EXPECTED_SKIP_PREFIX):
            report.longrepr = (file_path, line, f"{EXPECTED_SKIP_PREFIX}{reason}")
