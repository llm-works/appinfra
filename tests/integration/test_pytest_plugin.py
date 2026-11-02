# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for the appinfra.testing pytest plugin that run an inner pytest session."""

_TWO_TESTS_ONE_NAME = """
import logging

from appinfra.log import LoggerFactory
from appinfra.log.config import LogConfig


def _create():
    return LoggerFactory.create("plugin-teardown", LogConfig(level=logging.INFO))


def test_first():
    _create()


def test_second():
    _create()
"""

# The inner run needs neither worker processes nor an event loop
_INNER_ARGS = ("-p", "no:xdist", "-p", "no:asyncio")


class TestDestroyTestLoggers:
    """The plugin destroys loggers a test leaves, so later tests can reuse the name."""

    def test_next_test_can_create_the_same_name(self, pytester):
        pytester.makeconftest('pytest_plugins = ["appinfra.testing"]')
        pytester.makepyfile(_TWO_TESTS_ONE_NAME)

        pytester.runpytest(*_INNER_ARGS).assert_outcomes(passed=2)

    def test_without_the_plugin_the_name_stays_taken(self, pytester):
        """The control: without the fixture the second create() raises."""
        pytester.makepyfile(_TWO_TESTS_ONE_NAME)

        result = pytester.runpytest(*_INNER_ARGS, "-p", "no:appinfra.testing")

        result.assert_outcomes(passed=1, failed=1)
        result.stdout.fnmatch_lines(["*LoggerExistsError*"])


# A project's own time-based module and its test on the plugin's fake_clock
_RETRY_MODULE = """
import time


def wait_out(attempts, delay):
    start = time.monotonic()
    for _ in range(attempts):
        time.sleep(delay)
    return time.monotonic() - start
"""

_RETRY_TEST = """
import time

import retry


def test_retries_on_the_clock(fake_clock):
    fake_clock.patch("retry")
    assert retry.time is not time  # on the clock before the sleeps below
    assert retry.wait_out(3, 2.0) == 6.0
    assert fake_clock.monotonic() == 1000.0 + 6.0
"""


class TestFakeClock:
    """A project loading the plugin runs its own time-based code on fake_clock."""

    def test_project_module_runs_on_the_clock(self, pytester):
        pytester.makeconftest('pytest_plugins = ["appinfra.testing"]')
        pytester.makepyfile(retry=_RETRY_MODULE, test_retry=_RETRY_TEST)

        pytester.runpytest(*_INNER_ARGS).assert_outcomes(passed=1)
