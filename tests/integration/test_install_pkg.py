# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""make install / reinstall against stub interpreters.

Each stub env is a prefix with bin/python: `-m pip ...` is logged (and `pip wheel` leaves
a dummy wheel), anything else runs the real interpreter with sys.prefix and
sys.base_prefix set by a sitecustomize, so an env is a venv or not as a test needs.
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

MAKE_DIR = Path(__file__).resolve().parents[2] / "appinfra" / "scripts" / "make"
PKG = "fixturepkg"

STUB = """\
#!/bin/bash
if [ "$1" = "-m" ] && [ "$2" = "pip" ]; then
    echo "$*" >> "{log}"
    if [ "$3" = "wheel" ]; then
        while [ $# -gt 0 ]; do
            if [ "$1" = "-w" ]; then mkdir -p "$2" && touch "$2/{pkg}-0.1-py3-none-any.whl"; fi
            shift
        done
    fi
    exit 0
fi
exec env PYTHONPATH="{site}" "{python}" "$@"
"""


def _stub_env(root: Path, name: str, venv: bool, share: bool) -> Path:
    """A prefix whose bin/python is a stub; returns the stub's path."""
    prefix = root / name
    site = prefix / "site"
    site.mkdir(parents=True)
    base = "/nonexistent-base" if venv else str(prefix)
    (site / "sitecustomize.py").write_text(
        f"import sys\nsys.prefix = {str(prefix)!r}\nsys.base_prefix = {base!r}\n"
    )
    if share:
        (prefix / "share").mkdir(mode=0o750)
        (prefix / "share").chmod(0o750)
    python = prefix / "bin" / "python"
    python.parent.mkdir()
    python.write_text(
        STUB.format(log=prefix / "pip.log", pkg=PKG, site=site, python=sys.executable)
    )
    python.chmod(0o755)
    return python


def _pip_calls(python: Path) -> list[str]:
    log = python.parent.parent / "pip.log"
    return log.read_text().splitlines() if log.exists() else []


def _make(
    tmp_path: Path, target: str, envs: list[Path], answer: str | None = None
) -> subprocess.CompletedProcess[str]:
    project = tmp_path / "proj"
    project.mkdir(exist_ok=True)
    (project / "Makefile").write_text(
        f"APPINFRA_DEV_PKG_NAME := {PKG}\n"
        f"include {MAKE_DIR / 'Makefile.utils'}\n"
        f"include {MAKE_DIR / 'Makefile.install'}\n"
    )
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("INFRA_", "APPINFRA_", "_APPINFRA_", "PIP_"))
        and k not in ("MAKEFLAGS", "MFLAGS", "MAKELEVEL")
    }
    env["PYTHON"] = sys.executable
    args = [
        "make",
        "-C",
        str(project),
        target,
        f"APPINFRA_PYTHON_ENVS={' '.join(map(str, envs))}",
    ]
    if answer is None:
        args.append("APPINFRA_YES=true")
    return subprocess.run(
        args, input=answer, capture_output=True, text=True, env=env, timeout=120
    )


def test_reinstall_refused_before_uninstall(tmp_path: Path) -> None:
    """A prefix that cannot take the wheel stops reinstall before anything is uninstalled."""
    python = _stub_env(tmp_path / "envs", "system", venv=False, share=False)
    result = _make(tmp_path, "reinstall", [python])
    assert result.returncode != 0
    assert "share does not exist" in result.stdout + result.stderr
    assert _pip_calls(python) == []


def test_install_refused_before_any_env_changes(tmp_path: Path) -> None:
    """One env that would be refused leaves every env untouched, the ones before it too."""
    good = _stub_env(tmp_path / "envs", "good", venv=True, share=True)
    bad = _stub_env(tmp_path / "envs", "bad", venv=False, share=False)
    result = _make(tmp_path, "install", [good, bad])
    assert result.returncode != 0
    assert _pip_calls(good) == []
    assert _pip_calls(bad) == []


def test_install_creates_share_in_venv(tmp_path: Path) -> None:
    """A venv without share/ gets one (0755) and the wheel is published under it."""
    python = _stub_env(tmp_path / "envs", "venv", venv=True, share=False)
    result = _make(tmp_path, "install", [python])
    assert result.returncode == 0, result.stdout + result.stderr
    share = python.parent.parent / "share"
    assert stat.S_IMODE(share.stat().st_mode) == 0o755
    assert (share / PKG / "wheels" / f"{PKG}-0.1-py3-none-any.whl").is_file()
    assert any(call.startswith("-m pip install") for call in _pip_calls(python))


def test_install_takes_modes_from_share(tmp_path: Path) -> None:
    """An existing share/ sets the mode of the directories and wheel published under it."""
    python = _stub_env(tmp_path / "envs", "venv", venv=True, share=True)
    result = _make(tmp_path, "install", [python])
    assert result.returncode == 0, result.stdout + result.stderr
    wheels = python.parent.parent / "share" / PKG / "wheels"
    assert stat.S_IMODE(wheels.stat().st_mode) == 0o750
    wheel = wheels / f"{PKG}-0.1-py3-none-any.whl"
    assert stat.S_IMODE(wheel.stat().st_mode) == 0o640


def test_reinstall_asks_once(tmp_path: Path) -> None:
    """reinstall confirms once, not again for its uninstall and install steps."""
    python = _stub_env(tmp_path / "envs", "venv", venv=True, share=True)
    result = _make(tmp_path, "reinstall", [python], answer="y\n")
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.count("Are you sure?") == 1
    calls = _pip_calls(python)
    assert calls[0].startswith("-m pip uninstall")
    assert any(call.startswith("-m pip install") for call in calls)
