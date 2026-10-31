#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Report how far the installed dependencies are from their newest releases.

Reads the dependencies and every optional-dependency group of ./pyproject.toml
(as ``make setup`` installs them, see install_deps.py), the versions installed
in the running interpreter, and the releases pip finds for each: ``pip index
versions`` asks the indexes pip itself installs from (index-url,
extra-index-url, find-links, credentials), skipping yanked releases and
releases for other Python versions. Each package gets a line: required range,
installed version, newest release within the range and outside it, and a
status:

- ✓: up to date, the newest release within the range is installed
- behind: a newer release within the range is not installed
- capped: a newer release exists outside the range
- out of range: the installed version does not satisfy the range
- pre-release installed: the installed version is a pre-release
- direct install: installed from a URL or local path (PEP 610); not looked up
- missing: not installed
- unknown: pip found no release (index unreachable, or a pip without --json)

Behind and capped say how far that release is: "(3 majors)", "(2 minors)" or
"(patch)"; below 1.0 the minor counts as the major.

``--deep`` shows the whole tree of installed dependencies; a package's range
on each line is what its parent requires, its status uses every requirer's
range combined. Pre-releases count only with ``--include-pre``. Ends with
``pip check``'s conflicts. Read-only: nothing is installed.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tomllib
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from importlib import metadata

from install_deps import collect_deps
from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import Specifier, SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

UP_TO_DATE = "✓"  # the status when nothing else applies
_TIMEOUT_S = 60.0
_WORKERS = 16

# Lookups by canonical distribution name
RequiresLookup = Callable[[str], list[str] | None]
VersionsLookup = Callable[[str], list[Version] | None]


@dataclass
class Dependency:
    """A distribution the project needs: the range every requirer allows, and its extras."""

    spec: SpecifierSet = field(default_factory=SpecifierSet)
    extras: set[str] = field(default_factory=set)


@dataclass
class Graph:
    """Who requires what: the project at ``root``, then each installed distribution."""

    root: str
    deps: dict[str, Dependency] = field(default_factory=dict)
    edges: dict[str, dict[str, SpecifierSet]] = field(default_factory=dict)

    def add(self, req: Requirement, requirer: str) -> str:
        """Record that ``requirer`` requires ``req``; returns the canonical name."""
        name = canonicalize_name(req.name)
        dep = self.deps.setdefault(name, Dependency())
        dep.spec &= req.specifier
        dep.extras |= req.extras
        edges = self.edges.setdefault(requirer, {})
        edges[name] = edges.get(name, SpecifierSet()) & req.specifier
        return name


@dataclass(frozen=True)
class Row:
    """What is known about one distribution."""

    installed: Version | None
    in_range: Version | None
    newest: Version | None
    status: str
    ci: str  # what a fresh install resolves when it differs, see ci_version()


# -- the dependency graph ----------------------------------------------------


def _applies(req: Requirement, extra: str = "") -> bool:
    """Whether the requirement's marker holds in this interpreter for ``extra``."""
    return req.marker is None or req.marker.evaluate({"extra": extra})


def declared(requirements: Iterable[str], project: str) -> Graph:
    """The project's own requirements whose marker applies."""
    graph = Graph(root=project)
    for text in requirements:
        req = Requirement(text)
        if _applies(req):
            graph.add(req, project)
    return graph


def _child_requirements(
    name: str, extras: set[str], requires: RequiresLookup
) -> list[Requirement]:
    """The requirements of an installed distribution that apply for its extras."""
    out: list[Requirement] = []
    for text in requires(name) or []:
        try:
            req = Requirement(text)
        except InvalidRequirement:
            continue
        if any(_applies(req, extra) for extra in {"", *extras}):
            out.append(req)
    return out


def transitive(graph: Graph, requires: RequiresLookup) -> Graph:
    """Extend ``graph`` with what the installed distributions require, recursively."""
    queue = list(graph.deps)
    walked: dict[str, frozenset[str]] = {}
    while queue:
        name = queue.pop()
        extras = frozenset(graph.deps[name].extras)
        if walked.get(name) == extras:
            continue
        walked[name] = extras
        for req in _child_requirements(name, set(extras), requires):
            child = graph.add(req, name)
            if walked.get(child) != frozenset(graph.deps[child].extras):
                queue.append(child)
    return graph


