# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for appinfra/scripts/run_examples.py."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RUN_EXAMPLES_PY = REPO_ROOT / "appinfra" / "scripts" / "run_examples.py"


@pytest.mark.unit
def test_examples_import_uninstalled_project_from_source_tree(tmp_path: Path) -> None:
    """An example imports a project that is not installed, with no PYTHONPATH set.

    Mirrors a fresh clone after `make setup` (dependencies only): the project
    is importable only from the source tree, and the example does not patch
    sys.path itself. The runner is started from the project root, as `make`
    does.
    """
    (tmp_path / "srcpkg_fixture").mkdir()
    (tmp_path / "srcpkg_fixture" / "__init__.py").write_text("VALUE = 42\n")
    examples_dir = tmp_path / "examples"
    examples_dir.mkdir()
    (examples_dir / "use_pkg.py").write_text(
        "import srcpkg_fixture\n\nassert srcpkg_fixture.VALUE == 42\n"
    )
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}

    result = subprocess.run(
        [sys.executable, str(RUN_EXAMPLES_PY), str(examples_dir), "--jobs", "1"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed, 0 failed" in result.stdout
