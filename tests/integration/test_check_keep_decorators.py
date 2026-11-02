# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""APPINFRA_DEV_CQ_DEAD_KEEP_DECORATORS: nothing in the setting runs in a shell, in check.sh
(make check) or in Makefile.dev's cq targets."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
CHECK_SH = REPO / "appinfra" / "scripts" / "check.sh"
MAKE_DIR = REPO / "appinfra" / "scripts" / "make"


def _check(project: Path, keep_decorators: str) -> subprocess.CompletedProcess[str]:
    """Run check.sh over a one-module package with the given decorator setting.

    The package passes every check that runs before the code quality check, so without the
    validation the setting would reach cq_tool's eval.
    """
    package = project / "pkg"
    package.mkdir()
    (package / "__init__.py").write_text('"""A package for the check."""\n')
    env = {
        **os.environ,
        "APPINFRA_DEV_PROJECT_ROOT": str(project),
        "APPINFRA_DEV_PKG_NAME": "pkg",
        "APPINFRA_DEV_DOCSTRING_THRESHOLD": "0",
        "PYTHON": sys.executable,
        "APPINFRA_DEV_CQ_DEAD_KEEP_DECORATORS": keep_decorators,
    }
    return subprocess.run(
        ["bash", str(CHECK_SH), "--skip-tests"],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


# No spaces in the substitutions: the setting is split on whitespace before it reaches the eval
@pytest.mark.parametrize("value", ["a$(date>{marker})", "a`date>{marker}`", "*"])
def test_a_non_name_stops_check_sh_and_runs_nothing(tmp_path: Path, value: str) -> None:
    marker = tmp_path / "ran"
    result = _check(tmp_path, value.format(marker=marker))

    assert result.returncode == 1
    assert "APPINFRA_DEV_CQ_DEAD_KEEP_DECORATORS takes dotted decorator names" in (
        result.stderr
    )
    assert not marker.exists()


def _make_cq_dead(
    project: Path, keep_decorators: str
) -> subprocess.CompletedProcess[str]:
    """Run make cq.dead over a one-module package with the given decorator setting.

    The environment drops the APPINFRA_* names a surrounding make check exports, and puts this
    checkout first on the path, so the CLI under test is the source tree's.
    """
    package = project / "pkg"
    package.mkdir()
    (package / "__init__.py").write_text('"""A package for the check."""\n')
    (project / "Makefile").write_text(
        f"include {MAKE_DIR / 'Makefile.config'}\ninclude {MAKE_DIR / 'Makefile.dev'}\n"
    )
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("INFRA_", "APPINFRA_", "_APPINFRA_", "MAKE"))
    }
    env |= {
        "PYTHON": sys.executable,
        "PYTHONPATH": str(REPO),
        "APPINFRA_DEV_PKG_NAME": "pkg",
        "APPINFRA_DEV_CQ_DEAD_KEEP_DECORATORS": keep_decorators,
    }
    return subprocess.run(
        ["make", "--no-print-directory", "cq.dead"],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


# A $(...) in the setting is a make reference, expanded by make itself; the shell's own syntax
# is what must not run, a quote included
@pytest.mark.parametrize("value", ["a`date>{marker}`", "a'`date>{marker}`'"])
def test_a_non_name_fails_make_cq_dead_and_runs_nothing(
    tmp_path: Path, value: str
) -> None:
    marker = tmp_path / "ran"
    result = _make_cq_dead(tmp_path, value.format(marker=marker))

    assert result.returncode != 0
    assert "not a dotted decorator name" in result.stderr
    assert not marker.exists()