# -- versions ----------------------------------------------------------------


def pip_versions(name: str, include_pre: bool) -> list[Version] | None:
    """The releases pip can install for ``name``; None if pip cannot tell."""
    cmd = [
        sys.executable,
        "-m",
        "pip",
        "--disable-pip-version-check",
        "index",
        "versions",
        name,
        "--json",
    ]
    if include_pre:
        cmd.append("--pre")
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=_TIMEOUT_S, check=False
        )
        found = (
            json.loads(result.stdout)["versions"] if result.returncode == 0 else None
        )
    except (subprocess.TimeoutExpired, ValueError, KeyError, TypeError):
        return None
    if not isinstance(found, list):
        return None
    versions = []
    for text in found:
        try:
            versions.append(Version(str(text)))
        except InvalidVersion:
            continue
    return versions


def lookup_all(
    names: Iterable[str], versions: VersionsLookup
) -> dict[str, list[Version] | None]:
    """Look up every name, in parallel."""
    names = list(names)
    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        return dict(zip(names, pool.map(versions, names), strict=True))


def newest(
    versions: Iterable[Version], spec: SpecifierSet | None, include_pre: bool
) -> Version | None:
    """The newest version, within ``spec`` if one is given."""
    candidates = [v for v in versions if include_pre or not v.is_prerelease]
    if spec is not None:
        candidates = [v for v in candidates if spec.contains(v, prereleases=True)]
    return max(candidates, default=None)


def status(
    installed: Version | None,
    spec: SpecifierSet,
    in_range: Version | None,
    latest: Version | None,
    direct: bool,
) -> str:
    """The status; several apply at once, comma-separated."""
    if installed is None:
        return "missing"
    labels = []
    if installed.is_prerelease:
        labels.append("pre-release installed")
    if not spec.contains(installed, prereleases=True):
        labels.append("out of range")
    if direct:
        labels.append("direct install")
    elif latest is None:
        labels.append("unknown")
    else:
        if in_range is not None and in_range > installed:
            labels.append(_with_gap("behind", installed, in_range))
        if latest > max(in_range or installed, installed) and not spec.contains(
            latest, prereleases=True
        ):
            labels.append(_with_gap("capped", installed, latest))
    return ", ".join(labels) or UP_TO_DATE


def _with_gap(label: str, installed: Version, newer: Version) -> str:
    """``label`` with how far ``newer`` is: "(3 majors)", "(2 minors)" or "(patch)"."""
    level, steps = distance(installed, newer)
    if level == PATCH:
        return f"{label} (patch)"
    unit = "major" if level == MAJOR else "minor"
    return f"{label} ({steps} {unit}{'s' if steps != 1 else ''})"


def build_rows(
    graph: Graph,
    names: Iterable[str],
    installed: Callable[[str], Version | None],
    available: dict[str, list[Version] | None],
    direct: set[str],
    include_pre: bool,
) -> dict[str, Row]:
    """A row per name; its range is every requirer's in ``graph``, as pip resolves it."""
    rows = {}
    for name in names:
        dep = graph.deps[name]
        versions = available.get(name) or []
        in_range = newest(versions, dep.spec, include_pre)
        latest = newest(versions, None, include_pre)
        have = installed(name)
        rows[name] = Row(
            have,
            in_range,
            latest,
            status(have, dep.spec, in_range, latest, name in direct),
            ci_version(have, in_range, name in direct),
        )
    return rows


CI_SAME = "✓"


def ci_version(
    installed: Version | None, in_range: Version | None, direct: bool
) -> str:
    """What a fresh install (CI) resolves when it is not what is installed; CI_SAME when it is.

    The newest release within every requirer's range: a different version for a
    package behind, out of range or on a pre-release, the version a missing one
    gets. "index" for a direct install, whose index version is not compared, and
    "?" when nothing within the range is known.
    """
    if direct:
        return "index"
    if in_range is None:
        return "?"
    return CI_SAME if in_range == installed else str(in_range)


# -- rendering ---------------------------------------------------------------

_LOWER, _UPPER = (">=", ">"), ("<=", "<")

