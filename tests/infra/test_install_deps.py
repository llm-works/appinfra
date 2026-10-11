# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for appinfra/scripts/install_deps.py."""

from __future__ import annotations

import importlib.util
import sys
import tomllib
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALL_DEPS_PY = REPO_ROOT / "appinfra" / "scripts" / "install_deps.py"

# Self-references in several spellings (case, `_`, `.`, version, marker).
# "my-pkg-extra" shares the name prefix but is a different distribution.
PYPROJECT = """\
[project]
name = "My_Pkg"
dependencies = ["dep-a>=1", "my-pkg-extra>=1"]

[project.optional-dependencies]
alpha = ["dep-b>=2"]
beta = ["my-pkg[alpha]", "dep-c"]
all = ["My.Pkg[beta]>=0.1", "my_pkg[alpha] ; python_version >= '3.11'"]
"""

EXPECTED_DEPS = ["dep-a>=1", "my-pkg-extra>=1", "dep-b>=2", "dep-c"]


@pytest.fixture
def install_deps() -> ModuleType:
    """Load the script as a module (it is not part of an importable package)."""
    spec = importlib.util.spec_from_file_location("install_deps", INSTALL_DEPS_PY)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.unit
@pytest.mark.parametrize(
    ("requirement", "expected"),
    [
        ("dep-a>=1", "dep-a"),
        ("My_Pkg[alpha]", "my-pkg"),
        ("my.pkg [a,b] >=1 ; python_version >= '3.11'", "my-pkg"),
        ("  dep-b[extra]>=2", "dep-b"),
        ("dep-c @ https://example.com/dep_c.whl", "dep-c"),
        ("", None),
    ],
)
def test_requirement_name(
    install_deps: ModuleType, requirement: str, expected: str | None
) -> None:
    assert install_deps.requirement_name(requirement) == expected


@pytest.mark.unit
def test_collect_deps_drops_self_references(install_deps: ModuleType) -> None:
    project: dict[str, Any] = tomllib.loads(PYPROJECT)["project"]
    assert install_deps.collect_deps(project) == EXPECTED_DEPS


@pytest.mark.unit
def test_main_passes_filtered_deps_to_pip(
    install_deps: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "pyproject.toml").write_text(PYPROJECT)
    monkeypatch.chdir(tmp_path)
    calls: list[list[str]] = []
    monkeypatch.setattr(
        install_deps.subprocess, "run", lambda cmd, check: calls.append(cmd)
    )

    install_deps.main()

    assert calls == [[sys.executable, "-m", "pip", "install", *EXPECTED_DEPS]]
