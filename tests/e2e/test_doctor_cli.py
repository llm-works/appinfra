# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""appinfra doctor started on its own in this repository, outside make."""

import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_doctor_finds_the_package_without_arguments() -> None:
    """Without --pkg-name or the setting make exports, the name comes from pyproject.toml."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("APPINFRA_")}
    result = subprocess.run(
        [sys.executable, "-m", "appinfra.cli.cli", "-l", "error", "dr", "--json"],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    checks = {c["name"]: c for c in json.loads(result.stdout)["checks"]}
    assert checks["Package name"]["passed"], checks["Package name"]
    assert checks["Package name"]["message"] == "'appinfra/' is valid Python package"
