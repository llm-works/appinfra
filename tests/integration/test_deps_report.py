# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""make deps / make deps.deep on a fixture project, against a local package index."""

from __future__ import annotations

import functools
import os
import re
import subprocess
import sys
import threading
from collections.abc import Iterator
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from importlib import metadata
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest.mock import patch

import pytest
from packaging.version import Version

from tests.helpers.deps_report import V, load_deps_report, v


@pytest.fixture
def dr(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """The script, loaded as a module."""
    return load_deps_report(monkeypatch)


MAKE_DIR = Path(__file__).resolve().parents[2] / "appinfra" / "scripts" / "make"

PYPROJECT = """\
[project]
name = "fixture-proj"
dependencies = ["packaging>=22,<27", "pyyaml>=6"]

[project.optional-dependencies]
extra = ["fixture-not-installed"]
"""


def _write_index(root: Path, releases: dict[str, list[str]]) -> None:
    """A PEP 503 simple index: one page per project, a wheel link per version."""
    for name, versions in releases.items():
        page = root / "simple" / name
        page.mkdir(parents=True)
        links = "".join(
            f'<a href="/files/{name}-{v}-py3-none-any.whl">{name}-{v}-py3-none-any.whl</a>\n'
            for v in versions
        )
        (page / "index.html").write_text(f"<html><body>\n{links}</body></html>\n")


@pytest.fixture
def index_url(tmp_path: Path) -> Iterator[str]:
    """A local index: packaging has a release past the project's cap, pyyaml one within range."""
    root = tmp_path / "index"
    _write_index(
        root,
        {
            "packaging": [metadata.version("packaging"), "99.0"],
            "pyyaml": [metadata.version("pyyaml"), "6.99"],
        },
    )
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(root))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/simple/"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def _make(
    project: Path, target: str, index_url: str
) -> subprocess.CompletedProcess[str]:
    (project / "pyproject.toml").write_text(PYPROJECT)
    (project / "Makefile").write_text(f"include {MAKE_DIR / 'Makefile.dev'}\n")
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("INFRA_", "APPINFRA_", "_APPINFRA_", "PIP_"))
        and k not in ("MAKEFLAGS", "MFLAGS", "MAKELEVEL")
    }
    env.update(
        PYTHON=sys.executable,
        PIP_INDEX_URL=index_url,  # the index pip is configured with is the one asked
        PIP_CONFIG_FILE=os.devnull,
        PIP_NO_CACHE_DIR="1",
    )
    return subprocess.run(
        ["make", "--no-print-directory", target],
        cwd=project,
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=300,
    )


def _columns(output: str) -> dict[str, list[str]]:
    """Each report line cut at the header's column starts, by package."""
    lines = output.splitlines()
    starts = [lines[0].index(h) for h in lines[0].split()]
    ends = starts[1:] + [None]
    table = {}
    for line in lines[1:]:
        if not line.strip():
            break
        cells = [line[s:e].strip() for s, e in zip(starts, ends, strict=True)]
        table[cells[0]] = cells
    return table


@pytest.mark.parametrize("target", ["deps", "deps.deep"])
def test_reports_against_the_configured_index(
    tmp_path: Path, index_url: str, target: str
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    result = _make(project, target, index_url)
    assert result.returncode == 0, result.stderr

    # package, floor, ceil, installed, ci, available, status; no color off a terminal
    cols = _columns(result.stdout)
    assert "\033[" not in result.stdout
    if target == "deps.deep":
        # a top-level line shows the project's own range; the flat list combines it
        # with every installed requirer's, which depends on this environment
        assert cols["packaging"][1:3] == ["22", "27"]
        assert cols["pyyaml"][1:3] == ["6", ""]

    installed = metadata.version("packaging")
    majors = 99 - int(installed.split(".")[0])  # plain text carries the distance
    # CI gets the installed version within the cap; 99.0 needs a wider range
    assert cols["packaging"][3:] == [
        installed,
        "✓",
        "99.0",
        f"capped ({majors} majors)",
    ]
    installed_yaml = metadata.version("pyyaml")
    minors = 99 - int(installed_yaml.split(".")[1])
    # CI would install 6.99, which is newer than the local copy
    assert cols["pyyaml"][3:] == [
        installed_yaml,
        "6.99",
        "",
        f"behind ({minors} minors)",
    ]
    # the index has no such project, so what CI gets is unknown
    assert cols["fixture-not-installed"][3:] == ["-", "?", "", "missing"]
    assert "pip check: " in result.stdout


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
        project: dict[str, Any] | None = None,
        ci_extras: list[str] | None = None,
    ) -> list[str]:
        asked = [] if asked is None else asked
        project = self.PROJECT if project is None else project
        groups = list(project.get("optional-dependencies", {}))
        ci_extras = groups if ci_extras is None else ci_extras

        def versions(name: str) -> list[Version] | None:
            asked.append(name)
            return self.INDEX.get(name)

        with (
            patch.object(dr, "_installed_version", lambda n: v(self.INSTALLED.get(n))),
            patch.object(dr, "_installed_requires", (requires or self.REQUIRES).get),
            patch.object(dr, "_direct_install", lambda n: n == "local"),
            # the framework's tools without install_deps' floor, so the fixture's
            # appinfra versions do not follow it
            patch.dict(dr.collect_deps.__globals__, FRAMEWORK_TOOLS="appinfra[check]"),
        ):
            text = dr.report(project, ci_extras, deep, False, color, versions)
        assert "local" not in asked  # a direct install is not looked up
        return text.splitlines()

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

    def test_a_package_only_in_a_group_ci_skips_is_not_in_ci(
        self, dr: ModuleType
    ) -> None:
        """CI installs no optional group here: x's packages show "-", the rest as before."""
        cols = {
            row[0]: row[1:] for row in self.table(self.run(dr, False, ci_extras=[]))
        }
        # floor, ceil, installed, ci, available, status
        assert cols["gone"][3] == "-" and cols["offline"][3] == "-"
        assert cols["local"][3] == "-"  # not in CI: no "index" either
        assert cols["lib"][3] == "1.1" and cols["web"][3] == "✓"

    def test_ci_resolves_within_its_own_ranges(self, dr: ModuleType) -> None:
        """A group CI skips cannot cap what CI installs: lib<1.1 is in gpu only."""
        project = {
            "name": "proj",
            "dependencies": ["lib>=1"],
            "optional-dependencies": {"gpu": ["lib<1.1"]},
        }
        every = self.table(self.run(dr, False, project=project))
        ci_only = self.table(self.run(dr, False, project=project, ci_extras=[]))
        # with gpu, a fresh install keeps lib 1.0; without it, CI gets 1.1
        assert {r[0]: r[4] for r in every}["lib"] == "✓"
        assert {r[0]: r[4] for r in ci_only}["lib"] == "1.1"

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
            "ci: ✓ = CI installs the same version, - = CI does not install it, else "
            "the version it installs",
            "available: newest release outside the range",
        ]

    def test_color_keeps_the_columns_aligned(self, dr: ModuleType) -> None:
        plain = self.run(dr, deep=True)
        colored = self.run(dr, deep=True, color=True)
        assert any("\033[" in line for line in colored)
        assert [re.sub(r"\033\[[0-9;]*m", "", line) for line in colored] == plain