# A cell is text in styled pieces; the palette matches scripts/_ui.sh
Cell = list[tuple[str, str]]
_STYLES = {
    "bold": "\033[1m",
    "red": "\033[0;31m",
    "green": "\033[0;32m",
    "blue": "\033[0;34m",
    "gray": "\033[0;90m",
    # how far a newer release is from the installed one, see gap()
    "gap0": "\033[0;93m",  # bright yellow: within the same major
    "gap1": "\033[1;93m",  # bright bold yellow: one major behind
    "gap2": "\033[1;91m",  # bright bold red: two majors or more
    "ci": "\033[1;95m",  # bright bold magenta: CI resolves another version
}
_RESET = "\033[0m"
_STATUS_STYLES = {
    UP_TO_DATE: "green",
    "out of range": "red",
    "missing": "red",
    "unknown": "gray",
    "direct install": "blue",
    "pre-release installed": "blue",
}


MAJOR, MINOR, PATCH = 0, 1, 2


def distance(installed: Version, newer: Version) -> tuple[int, int]:
    """Where ``newer`` first differs from ``installed``, and by how many steps there.

    The level is MAJOR, MINOR or PATCH (any later component), counted from the
    first release component that is not zero: below 1.0 the minor is the major
    (0.5 to 0.6 is a major step), as semver treats it.
    """
    size = max(len(installed.release), len(newer.release), 3)
    a = (*installed.release, *(0,) * size)[:size]
    b = (*newer.release, *(0,) * size)[:size]
    lead: int | None = None
    for i, (x, y) in enumerate(zip(a, b, strict=True)):
        if lead is None and (x or y):
            lead = i
        if x != y:
            return min(i - (lead if lead is not None else i), PATCH), max(y - x, 0)
    return PATCH, 0  # same release, e.g. a post release


def gap(installed: Version, newer: Version) -> int:
    """Major steps from ``installed`` to ``newer``: 0 within the same major."""
    level, steps = distance(installed, newer)
    return steps if level == MAJOR else 0


def _gap_style(installed: Version, newer: Version) -> str:
    """gap0, gap1 or gap2 (two majors or more)."""
    return f"gap{min(gap(installed, newer), 2)}"


def _tightest(specs: list[Specifier], upper: bool) -> Specifier | None:
    """The strictest bound: highest lower or lowest upper; on a tie, the exclusive one."""
    if not specs:
        return None

    def key(s: Specifier) -> tuple[Version, bool]:
        """Order by version, then the exclusive bound as the stricter one."""
        exclusive = s.operator in (">", "<")
        return Version(s.version), (not exclusive if upper else exclusive)

    return min(specs, key=key) if upper else max(specs, key=key)


def _compatible(spec: Specifier) -> list[Specifier]:
    """``~=X.Y`` as its bounds, ``>=X.Y,<X+1`` (PEP 440); other specifiers as they are."""
    if spec.operator != "~=":
        return [spec]
    head = list(Version(spec.version).release[:-1])
    head[-1] += 1
    return [Specifier(f">={spec.version}"), Specifier(f"<{'.'.join(map(str, head))}")]


def bounds(spec: SpecifierSet) -> tuple[str, str]:
    """The floor and ceiling: bare versions for ``>=`` and ``<``, the operator otherwise."""
    try:
        specs = [s for each in spec for s in _compatible(each)]
        lower = _tightest([s for s in specs if s.operator in _LOWER], upper=False)
        upper = _tightest([s for s in specs if s.operator in _UPPER], upper=True)
    except InvalidVersion:
        return str(spec), ""
    pins = sorted(str(s) for s in specs if s.operator in ("==", "==="))
    excluded = sorted(str(s) for s in specs if s.operator == "!=")
    floor = [lower.version if lower.operator == ">=" else str(lower)] if lower else []
    ceil = [upper.version if upper.operator == "<" else str(upper)] if upper else []
    return ",".join(floor + pins), ",".join(ceil + excluded)


def _newer(row: Row) -> dict[str, Version]:
    """The newer releases: "behind" within the range, "capped" the newest outside it."""
    if row.installed is None:
        return {}
    newer = {}
    if row.in_range is not None and row.in_range > row.installed:
        newer["behind"] = row.in_range
    if row.newest is not None and row.newest > max(
        row.in_range or row.installed, row.installed
    ):
        newer["capped"] = row.newest
    return newer


