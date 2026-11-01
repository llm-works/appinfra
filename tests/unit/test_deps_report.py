# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for appinfra/scripts/deps_report.py."""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import pytest
from packaging.specifiers import SpecifierSet
from packaging.version import Version

SCRIPTS = Path(__file__).resolve().parents[2] / "appinfra" / "scripts"

# Distance colors: within a major, one major behind, two or more
GAP0, GAP1, GAP2, RESET = "\033[0;93m", "\033[1;93m", "\033[1;91m", "\033[0m"
CI = "\033[1;95m"  # the ci column: CI installs another version


@pytest.fixture
def dr(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Load the script as a module; it imports install_deps from its own directory."""
    monkeypatch.syspath_prepend(str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(
        "deps_report", SCRIPTS / "deps_report.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # @dataclass resolves the module's names through sys.modules
    monkeypatch.setitem(sys.modules, "deps_report", module)
    spec.loader.exec_module(module)
    return module


def V(*versions: str) -> list[Version]:
    return [Version(v) for v in versions]


def v(text: str | None) -> Version | None:
    return Version(text) if text else None


class TestGraph:
    REQUIRES = {
        "a": ["b>=1", "c; extra == 'fast'", "nope; python_version < '3.0'"],
        "b": ["a", "d<2"],  # cycle back to a
        "c": ["d>=1.5"],
        "d": [],
    }

    def requires(self, name: str) -> list[str] | None:
        return self.REQUIRES.get(name)

    def test_declared_merges_ranges_and_skips_other_markers(
        self, dr: ModuleType
    ) -> None:
        graph = dr.declared(
            ["Foo_Bar>=1", "foo-bar[x]<3", "old; python_version < '3.0'"], "proj"
        )
        assert set(graph.deps) == {"foo-bar"}
        assert graph.deps["foo-bar"].spec == SpecifierSet(">=1,<3")
        assert graph.deps["foo-bar"].extras == {"x"}
        assert graph.edges == {"proj": {"foo-bar": SpecifierSet(">=1,<3")}}

    def test_transitive_follows_extras_through_cycles(self, dr: ModuleType) -> None:
        graph = dr.transitive(dr.declared(["a[fast]"], "proj"), self.requires)
        assert set(graph.deps) == {"a", "b", "c", "d"}
        assert graph.deps["d"].spec == SpecifierSet(">=1.5,<2")
        assert graph.edges["b"] == {"a": SpecifierSet(), "d": SpecifierSet("<2")}
        assert graph.edges["c"] == {"d": SpecifierSet(">=1.5")}

    def test_an_extra_is_followed_only_when_requested(self, dr: ModuleType) -> None:
        graph = dr.transitive(dr.declared(["a"], "proj"), self.requires)
        assert "c" not in graph.deps

    def test_a_distribution_that_is_not_installed_ends_the_walk(
        self, dr: ModuleType
    ) -> None:
        graph = dr.transitive(dr.declared(["ghost>=1"], "proj"), self.requires)
        assert set(graph.deps) == {"ghost"}


class TestPipVersions:
    def run(
        self, dr: ModuleType, **result: object
    ) -> tuple[list[Version] | None, list[str]]:
        completed = subprocess.CompletedProcess(
            [], result.pop("returncode", 0), **result
        )
        with patch.object(dr.subprocess, "run", return_value=completed) as run:
            versions = dr.pip_versions("pkg", include_pre=False)
        return versions, run.call_args.args[0]

    def test_reads_the_json_pip_prints(self, dr: ModuleType) -> None:
        out = json.dumps({"name": "pkg", "versions": ["2.0", "1.0", "not a version"]})
        versions, cmd = self.run(dr, stdout=out, stderr="")
        assert versions == V("2.0", "1.0")
        assert cmd[1:] == [
            "-m",
            "pip",
            "--disable-pip-version-check",
            "index",
            "versions",
            "pkg",
            "--json",
        ]

    def test_pre_releases_are_asked_for_with_pre(self, dr: ModuleType) -> None:
        with patch.object(
            dr.subprocess, "run", side_effect=subprocess.TimeoutExpired("pip", 1)
        ) as run:
            assert dr.pip_versions("pkg", include_pre=True) is None
        assert run.call_args.args[0][-1] == "--pre"

    @pytest.mark.parametrize(
        "result",
        [
            {
                "returncode": 1,
                "stdout": "",
                "stderr": "ERROR: No matching distribution",
            },
            {"stdout": "not json", "stderr": ""},
            {"stdout": json.dumps({"name": "pkg"}), "stderr": ""},
            {"stdout": json.dumps({"versions": "1.0"}), "stderr": ""},
        ],
    )
    def test_anything_else_is_none(
        self, dr: ModuleType, result: dict[str, object]
    ) -> None:
        assert self.run(dr, **result)[0] is None


class TestNewest:
    def test_pre_releases_count_only_when_asked(self, dr: ModuleType) -> None:
        versions = V("1.0", "2.0rc1", "1.1.dev3")
        assert dr.newest(versions, None, include_pre=False) == Version("1.0")
        assert dr.newest(versions, None, include_pre=True) == Version("2.0rc1")

    def test_within_a_range(self, dr: ModuleType) -> None:
        versions = V("1.0", "1.9", "2.0")
        assert dr.newest(versions, SpecifierSet("<2"), include_pre=False) == Version(
            "1.9"
        )
        assert dr.newest(versions, SpecifierSet(">3"), include_pre=False) is None

    def test_a_spec_naming_a_pre_release_admits_it(self, dr: ModuleType) -> None:
        """As pip does: ==2.0rc1 installs without --pre."""
        versions = V("1.9", "2.0rc1")
        spec = SpecifierSet("==2.0rc1")
        assert dr.newest(versions, spec, include_pre=False) == Version("2.0rc1")


class TestStatus:
    @pytest.mark.parametrize(
        ("installed", "spec", "in_range", "latest", "direct", "expected"),
        [
            (None, "", "1.0", "1.0", False, "missing"),
            ("1.0", "", None, None, False, "unknown"),
            ("1.0", ">=1", "1.0", "1.0", False, "✓"),  # up to date
            ("1.0", ">=1", "1.2", "1.2", False, "behind (2 minors)"),
            ("1.0.1", ">=1", "1.0.4", "1.0.4", False, "behind (patch)"),
            ("1.9", "<2", "1.9", "3.0", False, "capped (2 majors)"),
            ("1.5", "<2", "1.9", "3.0", False, "behind (4 minors), capped (2 majors)"),
            ("1.9", "<2", "1.9", "2.4", False, "capped (1 major)"),
            (
                "0.5.0",
                "<0.6",
                "0.5.3",
                "0.6.0",
                False,
                "behind (3 minors), capped (1 major)",
            ),
            ("1.9", "<1.10", "1.9", "1.12", False, "capped (3 minors)"),
            ("3.0", "<2", "1.9", "3.0", False, "out of range"),
            # requirers' ranges exclude each other: >=2 from one, <2 from another
            ("2.4", ">=2,<2", None, "2.4", False, "no release fits"),
            ("1.0", ">=99", None, "1.0", False, "no release fits"),
            (None, ">=2,<2", None, "2.4", False, "missing, no release fits"),
            # an exact pin missing from the list may be yanked, which pip still installs
            ("1.5", "==1.5", None, "2.0", False, "unknown"),
            (None, "==1.5", None, "2.0", False, "missing"),
            ("2.0.dev1", "", "1.9", "1.9", False, "pre-release"),
            ("1.0", "", None, None, True, "local"),
            ("0.13.1.dev29", "", None, None, True, "local pre-release"),
            ("3.0", "<2", None, None, True, "out of range, local"),
        ],
    )
    def test_labels(
        self, dr, installed, spec, in_range, latest, direct, expected
    ) -> None:  # type: ignore[no-untyped-def]
        result = dr.status(
            v(installed), SpecifierSet(spec), v(in_range), v(latest), direct
        )
        assert result == expected


class TestBounds:
    @pytest.mark.parametrize(
        ("spec", "floor", "ceil"),
        [
            ("", "", ""),
            ("<8,>=7.4", "7.4", "8"),
            (">=4.5,>=4.16,<5.0,<6", "4.16", "5.0"),
            (">=2,>2", ">2", ""),
            ("<=3,<3", "", "3"),
            ("<=4.4", "", "<=4.4"),
            ("!=5.13,<10,>=5", "5", "10"),  # exclusions are not bounds
            ("<3,>=2.12,!=2.0.*,!=2.1.*", "2.12", "3"),
            ("==2.50.1", "==2.50.1", ""),  # a pin is the whole range
            (">=2.10,<3,==2.13.0", "==2.13.0", ""),
            ("==2.13.*", "==2.13.*", ""),
            ("==2.*,>=2.10,<2.13", "==2.*,2.10", "2.13"),  # a wildcard pin is a range
            ("===1.0+local", "===1.0+local", ""),
            (">=2,<2", "2", "2"),  # empty: the status says no release fits
            ("==1.0,==2.0", "==1.0,==2.0", ""),  # pins that cannot both hold
            ("~=0.1", "0.1", "1"),
            ("~=1.4.2", "1.4.2", "1.5"),
        ],
    )
    def test_floor_and_ceil(
        self, dr: ModuleType, spec: str, floor: str, ceil: str
    ) -> None:
        assert dr.bounds(SpecifierSet(spec)) == (floor, ceil)

    def test_requirers_pinning_the_same_version(self, dr: ModuleType) -> None:
        """Two requirers' identical pins show once."""
        spec = SpecifierSet(">=2.10,<3,==2.13.0") & SpecifierSet("==2.13.0")
        assert dr.bounds(spec) == ("==2.13.0", "")


class TestShownVersion:
    @pytest.mark.parametrize(
        ("version", "shown"),
        [
            ("1.0", "1.0"),
            ("0.1.dev29+ga47dbd027.d20261031", "0.1.dev29"),  # setuptools-scm build
            ("0.8.1.dev2+g0a4e9df", "0.8.1.dev2"),
            ("1.0+d20261031", "1.0"),  # dirty build of a tagged release
            ("2.13.0+cu124", "2.13.0+cu124"),  # a distribution's own label stays
            ("1.7.1+cpu", "1.7.1+cpu"),
        ],
    )
    def test_build_labels_dropped(
        self, dr: ModuleType, version: str, shown: str
    ) -> None:
        assert dr.shown_version(Version(version)) == shown


class TestAvailable:
    @pytest.mark.parametrize(
        ("installed", "in_range", "newest", "expected"),
        [
            (None, "1.0", "1.0", ""),
            ("1.0", "1.0", "1.0", ""),
            ("1.0", "1.2", "1.2", ""),  # within the range: the ci column
            ("1.9", "1.9", "3.0", "3.0"),
            ("1.5", "1.9", "3.0", "3.0"),
            ("1.0", None, None, ""),
        ],
    )
    def test_newest_outside_the_range(
        self, dr, installed, in_range, newest, expected
    ) -> None:  # type: ignore[no-untyped-def]
        row = dr.Row(v(installed), v(in_range), v(newest), "", "")
        assert dr._plain(dr.available(row)) == expected

    def test_colored_by_its_distance(self, dr: ModuleType) -> None:
        row = dr.Row(v("1.5"), v("1.9"), v("3.0"), "", "")
        assert dr._paint(dr.available(row), color=True) == f"{GAP2}3.0{RESET}"


class TestCiVersion:
    @pytest.mark.parametrize(
        ("installed", "in_range", "direct", "expected"),
        [
            ("1.9", "1.9", False, "✓"),  # CI gets what is installed
            ("1.5", "1.9", False, "1.9"),  # behind
            ("3.0", "1.9", False, "1.9"),  # out of range
            ("2.0rc1", "1.9", False, "1.9"),  # pre-release installed
            (None, "1.9", False, "1.9"),  # missing
            ("1.0", None, False, "?"),  # nothing known within the range
            ("0.1", None, True, "index"),  # a path or URL install
        ],
    )
    def test_what_a_fresh_install_resolves(
        self, dr, installed, in_range, direct, expected
    ) -> None:  # type: ignore[no-untyped-def]
        assert dr.ci_version(v(installed), v(in_range), direct) == expected

    def test_a_difference_in_bold_magenta_a_match_in_green(
        self, dr: ModuleType
    ) -> None:
        def ci_cell(ci: str) -> str:
            row = dr.Row(Version("1.0"), Version("1.0"), None, "✓", ci)
            tree = dr._Tree(dr.declared(["p"], "proj"), {"p": row}, deep=False)
            return dr._paint(tree.build()[0][4], color=True)

        assert ci_cell("1.9") == "\033[1;95m1.9\033[0m"
        assert ci_cell("✓") == "\033[0;32m✓\033[0m"


class TestDistance:
    @pytest.mark.parametrize(
        ("installed", "newer", "expected"),
        [
            ("4.0.2", "7.0.0", (0, 3)),
            ("2.1", "2.5", (1, 4)),
            ("6.170.13", "6.170.14", (2, 1)),
            # past the patch: PATCH, whose step count is not shown (dates would read 124)
            ("6.0.12.20260906", "6.0.12.20261030", (2, 124)),
            ("0.5", "0.6", (0, 1)),  # below 1.0 the minor is the major
            ("0.5.0", "0.5.3", (1, 3)),
            ("0.9", "1.2", (0, 1)),
            ("1.0", "1.0.post1", (2, 0)),  # same release
        ],
    )
    def test_level_and_steps(self, dr, installed, newer, expected) -> None:  # type: ignore[no-untyped-def]
        assert dr.distance(Version(installed), Version(newer)) == expected


class TestGap:
    @pytest.mark.parametrize(
        ("installed", "newer", "steps"),
        [
            ("2.1", "2.5", 0),  # minor within a major
            ("0.5.0", "0.5.3", 0),  # patch below 1.0
            ("1.9", "2.0", 1),
            ("0.5.0", "0.6.0", 1),  # below 1.0 the minor is the major
            ("0.9", "1.2", 1),
            ("0.0.3", "0.0.5", 2),  # below 0.1 the patch is
            ("4.0.2", "7.0.0", 3),
            ("0.30", "0.53", 23),
            ("2", "2.0.1", 0),  # short release tuples
            ("3.0", "2.0", 0),  # never negative
        ],
    )
    def test_major_steps(
        self, dr: ModuleType, installed: str, newer: str, steps: int
    ) -> None:
        assert dr.gap(Version(installed), Version(newer)) == steps


class TestColor:
    @pytest.mark.parametrize(
        ("no_color", "env", "tty", "expected"),
        [
            (False, {}, True, True),
            (True, {}, True, False),
            (False, {"NO_COLOR": "1"}, True, False),
            (False, {}, False, False),
        ],
    )
    def test_use_color(self, dr, monkeypatch, no_color, env, tty, expected) -> None:  # type: ignore[no-untyped-def]
        monkeypatch.delenv("NO_COLOR", raising=False)
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        with patch.object(dr.sys, "stdout") as stdout:
            stdout.isatty.return_value = tty
            assert dr.use_color(no_color) is expected

    @pytest.mark.parametrize(
        ("in_range", "newest", "expected"),
        [
            # behind in the ci column's color, capped in available's distance color
            ("1.6", "1.6", f"{CI}behind (1 minor){RESET}"),
            (
                "1.9",
                "2.0",
                f"{CI}behind (4 minors){RESET}, {GAP1}capped (1 major){RESET}",
            ),
            ("1.5", "9.0", f"{GAP2}capped (8 majors){RESET}"),
        ],
    )
    def test_behind_and_capped_in_their_columns_color(
        self, dr, in_range, newest, expected
    ) -> None:  # type: ignore[no-untyped-def]
        installed = Version("1.5")
        status = dr.status(installed, SpecifierSet("<2"), v(in_range), v(newest), False)
        row = dr.Row(installed, v(in_range), v(newest), status, "")
        assert dr._paint(dr._status_cell(row), color=True) == expected

    def test_other_labels_keep_their_color(self, dr: ModuleType) -> None:
        row = dr.Row(Version("3.0"), Version("1.9"), Version("3.0"), "out of range", "")
        assert (
            dr._paint(dr._status_cell(row), color=True)
            == "\033[0;31mout of range\033[0m"
        )

    def test_plain_without_color(self, dr: ModuleType) -> None:
        row = dr.Row(
            Version("1.5"), Version("1.9"), Version("3.0"), "behind, capped", ""
        )
        assert dr._paint(dr._status_cell(row), color=False) == "behind, capped"


class TestReport:
    PROJECT = {
        "name": "proj",
        "dependencies": ["web<2", "lib>=1"],
        "optional-dependencies": {"x": ["gone", "offline", "local", "proj[x]"]},
    }
    INSTALLED = {
        "web": "1.9",
        "lib": "1.0",
        "core": "2.0",
        "offline": "1.0",
        "local": "0.1",
        "appinfra": "0.13.0",
    }
    REQUIRES = {"web": ["lib>=1", "core<3"], "lib": ["core>=2"]}
    INDEX = {
        "web": V("1.9", "2.0"),
        "lib": V("1.0", "1.1"),
        "core": V("2.0"),
        "appinfra": V("0.13.0"),
        "local": V("9.9"),  # never asked: a direct install
    }

    def run(
        self,
        dr: ModuleType,
        deep: bool,
        color: bool = False,
        requires: dict[str, list[str]] | None = None,
        asked: list[str] | None = None,
    ) -> list[str]:
        asked = [] if asked is None else asked

        def versions(name: str) -> list[Version] | None:
            asked.append(name)
            return self.INDEX.get(name)

        with (
            patch.object(dr, "_installed_version", lambda n: v(self.INSTALLED.get(n))),
            patch.object(dr, "_installed_requires", (requires or self.REQUIRES).get),
            patch.object(dr, "_direct_install", lambda n: n == "local"),
        ):
            text = dr.report(self.PROJECT, deep, False, color, versions)
        assert "local" not in asked  # a direct install is not looked up
        return text.splitlines()

    def test_a_cap_from_another_dependency_counts_without_deep(
        self, dr: ModuleType
    ) -> None:
        """web caps lib below 1.1, so a fresh install (CI) gets lib 1.0 too: capped, not behind."""
        asked: list[str] = []
        requires = {"web": ["lib<1.1", "core<3"], "lib": ["core>=2"]}
        lines = self.run(dr, deep=False, requires=requires, asked=asked)
        cols = {row[0]: row[1:] for row in self.table(lines)}
        # floor, ceil, installed, ci, available, status: the flat list shows the
        # combined range, so web's cap is the ceil, and CI gets 1.0 as installed
        assert cols["lib"] == ["1", "1.1", "1.0", "✓", "1.1", "capped (1 minor)"]
        # only the lines shown are looked up
        assert "core" not in asked and "lib" in asked

    def table(self, lines: list[str]) -> list[list[str]]:
        """Each line cut at the header's column starts."""
        header = lines[0]
        starts = [header.index(h) for h in header.split()]
        ends = starts[1:] + [None]
        rows = []
        for line in lines[1:]:
            if not line.strip():
                break
            rows.append([line[s:e].strip() for s, e in zip(starts, ends, strict=True)])
        return rows

    def test_direct_dependencies_with_their_status(self, dr: ModuleType) -> None:
        cols = {row[0]: row[1:] for row in self.table(self.run(dr, deep=False))}
        # floor, ceil, installed, ci, available, status
        assert cols["web"] == ["", "2", "1.9", "✓", "2.0", "capped (1 major)"]
        assert cols["lib"] == ["1", "", "1.0", "1.1", "", "behind (1 minor)"]
        assert cols["gone"] == ["", "", "-", "?", "", "missing"]
        assert cols["offline"][3:] == ["?", "", "unknown"]
        assert cols["local"][3:] == ["index", "", "local"]
        # the framework's check tools, which make setup adds to every other project
        assert cols["appinfra"][3:] == ["✓", "", "✓"]  # CI matches, up to date
        assert "proj" not in cols and "core" not in cols

    def test_installed_without_the_local_label(self, dr: ModuleType) -> None:
        """A build's local label (+g<sha>.d<date>) is not shown; it is on no index."""
        with patch.dict(self.INSTALLED, {"local": "0.1.dev29+ga47dbd027.d20261031"}):
            cols = {row[0]: row[1:] for row in self.table(self.run(dr, deep=False))}
        assert cols["local"][2] == "0.1.dev29"

    def test_ci_shows_what_a_missing_package_gets(self, dr: ModuleType) -> None:
        with patch.dict(self.INDEX, {"gone": V("4.2")}):
            cols = {row[0]: row[1:] for row in self.table(self.run(dr, deep=False))}
        assert cols["gone"][2:] == ["-", "4.2", "", "missing"]

    def test_deep_shows_the_tree(self, dr: ModuleType) -> None:
        rows = self.table(self.run(dr, deep=True))
        names = [row[0] for row in rows]
        lib = names.index("lib")
        assert names[lib + 1] == "└── core" and rows[lib + 1][3] == "2.0"
        web = names.index("web")
        assert rows[web + 1][0] == "├── core" and rows[web + 1][3] == "(above)"
        assert rows[web + 2][0] == "└── lib" and rows[web + 2][3] == "(top level)"

    def test_header_and_legend(self, dr: ModuleType) -> None:
        lines = self.run(dr, deep=False)
        assert lines[0].split() == [
            "package",
            "floor",
            "ceil",
            "installed",
            "ci",
            "available",
            "status",
        ]
        assert lines[-2:] == [
            "ci: ✓ = CI installs the same version, else the version it installs",
            "available: newest release outside the range",
        ]

    def test_color_keeps_the_columns_aligned(self, dr: ModuleType) -> None:
        plain = self.run(dr, deep=True)
        colored = self.run(dr, deep=True, color=True)
        assert any("\033[" in line for line in colored)
        assert [re.sub(r"\033\[[0-9;]*m", "", line) for line in colored] == plain
