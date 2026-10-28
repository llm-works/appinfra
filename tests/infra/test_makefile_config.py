# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for appinfra/scripts/make/Makefile.config's INFRA_* assignment guard."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MAKE_DIR = REPO_ROOT / "appinfra" / "scripts" / "make"
MAKEFILE_CONFIG = MAKE_DIR / "Makefile.config"


def _make(
    tmp_path: Path,
    head: str,
    *args: str,
    env: dict[str, str] | None = None,
    include: Path = MAKEFILE_CONFIG,
) -> subprocess.CompletedProcess[str]:
    """Run `make ok` on a project Makefile whose `head` precedes the include."""
    (tmp_path / "Makefile").write_text(f"{head}\ninclude {include}\nok:\n\t@echo ok\n")
    return subprocess.run(
        ["make", "--no-print-directory", "ok", *args],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env={**_clean_env(), **(env or {})},
        check=False,
    )


def _clean_env() -> dict[str, str]:
    """The test environment without INFRA_* / APPINFRA_* names, plus an interpreter.

    make check exports APPINFRA_* into the environment; inherited, they would
    outrank the Makefile.local under test.
    """
    env = {
        k: v for k, v in os.environ.items() if not k.startswith(("INFRA_", "APPINFRA_"))
    }
    return {**env, "APPINFRA_ENV_PYTHON": sys.executable}


@pytest.mark.unit
class TestRenamedVariableCheck:
    """INFRA_X stops make when APPINFRA_X is declared; other INFRA_* pass through."""

    def test_project_makefile_assignment_fails(self, tmp_path: Path) -> None:
        result = _make(tmp_path, "INFRA_DEV_PKG_NAME := mypkg")
        assert result.returncode != 0
        assert "INFRA_DEV_PKG_NAME is renamed to APPINFRA_DEV_PKG_NAME" in (
            result.stderr
        )

    def test_environment_fails(self, tmp_path: Path) -> None:
        result = _make(tmp_path, "", env={"INFRA_CONTAINER_CMD": "podman"})
        assert result.returncode != 0
        assert "INFRA_CONTAINER_CMD is renamed to APPINFRA_CONTAINER_CMD" in (
            result.stderr
        )

    def test_command_line_fails(self, tmp_path: Path) -> None:
        result = _make(tmp_path, "", "INFRA_DEV_CQ_STRICT=false")
        assert result.returncode != 0
        assert "INFRA_DEV_CQ_STRICT is renamed to APPINFRA_DEV_CQ_STRICT" in (
            result.stderr
        )

    def test_variable_without_a_default_fails(self, tmp_path: Path) -> None:
        """Variables whose default is empty are declared too."""
        result = _make(tmp_path, "", env={"INFRA_NO_CONFIRM": "1"})
        assert result.returncode != 0
        assert "INFRA_NO_CONFIRM is renamed to APPINFRA_NO_CONFIRM" in result.stderr

    def test_exported_override_in_makefile_passes(self, tmp_path: Path) -> None:
        result = _make(tmp_path, "export INFRA_TEST_LOGGING_LEVEL := debug")
        assert result.returncode == 0, result.stderr

    def test_makefile_local_assignment_fails(self, tmp_path: Path) -> None:
        (tmp_path / "Makefile.local").write_text(
            "INFRA_ENV_PYTHON ?= /usr/bin/python3\n"
        )
        result = _make(tmp_path, "")
        assert result.returncode != 0
        assert "INFRA_ENV_PYTHON" in result.stderr

    def test_makefile_env_first_layout_fails(self, tmp_path: Path) -> None:
        """A project including Makefile.env without Makefile.config is checked too."""
        result = _make(
            tmp_path, "INFRA_DEV_PKG_NAME := mypkg", include=MAKE_DIR / "Makefile.env"
        )
        assert result.returncode != 0
        assert "INFRA_DEV_PKG_NAME" in result.stderr

    def test_makefile_env_first_layout_loads_makefile_local(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "Makefile.local").write_text("APPINFRA_DEV_PKG_NAME ?= fromlocal\n")
        (tmp_path / "Makefile").write_text(
            f"include {MAKE_DIR / 'Makefile.env'}\n"
            "ok:\n\t@echo pkg=$(APPINFRA_DEV_PKG_NAME)\n"
        )
        result = subprocess.run(
            ["make", "--no-print-directory", "ok"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            env=_clean_env(),
            check=False,
        )
        assert result.stdout.strip() == "pkg=fromlocal", result.stderr

    def test_appinfra_assignment_passes(self, tmp_path: Path) -> None:
        result = _make(tmp_path, "APPINFRA_DEV_PKG_NAME := mypkg")
        assert result.returncode == 0, result.stderr

    def test_override_from_environment_passes(self, tmp_path: Path) -> None:
        result = _make(tmp_path, "", env={"INFRA_PGSERVER_PORT": "5433"})
        assert result.returncode == 0, result.stderr

    def test_override_on_command_line_passes(self, tmp_path: Path) -> None:
        result = _make(tmp_path, "", "INFRA_PGSERVER_PORT=5433")
        assert result.returncode == 0, result.stderr


def _python(tmp_path: Path, local: str, env: dict[str, str]) -> str:
    """Return the PYTHON Makefile.env selects, given Makefile.local and the environment."""
    (tmp_path / "Makefile.local").write_text(local)
    (tmp_path / "Makefile").write_text(
        f"include {MAKE_DIR / 'Makefile.env'}\nok:\n\t@echo $(PYTHON)\n"
    )
    base = {
        k: v
        for k, v in _clean_env().items()
        if k not in ("PYTHON", "APPINFRA_ENV_PYTHON")
    }
    result = subprocess.run(
        ["make", "--no-print-directory", "ok"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env={**base, **env},
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


@pytest.mark.unit
class TestInterpreterSelection:
    """The environment outranks the project Makefile and Makefile.local."""

    def test_environment_python_beats_makefile_local(self, tmp_path: Path) -> None:
        local = "APPINFRA_ENV_PYTHON ?= /local/python\n"
        assert _python(tmp_path, local, {"PYTHON": "/env/python"}) == "/env/python"

    def test_environment_appinfra_env_python_beats_all(self, tmp_path: Path) -> None:
        local = "APPINFRA_ENV_PYTHON ?= /local/python\n"
        env = {"APPINFRA_ENV_PYTHON": "/env/appinfra", "PYTHON": "/env/python"}
        assert _python(tmp_path, local, env) == "/env/appinfra"

    def test_makefile_local_used_without_environment(self, tmp_path: Path) -> None:
        local = "APPINFRA_ENV_PYTHON ?= /local/python\n"
        assert _python(tmp_path, local, {}) == "/local/python"
