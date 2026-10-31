#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Judge the test structure reports appinfra.pytest_suites writes during make check, for check.sh.

Each pytest process of make check's test run writes a report (appinfra/_suite_health.py): the
tests collected, each scope (a class, or a file's module-level tests) under ``tests/<suite>/``
holding tests of another suite, and each unit test that left process-wide state changed. This
script merges the reports of a directory and applies the rules of docs/guides/test-suites.md:

- ``placement``: most of a scope's tests belong to another suite, so the scope moves to that
  suite's directory; a file's module-level tests are placed by every test of the file;
- ``overrides``: more than ``--override-threshold`` percent of a scope's tests belong to another
  suite, so they split off into a class in that suite's directory; a file's module-level
  overrides count against every test of the file;
- ``leak``: a unit test left process-wide state changed.

A scope takes one finding at most, placement first. A test is not clean when it needs moving
(it runs in a suite other than its directory's, in a flagged scope) or leaks. The output is one
line with the share of clean tests, then one line per finding:

    <percent><TAB><unclean><TAB><total>
    <kind><TAB><where><TAB><detail>

The exit code is 0, or 3 when the directory holds no report: the project does not load
appinfra.pytest_suites. Standard library only: check.sh runs it with the project's Python.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

NO_REPORT = 3


def load(report_dir: Path, root: Path) -> list[dict[str, Any]]:
    """The project's reports in a directory; the processes of one run see the same collection.

    A pytest that a test starts inherits the report directory and writes its report there too,
    from its own rootdir; only the reports from ``root`` count.
    """
    reports = [json.loads(p.read_text()) for p in sorted(report_dir.glob("*.json"))]
    return [r for r in reports if Path(r["rootdir"]).resolve() == root.resolve()]


def _scope_finding(scope: dict[str, Any], threshold: float) -> tuple[str, str] | None:
    """The finding for one scope, as (kind, detail), or None when it keeps to the rules.

    A file's module-level tests are judged against every test of the file (``file_suites``):
    one integration function in a file of unit classes is a small override, not a misplaced
    file.
    """
    home = scope["directory"]
    whole: dict[str, int] = scope.get("file_suites") or scope["suites"]
    total = sum(whole.values())
    top = max(sorted(whole), key=lambda suite: whole[suite])
    if top != home and whole[top] > whole.get(home, 0):
        share = round(whole[top] * 100 / total)
        return (
            "placement",
            f"{whole[top]} of {total} tests ({share}%) are {top}, the majority: "
            f"move to tests/{top}/",
        )
    others = {suite: n for suite, n in scope["suites"].items() if suite != home}
    overridden = sum(others.values())
    if overridden * 100 > threshold * total:
        which = ", ".join(f"{n} {suite}" for suite, n in sorted(others.items()))
        share = round(overridden * 100 / total)
        return (
            "overrides",
            f"{which} of {total} tests ({share}%, over {threshold:g}%): split them into "
            "their suite's directory",
        )
    return None


def _misplaced(scope: dict[str, Any]) -> int:
    """A flagged scope's tests that run in a suite other than their directory's: the majority a
    placement moves, or the tests an overrides finding splits off."""
    return sum(n for suite, n in scope["suites"].items() if suite != scope["directory"])


def judge(
    reports: Iterable[dict[str, Any]], threshold: float
) -> tuple[int, int, list[tuple[str, str, str]]]:
    """The tests that need moving or leak, the tests in all, and the findings."""
    total = 0
    scopes: dict[str, dict[str, Any]] = {}
    leaks: dict[str, dict[str, Any]] = {}
    for report in reports:
        total = max(total, report["total"])
        scopes.update((s["scope"], s) for s in report["scopes"])
        leaks.update((leak["test"], leak) for leak in report["leaks"])
    findings: list[tuple[str, str, str]] = []
    # Flagged scopes whose directory is not unit: their unit tests are counted already
    counted_unit: set[str] = set()
    unclean = 0
    for name in sorted(scopes):
        scope = scopes[name]
        found = _scope_finding(scope, threshold)
        if found:
            findings.append((found[0], name, found[1]))
            unclean += _misplaced(scope)
            if scope["directory"] != "unit":
                counted_unit.add(name)
    for test in sorted(leaks):
        leak = leaks[test]
        findings.append(("leak", test, "left changed: " + ", ".join(leak["changed"])))
        if leak["scope"] not in counted_unit:
            unclean += 1
    findings.sort(key=lambda f: ("placement", "overrides", "leak").index(f[0]))
    return unclean, total, findings


def clean_percent(unclean: int, total: int) -> str:
    """The share of clean tests, rounded down, so 100.0 means no test needs moving or leaks."""
    if not total:
        return "100.0"
    return f"{math.floor((total - unclean) * 1000 / total) / 10:.1f}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("report_dir", type=Path)
    parser.add_argument(
        "--root", type=Path, default=Path.cwd(), help="the project's rootdir"
    )
    parser.add_argument("--override-threshold", type=float, default=15.0)
    args = parser.parse_args(argv)
    reports = load(args.report_dir, args.root) if args.report_dir.is_dir() else []
    if not reports:
        return NO_REPORT
    unclean, total, findings = judge(reports, args.override_threshold)
    print(f"{clean_percent(unclean, total)}\t{unclean}\t{total}")
    for kind, where, detail in findings:
        print(f"{kind}\t{where}\t{detail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
