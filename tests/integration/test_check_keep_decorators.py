# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""check.sh's APPINFRA_DEV_CQ_DEAD_KEEP_DECORATORS: only dotted names reach cq_tool's eval."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

CHECK_SH = Path(__file__).resolve().parents[2] / "appinfra" / "scripts" / "check.sh"


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
