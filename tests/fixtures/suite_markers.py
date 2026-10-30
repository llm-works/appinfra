# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Gives each test the suite of its directory unless it names one.

A test under tests/unit, tests/integration, tests/e2e, tests/security or tests/performance runs
in that suite and needs no marker; a test marked with another suite runs in that one instead,
so a file of unit tests may hold a few integration tests. A test outside those directories names
its suite with a marker; collection stops on one that does not, since it would run in no suite.
"""

from pathlib import Path

import pytest

SUITES = ("unit", "integration", "e2e", "security", "performance")


def _directory_suite(item: pytest.Item, root: Path) -> str | None:
    parts = item.path.relative_to(root).parts
    if len(parts) > 2 and parts[0] == "tests" and parts[1] in SUITES:
        return parts[1]
    return None


# tryfirst: the marker must be in place before pytest's own -m deselection runs
@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    unmarked = []
    for item in items:
        if any(item.get_closest_marker(suite) for suite in SUITES):
            continue
        suite = _directory_suite(item, config.rootpath)
        if suite:
            item.add_marker(suite)
        else:
            unmarked.append(item.nodeid)
    if unmarked:
        raise pytest.UsageError(
            "tests without a suite marker (unit, integration, e2e, security or "
            "performance): " + ", ".join(unmarked)
        )