def available(row: Row) -> Cell:
    """The newest release outside the range, colored by how far it is from the installed one.

    A newer release within the range is what a fresh install gets: the ci column.
    """
    capped = _newer(row).get("capped")
    if row.installed is None or capped is None:
        return []
    return [(str(capped), _gap_style(row.installed, capped))]


def _status_cell(row: Row) -> Cell:
    """The status, each label in the color of the column it refers to.

    behind is about the ci column, so it is in the ci color; capped is about
    available, so it is colored by the distance to that release, as available is.
    """
    capped = _newer(row).get("capped")  # None when nothing is installed
    cell: Cell = []
    for label in row.status.split(", ") if row.status else []:
        cell += [(", ", "")] if cell else []
        kind = label.split(" (")[0]  # "capped (3 majors)" is a capped label
        if kind == "behind":
            cell.append((label, "ci"))
        elif kind == "capped" and capped is not None and row.installed is not None:
            cell.append((label, _gap_style(row.installed, capped)))
        else:
            cell.append((label, _STATUS_STYLES.get(label, "")))
    return cell


class _Tree:
    """Lines of the report: the project's requirements, with their subtrees if deep."""

    def __init__(self, graph: Graph, rows: dict[str, Row], deep: bool) -> None:
        self.graph, self.rows, self.deep = graph, rows, deep
        self.roots = sorted(graph.edges.get(graph.root, {}).items())
        self.shown = {name for name, _ in self.roots}
        self.lines: list[list[Cell]] = []

    def build(self) -> list[list[Cell]]:
        """The cells of every line: package, floor, ceil, installed, ci, available, status.

        In the tree a line's range is what its parent requires, which shows where a
        cap comes from; the flat list shows every requirer's range combined, the one
        its status and ci value come from.
        """
        for name, spec in self.roots:
            self._line(name, spec if self.deep else self.graph.deps[name].spec, "", "")
        return self.lines

    def _range(self, lead: str, name: str, spec: SpecifierSet, top: bool) -> list[Cell]:
        """The package and floor / ceil cells of a line."""
        floor, ceil = bounds(spec)
        return [
            [(lead, "gray"), (name, "bold" if top else "")],
            [(floor, "")],
            [(ceil, "")],
        ]

    def _line(self, name: str, spec: SpecifierSet, lead: str, indent: str) -> None:
        """A package's line, then its children under ``indent`` if deep."""
        row = self.rows[name]
        installed = str(row.installed) if row.installed is not None else "-"
        self.lines.append(
            self._range(lead, name, spec, not lead)
            + [
                [(installed, "")],
                [(row.ci, "green" if row.ci == CI_SAME else "ci")],
                available(row),
                _status_cell(row),
            ]
        )
        if self.deep:
            self._children(name, indent)

    def _children(self, name: str, indent: str) -> None:
        """A package's requirements; one shown before is referred to, not expanded again."""
        children = sorted(self.graph.edges.get(name, {}).items())
        for i, (child, spec) in enumerate(children):
            last = i == len(children) - 1
            lead = indent + ("└── " if last else "├── ")
            if child in self.shown:
                where = "(top level)" if child in dict(self.roots) else "(above)"
                self.lines.append(
                    self._range(lead, child, spec, False)
                    + [[(where, "gray")], [], [], []]
                )
                continue
            self.shown.add(child)
            self._line(child, spec, lead, indent + ("    " if last else "│   "))


_HEADER = ["package", "floor", "ceil", "installed", "ci", "available", "status"]
_LEGEND = """\
ci: ✓ = CI installs the same version, else the version it installs
available: newest release outside the range"""


def _plain(cell: Cell) -> str:
    """The cell's text, without styles."""
    return "".join(text for text, _ in cell)


def _paint(cell: Cell, color: bool) -> str:
    """The cell's text, with its styles when ``color``."""
    return "".join(
        f"{_STYLES[style]}{text}{_RESET}" if color and style and text else text
        for text, style in cell
    )


