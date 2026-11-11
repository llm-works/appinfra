# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""check.sh (make check) worker counts: APPINFRA_PYTEST_CHECK_WORKERS for each standalone suite
and APPINFRA_PYTEST_COVERAGE_WORKERS for the coverage run. A fraction below 1 is a share of
the CPUs, at least 2 workers; a whole number is that many workers."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
CHECK_SH = REPO / "appinfra" / "scripts" / "check.sh"

# Each pytest controller writes its suite and worker count; xdist workers have workerinput
_CONFTEST = '''"""Suites, and the worker count of each pytest run."""

import os

pytest_plugins = ["appinfra.pytest_suites"]


def pytest_configure(config):
    """Record the run's suite and -n."""
    if not hasattr(config, "workerinput"):
        with open(os.environ["WORKERS_LOG"], "a") as log:
            suite = os.environ["_APPINFRA_CHECK_PYTEST_SUITE"]
            log.write(f"{suite} {config.option.numprocesses}\\n")
'''


def _cpus() -> int:
    """What check.sh's nproc counts: the CPUs this process may run on."""
    affinity = getattr(os, "sched_getaffinity", None)
    return len(affinity(0)) if affinity else os.cpu_count() or 8


def _workers(project: Path, coverage: str, settings: dict[str, str]) -> dict[str, int]:
    """Run check.sh over a package and one unit test; return each run's worker count by suite.

    The environment drops the settings a surrounding make check exports.
    """
    (project / "pkg").mkdir()
    (project / "pkg" / "__init__.py").write_text('"""A package for the check."""\n')
    (project / "tests" / "unit").mkdir(parents=True)
    (project / "tests" / "conftest.py").write_text(_CONFTEST)
    (project / "tests" / "unit" / "test_unit.py").write_text(
        '"""A test."""\n\n\ndef test_plain():\n    """Passes."""\n'
    )
    log = project / "workers.log"
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("INFRA_", "APPINFRA_", "_APPINFRA_", "MAKE", "PYTEST_"))
        and k not in ("OMP_NUM_THREADS", "OMP_THREAD_LIMIT")
    }
    env |= {
        "PYTHON": sys.executable,
        "PYTHONPATH": str(REPO),
        "WORKERS_LOG": str(log),
        "APPINFRA_DEV_PROJECT_ROOT": str(project),
        "APPINFRA_DEV_PKG_NAME": "pkg",
        "APPINFRA_DEV_DOCSTRING_THRESHOLD": "0",
        "APPINFRA_PYTEST_COVERAGE_THRESHOLD": coverage,
        **settings,
    }
    result = subprocess.run(
        ["bash", str(CHECK_SH)],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    runs = (line.split() for line in log.read_text().splitlines())
    return {suite: int(n) for suite, n in runs}


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, max(2, _cpus() // 4)),
        ("0.125", max(2, _cpus() // 8)),
        ("0.01", 2),
        ("3", 3),
        ("1", 1),
    ],
    ids=["default", "share", "share-at-least-2", "count", "one"],
)
def test_a_standalone_suite_takes_check_workers(
    tmp_path: Path, value: str | None, expected: int
) -> None:
    settings = {} if value is None else {"APPINFRA_PYTEST_CHECK_WORKERS": value}
    assert _workers(tmp_path, "0", settings)["unit"] == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, max(2, _cpus() // 2)), ("0.25", max(2, _cpus() // 4)), ("3", 3)],
    ids=["default", "share", "count"],
)
def test_the_coverage_run_takes_coverage_workers(
    tmp_path: Path, value: str | None, expected: int
) -> None:
    settings = {} if value is None else {"APPINFRA_PYTEST_COVERAGE_WORKERS": value}
    assert _workers(tmp_path, "1", settings)["cov"] == expected


def test_an_invalid_share_stops_check_sh(tmp_path: Path) -> None:
    with pytest.raises(AssertionError, match="is not a worker share"):
        _workers(tmp_path, "0", {"APPINFRA_PYTEST_CHECK_WORKERS": "1.5"})
