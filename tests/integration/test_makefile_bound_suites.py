# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Makefile.pytest: a bound suite's test.<suite> target runs pytest over tests/<suite>/ only
when that directory holds test files, the rule check.sh applies."""

import os
import subprocess
from pathlib import Path

import pytest

MAKE_DIR = Path(__file__).resolve().parents[2] / "appinfra" / "scripts" / "make"


def _dry_run(project: Path, files: list[str]) -> str:
    """The commands `make test.e2e` would run, with e2e bound, given the project's files.

    The environment drops the settings a surrounding make exports.
    """
    for path in files:
        target = project / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("")
    (project / "Makefile").write_text(
        "APPINFRA_PYTEST_BOUND_SUITES ?= e2e\n"
        + "".join(
            f"include {MAKE_DIR / name}\n"
            for name in ("Makefile.config", "Makefile.env", "Makefile.pytest")
        )
    )
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("INFRA_", "APPINFRA_", "_APPINFRA_", "MAKE"))
    }
    result = subprocess.run(
        ["make", "--no-print-directory", "-n", "test.e2e"],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


@pytest.mark.parametrize(
    "files",
    [[], ["tests/e2e/__init__.py"], ["tests/e2e/__init__.py", "tests/e2e/conftest.py"]],
    ids=["no directory", "package file", "package and fixture files"],
)
def test_a_bound_suite_without_test_files_runs_no_pytest(
    tmp_path: Path, files: list[str]
) -> None:
    commands = _dry_run(tmp_path, files)
    assert "* no e2e tests" in commands, commands
    assert "-m pytest" not in commands, commands


def test_a_bound_suite_with_a_test_file_below_its_directory_runs_pytest_there(
    tmp_path: Path,
) -> None:
    commands = _dry_run(tmp_path, ["tests/e2e/__init__.py", "tests/e2e/cli/test_c.py"])
    assert "-m pytest" in commands, commands
    assert " tests/e2e/ -m e2e " in commands, commands
