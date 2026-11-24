# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""check.sh (make check) runs the examples with the pg endpoint of the project's config."""

import os
import socket
import subprocess
import sys
from pathlib import Path

from tests.helpers.check_sh import FIXTURE_WORKERS

REPO = Path(__file__).resolve().parents[3]
CHECK_SH = REPO / "appinfra" / "scripts" / "check.sh"

_CONFTEST = '"""Suites."""\n\npytest_plugins = ["appinfra.pytest_suites"]\n'
_TEST = '"""A test."""\n\n\ndef test_plain():\n    """Passes."""\n'
# Runs only when the pg probe finds the endpoint; leaves a file to say so
_PG_EXAMPLE = (
    '"""An example that needs Postgres."""\n\n'
    "# ci-requires: pg\n"
    "from pathlib import Path\n\n"
    'Path("pg-example-ran").write_text("ran\\n")\n'
)


def _project(root: Path, port: int) -> Path:
    """A package, a unit test, a pg example and a config naming the endpoint."""
    (root / "pkg" / "examples").mkdir(parents=True)
    (root / "pkg" / "__init__.py").write_text('"""A package for the check."""\n')
    (root / "pkg" / "examples" / "needs_pg.py").write_text(_PG_EXAMPLE)
    (root / "tests" / "unit").mkdir(parents=True)
    (root / "tests" / "conftest.py").write_text(_CONFTEST)
    (root / "tests" / "unit" / "test_unit.py").write_text(_TEST)
    (root / "pyproject.toml").write_text(
        '[tool.pytest.ini_options]\nasyncio_default_fixture_loop_scope = "function"\n'
    )
    config = root / "etc" / "infra.yaml"
    config.parent.mkdir()
    config.write_text(f"pgserver:\n  host: 127.0.0.1\n  port: {port}\n")
    return config


def _check(project: Path, config: Path) -> subprocess.CompletedProcess[str]:
    """Run check.sh over the project, as make check runs it with examples enabled.

    The environment drops the settings a surrounding make check exports.
    """
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("INFRA_", "APPINFRA_", "_APPINFRA_", "MAKE", "PYTEST_"))
    }
    env |= FIXTURE_WORKERS | {
        "PYTHON": sys.executable,
        "PYTHONPATH": str(REPO),
        "APPINFRA_DEV_PROJECT_ROOT": str(project),
        "APPINFRA_DEV_PKG_NAME": "pkg",
        "APPINFRA_DEV_CHECK_EXAMPLES": "true",
        "APPINFRA_DEV_DOCSTRING_THRESHOLD": "0",
        "APPINFRA_PYTEST_COVERAGE_THRESHOLD": "0",
        "_APPINFRA_DEV_EXAMPLES_PG_CONFIG": str(config),
        "_APPINFRA_DEV_EXAMPLES_PG_KEY": "pgserver",
    }
    return subprocess.run(
        ["bash", str(CHECK_SH)],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )


def test_a_config_path_with_a_space_reaches_the_examples(tmp_path: Path) -> None:
    """The config path is one argument to run_examples.py, which check.sh runs through eval."""
    project = tmp_path / "my project"
    with socket.socket() as pg:
        pg.bind(("127.0.0.1", 0))
        pg.listen()
        config = _project(project, pg.getsockname()[1])
        result = _check(project, config)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (project / "pg-example-ran").exists(), result.stdout + result.stderr
