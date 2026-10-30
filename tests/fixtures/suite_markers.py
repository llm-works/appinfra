# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Gives each test the suite of its directory.

A test under tests/unit, tests/integration, tests/e2e, tests/security or tests/performance runs
in that suite and needs no marker; a suite marker that names another suite stops collection, so
a test of another kind cannot sit in the directory. A test outside those directories names its
suite with a marker; collection stops on one that does not, since it would run in no suite.
"""

from pathlib import Path

import pytest

SUITES = ("unit", "integration", "e2e", "security", "performance")


def _directory_suite(item: pytest.Item, root: Path) -> str | None:
    parts = item.path.relative_to(root).parts
    if len(parts) > 2 and parts[0] == "tests" and parts[1] in SUITES:
        return parts[1]
    return None


def _usage_error(problem: str, nodeids: list[str]) -> pytest.UsageError:
    return pytest.UsageError(f"{problem}: " + ", ".join(nodeids))


# tryfirst: the marker must be in place before pytest's own -m deselection runs
@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    contradicting, unmarked = [], []
    for item in items:
        named = {m.name for m in item.iter_markers() if m.name in SUITES}
        suite = _directory_suite(item, config.rootpath)
        if suite and named - {suite}:
            contradicting.append(item.nodeid)
        elif suite:
            item.add_marker(suite)
        elif not named:
            unmarked.append(item.nodeid)
    if contradicting:
        raise _usage_error(
            "tests marked for a suite other than their directory's", contradicting
        )
    if unmarked:
        raise _usage_error(
            "tests without a suite marker (unit, integration, e2e, security or performance)",
            unmarked,
        )
