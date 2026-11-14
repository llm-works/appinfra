# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for cli/tools/pg_make.py, the entry of the make pg.* targets."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from appinfra.cli.tools import pg_make

# Synthetic values: they track no real pgserver config
SERVER = """\
  name: stub-pg
  version: stub
  port: 40101
  host: 127.0.0.1
  user: app_owner
  bind: ''
  pass: ''
"""


class _Calls:
    """Stands in for subprocess.call: keeps each command and its environment."""

    def __init__(self) -> None:
        self.calls: list[tuple[list[str], dict[str, str]]] = []

    def __call__(self, cmd: list[str], env: dict[str, str], **_: Any) -> int:
        self.calls.append((cmd, env))
        return 0

    @property
    def env(self) -> dict[str, str]:
        return self.calls[-1][1]

    @property
    def cmd(self) -> list[str]:
        return self.calls[-1][0]


@pytest.fixture
def pg_sh(monkeypatch: pytest.MonkeyPatch) -> _Calls:
    """subprocess.call recorded, and none of the caller's INFRA_* overrides or
    make wire variables: Config rejects an override the file does not declare."""
    calls = _Calls()
    monkeypatch.setattr("appinfra.cli.tools.pg_tool.subprocess.call", calls)
    for name in list(os.environ):
        if name.startswith(("INFRA_", "_APPINFRA_PG_")):
            monkeypatch.delenv(name)
    return calls


def _config(tmp_path: Path, body: str = f"pgserver:\n{SERVER}") -> Path:
    path = tmp_path / "etc" / "infra.yaml"
    path.parent.mkdir(exist_ok=True)
    path.write_text(body)
    return path


@pytest.mark.integration
class TestMain:
    """Config file → pg.sh verb, with the projection of the appinfra pg tools."""

    def test_runs_the_verb_with_the_projected_config(
        self, tmp_path: Path, pg_sh: _Calls
    ) -> None:
        code = pg_make.main([str(_config(tmp_path)), "pgserver", "info", "--short"])
        assert code == 0
        assert pg_sh.cmd[1:] == ["info", "--short"]
        assert pg_sh.env["_APPINFRA_PG_CONTAINER_NAME"] == "stub-pg"
        assert pg_sh.env["_APPINFRA_PG_PORT"] == "40101"

    def test_environment_overrides_reach_the_server(
        self, tmp_path: Path, pg_sh: _Calls, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("INFRA_PGSERVER_PORT", "40201")
        monkeypatch.setenv("INFRA_PGSERVER_PASS", "s3cret")
        monkeypatch.setenv("INFRA_PGSERVER_BIND", "0.0.0.0")
        pg_make.main([str(_config(tmp_path)), "pgserver", "up"])
        assert pg_sh.env["_APPINFRA_PG_PORT"] == "40201"
        assert pg_sh.env["_APPINFRA_PG_PASS"] == "s3cret"
        assert pg_sh.env["_APPINFRA_PG_BIND"] == "0.0.0.0"

    def test_an_included_server_section_resolves(
        self, tmp_path: Path, pg_sh: _Calls
    ) -> None:
        (tmp_path / "etc").mkdir()
        (tmp_path / "etc" / "pg.yaml").write_text(f"pgserver:\n{SERVER}")
        path = _config(tmp_path, "pgserver: !include pg.yaml#pgserver\n")
        assert pg_make.main([str(path), "pgserver", "up"]) == 0
        assert pg_sh.env["_APPINFRA_PG_CONTAINER_NAME"] == "stub-pg"

    def test_reads_the_given_key(self, tmp_path: Path, pg_sh: _Calls) -> None:
        path = _config(tmp_path, f"db_server:\n{SERVER}")
        assert pg_make.main([str(path), "db_server", "up"]) == 0
        assert pg_sh.env["_APPINFRA_PG_CONTAINER_NAME"] == "stub-pg"

    def test_make_settings_win_over_the_config(
        self, tmp_path: Path, pg_sh: _Calls, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("_APPINFRA_PG_HOST", "127.0.0.9")
        monkeypatch.setenv("_APPINFRA_PG_USER", "make_role")
        monkeypatch.setenv("_APPINFRA_PG_DATABASES", "one two")
        pg_make.main([str(_config(tmp_path)), "pgserver", "clean"])
        assert pg_sh.env["_APPINFRA_PG_HOST"] == "127.0.0.9"
        assert pg_sh.env["_APPINFRA_PG_USER"] == "make_role"
        assert pg_sh.env["_APPINFRA_PG_DATABASES"] == "one two"

    def test_an_override_the_file_does_not_declare_is_reported(
        self,
        tmp_path: Path,
        pg_sh: _Calls,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # The application's own load rejects it the same way
        monkeypatch.setenv("INFRA_LOGGING_LEVEL", "debug")
        assert pg_make.main([str(_config(tmp_path)), "pgserver", "up"]) == 2
        assert "INFRA_LOGGING_LEVEL" in capsys.readouterr().err
        assert pg_sh.calls == []

    def test_a_missing_file_is_reported(
        self, tmp_path: Path, pg_sh: _Calls, capsys: pytest.CaptureFixture[str]
    ) -> None:
        missing = tmp_path / "etc" / "absent.yaml"
        assert pg_make.main([str(missing), "pgserver", "up"]) == 2
        assert f"config file not found: {missing}" in capsys.readouterr().err
        assert pg_sh.calls == []

    def test_an_invalid_config_is_reported(
        self, tmp_path: Path, pg_sh: _Calls, capsys: pytest.CaptureFixture[str]
    ) -> None:
        path = _config(
            tmp_path, f"pgserver:\n{SERVER}  postgres_conf:\n    fsync: false\n"
        )
        assert pg_make.main([str(path), "pgserver", "up"]) == 2
        assert "unsupported key(s) ['fsync']" in capsys.readouterr().err
        assert pg_sh.calls == []


@pytest.mark.unit
def test_usage_without_a_verb(capsys: pytest.CaptureFixture[str]) -> None:
    assert pg_make.main(["etc/infra.yaml", "pgserver"]) == 2
    assert "usage:" in capsys.readouterr().err