def render(graph: Graph, rows: dict[str, Row], deep: bool, color: bool) -> str:
    """The report as aligned columns, then the legend."""
    table = [[[(h, "bold")] for h in _HEADER], *_Tree(graph, rows, deep).build()]
    widths = [
        max(len(_plain(line[i])) for line in table) for i in range(len(_HEADER) - 1)
    ]
    lines = []
    for line in table:
        cells = [
            _paint(cell, color) + " " * (width - len(_plain(cell)))
            for cell, width in zip(line[:-1], widths, strict=True)
        ]
        lines.append(("  ".join(cells) + "  " + _paint(line[-1], color)).rstrip())
    return "\n".join(lines) + "\n\n" + _paint([(_LEGEND, "gray")], color)


# -- main --------------------------------------------------------------------


def _installed_version(name: str) -> Version | None:
    """The version installed in this interpreter; None if not installed."""
    try:
        return Version(metadata.version(name))
    except (metadata.PackageNotFoundError, InvalidVersion):
        return None


def _installed_requires(name: str) -> list[str] | None:
    """The installed distribution's Requires-Dist; None if not installed."""
    try:
        return metadata.requires(name)
    except metadata.PackageNotFoundError:
        return None


def _direct_install(name: str) -> bool:
    """Installed from a URL or local path (PEP 610), not from an index."""
    try:
        return metadata.distribution(name).read_text("direct_url.json") is not None
    except metadata.PackageNotFoundError:
        return False


def report(
    project: dict[str, object],
    deep: bool,
    include_pre: bool,
    color: bool,
    versions: VersionsLookup,
) -> str:
    """The report for a loaded [project] table.

    The whole installed tree is read either way (local metadata only), so a
    range is every requirer's, as a fresh install (CI) resolves it; only the
    lines shown are looked up on the index.
    """
    graph = declared(collect_deps(project), str(project["name"]))
    roots = list(graph.deps)
    transitive(graph, _installed_requires)
    shown = list(graph.deps) if deep else roots
    direct = {name for name in shown if _direct_install(name)}
    # missing packages too: the ci column shows what a fresh install gets for them
    wanted = [n for n in shown if n not in direct]
    rows = build_rows(
        graph,
        shown,
        _installed_version,
        lookup_all(wanted, versions),
        direct,
        include_pre,
    )
    return render(graph, rows, deep, color)


def use_color(no_color: bool) -> bool:
    """Color on a terminal unless --no-color or NO_COLOR (https://no-color.org/)."""
    return not no_color and not os.environ.get("NO_COLOR") and sys.stdout.isatty()


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """--deep, --include-pre and --no-color."""
    parser = argparse.ArgumentParser(
        description="Report installed versus newest dependencies."
    )
    parser.add_argument(
        "--deep", action="store_true", help="show the whole dependency tree"
    )
    parser.add_argument("--include-pre", action="store_true", help="count pre-releases")
    parser.add_argument("--no-color", action="store_true", help="plain text, no colors")
    return parser.parse_args(argv)


def _load_project() -> dict[str, object]:
    """The [project] table of ./pyproject.toml."""
    with open("pyproject.toml", "rb") as f:
        project: dict[str, object] = tomllib.load(f)["project"]
    return project


def _pip_check() -> str:
    """What ``pip check`` says about the installed packages."""
    result = subprocess.run(
        [sys.executable, "-m", "pip", "--disable-pip-version-check", "check"],
        capture_output=True,
        text=True,
        check=False,
    )
    return (result.stdout or result.stderr).rstrip()


def main(argv: list[str] | None = None) -> int:
    """Print the report for ./pyproject.toml; 2 if it cannot be read."""
    args = _parse_args(argv)
    color = use_color(args.no_color)
    try:
        project = _load_project()
        text = report(
            project,
            args.deep,
            args.include_pre,
            color,
            lambda name: pip_versions(name, args.include_pre),
        )
    except (OSError, tomllib.TOMLDecodeError, KeyError, InvalidRequirement) as e:
        print(f"deps: cannot read pyproject.toml: {e!r}", file=sys.stderr)
        return 2
    print(text)
    check = _pip_check()
    style = "green" if check.startswith("No broken requirements") else "red"
    print("\npip check: " + _paint([(check, style)], color))
    return 0


if __name__ == "__main__":
    sys.exit(main())
