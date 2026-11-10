# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""check.sh (make check) with bound suites and no run over the whole test tree: test files
outside the bound directories are still collected, so the suite plugin stops on them."""

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CHECK_SH = REPO / "appinfra" / "scripts" / "check.sh"

_CONFTEST = 'pytest_plugins = ["appinfra.pytest_suites"]\n'
_PLAIN = "def test_plain():\n    pass\n"
_MARKED_UNIT = "import pytest\n\n\n@pytest.mark.unit\ndef test_marked():\n    pass\n"


def _check(project: Path, layout: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run check.sh over a package and the given test files, with coverage off and the unit
    suite bound: no run collects the whole tree.

    The environment drops the settings a surrounding make check exports.
    """
    files = {
        "pkg/__init__.py": '"""A package for the check."""\n',
        "tests/conftest.py": _CONFTEST,
        "tests/unit/test_unit_plain.py": _PLAIN,
    } | layout
    for path, source in files.items():
        target = project / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source)
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("INFRA_", "APPINFRA_", "_APPINFRA_", "MAKE", "PYTEST_"))
    }
    env |= {
        "PYTHON": sys.executable,
        "PYTHONPATH": str(REPO),
        "APPINFRA_DEV_PROJECT_ROOT": str(project),
        "APPINFRA_DEV_PKG_NAME": "pkg",
        "APPINFRA_DEV_DOCSTRING_THRESHOLD": "0",
        "APPINFRA_PYTEST_COVERAGE_THRESHOLD": "0",
        "APPINFRA_PYTEST_BOUND_SUITES": "unit",
    }
    return subprocess.run(
        ["bash", str(CHECK_SH)],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )


def test_a_bound_suite_test_outside_every_suite_directory_fails_the_check(
    tmp_path: Path,
) -> None:
    """The unit run collects tests/unit/ alone and no other run starts: without a run over
    the rest of the tree, tests/cli/ would never be collected and its test never run."""
    result = _check(tmp_path, {"tests/cli/test_cli_marked.py": _MARKED_UNIT})
    assert result.returncode != 0, result.stdout + result.stderr
    log = (tmp_path / ".build" / "check" / "suite-placement.log").read_text()
    assert "tests/cli/test_cli_marked.py::test_marked" in log, log


def test_files_without_tests_outside_the_suite_directories_pass_the_check(
    tmp_path: Path,
) -> None:
    """The control: a helper module outside the suite directories holds no tests."""
    result = _check(tmp_path, {"tests/helpers/util.py": "VALUE = 1\n"})
    assert result.returncode == 0, result.stdout + result.stderr
