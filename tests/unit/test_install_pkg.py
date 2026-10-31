# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for appinfra/scripts/install_pkg.py."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

INSTALL_PKG_PY = (
    Path(__file__).resolve().parents[2] / "appinfra" / "scripts" / "install_pkg.py"
)


@pytest.fixture
def ip(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Load the script as a module; dataclasses look the module up in sys.modules."""
    spec = importlib.util.spec_from_file_location("install_pkg", INSTALL_PKG_PY)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "install_pkg", module)
    spec.loader.exec_module(module)
    return module


def _env(ip: ModuleType, venv: bool) -> Any:
    return ip.Env("/p/bin/python", Path("/p"), venv)


def _share_exists(monkeypatch: pytest.MonkeyPatch, exists: bool) -> None:
    monkeypatch.setattr(Path, "is_dir", lambda self: exists)


class TestProbe:
    def _run(
        self, monkeypatch: pytest.MonkeyPatch, ip: ModuleType, out: list[str]
    ) -> None:
        self._run_raw(monkeypatch, ip, json.dumps(out) + "\n")

    def _run_raw(
        self, monkeypatch: pytest.MonkeyPatch, ip: ModuleType, stdout: str
    ) -> None:
        result = SimpleNamespace(stdout=stdout)
        monkeypatch.setattr(ip.subprocess, "run", lambda *a, **k: result)

    def test_output_before_the_prefix_ignored(
        self, ip: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A sitecustomize that prints at startup does not hide the prefix."""
        self._run_raw(monkeypatch, ip, 'hello from sitecustomize\n["/v", "/usr"]\n')
        assert ip.probe("py") == ip.Env("py", Path("/v"), True)

    @pytest.mark.parametrize("stdout", ["", "not json\n", '["/only-one"]\n', "5\n"])
    def test_unreadable_output_refused(
        self, ip: ModuleType, monkeypatch: pytest.MonkeyPatch, stdout: str
    ) -> None:
        """An interpreter that does not report a prefix is refused, not a traceback."""
        self._run_raw(monkeypatch, ip, stdout)
        with pytest.raises(ip.RefusedError, match="py did not report its prefix"):
            ip.probe("py")

    def test_venv(self, ip: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
        self._run(monkeypatch, ip, ["/home/u/.venv", "/usr"])
        assert ip.probe("py") == ip.Env("py", Path("/home/u/.venv"), True)

    def test_not_venv(self, ip: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
        self._run(monkeypatch, ip, ["/usr", "/usr"])
        assert ip.probe("py").venv is False

    def test_empty_prefix_refused(
        self, ip: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._run(monkeypatch, ip, ["", "/usr"])
        with pytest.raises(ip.RefusedError, match="empty sys.prefix"):
            ip.probe("py")


class TestPreflight:
    @pytest.mark.parametrize(
        ("venv", "share"), [(True, True), (True, False), (False, True)]
    )
    def test_admitted(
        self, ip: ModuleType, monkeypatch: pytest.MonkeyPatch, venv: bool, share: bool
    ) -> None:
        _share_exists(monkeypatch, share)
        ip.preflight([_env(ip, venv)])

    def test_non_venv_without_share_refused(
        self, ip: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _share_exists(monkeypatch, False)
        with pytest.raises(ip.RefusedError, match=r"/p/share does not exist") as exc:
            ip.preflight([_env(ip, True), _env(ip, False)])
        assert "mkdir -p '/p/share'" in str(exc.value)


def test_share_modes_keep_special_bits_off_files(
    ip: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Directories take share/'s bits verbatim; the wheel drops setgid and execute."""
    monkeypatch.setattr(ip.os, "stat", lambda p: SimpleNamespace(st_mode=0o42775))
    assert ip.share_modes(Path("/p/share")) == (0o2775, 0o664)


@pytest.mark.parametrize(
    ("extras", "expected"), [("", "w.whl"), ("ui,dev", "w.whl[ui,dev]")]
)
def test_with_extras(ip: ModuleType, extras: str, expected: str) -> None:
    assert ip.with_extras("w.whl", extras) == expected


class TestReinstall:
    def _record(self, ip: ModuleType, monkeypatch: pytest.MonkeyPatch) -> list[str]:
        calls: list[str] = []
        monkeypatch.setattr(
            ip, "uninstall", lambda envs, pkg: calls.append("uninstall")
        )
        monkeypatch.setattr(
            ip, "install", lambda envs, pkg, extras: calls.append("install")
        )
        return calls

    def test_uninstall_then_install(
        self, ip: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = self._record(ip, monkeypatch)
        monkeypatch.setattr(ip, "preflight", lambda envs: calls.append("preflight"))
        ip.reinstall([], "pkg", "")
        assert calls == ["preflight", "uninstall", "install"]

    def test_refused_uninstalls_nothing(
        self, ip: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = self._record(ip, monkeypatch)

        def refuse(envs: list[Any]) -> None:
            raise ip.RefusedError("no")

        monkeypatch.setattr(ip, "preflight", refuse)
        with pytest.raises(ip.RefusedError):
            ip.reinstall([], "pkg", "")
        assert calls == []


def test_install_refused_before_cleaning(
    ip: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A refused install leaves the build directory as it was."""
    cleaned: list[bool] = []
    monkeypatch.setattr(ip, "clean_build", lambda: cleaned.append(True))
    _share_exists(monkeypatch, False)
    with pytest.raises(ip.RefusedError):
        ip.install([_env(ip, False)], "pkg", "")
    assert cleaned == []


def test_install_env_never_creates_share_outside_a_venv(
    ip: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """share/ gone after preflight: a non-venv is refused, nothing created or built."""
    made: list[Path] = []
    monkeypatch.setattr(ip, "_make_dir", lambda path, mode: made.append(path))
    monkeypatch.setattr(ip, "build_wheel", lambda env: pytest.fail("built a wheel"))
    _share_exists(monkeypatch, False)
    with pytest.raises(ip.RefusedError, match="/p/share no longer exists"):
        ip.install_env(_env(ip, False), "pkg", "")
    assert made == []


def test_resolve_skips_missing(
    ip: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(ip.os.path, "isfile", lambda p: p == "/ok/python")
    monkeypatch.setattr(ip.os, "access", lambda p, mode: True)
    monkeypatch.setattr(ip, "probe", lambda p: _env(ip, True))
    assert len(ip.resolve(["/missing/python", "/ok/python"])) == 1
    assert "/missing/python (skipped, not found)" in capsys.readouterr().out


@pytest.mark.parametrize("pkg", ["", ".", "..", "-pkg", "pkg.", "a/b"])
def test_pkg_name_rejected(ip: ModuleType, pkg: str) -> None:
    with pytest.raises(SystemExit):
        ip.parse_args(["install", "--pkg", pkg])


class TestMain:
    def test_refused_exits_1(
        self,
        ip: ModuleType,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        def refuse(*args: Any) -> None:
            raise ip.RefusedError("ERROR: first\nsecond")

        monkeypatch.setattr(ip, "resolve", lambda envs: [])
        monkeypatch.setattr(ip, "run", refuse)
        assert ip.main(["install", "--pkg", "pkg"]) == 1
        assert capsys.readouterr().err == "    ERROR: first\n    second\n"

    def test_failed_command_exits_1(
        self,
        ip: ModuleType,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        def fail(*args: Any) -> None:
            raise subprocess.CalledProcessError(2, ["py", "-m", "pip", "wheel"])

        monkeypatch.setattr(ip, "resolve", lambda envs: [])
        monkeypatch.setattr(ip, "run", fail)
        assert ip.main(["install", "--pkg", "pkg"]) == 1
        assert "py -m pip wheel failed (2)" in capsys.readouterr().err

    def test_dispatch(self, ip: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: list[tuple[str, ...]] = []
        monkeypatch.setattr(ip, "resolve", lambda envs: envs)
        monkeypatch.setattr(
            ip, "uninstall", lambda envs, pkg: seen.append(("uninstall", pkg))
        )
        assert ip.main(["uninstall", "--pkg", "pkg", "/a", "/b"]) == 0
        assert seen == [("uninstall", "pkg")]
