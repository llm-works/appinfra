#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Judge the test structure reports appinfra.pytest_suites writes during make check, for check.sh.

Each pytest process of make check's test run writes a report (appinfra/_suite_health.py): the
tests under ``tests/<suite>/`` directories, each scope (a class, or a file's module-level tests)
there holding tests of another suite, and each unit test that left process-wide state changed. This
script merges the reports of a directory and applies the rules of docs/guides/test-suites.md.
A scope holding at most ``--outliers`` tests of other suites keeps to the rules, whatever its
size; past that:

- ``placement``: most of a scope's tests belong to another suite, so they move to that suite's
  directory; a file's module-level tests are placed by every test of the file;
- ``overrides``: more than ``--threshold`` percent of a scope's tests belong to another
  suite, so they split off into a class in that suite's directory; a file's module-level
  overrides count against every test of the file.

A unit test that left process-wide state changed is a ``leak``, a finding of its own.

A scope takes one finding at most, placement first. The output is the share of tests that run in
their directory's suite, tolerated ones counted as outside, then one line per finding:

    <percent>
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


def _scope_finding(
    scope: dict[str, Any], threshold: float, outliers: int
) -> tuple[str, str] | None:
    """The finding for one scope, as (kind, detail), or None when it keeps to the rules.

    A file's module-level tests are judged against every test of the file (``file_suites``):
    one integration function in a file of unit classes is a small override, not a misplaced
    file.
    """
    home = scope["directory"]
    others = {suite: n for suite, n in scope["suites"].items() if suite != home}
    overridden = sum(others.values())
    if overridden <= outliers:
        return None
    whole: dict[str, int] = scope.get("file_suites") or scope["suites"]
    total = sum(whole.values())
    top = max(sorted(whole), key=lambda suite: whole[suite])
    if top != home and whole[top] > whole.get(home, 0):
        share = round(whole[top] * 100 / total)
        return (
            "placement",
            f"{whole[top]} of {total} tests ({share}%) are {top}, the majority: "
            f"move them to tests/{top}/",
        )
    if overridden * 100 > threshold * total:
        which = ", ".join(f"{n} {suite}" for suite, n in sorted(others.items()))
        share = round(overridden * 100 / total)
        return (
            "overrides",
            f"{which} of {total} tests ({share}%, over {threshold:g}%): split them into "
            "their suite's directory",
        )
    return None


def judge(
    reports: Iterable[dict[str, Any]], threshold: float, outliers: int
) -> list[tuple[str, str, str]]:
    """The findings, as (kind, where, detail): placements, then overrides, then leaks."""
    scopes: dict[str, dict[str, Any]] = {}
    leaks: dict[str, list[str]] = {}
    for report in reports:
        scopes.update((s["scope"], s) for s in report["scopes"])
        leaks.update((leak["test"], leak["changed"]) for leak in report["leaks"])
    findings: list[tuple[str, str, str]] = []
    for name in sorted(scopes):
        found = _scope_finding(scopes[name], threshold, outliers)
        if found:
            findings.append((found[0], name, found[1]))
    findings.extend(
        ("leak", test, "left changed: " + ", ".join(leaks[test]))
        for test in sorted(leaks)
    )
    findings.sort(key=lambda f: ("placement", "overrides", "leak").index(f[0]))
    return findings


def health(reports: Iterable[dict[str, Any]]) -> str:
    """The share of tests that run in their directory's suite, rounded down, so 100.0 means
    every test does; tests the rules tolerate in another directory count as outside it."""
    total = 0
    outside: dict[str, int] = {}
    for report in reports:
        total = max(total, report["total"])
        for scope in report["scopes"]:
            outside[scope["scope"]] = sum(
                n for suite, n in scope["suites"].items() if suite != scope["directory"]
            )
    if not total:
        return "100.0"
    inside = total - sum(outside.values())
    return f"{math.floor(inside * 1000 / total) / 10:.1f}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("report_dir", type=Path)
    parser.add_argument(
        "--root", type=Path, default=Path.cwd(), help="the project's rootdir"
    )
    parser.add_argument("--threshold", type=float, default=15.0)
    parser.add_argument("--outliers", type=int, default=3)
    args = parser.parse_args(argv)
    reports = load(args.report_dir, args.root) if args.report_dir.is_dir() else []
    if not reports:
        return NO_REPORT
    print(health(reports))
    for kind, where, detail in judge(reports, args.threshold, args.outliers):
        print(f"{kind}\t{where}\t{detail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
