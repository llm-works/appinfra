# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""appinfra/scripts/pg.sh started from a project, against stub container tools."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.helpers.pg_sh import CONTAINER, PORT, ROLE, run_pg_sh

MODES = ["single", "repl"]


def _mounted_files(compose: dict) -> list[Path]:
    """Host paths of every bind mount in the compose file."""
    sources = []
    for service in compose["services"].values():
        for volume in service.get("volumes", []):
            source = volume.split(":", 1)[0]
            if source.startswith("/"):
                sources.append(Path(source))
    return sources


def _published(compose: dict) -> list[str]:
    """Every published port mapping, across services."""
    return [p for s in compose["services"].values() for p in s.get("ports", [])]


# Where the containers mount the shipped pg_hba file, and the copy the server reads
_HBA_MOUNT = "/opt/appinfra/pg_hba.conf"
_HBA_COPY = "/etc/postgresql/pg_hba.conf"


def _hba_file(service: dict) -> Path:
    """The host file a service mounts as its pg_hba.conf."""
    for volume in service.get("volumes", []):
        source, _, rest = volume.partition(":")
        if rest.startswith(_HBA_MOUNT):
            return Path(source)
    raise AssertionError(f"no pg_hba.conf mounted: {service.get('volumes')}")


def _startup(service: dict) -> str:
    """What a service runs at start: its entrypoint and command, as one string."""
    entrypoint = service.get("entrypoint") or ""
    if isinstance(entrypoint, list):
        entrypoint = " ".join(entrypoint)
    return f"{entrypoint} {' '.join(service.get('command') or [])}"


def _hba_lines(service: dict) -> list[list[str]]:
    """The rules of the pg_hba.conf a service mounts, comments dropped."""
    text = _hba_file(service).read_text()
    return [
        line.split() for line in text.splitlines() if line.split() and line[0] != "#"
    ]


def _services(compose: dict) -> list[dict]:
    return list(compose["services"].values())


def _up(tmp_path: Path, mode: str, **env: str):
    run = run_pg_sh(tmp_path, "up", env={"_APPINFRA_PG_MODE": mode, **env})
    assert run.result.returncode == 0, run.result.stderr
    return run


@pytest.mark.parametrize("mode", MODES)
def test_every_mounted_file_exists_from_a_project(tmp_path: Path, mode: str) -> None:
    """Compose mounts files shipped with appinfra, not paths under the project."""
    run = _up(tmp_path, mode)
    missing = [p for p in _mounted_files(run.compose_file()) if not p.exists()]
    assert missing == []


class TestBind:
    """Which host address the published ports listen on."""

    @pytest.mark.parametrize("mode", MODES)
    def test_ports_publish_on_loopback_by_default(
        self, tmp_path: Path, mode: str
    ) -> None:
        ports = _published(_up(tmp_path, mode).compose_file())
        assert ports and all(p.startswith("127.0.0.1:") for p in ports), ports

    @pytest.mark.parametrize("mode", MODES)
    def test_bind_sets_the_host_address(self, tmp_path: Path, mode: str) -> None:
        run = _up(tmp_path, mode, _APPINFRA_PG_BIND="0.0.0.0", _APPINFRA_PG_PASS="pw")
        ports = _published(run.compose_file())
        assert all(p.startswith("0.0.0.0:") for p in ports), ports

    def test_an_ipv6_bind_is_bracketed(self, tmp_path: Path) -> None:
        run = _up(tmp_path, "single", _APPINFRA_PG_BIND="::1")
        assert _published(run.compose_file()) == [f"[::1]:{PORT}:{PORT}"]

    def test_lan_bind_without_password_warns(self, tmp_path: Path) -> None:
        run = _up(tmp_path, "single", _APPINFRA_PG_BIND="0.0.0.0")
        output = run.result.stdout + run.result.stderr
        assert "0.0.0.0" in output and "without a password" in output

    @pytest.mark.parametrize(
        "env",
        [
            {},
            {"_APPINFRA_PG_BIND": "127.0.0.2"},
            {"_APPINFRA_PG_BIND": "::1"},
            {"_APPINFRA_PG_BIND": "0.0.0.0", "_APPINFRA_PG_PASS": "pw"},
        ],
        ids=["default", "loopback", "ipv6-loopback", "lan-with-password"],
    )
    def test_no_warning_otherwise(self, tmp_path: Path, env: dict[str, str]) -> None:
        run = _up(tmp_path, "single", **env)
        assert "without a password" not in run.result.stdout + run.result.stderr


