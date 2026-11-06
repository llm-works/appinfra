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

What the unit tests did (appinfra/_suite_behavior.py) is judged against their suite, by scope:

``misfiled``: unit tests seen doing integration work (files, processes, sockets, databases,
signals, the working directory) or running the project as its own process; they move to the
suite their work needs. Only what a test was seen doing is a finding: what the recording did
not see is no evidence, so no test is judged by what it did not do. A test whose work belongs
to its directory's suite counts as that suite for placement and overrides: its marker is wrong,
not its place.

A test marked ``suite_exempt`` is not judged. A scope takes one placement or overrides finding at
most, placement first. The output is the share of collected tests that keep to the rules (in
their directory's suite, tolerated ones counted as outside, and not misfiled), then one line per
finding:

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
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Any

NO_REPORT = 3

# Evidence categories of integration work, in the order a finding names the first one found
_INTEGRATION_WORK = (
    "fs-write",
    "process",
    "socket",
    "db",
    "signal",
    "chdir",
    "fs-read",
)
_ENTRY_POINT = "entry-point"
_ORDER = ("placement", "overrides", "misfiled", "leak")


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


def _behavior(reports: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """What each judged test did, by node id; a test appears in the report of its process."""
    behavior: dict[str, dict[str, Any]] = {}
    for report in reports:
        behavior.update(report.get("behavior", {}))
    return behavior


def _scope_of(nodeid: str) -> str:
    """A test's class, or its file for a module-level test."""
    parts = nodeid.split("::")
    return "::".join(parts[:-1]) if len(parts) > 2 else parts[0]


def _first(evidence: dict[str, str], categories: Iterable[str]) -> str:
    """The first of the categories found, with its detail; "" for none."""
    for category in categories:
        if category in evidence:
            return f"{category} {evidence[category]}"
    return ""


def _verdict(entry: dict[str, Any]) -> tuple[str, str] | None:
    """(target suite, first evidence) for a unit test seen doing work its suite does not
    allow: running the project needs e2e, other integration work needs integration."""
    if entry.get("exempt") is not None or entry["suite"] != "unit":
        return None
    evidence = entry["evidence"]
    if _ENTRY_POINT in evidence:
        return ("e2e", _first(evidence, [_ENTRY_POINT]))
    if any(c in evidence for c in _INTEGRATION_WORK):
        return ("integration", _first(evidence, _INTEGRATION_WORK))
    return None


def _behavior_findings(
    behavior: dict[str, dict[str, Any]],
) -> list[tuple[str, str, str]]:
    """Misfiled tests, one finding per scope and target suite:
    "3 unit ➜ integration (fs-write /tmp/x)", the first test's evidence in parentheses."""
    groups: dict[tuple[str, str, str], list[str]] = {}
    for nodeid in sorted(behavior):
        verdict = _verdict(behavior[nodeid])
        if verdict is not None:
            target, evidence = verdict
            key = (_scope_of(nodeid), behavior[nodeid]["suite"], target)
            groups.setdefault(key, []).append(evidence)
    findings = []
    for (scope, suite, target), found in groups.items():
        findings.append(
            ("misfiled", scope, f"{len(found)} {suite} ➜ {target} ({found[0]})")
        )
    return findings


def _remarked(behavior: dict[str, dict[str, Any]]) -> dict[str, Counter[str]]:
    """Tests whose work belongs to their directory's suite though marked for another, counted
    by scope and marked suite: their marker is wrong, not their place."""
    remarked: dict[str, Counter[str]] = {}
    for nodeid, entry in behavior.items():
        verdict = _verdict(entry)
        if verdict is not None and verdict[0] == entry.get("directory"):
            remarked.setdefault(_scope_of(nodeid), Counter())[entry["suite"]] += 1
    return remarked


def _shifted(suites: dict[str, int], home: str, moved: Counter[str]) -> dict[str, int]:
    """Suite counts with the moved tests counted under the home suite."""
    shifted = Counter(suites)
    shifted.subtract(moved)
    shifted[home] += moved.total()
    return {suite: n for suite, n in shifted.items() if n > 0}


def _as_placed(
    scope: dict[str, Any], remarked: dict[str, Counter[str]]
) -> dict[str, Any]:
    """A scope with its remarked tests counted under its directory's suite; a file's
    ``file_suites`` take those of every scope of the file."""
    home, name = scope["directory"], scope["scope"]
    placed = {
        **scope,
        "suites": _shifted(scope["suites"], home, remarked.get(name, Counter())),
    }
    if "file_suites" in scope:
        in_file: Counter[str] = Counter()
        for other, moved in remarked.items():
            if other.split("::")[0] == name:
                in_file.update(moved)
        placed["file_suites"] = _shifted(scope["file_suites"], home, in_file)
    return placed


def judge(
    reports: Iterable[dict[str, Any]], threshold: float, outliers: int
) -> list[tuple[str, str, str]]:
    """The findings, as (kind, where, detail): placements, overrides, misfiled tests, then
    leaks."""
    reports = list(reports)
    scopes: dict[str, dict[str, Any]] = {}
    leaks: dict[str, list[str]] = {}
    for report in reports:
        scopes.update((s["scope"], s) for s in report["scopes"])
        leaks.update((leak["test"], leak["changed"]) for leak in report["leaks"])
    behavior = _behavior(reports)
    remarked = _remarked(behavior)
    findings: list[tuple[str, str, str]] = []
    for name in sorted(scopes):
        found = _scope_finding(_as_placed(scopes[name], remarked), threshold, outliers)
        if found:
            findings.append((found[0], name, found[1]))
    findings.extend(_behavior_findings(behavior))
    findings.extend(
        ("leak", test, "left changed: " + ", ".join(leaks[test]))
        for test in sorted(leaks)
    )
    findings.sort(key=lambda f: (_ORDER.index(f[0]), f[1]))
    return findings


def _misfiled_in_place(behavior: dict[str, dict[str, Any]]) -> int:
    """Misfiled tests that sit in their directory's suite, or in no suite directory: those
    outside their directory already count against the share."""
    return sum(
        1
        for entry in behavior.values()
        if _verdict(entry) and entry.get("directory", "") in ("", entry["suite"])
    )


def health(reports: Iterable[dict[str, Any]]) -> str:
    """The share of collected tests that keep to the rules, rounded down, so 100.0 means every
    test does: a test outside its directory's suite (tolerated or not) or misfiled does not."""
    reports = list(reports)
    whole = 0
    outside: dict[str, int] = {}
    for report in reports:
        whole = max(whole, report.get("suited", report["total"]))
        for scope in report["scopes"]:
            outside[scope["scope"]] = sum(
                n for suite, n in scope["suites"].items() if suite != scope["directory"]
            )
    if not whole:
        return "100.0"
    keeping = whole - sum(outside.values()) - _misfiled_in_place(_behavior(reports))
    return f"{math.floor(keeping * 1000 / whole) / 10:.1f}"


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
