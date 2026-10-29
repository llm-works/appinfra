# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for Makefile.config / Makefile.env: config loading, interpreter, empty values."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.helpers.makefile_registry import registry

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
    """The test environment without INFRA_* / APPINFRA_* / _APPINFRA_* names, plus an interpreter.

    make check exports these into the environment (_APPINFRA_PROJECT_DIR would
    mark the make under test as nested), and MAKEFLAGS carries a parent make's
    command-line assignments; inherited, any would reach the make under test.
    """
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("INFRA_", "APPINFRA_", "_APPINFRA_"))
        and k not in ("MAKEFLAGS", "MFLAGS", "MAKELEVEL")
    }
    return {**env, "PYTHON": sys.executable}


def _setting(
    tmp_path: Path,
    project: str,
    local: str,
    env: dict[str, str] | None = None,
    *args: str,
) -> str:
    """APPINFRA_DEV_PKG_NAME's value, given the project Makefile and Makefile.local."""
    (tmp_path / "Makefile.local").write_text(local)
    (tmp_path / "Makefile").write_text(
        f"{project}\ninclude {MAKEFILE_CONFIG}\nok:\n\t@echo $(APPINFRA_DEV_PKG_NAME)\n"
    )
    result = subprocess.run(
        ["make", "--no-print-directory", "ok", *args],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env={**_clean_env(), **(env or {})},
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


@pytest.mark.integration
class TestPrecedence:
    """command line > environment > Makefile.local := > project ?= > default."""

    PROJECT = "APPINFRA_DEV_PKG_NAME ?= project"
    LOCAL = "APPINFRA_DEV_PKG_NAME := local\n"
    ENV = {"APPINFRA_DEV_PKG_NAME": "env"}

    def test_default(self, tmp_path: Path) -> None:
        assert _setting(tmp_path, "", "") == "appinfra"

    def test_project_beats_default(self, tmp_path: Path) -> None:
        assert _setting(tmp_path, self.PROJECT, "") == "project"

    def test_makefile_local_beats_project(self, tmp_path: Path) -> None:
        assert _setting(tmp_path, self.PROJECT, self.LOCAL) == "local"

    def test_environment_beats_makefile_local(self, tmp_path: Path) -> None:
        assert _setting(tmp_path, self.PROJECT, self.LOCAL, self.ENV) == "env"

    def test_environment_beats_project(self, tmp_path: Path) -> None:
        assert _setting(tmp_path, self.PROJECT, "", self.ENV) == "env"

    def test_command_line_beats_environment(self, tmp_path: Path) -> None:
        args = ("APPINFRA_DEV_PKG_NAME=cli",)
        assert _setting(tmp_path, self.PROJECT, self.LOCAL, self.ENV, *args) == "cli"

    def test_project_colon_assign_pins_against_environment(
        self, tmp_path: Path
    ) -> None:
        pinned = "APPINFRA_DEV_PKG_NAME := pinned"
        assert _setting(tmp_path, pinned, "", self.ENV) == "pinned"

    def test_makefile_local_beats_pinned_project(self, tmp_path: Path) -> None:
        pinned = "APPINFRA_DEV_PKG_NAME := pinned"
        assert _setting(tmp_path, pinned, self.LOCAL) == "local"

    def test_environment_value_is_validated(self, tmp_path: Path) -> None:
        """An environment value reaches validation over a project ?= (the wrrn case)."""
        (tmp_path / "Makefile").write_text(
            f"APPINFRA_DEV_CQ_DUP ?= strict\ninclude {MAKEFILE_CONFIG}\nok:\n\t@echo ok\n"
        )
        result = subprocess.run(
            ["make", "--no-print-directory", "ok"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            env={**_clean_env(), "APPINFRA_DEV_CQ_DUP": "wrrn"},
            check=False,
        )
        assert result.returncode != 0
        assert "APPINFRA_DEV_CQ_DUP=wrrn is not a mode" in result.stderr

    def test_restored_environment_value_reaches_recipes(self, tmp_path: Path) -> None:
        (tmp_path / "Makefile.local").write_text(self.LOCAL)
        (tmp_path / "Makefile").write_text(
            f"include {MAKEFILE_CONFIG}\nok:\n\t@echo $$APPINFRA_DEV_PKG_NAME\n"
        )
        result = subprocess.run(
            ["make", "--no-print-directory", "ok"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            env={**_clean_env(), **self.ENV},
            check=False,
        )
        assert result.stdout.strip() == "env", result.stderr

    def test_interpreter_environment_beats_makefile_local(self, tmp_path: Path) -> None:
        (tmp_path / "Makefile.local").write_text("PYTHON := /local/python\n")
        (tmp_path / "Makefile").write_text(
            f"include {MAKE_DIR / 'Makefile.env'}\nok:\n\t@echo $(PYTHON)\n"
        )
        result = subprocess.run(
            ["make", "--no-print-directory", "ok"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            env={**_clean_env(), "PYTHON": "/env/python"},
            check=False,
        )
        assert result.stdout.strip() == "/env/python", result.stderr


def _nested(
    tmp_path: Path, recipe: str, target: str = "nested"
) -> subprocess.CompletedProcess[str]:
    """Run `make <target>` in a parent project whose `nested` recipe makes the child."""
    (tmp_path / "child").mkdir()
    (tmp_path / "child" / "Makefile").write_text(
        "APPINFRA_DEV_PKG_NAME ?= childpkg\n"
        f"include {MAKEFILE_CONFIG}\nshow:\n\t@echo child=$(APPINFRA_DEV_PKG_NAME)\n"
    )
    (tmp_path / "Makefile").write_text(
        "APPINFRA_DEV_PKG_NAME ?= parentpkg\n"
        f"include {MAKEFILE_CONFIG}\ninclude {MAKE_DIR / 'Makefile.dev'}\n"
        f"nested:\n\t@{recipe}\nself:\n\t@$(MAKE) --no-print-directory nested-self\n"
        "nested-self:\n\t@echo self=$(APPINFRA_DEV_PKG_NAME)\n"
    )
    return subprocess.run(
        ["make", "--no-print-directory", target],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=_clean_env(),
        check=False,
    )


@pytest.mark.integration
class TestNestedProjects:
    """A make of one appinfra project inside another's make must not take its settings."""

    def test_inherited_environment_stops_make(self, tmp_path: Path) -> None:
        result = _nested(tmp_path, "$(MAKE) --no-print-directory -C child show")
        assert result.returncode != 0
        assert "child=parentpkg" not in result.stdout
        assert f"running inside the make of {tmp_path}" in result.stderr

    def test_clean_environment_runs(self, tmp_path: Path) -> None:
        recipe = (
            'env -i HOME="$$HOME" PATH="$$PATH" '
            "$(MAKE) --no-print-directory -C child show"
        )
        result = _nested(tmp_path, recipe)
        assert result.returncode == 0, result.stderr
        assert "child=childpkg" in result.stdout

    def test_recursive_make_in_same_project_runs(self, tmp_path: Path) -> None:
        result = _nested(tmp_path, "true", target="self")
        assert result.returncode == 0, result.stderr
        assert "self=parentpkg" in result.stdout


@pytest.mark.integration
class TestScriptsLocation:
    """APPINFRA_SCRIPTS must name the framework copy make loaded."""

    def test_makefile_local_other_copy_stops_make(self, tmp_path: Path) -> None:
        (tmp_path / "Makefile.local").write_text(f"APPINFRA_SCRIPTS := {tmp_path}\n")
        result = _make(tmp_path, "")
        assert result.returncode != 0
        assert f"APPINFRA_SCRIPTS={tmp_path}, but the framework was loaded from" in (
            result.stderr
        )

    def test_command_line_same_copy_passes(self, tmp_path: Path) -> None:
        result = _make(tmp_path, "", f"APPINFRA_SCRIPTS={MAKE_DIR.parent}")
        assert result.returncode == 0, result.stderr

    def test_same_copy_through_symlink_passes(self, tmp_path: Path) -> None:
        (tmp_path / "link").symlink_to(MAKE_DIR.parent)
        result = _make(tmp_path, f"APPINFRA_SCRIPTS ?= {tmp_path / 'link'}")
        assert result.returncode == 0, result.stderr


MODULES = ["dev", "docs", "install", "help", "clean", "pg", "pytest", "utils", "env"]


@pytest.mark.integration
class TestModuleIncludedAlone:
    """Each framework module loads Makefile.config itself, so its defaults apply."""

    @pytest.mark.parametrize("module", MODULES)
    def test_defaults_loaded(self, tmp_path: Path, module: str) -> None:
        (tmp_path / "Makefile").write_text(
            f"include {MAKE_DIR / f'Makefile.{module}'}\n"
            "show:\n\t@echo $(_APPINFRA_CONFIG_LOADED) $(APPINFRA_DEV_CHECK_SCRIPT)\n"
        )
        result = subprocess.run(
            ["make", "--no-print-directory", "show"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            env=_clean_env(),
            check=False,
        )
        assert result.returncode == 0, result.stderr
        loaded, script = result.stdout.split()
        assert loaded == "1"
        assert script.endswith("/check.sh") and Path(script).is_file()

    def test_dev_alone_runs_check_script(self, tmp_path: Path) -> None:
        """make check from a Makefile that includes only Makefile.dev names check.sh."""
        (tmp_path / "Makefile").write_text(f"include {MAKE_DIR / 'Makefile.dev'}\n")
        result = subprocess.run(
            ["make", "--no-print-directory", "-n", "check"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            env=_clean_env(),
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert "check.sh --fail-fast" in result.stdout


@pytest.mark.integration
class TestConfigLoading:
    """Makefile.local loads in every layout; INFRA_* config overrides pass through."""

    def test_exported_override_in_makefile_passes(self, tmp_path: Path) -> None:
        result = _make(tmp_path, "export INFRA_TEST_LOGGING_LEVEL := debug")
        assert result.returncode == 0, result.stderr

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


def _python(
    tmp_path: Path, local: str, env: dict[str, str], *args: str, project: str = ""
) -> str:
    """Return the PYTHON Makefile.env resolves, given the Makefiles and the environment."""
    (tmp_path / "Makefile.local").write_text(local)
    (tmp_path / "Makefile").write_text(
        f"{project}\ninclude {MAKE_DIR / 'Makefile.env'}\nok:\n\t@echo $(PYTHON)\n"
    )
    base = {k: v for k, v in _clean_env().items() if k != "PYTHON"}
    result = subprocess.run(
        ["make", "--no-print-directory", "ok", *args],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env={**base, **env},
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


@pytest.fixture
def path_python(tmp_path: Path) -> dict[str, str]:
    """A PATH whose first python3 is a stub, as the environment to pass."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "python3").write_text("#!/bin/sh\n")
    (bin_dir / "python3").chmod(0o755)
    return {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}


@pytest.mark.integration
class TestInterpreterSelection:
    """PYTHON follows the settings' precedence, then python3 on PATH."""

    LOCAL = "PYTHON := /local/python\n"

    def test_command_line_beats_environment(self, tmp_path: Path) -> None:
        env = {"PYTHON": "/env/python"}
        assert _python(tmp_path, self.LOCAL, env, "PYTHON=/cli/python") == "/cli/python"

    def test_environment_beats_makefile_local(self, tmp_path: Path) -> None:
        assert _python(tmp_path, self.LOCAL, {"PYTHON": "/env/python"}) == "/env/python"

    def test_makefile_local_beats_project(self, tmp_path: Path) -> None:
        project = "PYTHON ?= /project/python"
        assert _python(tmp_path, self.LOCAL, {}, project=project) == "/local/python"

    def test_project_beats_path(
        self, tmp_path: Path, path_python: dict[str, str]
    ) -> None:
        project = "PYTHON ?= /project/python"
        assert _python(tmp_path, "", path_python, project=project) == "/project/python"

    def test_path_default(self, tmp_path: Path, path_python: dict[str, str]) -> None:
        assert _python(tmp_path, "", path_python) == str(tmp_path / "bin" / "python3")

    def test_no_python3_on_path_stops_make(self, tmp_path: Path) -> None:
        (tmp_path / "Makefile").write_text(
            f"include {MAKE_DIR / 'Makefile.env'}\nok:\n"
        )
        env = {k: v for k, v in _clean_env().items() if k != "PYTHON"}
        result = subprocess.run(
            [shutil.which("make") or "make", "--no-print-directory", "ok"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            env={**env, "PATH": str(tmp_path)},
            check=False,
        )
        assert result.returncode != 0
        assert "python3 is not on PATH" in result.stderr

    def test_appinfra_python_is_not_a_setting(self, tmp_path: Path) -> None:
        result = _make(tmp_path, "", "APPINFRA_PYTHON=/cli/python")
        assert "APPINFRA_PYTHON: not an appinfra setting" in result.stderr


@pytest.mark.integration
class TestEmptyValues:
    """An APPINFRA_* or PYTHON the environment or command line sets empty stops make."""

    @pytest.mark.parametrize("name", ["PYTHON", "APPINFRA_PYTEST_COVERAGE_THRESHOLD"])
    def test_environment(self, tmp_path: Path, name: str) -> None:
        result = _make(tmp_path, "", env={name: ""})
        assert result.returncode != 0
        assert f"{name} set but empty" in result.stderr

    @pytest.mark.parametrize("name", ["PYTHON", "APPINFRA_PYTEST_COVERAGE_THRESHOLD"])
    def test_command_line(self, tmp_path: Path, name: str) -> None:
        result = _make(tmp_path, "", f"{name}=")
        assert result.returncode != 0
        assert f"{name} set but empty" in result.stderr

    def test_all_empty_names_reported(self, tmp_path: Path) -> None:
        result = _make(tmp_path, "", "PYTHON=", env={"APPINFRA_DEV_CQ_EXCLUDE": ""})
        assert "APPINFRA_DEV_CQ_EXCLUDE" in result.stderr
        assert "PYTHON" in result.stderr

    def test_makefile_empty_value_allowed(self, tmp_path: Path) -> None:
        """An empty value the project's own Makefile sets is a value, not an error."""
        result = _make(tmp_path, "APPINFRA_DEV_CQ_LINT_SELECT :=")
        assert result.returncode == 0, result.stderr

    def test_sub_make_inherits_empty_exports(self, tmp_path: Path) -> None:
        """A sub-make sees the parent's exported settings, some empty by default."""
        (tmp_path / "Makefile").write_text(
            f"include {MAKEFILE_CONFIG}\n"
            "export APPINFRA_DEV_CQ_EXCLUDE\n"
            "ok:\n\t@$(MAKE) --no-print-directory inner\n"
            "inner:\n\t@echo inner-ok\n"
        )
        result = subprocess.run(
            ["make", "--no-print-directory", "ok"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            env=_clean_env(),
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert "inner-ok" in result.stdout


def _areyousure(
    tmp_path: Path, env: dict[str, str], answer: str = "", local: str = ""
) -> subprocess.CompletedProcess[str]:
    """Run a target guarded by areyousure, answering the prompt with `answer`."""
    (tmp_path / "Makefile.local").write_text(local)
    (tmp_path / "Makefile").write_text(
        f"include {MAKE_DIR / 'Makefile.env'}\ninclude {MAKE_DIR / 'Makefile.utils'}\n"
        "ok: areyousure\n\t@echo done\n"
    )
    return subprocess.run(
        ["make", "--no-print-directory", "ok"],
        cwd=tmp_path,
        input=answer,
        capture_output=True,
        text=True,
        env={**_clean_env(), **env},
        check=False,
    )


@pytest.mark.integration
class TestAreYouSure:
    """APPINFRA_YES=true|1|y|yes (any case) skips the prompt; otherwise it asks."""

    @pytest.mark.parametrize("value", ["true", "1", "y", "yes", "TRUE", "Y", "Yes"])
    def test_yes_values_skip_prompt(self, tmp_path: Path, value: str) -> None:
        result = _areyousure(tmp_path, {"APPINFRA_YES": value})
        assert result.returncode == 0, result.stderr
        assert "Are you sure" not in result.stdout
        assert "done" in result.stdout

    def test_makefile_local_value_skips_prompt(self, tmp_path: Path) -> None:
        result = _areyousure(tmp_path, {}, local="APPINFRA_YES ?= 1\n")
        assert result.returncode == 0, result.stderr
        assert "done" in result.stdout

    @pytest.mark.parametrize("value", ["0", "no", "false"])
    def test_other_values_prompt(self, tmp_path: Path, value: str) -> None:
        result = _areyousure(tmp_path, {"APPINFRA_YES": value}, answer="n\n")
        assert result.returncode != 0
        assert "Are you sure" in result.stdout
        assert "done" not in result.stdout

    @pytest.mark.parametrize("answer", ["y\n", "yes\n", "Y\n"])
    def test_prompt_accepts_yes(self, tmp_path: Path, answer: str) -> None:
        result = _areyousure(tmp_path, {}, answer=answer)
        assert result.returncode == 0, result.stderr
        assert "done" in result.stdout

    def test_prompt_without_input_fails(self, tmp_path: Path) -> None:
        result = _areyousure(tmp_path, {})
        assert result.returncode != 0
        assert "done" not in result.stdout


BOOLEANS = registry()["_APPINFRA_BOOLEANS"]
TRUE = ["true", "1", "y", "yes", "TRUE", "Yes"]
FALSE = ["false", "0", "n", "no", "FALSE", "No"]


def _bool_value(
    tmp_path: Path, name: str, env: dict[str, str], *args: str
) -> subprocess.CompletedProcess[str]:
    """Run make printing NAME as Make's readers see it and as a recipe's environment holds it."""
    (tmp_path / "Makefile").write_text(
        f"include {MAKEFILE_CONFIG}\n"
        f"ok:\n\t@echo $(call _APPINFRA_BOOL_VALUE,{name}) $${name}\n"
    )
    return subprocess.run(
        ["make", "--no-print-directory", "ok", *args],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env={**_clean_env(), **env},
        check=False,
    )


@pytest.mark.integration
class TestBooleanSettings:
    """Every on/off setting takes the same values; it is exported as written."""

    @pytest.mark.parametrize("name", BOOLEANS)
    @pytest.mark.parametrize("value", TRUE)
    def test_true_values(self, tmp_path: Path, name: str, value: str) -> None:
        result = _bool_value(tmp_path, name, {name: value})
        assert result.stdout.split() == ["true", value], result.stderr

    @pytest.mark.parametrize("name", BOOLEANS)
    @pytest.mark.parametrize("value", FALSE)
    def test_false_values(self, tmp_path: Path, name: str, value: str) -> None:
        result = _bool_value(tmp_path, name, {name: value})
        assert result.stdout.split() == ["false", value], result.stderr

    @pytest.mark.parametrize("name", BOOLEANS)
    def test_default_is_false(self, tmp_path: Path, name: str) -> None:
        result = _bool_value(tmp_path, name, {})
        assert result.stdout.split() == ["false", "false"], result.stderr

    def test_command_line_value(self, tmp_path: Path) -> None:
        result = _bool_value(tmp_path, "APPINFRA_DRY_RUN", {}, "APPINFRA_DRY_RUN=Yes")
        assert result.stdout.split() == ["true", "Yes"], result.stderr

    def test_makefile_local_value(self, tmp_path: Path) -> None:
        (tmp_path / "Makefile.local").write_text("APPINFRA_DEV_CQ_STRICT ?= 1\n")
        result = _bool_value(tmp_path, "APPINFRA_DEV_CQ_STRICT", {})
        assert result.stdout.split() == ["true", "1"], result.stderr

    @pytest.mark.parametrize("value", ["ture", "on", "2", "yes no"])
    def test_other_values_stop_make(self, tmp_path: Path, value: str) -> None:
        result = _bool_value(tmp_path, "APPINFRA_DRY_RUN", {"APPINFRA_DRY_RUN": value})
        assert result.returncode != 0
        assert "APPINFRA_DRY_RUN=" in result.stderr
        assert "is not a boolean" in result.stderr


SETTINGS_SH = MAKE_DIR.parent / "_settings.sh"


def _bool_sh(
    value: str | None, default: str = "false"
) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in _clean_env().items() if k != "X"}
    if value is not None:
        env["X"] = value
    return subprocess.run(
        ["bash", "-c", f'. "{SETTINGS_SH}"; appinfra_bool X {default}'],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


@pytest.mark.integration
class TestSettingsSh:
    """scripts/_settings.sh applies the same rule for scripts run outside make."""

    @pytest.mark.parametrize("value", [*TRUE, " yes ", "\ttrue  "])
    def test_true_values(self, value: str) -> None:
        assert _bool_sh(value).stdout.strip() == "true"

    @pytest.mark.parametrize("value", FALSE)
    def test_false_values(self, value: str) -> None:
        assert _bool_sh(value).stdout.strip() == "false"

    def test_unset_takes_default(self) -> None:
        assert _bool_sh(None, default="true").stdout.strip() == "true"

    def test_trailing_comment_values_reach_check_sh_trimmed(
        self, tmp_path: Path
    ) -> None:
        """make keeps the spaces before a trailing comment; check.sh trims them."""
        (tmp_path / "Makefile").write_text(
            "APPINFRA_DEV_CQ_STRICT ?= true  # fail on warnings\n"
            "APPINFRA_DEV_CQ_DUP ?= strict  # duplicated code\n"
            f"include {MAKEFILE_CONFIG}\n"
            f"ok:\n\t@bash -c '. {SETTINGS_SH}; appinfra_trim_settings; "
            'appinfra_bool APPINFRA_DEV_CQ_STRICT false; echo "[$$APPINFRA_DEV_CQ_DUP]"\'\n'
        )
        result = subprocess.run(
            ["make", "--no-print-directory", "ok"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            env=_clean_env(),
            check=False,
        )
        assert result.stdout.split() == ["true", "[strict]"], result.stderr

    @pytest.mark.parametrize("value", ["", "  ", "ture", "on", "2"])
    def test_other_values_fail(self, value: str) -> None:
        result = _bool_sh(value)
        assert result.returncode == 2
        assert "X=" in result.stderr and "is not a boolean" in result.stderr


@pytest.mark.integration
class TestMakeConfig:
    """`make config` names each setting's source and the interpreter's."""

    def _config(
        self, tmp_path: Path, head: str, local: str, *args: str
    ) -> dict[str, str]:
        (tmp_path / "Makefile.local").write_text(local)
        (tmp_path / "Makefile").write_text(
            f"{head}\ninclude {MAKEFILE_CONFIG}\ninclude {MAKE_DIR / 'Makefile.env'}\n"
        )
        result = subprocess.run(
            ["make", "--no-print-directory", "config", *args],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            env={**_clean_env(), "APPINFRA_PYTEST_WORKERS": "4"},
            check=False,
        )
        assert result.returncode == 0, result.stderr
        sources = {}
        for line in result.stdout.splitlines():
            parts = line.split()
            if parts and parts[0].startswith("APPINFRA_"):
                sources[parts[0]] = parts[1]
            elif line.startswith("Python:"):
                sources["Python"] = line
        return sources

    def test_sources(self, tmp_path: Path) -> None:
        sources = self._config(
            tmp_path,
            "APPINFRA_DEV_PKG_NAME := mypkg",
            "APPINFRA_CONTAINER_CMD ?= podman\nAPPINFRA_DEV_CQ_STRICT := true\n",
            "APPINFRA_DEV_CQ_DUP=warn",
        )
        assert sources["APPINFRA_DEV_PKG_NAME"] == "Makefile"
        assert sources["APPINFRA_CONTAINER_CMD"] == "Makefile.local"
        assert sources["APPINFRA_DEV_CQ_STRICT"] == "Makefile.local"
        assert sources["APPINFRA_DEV_CQ_DUP"] == "command-line"
        assert sources["APPINFRA_PYTEST_WORKERS"] == "environment"
        assert sources["APPINFRA_CLEAN_PRESERVE"] == "default"
        assert "APPINFRA_PYTHON" not in sources
        assert "(environment)" in sources["Python"]

    def test_makefile_local_question_assign_does_not_claim_makefile_value(
        self, tmp_path: Path
    ) -> None:
        """A Makefile.local ?= that does not apply leaves the source at Makefile."""
        sources = self._config(
            tmp_path,
            "APPINFRA_DEV_PKG_NAME := mypkg",
            "APPINFRA_DEV_PKG_NAME ?= other\n",
        )
        assert sources["APPINFRA_DEV_PKG_NAME"] == "Makefile"

    def test_macros_not_listed(self, tmp_path: Path) -> None:
        (tmp_path / "Makefile.local").write_text("")
        (tmp_path / "Makefile").write_text(
            f"include {MAKEFILE_CONFIG}\ninclude {MAKE_DIR / 'Makefile.env'}\n"
            f"include {MAKE_DIR / 'Makefile.pytest'}\n"
        )
        result = subprocess.run(
            ["make", "--no-print-directory", "config"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            env=_clean_env(),
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert "APPINFRA_RUN_PYTEST" not in result.stdout


@pytest.mark.integration
class TestUnknownSettings:
    """An APPINFRA_* name the registry does not declare stops make; from the environment it warns."""

    def test_environment_warns(self, tmp_path: Path) -> None:
        """The environment is shared with projects on other appinfra versions."""
        result = _make(tmp_path, "", env={"APPINFRA_DEV_CQ_STRCT": "true"})
        assert result.returncode == 0, result.stderr
        assert (
            "APPINFRA_DEV_CQ_STRCT: not a setting of this appinfra version"
            in result.stderr
        )

    def test_environment_warning_not_repeated_by_sub_make(self, tmp_path: Path) -> None:
        (tmp_path / "Makefile").write_text(
            f"include {MAKEFILE_CONFIG}\n"
            "ok:\n\t@$(MAKE) --no-print-directory inner\ninner:\n\t@echo inner-ok\n"
        )
        result = subprocess.run(
            ["make", "--no-print-directory", "ok"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            env={**_clean_env(), "APPINFRA_NEWER": "1"},
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert result.stderr.count("APPINFRA_NEWER") == 1

    def test_command_line(self, tmp_path: Path) -> None:
        result = _make(tmp_path, "", "APPINFRA_TYPO=1")
        assert "APPINFRA_TYPO: not an appinfra setting" in result.stderr

    def test_makefile(self, tmp_path: Path) -> None:
        result = _make(tmp_path, "APPINFRA_MY_OWN := x")
        assert "APPINFRA_MY_OWN: not an appinfra setting" in result.stderr

    def test_makefile_local(self, tmp_path: Path) -> None:
        (tmp_path / "Makefile.local").write_text("APPINFRA_PG_PORT ?= 5433\n")
        result = _make(tmp_path, "")
        assert "APPINFRA_PG_PORT: not an appinfra setting" in result.stderr

    def test_internal_names_pass(self, tmp_path: Path) -> None:
        result = _make(tmp_path, "", env={"_APPINFRA_CHECK_PYTEST_SUITE": "unit"})
        assert result.returncode == 0, result.stderr


def _value(tmp_path: Path, name: str, value: str) -> subprocess.CompletedProcess[str]:
    """Run make printing NAME, with NAME=value on the command line."""
    (tmp_path / "Makefile").write_text(
        f"include {MAKEFILE_CONFIG}\nok:\n\t@echo $({name})\n"
    )
    return subprocess.run(
        ["make", "--no-print-directory", "ok", f"{name}={value}"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=_clean_env(),
        check=False,
    )


@pytest.mark.integration
class TestSettingTypes:
    """Each typed setting accepts exactly its type's values."""

    @pytest.mark.parametrize(
        ("name", "value", "expected"),
        [
            ("APPINFRA_DEV_CQ_DUP", "warn", "warn"),
            ("APPINFRA_DEV_CQ_DEAD", "Strict", "Strict"),
            ("APPINFRA_DEV_CQ_DUP", "FALSE", "FALSE"),
            ("APPINFRA_PYTEST_COVERAGE_THRESHOLD", "0", "0"),
            ("APPINFRA_PYTEST_COVERAGE_THRESHOLD", "95.5", "95.5"),
            ("APPINFRA_DEV_DOCSTRING_THRESHOLD", "100", "100"),
            ("APPINFRA_DEV_DOCSTRING_THRESHOLD", "100.0", "100.0"),
            ("APPINFRA_PYTEST_HANG_DUMP_SECONDS", "0", "0"),
            ("APPINFRA_PYTEST_HANG_DUMP_SECONDS", "300", "300"),
            ("APPINFRA_PYTEST_WORKERS", "auto", "auto"),
            ("APPINFRA_PYTEST_WORKERS", "logical", "logical"),
            ("APPINFRA_PYTEST_WORKERS", "8", "8"),
        ],
    )
    def test_valid(self, tmp_path: Path, name: str, value: str, expected: str) -> None:
        result = _value(tmp_path, name, value)
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == expected

    @pytest.mark.parametrize(
        ("name", "value", "kind"),
        [
            ("APPINFRA_DEV_CQ_DUP", "strcit", "a mode: use false, warn or strict"),
            ("APPINFRA_DEV_CQ_DEAD", "on", "a mode"),
            ("APPINFRA_PYTEST_COVERAGE_THRESHOLD", "101", "a percent"),
            ("APPINFRA_PYTEST_COVERAGE_THRESHOLD", "100.5", "a percent"),
            ("APPINFRA_PYTEST_COVERAGE_THRESHOLD", "95.", "a percent"),
            ("APPINFRA_PYTEST_COVERAGE_THRESHOLD", ".5", "a percent"),
            ("APPINFRA_PYTEST_COVERAGE_THRESHOLD", "9.5.1", "a percent"),
            ("APPINFRA_DEV_DOCSTRING_THRESHOLD", "007", "a percent"),
            ("APPINFRA_DEV_DOCSTRING_THRESHOLD", "high", "a percent"),
            ("APPINFRA_PYTEST_HANG_DUMP_SECONDS", "-1", "an integer"),
            ("APPINFRA_PYTEST_HANG_DUMP_SECONDS", "2m", "an integer"),
            ("APPINFRA_PYTEST_WORKERS", "0", "a worker count"),
            ("APPINFRA_PYTEST_WORKERS", "04", "a worker count"),
            ("APPINFRA_PYTEST_WORKERS", "many", "a worker count"),
        ],
    )
    def test_invalid(self, tmp_path: Path, name: str, value: str, kind: str) -> None:
        result = _value(tmp_path, name, value)
        assert result.returncode != 0
        assert f"{name}={value} is not {kind}" in result.stderr


def _late(tmp_path: Path, assign: str, recipe: str) -> subprocess.CompletedProcess[str]:
    """Run `make ok` on a project Makefile that assigns a setting after the include."""
    (tmp_path / "Makefile").write_text(
        f"include {MAKEFILE_CONFIG}\n{assign}\nok:\n\t{recipe}\n"
    )
    return subprocess.run(
        ["make", "--no-print-directory", "ok"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=_clean_env(),
        check=False,
    )


@pytest.mark.integration
class TestLateAssignment:
    """A setting assigned after the include takes effect, as it did before the registry."""

    def test_boolean_reaches_make_and_check_sh(self, tmp_path: Path) -> None:
        result = _late(
            tmp_path,
            "APPINFRA_DEV_CQ_STRICT := Yes",
            "@echo $(call _APPINFRA_BOOL_VALUE,APPINFRA_DEV_CQ_STRICT) "
            f"$$(bash -c '. {SETTINGS_SH}; appinfra_bool APPINFRA_DEV_CQ_STRICT false')",
        )
        assert result.stdout.split() == ["true", "true"], result.stderr

    def test_mode_reaches_make(self, tmp_path: Path) -> None:
        result = _late(
            tmp_path,
            "APPINFRA_DEV_CQ_DUP := Strict",
            "@echo $(call _APPINFRA_MODE_VALUE,APPINFRA_DEV_CQ_DUP) $$APPINFRA_DEV_CQ_DUP",
        )
        assert result.stdout.split() == ["strict", "Strict"], result.stderr

    def test_environment_value_restored_over_makefile_local_yields(
        self, tmp_path: Path
    ) -> None:
        """Whether Makefile.local touched a setting does not change a later assignment."""
        (tmp_path / "Makefile.local").write_text("APPINFRA_DEV_CQ_DUP := false\n")
        (tmp_path / "Makefile").write_text(
            f"include {MAKEFILE_CONFIG}\n"
            "APPINFRA_DEV_CQ_DUP := strict\nAPPINFRA_DEV_CQ_DEAD := strict\n"
            "ok:\n\t@echo $(APPINFRA_DEV_CQ_DUP) $(APPINFRA_DEV_CQ_DEAD)\n"
        )
        result = subprocess.run(
            ["make", "--no-print-directory", "ok"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            env={
                **_clean_env(),
                "APPINFRA_DEV_CQ_DUP": "warn",
                "APPINFRA_DEV_CQ_DEAD": "warn",
            },
            check=False,
        )
        assert result.stdout.split() == ["strict", "strict"], result.stderr

    def test_invalid_boolean_stops_make_when_read(self, tmp_path: Path) -> None:
        result = _late(
            tmp_path, "APPINFRA_YES := maybe", "@echo $(call _APPINFRA_ON,APPINFRA_YES)"
        )
        assert result.returncode != 0
        assert "APPINFRA_YES=maybe is not a boolean" in result.stderr

    def test_invalid_mode_stops_make_when_read(self, tmp_path: Path) -> None:
        result = _late(
            tmp_path,
            "APPINFRA_DEV_CQ_DEAD := on",
            "@echo $(call _APPINFRA_MODE_VALUE,APPINFRA_DEV_CQ_DEAD)",
        )
        assert result.returncode != 0
        assert "APPINFRA_DEV_CQ_DEAD=on is not a mode" in result.stderr
