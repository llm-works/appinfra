# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for appinfra.testing pytest plugin (expected_skip marker, logger teardown)."""

import pytest

from appinfra.testing import EXPECTED_SKIP_PREFIX, _prefix_skip_reason


class TestExpectedSkipPrefix:
    """Tests for the expected skip reason prefix constant."""

    def test_prefix_value(self):
        """Prefix should be [expected] with trailing space."""
        assert EXPECTED_SKIP_PREFIX == "[expected] "

    def test_prefix_is_filterable(self):
        """Prefix should be suitable for shell pattern matching."""
        # check.sh uses: [[ "$reason" == "[expected] "* ]]
        test_reason = f"{EXPECTED_SKIP_PREFIX}Windows-only test"
        assert test_reason.startswith("[expected] ")


class TestPrefixSkipReason:
    """Tests for the _prefix_skip_reason helper function."""

    def test_prefixes_tuple_longrepr(self):
        """Should prefix reason in (file, line, reason) tuple."""

        class MockReport:
            longrepr = ("/path/to/test.py", 42, "Some skip reason")

        report = MockReport()
        _prefix_skip_reason(report)

        assert report.longrepr == (
            "/path/to/test.py",
            42,
            "[expected] Some skip reason",
        )

    def test_does_not_double_prefix(self):
        """Should not add prefix if already present."""

        class MockReport:
            longrepr = ("/path/to/test.py", 42, "[expected] Already prefixed")

        report = MockReport()
        _prefix_skip_reason(report)

        assert report.longrepr == (
            "/path/to/test.py",
            42,
            "[expected] Already prefixed",
        )

    def test_handles_non_tuple_longrepr(self):
        """Should not crash on non-tuple longrepr."""

        class MockReport:
            longrepr = "Some string representation"

        report = MockReport()
        _prefix_skip_reason(report)  # Should not raise

        # longrepr unchanged
        assert report.longrepr == "Some string representation"


class TestExpectedSkipMarkerIntegration:
    """Integration tests for the expected_skip marker.

    These tests verify the marker works correctly with pytest's skip machinery.
    The actual hook behavior is tested by running pytest with the plugin loaded.
    """

    @pytest.mark.expected_skip
    @pytest.mark.skip(reason="Intentionally skipped for testing")
    def test_marker_can_be_applied(self):
        """Verify marker can be applied to a test."""
        pytest.fail("This should not run - test is skipped")

    def test_marker_is_registered(self, request):
        """Verify the expected_skip marker is registered."""
        # If not registered, pytest would warn about unknown markers
        markers = [m.name for m in request.node.iter_markers()]
        # This test doesn't have the marker, but we verify registration worked
        # by checking we can get marker info
        marker_info = request.config.getini("markers")
        assert any("expected_skip" in m for m in marker_info)


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


@pytest.mark.integration
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