class TestAuth:
    """Trust without a password, scram with one; in-container connections stay trusted."""

    @pytest.mark.parametrize("mode", MODES)
    def test_every_server_uses_the_mounted_hba_file(
        self, tmp_path: Path, mode: str
    ) -> None:
        compose = _up(tmp_path, mode).compose_file()
        for service in _services(compose):
            started = _startup(service)
            assert f"hba_file={_HBA_COPY}" in started
            _hba_file(service)

    @pytest.mark.parametrize("mode", MODES)
    def test_the_server_reads_a_copy_postgres_owns(
        self, tmp_path: Path, mode: str
    ) -> None:
        # The mount keeps the host file's mode, which postgres may not read
        compose = _up(tmp_path, mode).compose_file()
        copy = f"install -D -m 0600 -o postgres -g postgres {_HBA_MOUNT} {_HBA_COPY}"
        for service in _services(compose):
            started = _startup(service)
            assert copy in started
            assert started.index(copy) < started.index(f"hba_file={_HBA_COPY}")

    @pytest.mark.parametrize("mode", MODES)
    def test_without_password_every_connection_is_trusted(
        self, tmp_path: Path, mode: str
    ) -> None:
        for service in _services(_up(tmp_path, mode).compose_file()):
            methods = {rule[-1] for rule in _hba_lines(service)}
            assert methods == {"trust"}

    @pytest.mark.parametrize("mode", MODES)
    def test_with_password_only_in_container_connections_are_trusted(
        self, tmp_path: Path, mode: str
    ) -> None:
        compose = _up(tmp_path, mode, _APPINFRA_PG_PASS="pw").compose_file()
        for service in _services(compose):
            rules = _hba_lines(service)
            trusted = [r for r in rules if r[-1] == "trust"]
            assert all(
                r[0] == "local" or r[3] in ("127.0.0.1/32", "::1/128") for r in trusted
            )
            assert ["host", "all", "all", "all", "scram-sha-256"] in rules
            assert ["host", "replication", "all", "all", "scram-sha-256"] in rules

    @pytest.mark.parametrize("mode", MODES)
    def test_a_new_volume_gets_the_password(self, tmp_path: Path, mode: str) -> None:
        compose = _up(tmp_path, mode, _APPINFRA_PG_PASS="pw").compose_file()
        first = _services(compose)[0]
        assert "POSTGRES_PASSWORD=pw" in first["environment"]

    def test_the_role_name_stays_out_of_the_standby_script(
        self, tmp_path: Path
    ) -> None:
        # Compose substitutes into the bash -c script before bash parses it, so
        # spaces, quotes or $ there would reach bash as code
        role = 'app "$owner"'
        run = _up(tmp_path, "repl", _APPINFRA_PG_USER=role)
        standby = run.compose_file()["services"]["postgres-standby"]
        assert f"PGUSER={role}" in standby["environment"]
        assert "owner" not in standby["entrypoint"]

    def test_the_standby_copies_with_the_password(self, tmp_path: Path) -> None:
        compose = _up(tmp_path, "repl", _APPINFRA_PG_PASS="pw").compose_file()
        standby = compose["services"]["postgres-standby"]
        # The password is the configured role's, so the copy logs in as that role
        assert "PGPASSWORD=pw" in standby["environment"]
        assert f"PGUSER={ROLE}" in standby["environment"]
        assert (
            f"until pg_basebackup -w -h postgres-primary -p {PORT} -D"
            in (standby["entrypoint"])
        )

    def test_the_standby_stops_retrying_a_refused_copy(self, tmp_path: Path) -> None:
        # A role or password the primary never accepts must not retry forever
        compose = _up(tmp_path, "repl").compose_file()
        entrypoint = compose["services"]["postgres-standby"]["entrypoint"]
        assert 'if [ \\"$attempt\\" -ge 15 ]' in entrypoint
        assert "Base backup failed 15 times; check pgserver.user and pgserver.pass" in (
            entrypoint
        )
        assert "exit 1" in entrypoint


