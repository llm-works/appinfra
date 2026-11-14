# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""The commands the pg targets and examples.check run, as make prints them (make -n)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MAKE_DIR = REPO_ROOT / "appinfra" / "scripts" / "make"


def _recipe(tmp_path: Path, target: str, **settings: str) -> str:
    """The commands `make -n <target>` prints for a project including Makefile.dev and
    Makefile.pg, with the given settings in the environment."""
    (tmp_path / "Makefile").write_text(
        f"include {MAKE_DIR / 'Makefile.dev'}\ninclude {MAKE_DIR / 'Makefile.pg'}\n"
    )
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("INFRA_", "APPINFRA_", "_APPINFRA_"))
        and k not in ("MAKEFLAGS", "MFLAGS", "MAKELEVEL")
    }
    result = subprocess.run(
        ["make", "--no-print-directory", "-n", target],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env={**env, "PYTHON": sys.executable, **settings},
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


@pytest.mark.parametrize(
    ("target", "argument"),
    [("pg.info", '"db server" info'), ("examples.check", '--pg-key "db server"')],
)
def test_the_config_key_is_one_argument(
    tmp_path: Path, target: str, argument: str
) -> None:
    """A section name with a space reaches pg_make and run_examples.py whole."""
    recipe = _recipe(tmp_path, target, APPINFRA_PG_CONFIG_KEY="db server")
    assert argument in recipe, recipe
