# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for appinfra/scripts/make/Makefile.config's INFRA_* assignment guard."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MAKEFILE_CONFIG = REPO_ROOT / "appinfra" / "scripts" / "make" / "Makefile.config"


def _make(
    tmp_path: Path, head: str, *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Run `make ok` on a project Makefile whose `head` precedes the include."""
    (tmp_path / "Makefile").write_text(
        f"{head}\ninclude {MAKEFILE_CONFIG}\nok:\n\t@echo ok\n"
    )
    return subprocess.run(
        ["make", "--no-print-directory", "ok", *args],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env={**os.environ, **(env or {})},
        check=False,
    )


@pytest.mark.unit
class TestInfraAssignmentGuard:
    """A makefile assigning INFRA_* fails; INFRA_* from outside passes through."""

    def test_project_makefile_assignment_fails(self, tmp_path: Path) -> None:
        result = _make(tmp_path, "INFRA_DEV_PKG_NAME := mypkg")
        assert result.returncode != 0
        assert "INFRA_DEV_PKG_NAME: framework variables are named APPINFRA_*" in (
            result.stderr
        )

    def test_makefile_local_assignment_fails(self, tmp_path: Path) -> None:
        (tmp_path / "Makefile.local").write_text(
            "INFRA_ENV_PYTHON ?= /usr/bin/python3\n"
        )
        result = _make(tmp_path, "")
        assert result.returncode != 0
        assert "INFRA_ENV_PYTHON" in result.stderr

    def test_appinfra_assignment_passes(self, tmp_path: Path) -> None:
        result = _make(tmp_path, "APPINFRA_DEV_PKG_NAME := mypkg")
        assert result.returncode == 0, result.stderr

    def test_override_from_environment_passes(self, tmp_path: Path) -> None:
        result = _make(tmp_path, "", env={"INFRA_PGSERVER_PORT": "5433"})
        assert result.returncode == 0, result.stderr

    def test_override_on_command_line_passes(self, tmp_path: Path) -> None:
        result = _make(tmp_path, "", "INFRA_PGSERVER_PORT=5433")
        assert result.returncode == 0, result.stderr