class TestPasswordOnUp:
    """The role's password follows the configured one on every up."""

    def test_up_sets_the_password(self, tmp_path: Path) -> None:
        run = _up(tmp_path, "single", _APPINFRA_PG_PASS="it's")
        assert f"ALTER ROLE \"{ROLE}\" PASSWORD 'it''s';" in run.exec_log

    @pytest.mark.parametrize(
        "setting",
        [
            # The scram pg_hba rule cannot check a password stored as md5
            "SET password_encryption = 'scram-sha-256';",
            # The escaping doubles quotes only: a backslash must stay literal
            "SET standard_conforming_strings = on;",
        ],
    )
    def test_the_password_statement_pins_its_session_settings(
        self, tmp_path: Path, setting: str
    ) -> None:
        log = _up(tmp_path, "single", _APPINFRA_PG_PASS="pw").exec_log
        assert setting in log
        assert log.index(setting) < log.index("ALTER ROLE")

    def test_up_without_password_clears_it(self, tmp_path: Path) -> None:
        run = _up(tmp_path, "single")
        assert f'ALTER ROLE "{ROLE}" PASSWORD NULL;' in run.exec_log

    def test_the_password_is_not_on_a_command_line(self, tmp_path: Path) -> None:
        run = _up(tmp_path, "single", _APPINFRA_PG_PASS="s3cret")
        command_lines = [
            line for line in run.exec_log.splitlines() if line.startswith("exec ")
        ]
        assert not any("s3cret" in line for line in command_lines)

    def test_no_wait_with_a_password_says_when_it_applies(self, tmp_path: Path) -> None:
        run = _up(tmp_path, "single", _APPINFRA_PG_PASS="pw", _APPINFRA_PG_WAIT="0")
        output = run.result.stdout + run.result.stderr
        assert "applied once the server is ready" in output
        assert "pg.server.wait.up" in output

    @pytest.mark.parametrize(
        "env",
        [{"_APPINFRA_PG_WAIT": "0"}, {"_APPINFRA_PG_PASS": "pw"}],
        ids=["no-wait-without-password", "wait-with-password"],
    )
    def test_no_password_note_otherwise(
        self, tmp_path: Path, env: dict[str, str]
    ) -> None:
        run = _up(tmp_path, "single", **env)
        assert "applied once the server is ready" not in (
            run.result.stdout + run.result.stderr
        )

    def test_no_wait_leaves_the_password_to_wait_up(self, tmp_path: Path) -> None:
        run = _up(tmp_path, "single", _APPINFRA_PG_PASS="pw", _APPINFRA_PG_WAIT="0")
        assert "ALTER ROLE" not in run.exec_log
        waited = run_pg_sh(tmp_path, "wait-up", env={"_APPINFRA_PG_PASS": "pw"})
        assert waited.result.returncode == 0, waited.result.stderr
        assert f"ALTER ROLE \"{ROLE}\" PASSWORD 'pw';" in waited.exec_log


class TestReboot:
    """A reboot starts the server again with the current config, so it warns as up does."""

    _RUNNING = {"single": CONTAINER, "repl": f"{CONTAINER}-primary {CONTAINER}-standby"}

    def _reboot(self, tmp_path: Path, mode: str, **env: str) -> str:
        run = run_pg_sh(
            tmp_path, "reboot", env={"PG_STUB_RUNNING": self._RUNNING[mode], **env}
        )
        assert run.result.returncode == 0, run.result.stderr
        assert run.compose_args, "reboot started nothing"
        return run.result.stdout + run.result.stderr

    @pytest.mark.parametrize("mode", MODES)
    def test_lan_bind_without_password_warns(self, tmp_path: Path, mode: str) -> None:
        output = self._reboot(tmp_path, mode, _APPINFRA_PG_BIND="0.0.0.0")
        assert "without a password" in output

    def test_no_wait_with_a_password_says_when_it_applies(self, tmp_path: Path) -> None:
        output = self._reboot(
            tmp_path, "single", _APPINFRA_PG_PASS="pw", _APPINFRA_PG_WAIT="0"
        )
        assert "applied once the server is ready" in output

    def test_loopback_reboot_warns_nothing(self, tmp_path: Path) -> None:
        output = self._reboot(tmp_path, "single")
        assert "without a password" not in output
        assert "applied once the server is ready" not in output


@pytest.mark.parametrize(
    ("env", "needs"),
    [
        ({"_APPINFRA_PG_REPLICA_ENABLED": "false"}, "pgserver.replica.enabled: true"),
        ({"_APPINFRA_PG_PORT_R": ""}, "pgserver.replica.port"),
    ],
    ids=["disabled", "no-port"],
)
def test_repl_up_names_the_missing_replica_setting(
    tmp_path: Path, env: dict[str, str], needs: str
) -> None:
    run = run_pg_sh(tmp_path, "up", env={"_APPINFRA_PG_MODE": "repl", **env})
    assert run.result.returncode == 2
    assert needs in run.result.stderr
    assert run.compose_args == []


def test_client_commands_use_the_password(tmp_path: Path) -> None:
    run = run_pg_sh(tmp_path, "info", "--short", env={"_APPINFRA_PG_PASS": "pw"})
    assert run.psql_log and all(
        line == "PGPASSWORD=pw" for line in run.psql_log.splitlines()
    )
