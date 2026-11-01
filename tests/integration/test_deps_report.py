# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""make deps / make deps.deep on a fixture project, against a local package index."""

from __future__ import annotations

import functools
import os
import subprocess
import sys
import threading
from collections.abc import Iterator
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from importlib import metadata
from pathlib import Path

import pytest

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
