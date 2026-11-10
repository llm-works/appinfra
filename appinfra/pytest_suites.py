# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Pytest plugin: gives each test the suite of its nearest suite marker, or of its directory.

A project opts in from its top-level ``conftest.py``::

    pytest_plugins = ["appinfra.pytest_suites"]

It needs the test tooling of the ``check`` extra (``pip install appinfra[check]``).

The suites are unit, integration, e2e, security and performance. The nearest marker wins: one on
the test overrides its class, a class overrides its module, and a module overrides the directory.
A test under ``tests/<suite>/`` with no marker runs in that directory's suite; a test outside
those directories needs a marker. Collection stops on a test with no suite, and on one whose
nearest marked level names two suites, since it would run in both. The suite directories are
fixed at ``tests/<suite>/`` under the rootdir, where the Makefile framework's ``make check``
looks for them as well.

``-m`` selects by each test's resolved suite, so an integration test in a class marked unit is
left out of ``-m unit``. A suite named in ``APPINFRA_PYTEST_BOUND_SUITES`` is bound to its
directory: its tests must all sit under ``tests/<suite>/``, and collection stops on one that
does not. The rules: appinfra's docs/guides/test-suites.md.
"""

import os
from pathlib import Path

import pytest
from _pytest.mark import MarkMatcher
from _pytest.mark.expression import Expression

from ._suite_health import REPORT_DIR_ENV, SuiteHealth, exempt_reason

_HEALTH_KEY = pytest.StashKey[SuiteHealth]()

SUITES = ("unit", "integration", "e2e", "security", "performance")

# Suites bound to their tests/<suite>/ directory, set by the Makefile framework's setting
BOUND_SUITES_ENV = "APPINFRA_PYTEST_BOUND_SUITES"

_MARKER_HELP = {
    "unit": "stays in one process, no I/O or process-wide state; default under tests/unit/",
    "integration": "one machine: processes, files, localhost services, databases, signals, "
    "timers; default under tests/integration/",
    "e2e": "runs an entry point as its own process; default under tests/e2e/",
    "security": "security behaviour (injection, validation); default under tests/security/",
    "performance": "benchmarks; default under tests/performance/",
}


def pytest_configure(config: pytest.Config) -> None:
    """Register the suite markers, so they work in a project that declares none.

    Under make check, which names a report directory, also record the suite health report.
    """
    for suite in SUITES:
        config.addinivalue_line("markers", f"{suite}: {_MARKER_HELP[suite]}")
    config.addinivalue_line(
        "markers",
        "suite_exempt(reason): the test may do what its suite does not allow; "
        "Test structure health leaves its behavior unjudged",
    )
    report_dir = os.environ.get(REPORT_DIR_ENV)
    if report_dir:
        health = SuiteHealth(Path(report_dir), config.rootpath)
        config.stash[_HEALTH_KEY] = health
        config.pluginmanager.register(health, "appinfra-suite-health")


def _directory_suite(item: pytest.Item, root: Path) -> str | None:
    """The suite of the tests/<suite>/ directory the test file sits under, if any."""
    try:
        parts = item.path.relative_to(root).parts
    except ValueError:  # a test file outside the rootdir has no suite directory
        return None
    if len(parts) > 2 and parts[0] == "tests" and parts[1] in SUITES:
        return parts[1]
    return None


def _bound_suites() -> set[str]:
    """The suites bound to their directory: make check and the test.<suite> targets collect
    them from tests/<suite>/ alone (BOUND_SUITES_ENV, space-separated)."""
    bound = set(os.environ.get(BOUND_SUITES_ENV, "").split())
    unknown = bound - set(SUITES)
    if unknown:
        raise pytest.UsageError(
            f"{BOUND_SUITES_ENV} names no suite: {' '.join(sorted(unknown))}; "
            f"the suites are {' '.join(SUITES)}"
        )
    return bound


def _stop_on_misplaced(
    items: list[pytest.Item], suite_of: dict[str, str], root: Path
) -> None:
    """Stop on a test of a bound suite outside its directory: the bound suite's run never
    collects it and every other run leaves it out, so it would never run. Checked on the
    tests already collected: such a test shows up in a run that collects the whole tree
    (coverage, an unbound suite) or, when make check has none, in its Suite placement
    collection of the files outside the bound directories."""
    bound = _bound_suites()
    misplaced = [
        item.nodeid
        for item in items
        if suite_of.get(item.nodeid) in bound
        and _directory_suite(item, root) != suite_of[item.nodeid]
    ]
    if misplaced:
        raise pytest.UsageError(
            f"tests of a suite {BOUND_SUITES_ENV} binds to tests/<suite>/, outside that "
            "directory: " + ", ".join(misplaced)
        )


def _nearest_suites(item: pytest.Item) -> set[str]:
    """Suite markers on the nearest of the test, its class and its module that has any."""
    for node in reversed(item.listchain()):
        named = {m.name for m in node.own_markers if m.name in SUITES}
        if named:
            return named
    return set()


def _resolve_suites(
    items: list[pytest.Item], root: Path
) -> tuple[dict[str, str], list[str], list[str]]:
    """Each test's suite by node id, then the tests with no suite and those with two."""
    suite_of: dict[str, str] = {}
    unmarked: list[str] = []
    conflicting: list[str] = []
    for item in items:
        named = _nearest_suites(item)
        if len(named) > 1:
            conflicting.append(item.nodeid)
            continue
        if named:
            suite_of[item.nodeid] = named.pop()
            continue
        suite = _directory_suite(item, root)
        if suite is None:
            unmarked.append(item.nodeid)
            continue
        item.add_marker(suite)
        suite_of[item.nodeid] = suite
    return suite_of, unmarked, conflicting


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
    remaining: list[pytest.Item] = []
    deselected: list[pytest.Item] = []
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
    """Give every test one suite, stop on tests with none, two or a misplaced bound one, then
    apply -m by suite."""
    suite_of, unmarked, conflicting = _resolve_suites(items, config.rootpath)
    if unmarked:
        raise pytest.UsageError(
            "tests without a suite marker (unit, integration, e2e, security or "
            "performance): " + ", ".join(unmarked)
        )
    if conflicting:
        raise pytest.UsageError(
            "tests with more than one suite marker: " + ", ".join(conflicting)
        )
    _stop_on_misplaced(items, suite_of, config.rootpath)
    unexplained = [i.nodeid for i in items if exempt_reason(i) == ""]
    if unexplained:
        raise pytest.UsageError(
            "suite_exempt needs a reason, as suite_exempt(reason=...): "
            + ", ".join(unexplained)
        )
    health = config.stash.get(_HEALTH_KEY, None)
    if health is not None:
        root = config.rootpath
        health.record_collection(
            root, items, suite_of, lambda i: _directory_suite(i, root)
        )
    _deselect_by_suite(config, items, suite_of)
