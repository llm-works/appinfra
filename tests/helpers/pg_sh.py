# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Run appinfra/scripts/pg.sh against a stub container runtime and compose command.

The stubs record what pg.sh asks of them instead of starting containers: the
compose command keeps its arguments and the ``_APPINFRA_PG_*`` variables it was
started with, the runtime keeps every ``exec`` with the SQL sent on stdin.
``compose_file`` then reads the compose file pg.sh chose with those variables
substituted, as compose would.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
PG_SH = REPO_ROOT / "appinfra" / "scripts" / "pg.sh"

# Stub inputs: no container starts and no image is pulled, so these track no
# pgserver config. They differ from every default (port 5432, role postgres) so
# a value pg.sh hardcodes instead of taking from its input shows up.
CONTAINER = "stub-pg"
IMAGE = "stub/postgres:test"
VERSION = "stub"
PORT = "40101"
PORT_R = "40102"
ROLE = "app_owner"

# Answers `ps` with the containers named in PG_STUB_RUNNING (none by default),
# then PG_STUB_OTHERS more names, as on a host running other containers; and
# every `exec` (the readiness probe and the password statement) with success.
# Records each exec and its stdin.
_RUNTIME = """#!/usr/bin/env bash
case "$1" in
  ps)
    for name in ${PG_STUB_RUNNING:-}; do printf '%s\\n' "$name"; done
    for i in $(seq 1 "${PG_STUB_OTHERS:-0}"); do printf 'other-container-%s\\n' "$i"; done
    exit 0 ;;
  exec)
    shift
    if [ "$1" = "-i" ]; then
      printf 'exec %s\\n' "$*" >> "$PG_STUB_DIR/exec.log"
      cat >> "$PG_STUB_DIR/exec.log"
      printf '\\n' >> "$PG_STUB_DIR/exec.log"
    else
      printf 'exec %s\\n' "$*" >> "$PG_STUB_DIR/exec.log"
    fi
    exit 0 ;;
  *) exit 0 ;;
esac
"""

# Stands in for the host's psql (info, clean, psql): records the password it was
# given and reports the server as down, so no test reaches a real server.
_PSQL = """#!/usr/bin/env bash
printf 'PGPASSWORD=%s\\n' "${PGPASSWORD-<unset>}" >> "$PG_STUB_DIR/psql.log"
exit 2
"""

# Records its arguments and the wire variables of each call that starts services.
_COMPOSE = """#!/usr/bin/env bash
for arg in "$@"; do
  if [ "$arg" = "up" ]; then
    printf '%s\\n' "$@" > "$PG_STUB_DIR/compose.args"
    env | grep '^_APPINFRA_PG_' > "$PG_STUB_DIR/compose.env" || true
  fi
done
exit 0
"""

_VAR = re.compile(r"\$\{(\w+)(?::([?-])([^}]*))?\}|\$(\w+)")


@dataclass
class PgShRun:
    """What one pg.sh call did: its output and what the stubs recorded."""

    result: subprocess.CompletedProcess[str]
    stub_dir: Path
    cwd: Path
    compose_args: list[str] = field(default_factory=list)
    compose_env: dict[str, str] = field(default_factory=dict)

    @property
    def exec_log(self) -> str:
        """Every exec into a container, with the SQL sent on stdin."""
        path = self.stub_dir / "exec.log"
        return path.read_text() if path.exists() else ""

    @property
    def psql_log(self) -> str:
        """The password each run of the host's psql was given."""
        path = self.stub_dir / "psql.log"
        return path.read_text() if path.exists() else ""

    def compose_file(self) -> dict[str, Any]:
        """The compose file pg.sh chose, with its variables substituted."""
        path = Path(self.compose_args[self.compose_args.index("-f") + 1])
        env = {**self.compose_env, "PWD": str(self.cwd)}
        return _substitute(yaml.safe_load(path.read_text()), env)


def _substitute(node: Any, env: dict[str, str]) -> Any:
    """Substitute ${VAR}, ${VAR:-default}, ${VAR:?} and $VAR in every string."""
    if isinstance(node, dict):
        return {k: _substitute(v, env) for k, v in node.items()}
    if isinstance(node, list):
        return [_substitute(v, env) for v in node]
    if not isinstance(node, str):
        return node

    def value(m: re.Match[str]) -> str:
        name = m.group(1) or m.group(4)
        if m.group(2) == "-":
            return env.get(name) or m.group(3)
        if m.group(2) == "?" and not env.get(name):
            raise KeyError(f"compose requires {name}")
        return env.get(name, "")

    return _VAR.sub(value, node.replace("$$", "\0")).replace("\0", "$")


def run_pg_sh(
    tmp_path: Path, verb: str, *args: str, env: dict[str, str] | None = None
) -> PgShRun:
    """Run `pg.sh <verb>` from a project directory under tmp_path."""
    stub_dir = tmp_path / "stubs"
    stub_dir.mkdir(exist_ok=True)
    for name, body in (("runtime", _RUNTIME), ("compose", _COMPOSE), ("psql", _PSQL)):
        script = stub_dir / name
        script.write_text(body)
        script.chmod(0o755)
    cwd = tmp_path / "project"
    cwd.mkdir(exist_ok=True)
    full_env = {
        "PATH": f"{stub_dir}{os.pathsep}{os.environ['PATH']}",
        "HOME": str(tmp_path),
        "PG_STUB_DIR": str(stub_dir),
        "APPINFRA_CONTAINER_CMD": str(stub_dir / "runtime"),
        "APPINFRA_COMPOSE_CMD": str(stub_dir / "compose"),
        "_APPINFRA_PG_CONTAINER_NAME": CONTAINER,
        "_APPINFRA_PG_IMAGE": IMAGE,
        "_APPINFRA_PG_VERSION": VERSION,
        "_APPINFRA_PG_PORT": PORT,
        "_APPINFRA_PG_PORT_R": PORT_R,
        "_APPINFRA_PG_REPLICA_ENABLED": "true",
        "_APPINFRA_PG_USER": ROLE,
        "_APPINFRA_PG_HOST": "127.0.0.1",
        **(env or {}),
    }
    result = subprocess.run(
        ["bash", str(PG_SH), verb, *args],
        cwd=cwd,
        env=full_env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    run = PgShRun(result=result, stub_dir=stub_dir, cwd=cwd)
    if (stub_dir / "compose.args").exists():
        run.compose_args = (stub_dir / "compose.args").read_text().splitlines()
        run.compose_env = dict(
            line.split("=", 1)
            for line in (stub_dir / "compose.env").read_text().splitlines()
        )
    return run
