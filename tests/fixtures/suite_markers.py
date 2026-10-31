# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Gives each test the suite of its nearest suite marker, or of its directory.

The nearest marker wins: one on the test overrides its class, a class overrides its module, and
a module overrides the directory. A test under tests/unit, tests/integration, tests/e2e,
tests/security or tests/performance with no marker runs in that directory's suite; a test outside
those directories needs a marker. Collection stops on a test with no suite, and on one whose
nearest marked level names two suites, since it would run in both.
"""

from pathlib import Path

import pytest
from _pytest.mark import MarkMatcher
from _pytest.mark.expression import Expression

SUITES = ("unit", "integration", "e2e", "security", "performance")


def _directory_suite(item: pytest.Item, root: Path) -> str | None:
    parts = item.path.relative_to(root).parts
    if len(parts) > 2 and parts[0] == "tests" and parts[1] in SUITES:
        return parts[1]
    return None


def _nearest_suites(item: pytest.Item) -> set[str]:
    """Suite markers on the nearest of the test, its class and its module that has any."""
    for node in reversed(item.listchain()):
        named = {m.name for m in node.own_markers if m.name in SUITES}
        if named:
            return named
    return set()


def _deselect_by_suite(
    config: pytest.Config, items: list[pytest.Item], suite_of: dict[str, str]
) -> None:
    """Apply -m with each test's resolved suite in place of every suite marker it inherits.

    pytest's own -m pass matches all markers up the chain, so a test marked integration in a
    unit class would match -m unit as well; this pass replaces it.
    """
    markexpr = config.option.markexpr
    if not markexpr:
        return
    expr = Expression.compile(markexpr)
    remaining, deselected = [], []
    for item in items:
        marks = [m for m in item.iter_markers() if m.name not in SUITES]
        marks.append(getattr(pytest.mark, suite_of[item.nodeid]).mark)
        matched = expr.evaluate(MarkMatcher.from_markers(marks))
        (remaining if matched else deselected).append(item)
    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = remaining
    # The expression is fully applied; left set, pytest's pass would drop an overridden test
    # under a negated suite (-m "not unit") through the suite marker on its class.
    config.option.markexpr = ""


# tryfirst: the suite must be resolved, and -m applied, before pytest's own -m deselection runs
@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    suite_of: dict[str, str] = {}
    unmarked, conflicting = [], []
    for item in items:
        named = _nearest_suites(item)
        if len(named) > 1:
            conflicting.append(item.nodeid)
            continue
        if named:
            suite = named.pop()
        else:
            suite = _directory_suite(item, config.rootpath)
            if suite is None:
                unmarked.append(item.nodeid)
                continue
            item.add_marker(suite)
        suite_of[item.nodeid] = suite
    if unmarked:
        raise pytest.UsageError(
            "tests without a suite marker (unit, integration, e2e, security or "
            "performance): " + ", ".join(unmarked)
        )
    if conflicting:
        raise pytest.UsageError(
            "tests with more than one suite marker: " + ", ".join(conflicting)
        )
    _deselect_by_suite(config, items, suite_of)
