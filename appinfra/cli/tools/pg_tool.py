# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
PostgreSQL lifecycle commands.

Parent tool `pg` with per-verb sub-tools. Each sub-tool projects the
resolved YAML config (``pgserver.*`` / ``dbs.*``) into the ``_INFRA_PG_*``
wire protocol and execs ``appinfra/scripts/pg.sh <verb>``. Location of
pg.sh is resolved from ``appinfra.__file__`` so wheel installs work
without a repo checkout.

The projection matches ``appinfra/scripts/pg-config.sh`` exactly (same
whitelist, same rendering) so ``make pg.server.up`` and ``appinfra pg up``
resolve to identical container state.
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote

import appinfra

from ...app.tools import Tool, ToolConfig
from ...app.tracing.traceable import Traceable

_SUPPORTED_POSTGRES_CONF = {
    "max_connections",
    "shared_preload_libraries",
    "work_mem",
    "autovacuum",
}


def _pg_script_path() -> Path:
    """Resolve pg.sh via the installed package (wheel-install safe)."""
    return Path(appinfra.__file__).parent / "scripts" / "pg.sh"


def _render_conf_value(key: str, value: Any) -> str:
    """Render a postgres_conf value as ``key=value`` for pg.sh env."""
    if isinstance(value, bool):
        return f"{key}=" + ("on" if value else "off")
    if isinstance(value, list):
        return f"{key}=" + ",".join(str(v) for v in value)
    return f"{key}={value}"


def _resolve_image(image: Any, version: Any) -> str:
    """Resolve the container image: explicit ``pgserver.image`` wins, else
    ``docker.io/postgres:<version>``. Fully qualifies the default because
    podman doesn't assume docker.io for bare image names.
    """
    if image:
        return str(image)
    if version != "":
        return f"docker.io/postgres:{version}"
    return ""


def _project_postgres_conf(postgres_conf: Any) -> dict[str, str]:
    """Validate a curated ``postgres_conf`` mapping and render each entry
    as ``KEY: 'key=value'``. Unknown keys and null values hard-fail.
    """
    if not isinstance(postgres_conf, dict):
        raise ValueError(
            f"pgserver.postgres_conf must be a mapping, got {type(postgres_conf).__name__}"
        )
    unknown = sorted(set(postgres_conf) - _SUPPORTED_POSTGRES_CONF)
    if unknown:
        raise ValueError(
            f"pgserver.postgres_conf has unsupported key(s) {unknown}. "
            f"Supported: {sorted(_SUPPORTED_POSTGRES_CONF)}"
        )
    knobs: dict[str, str] = {}
    for k, v in postgres_conf.items():
        if v is None:
            raise ValueError(
                f"pgserver.postgres_conf.{k} is null; provide a value or remove the key"
            )
        knobs[k.upper()] = _render_conf_value(k, v)
    return knobs


def _project_env(cfg: Any) -> dict[str, str]:
    """
    Project resolved YAML config → ``_INFRA_PG_*`` wire-protocol env vars.

    Mirrors ``appinfra/scripts/pg-config.sh`` + ``Makefile.pg`` so the CLI
    path and the Make path produce identical container state. Missing
    optional fields become empty strings (pg.sh treats those as unset).
    """
    version = cfg.get("pgserver.version", "") or ""
    replica_enabled = bool(cfg.get("pgserver.replica.enabled", False))
    resolved_image = _resolve_image(cfg.get("pgserver.image", ""), version)
    knobs = _project_postgres_conf(cfg.get("pgserver.postgres_conf", {}) or {})

    return {
        "_INFRA_PG_CONTAINER_NAME": str(cfg.get("pgserver.name", "") or ""),
        "_INFRA_PG_VERSION": str(version),
        "_INFRA_PG_HOST": str(cfg.get("pgserver.host", "127.0.0.1") or "127.0.0.1"),
        "_INFRA_PG_PORT": str(cfg.get("pgserver.port", "") or ""),
        "_INFRA_PG_PORT_R": str(cfg.get("pgserver.replica.port", "") or ""),
        "_INFRA_PG_USER": str(cfg.get("pgserver.user", "postgres") or "postgres"),
        "_INFRA_PG_REPLICA_ENABLED": "true" if replica_enabled else "false",
        "_INFRA_PG_IMAGE": resolved_image,
        "_INFRA_PG_MAX_CONNECTIONS": knobs.get("MAX_CONNECTIONS", ""),
        "_INFRA_PG_SHARED_PRELOAD_LIBRARIES": knobs.get("SHARED_PRELOAD_LIBRARIES", ""),
        "_INFRA_PG_WORK_MEM": knobs.get("WORK_MEM", ""),
        "_INFRA_PG_AUTOVACUUM": knobs.get("AUTOVACUUM", ""),
    }


def _detect_runtime_env() -> dict[str, str]:
    """
    Auto-detect a container runtime for pg.sh when the caller didn't set one.

    Precedence: honor an explicit ``INFRA_CONTAINER_CMD`` (Makefile.config
    does this); else prefer ``podman`` if on PATH; else ``docker``. Sets
    ``INFRA_COMPOSE_CMD`` to a matching ``<runtime> compose`` when
    unset. Falls through empty if neither is present — pg.sh will then
    report its own missing-runtime error.
    """
    if os.environ.get("INFRA_CONTAINER_CMD"):
        return {}
    for runtime in ("podman", "docker"):
        if shutil.which(runtime):
            env = {"INFRA_CONTAINER_CMD": runtime}
            if not os.environ.get("INFRA_COMPOSE_CMD"):
                env["INFRA_COMPOSE_CMD"] = f"{runtime} compose"
            return env
    return {}


def _exec_pg(
    cfg: Any,
    verb: str,
    extra_args: list[str] | None = None,
    extra_env: dict[str, str] | None = None,
) -> int:
    """Project env + exec pg.sh <verb>. Returns exit code."""
    env = {**os.environ, **_detect_runtime_env(), **_project_env(cfg)}
    if extra_env:
        env.update(extra_env)
    cmd = [str(_pg_script_path()), verb, *(extra_args or [])]
    return subprocess.call(cmd, env=env)


class _PgVerbTool(Tool):
    """Base for pg sub-tools that project env and exec a pg.sh verb."""

    VERB: str = ""
    NAME: str = ""
    HELP: str = ""
    ALIASES: list[str] = []

    def __init__(self, parent: Traceable | None = None):
        config = ToolConfig(
            name=self.NAME,
            aliases=list(self.ALIASES),
            help_text=self.HELP,
            description=self.HELP,
        )
        super().__init__(parent, config)

    def _extra_args(self) -> list[str]:
        """Extra positional args to append after the verb. Overridable."""
        return []

    def _extra_env(self) -> dict[str, str]:
        """Extra env vars specific to this verb (added on top of _project_env). Overridable."""
        return {}

    def run(self, **kwargs: Any) -> int:
        """Project env + exec pg.sh <verb>."""
        return _exec_pg(
            self.app.config,
            self.VERB,
            extra_args=self._extra_args(),
            extra_env=self._extra_env(),
        )


class PgUpTool(_PgVerbTool):
    """Start the postgres server (single or replication mode)."""

    VERB = "up"
    NAME = "up"
    HELP = "Start postgres server (single mode by default; --repl for primary+standby)"

    def add_args(self, parser: argparse.ArgumentParser) -> None:
        """Add --repl, --no-wait, and --timeout flags."""
        parser.add_argument(
            "--repl",
            action="store_true",
            help="Start in replication mode (primary + standby)",
        )
        parser.add_argument(
            "--no-wait",
            action="store_true",
            help="Skip readiness wait after start",
        )
        parser.add_argument(
            "--timeout",
            type=int,
            metavar="SECS",
            help="Readiness wait timeout in seconds (default: 30)",
        )

    def _extra_env(self) -> dict[str, str]:
        """Set _INFRA_PG_MODE, _INFRA_PG_WAIT, and _INFRA_PG_WAIT_TIMEOUT from flags."""
        env = {
            "_INFRA_PG_MODE": "repl" if self.args.repl else "single",
            "_INFRA_PG_WAIT": "0" if self.args.no_wait else "1",
        }
        if self.args.timeout is not None:
            env["_INFRA_PG_WAIT_TIMEOUT"] = str(self.args.timeout)
        return env


class PgDownTool(_PgVerbTool):
    """Stop the postgres server."""

    VERB = "down"
    NAME = "down"
    HELP = "Stop postgres server (auto-detects mode)"

    def add_args(self, parser: argparse.ArgumentParser) -> None:
        """Add --no-wait and --timeout flags."""
        parser.add_argument(
            "--no-wait",
            action="store_true",
            help="Skip teardown-verification wait",
        )
        parser.add_argument(
            "--timeout",
            type=int,
            metavar="SECS",
            help="Teardown wait timeout in seconds (default: 30)",
        )

    def _extra_env(self) -> dict[str, str]:
        """Set _INFRA_PG_WAIT and _INFRA_PG_WAIT_TIMEOUT from flags."""
        env = {"_INFRA_PG_WAIT": "0" if self.args.no_wait else "1"}
        if self.args.timeout is not None:
            env["_INFRA_PG_WAIT_TIMEOUT"] = str(self.args.timeout)
        return env


class PgRebootTool(_PgVerbTool):
    """Restart the postgres server."""

    VERB = "reboot"
    NAME = "reboot"
    HELP = "Restart postgres server (auto-detects mode)"

    def add_args(self, parser: argparse.ArgumentParser) -> None:
        """Add --no-wait and --timeout flags."""
        parser.add_argument(
            "--no-wait",
            action="store_true",
            help="Skip readiness wait after restart",
        )
        parser.add_argument(
            "--timeout",
            type=int,
            metavar="SECS",
            help="Readiness wait timeout in seconds (default: 30)",
        )

    def _extra_env(self) -> dict[str, str]:
        """Set _INFRA_PG_WAIT and _INFRA_PG_WAIT_TIMEOUT from flags."""
        env = {"_INFRA_PG_WAIT": "0" if self.args.no_wait else "1"}
        if self.args.timeout is not None:
            env["_INFRA_PG_WAIT_TIMEOUT"] = str(self.args.timeout)
        return env


class PgLogsTool(_PgVerbTool):
    """Tail postgres server logs."""

    VERB = "logs"
    NAME = "logs"
    HELP = "Tail postgres server logs (auto-detects mode)"


class PgInfoTool(_PgVerbTool):
    """Comprehensive server + database status report."""

    VERB = "info"
    NAME = "info"
    HELP = "Comprehensive server + database status (use --short for one-line summary)"

    def add_args(self, parser: argparse.ArgumentParser) -> None:
        """Add --short flag."""
        parser.add_argument(
            "--short",
            action="store_true",
            help="One-line summary instead of full report",
        )

    def _extra_args(self) -> list[str]:
        """Pass --short to pg.sh info when set."""
        return ["--short"] if self.args.short else []


class PgStatusTool(_PgVerbTool):
    """One-line server status. Alias for `pg info --short`."""

    VERB = "info"
    NAME = "status"
    HELP = "One-line server status summary (alias for `info --short`)"

    def _extra_args(self) -> list[str]:
        """Always pass --short to pg.sh info."""
        return ["--short"]


class PgCleanTool(_PgVerbTool):
    """Drop the databases named by --db (server keeps running)."""

    VERB = "clean"
    NAME = "clean"
    HELP = "Drop the databases named by --db (server keeps running)"

    def add_args(self, parser: argparse.ArgumentParser) -> None:
        """Add repeatable --db flag."""
        parser.add_argument(
            "--db",
            action="append",
            default=[],
            metavar="NAME",
            help="Database to drop (repeatable). Required for `clean`.",
        )

    def _extra_env(self) -> dict[str, str]:
        """Project --db list into the _INFRA_PG_DATABASES allowlist."""
        return {"_INFRA_PG_DATABASES": " ".join(self.args.db)}


# Exact resource names touched by `pg erase` for a given pgserver.name.
# Enumerated (not substring-matched) so unrelated resources with a shared
# prefix — a hypothetical `${name}-backup` volume, say — can't be caught up.
_ERASE_CONTAINER_SUFFIXES = ("", "-primary", "-standby")
_ERASE_VOLUME_SUFFIXES = ("_pgdata", "_pgdata_primary", "_pgdata_standby")
_ERASE_NETWORK_SUFFIXES = ("_default",)


def _resolve_preview_runtime() -> str | None:
    """Runtime binary to use for the pre-erase inventory query. None means
    the check is skipped and pg.sh's own runtime pre-flight will fire."""
    explicit = os.environ.get("INFRA_CONTAINER_CMD", "").strip()
    if explicit:
        return explicit if shutil.which(explicit) else None
    for r in ("podman", "docker"):
        if shutil.which(r):
            return r
    return None


def _run_query(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    """Read-only runtime query with a short timeout; failures are treated
    as 'resource not present' rather than propagated."""
    return subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=5)


def _container_status(runtime: str, name: str) -> str | None:
    """Container status line if the container exists (any state), else None.
    Uses regex-anchored name filter so `${name}-primary` doesn't spuriously
    match a query for `${name}`."""
    try:
        out = _run_query(
            [
                runtime,
                "ps",
                "-a",
                "--filter",
                f"name=^{name}$",
                "--format",
                "{{.Status}}",
            ]
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    line = out.stdout.strip().splitlines()
    return line[0] if line else None


def _resource_exists(runtime: str, kind: str, name: str) -> bool:
    """True iff `runtime <kind> inspect <name>` returns 0. Portable across
    podman and docker (both use exit code 0/1 for present/absent)."""
    try:
        r = _run_query([runtime, kind, "inspect", name])
    except (OSError, subprocess.TimeoutExpired):
        return False
    return r.returncode == 0


def _gather_erase_targets(
    runtime: str, name: str
) -> tuple[list[str], list[str], list[str]]:
    """Read-only inventory of what erase would touch for this instance.
    Split from rendering so the caller can short-circuit when everything
    is missing (no point prompting for a no-op)."""
    containers = [
        f"{name}{s} ({status})"
        for s in _ERASE_CONTAINER_SUFFIXES
        if (status := _container_status(runtime, f"{name}{s}")) is not None
    ]
    volumes = [
        f"{name}{s}"
        for s in _ERASE_VOLUME_SUFFIXES
        if _resource_exists(runtime, "volume", f"{name}{s}")
    ]
    networks = [
        f"{name}{s}"
        for s in _ERASE_NETWORK_SUFFIXES
        if _resource_exists(runtime, "network", f"{name}{s}")
    ]
    return containers, volumes, networks


def _render_erase_preview(
    name: str,
    image: str,
    config_src: str,
    containers: list[str],
    volumes: list[str],
    networks: list[str],
) -> str:
    """Preview shown before the confirm prompt. Split into two visually
    distinct sections so the boundary between what erase touches and what
    it doesn't is unambiguous — the images line under the same column as
    containers/volumes/networks previously read as 'also affected'."""
    lines: list[str] = [
        f"\nAbout to erase pgserver instance '{name}':\n",
        f"  config:  {config_src or '(not tracked)'}",
        "",
        "Will be removed:",
    ]
    _append_group(lines, "containers:", containers)
    _append_group(lines, "volumes:   ", volumes)
    _append_group(lines, "networks:  ", networks)
    lines.append("")
    lines.append("Left in place (out of scope — see post-erase note):")
    lines.append(f"  image:       {image or '(none configured)'}")
    lines.append("")
    return "\n".join(lines)


def _append_group(lines: list[str], label: str, items: list[str]) -> None:
    """Render a label + wrapped list under a section heading; items are
    indented twice (heading level + list level) to sit visually inside
    their section."""
    pad = " " * (len("    " + label) + 1)
    if not items:
        lines.append(f"    {label} (none)")
        return
    lines.append(f"    {label} {items[0]}")
    for extra in items[1:]:
        lines.append(f"{pad}{extra}")


def _prompt_erase_confirm() -> int | None:
    """Interactive typed-confirmation prompt after the preview prints.
    Returns None on typed 'erase' (caller proceeds), or an int exit code
    when the request is fully resolved here — 2 on non-tty (destructive
    verb; needs interactive intent or explicit --yes), 1 on abort/wrong
    input."""
    if not sys.stdin.isatty():
        print(
            "appinfra pg erase: refusing without --yes on non-tty "
            "(destructive; needs interactive confirmation or explicit --yes)",
            file=sys.stderr,
        )
        return 2
    try:
        resp = input("Type 'erase' to confirm: ")
    except (EOFError, KeyboardInterrupt):
        print("\naborted", file=sys.stderr)
        return 1
    if resp.strip() != "erase":
        print("aborted", file=sys.stderr)
        return 1
    return None


def _config_source_path(app: Any) -> str:
    """Best-effort resolved-config path for the preview. Not fatal if
    unavailable — the app may have been built without a config spec.
    Entries are (etc_dir, filename, full_path) tuples; take the full path."""
    paths = getattr(app, "loaded_config_paths", [])
    if not paths:
        return ""
    last = paths[-1]
    if isinstance(last, tuple) and len(last) >= 3:
        return str(last[2])
    return str(last)


class PgEraseTool(_PgVerbTool):
    """Remove this instance's containers, volumes, networks (destructive)."""

    VERB = "erase"
    NAME = "erase"
    HELP = (
        "Remove this instance's containers, volumes, networks "
        "(destructive; images untouched)"
    )

    def add_args(self, parser: argparse.ArgumentParser) -> None:
        """Add --yes to bypass the interactive confirmation. No short alias:
        erase is destructive enough that the caller should type the flag
        out — a bare `-y` is too casual for the blast radius."""
        parser.add_argument(
            "--yes",
            action="store_true",
            help="Skip the interactive confirmation (for scripting)",
        )

    def run(self, **kwargs: Any) -> int:
        """Preview + confirm, then delegate to pg.sh erase."""
        cfg = self.app.config
        name = str(cfg.get("pgserver.name", "") or "")
        if not name:
            print(
                "appinfra pg erase: pgserver.name is empty in resolved config",
                file=sys.stderr,
            )
            return 2

        if self.args.yes:
            return _exec_pg(cfg, self.VERB)

        gate = self._interactive_gate(cfg, name)
        if gate is not None:
            return gate
        return _exec_pg(cfg, self.VERB)

    def _interactive_gate(self, cfg: Any, name: str) -> int | None:
        """Render the preview and prompt. Return None to signal 'proceed
        with erase', or an int exit code to signal the request is fully
        resolved here (no-op, non-tty refusal, aborted confirm). No
        runtime → return None so pg.sh's own pre-flight fires and reports."""
        runtime = _resolve_preview_runtime()
        if runtime is None:
            return None
        containers, volumes, networks = _gather_erase_targets(runtime, name)
        if not (containers or volumes or networks):
            print(
                f"\nNothing to erase — pgserver instance '{name}' has no "
                f"containers, volumes, or networks on {runtime}."
            )
            return 0
        image = _resolve_image(
            cfg.get("pgserver.image", ""),
            cfg.get("pgserver.version", "") or "",
        )
        print(
            _render_erase_preview(
                name,
                image,
                _config_source_path(self.app),
                containers,
                volumes,
                networks,
            )
        )
        return _prompt_erase_confirm()


class PgPsqlTool(_PgVerbTool):
    """Interactive psql shell against the primary or standby server."""

    VERB = "psql"
    NAME = "psql"
    ALIASES = ["shell"]
    HELP = "Interactive psql shell (--target primary|standby; default primary)"

    def add_args(self, parser: argparse.ArgumentParser) -> None:
        """Add --target primary|standby."""
        parser.add_argument(
            "--target",
            choices=["primary", "standby"],
            default="primary",
            help="Which server to connect to (default: primary; standby is read-only)",
        )

    def _extra_args(self) -> list[str]:
        """Pass --target through to pg.sh psql."""
        return ["--target", self.args.target]


class PgTopTool(_PgVerbTool):
    """pg_top process/query monitor for the primary server."""

    VERB = "top"
    NAME = "top"
    HELP = "pg_top for the primary server"


class PgUrlTool(Tool):
    """Print a postgres connection URL derived from config."""

    def __init__(self, parent: Traceable | None = None):
        config = ToolConfig(
            name="url",
            help_text="Print postgres connection URL from config",
            description=(
                "Print a postgresql:// URL. With --db NAME, prints the resolved "
                "URL for that entry under `dbs.<name>`; otherwise prints the "
                "server-level URL (postgresql://<user>@<host>:<port>). Use "
                "--target standby to select the replica port."
            ),
        )
        super().__init__(parent, config)

    def add_args(self, parser: argparse.ArgumentParser) -> None:
        """Add --db NAME and --target primary|standby flags."""
        parser.add_argument(
            "--db",
            metavar="NAME",
            help="Name of a `dbs.<name>` entry — prints its resolved url",
        )
        parser.add_argument(
            "--target",
            choices=["primary", "standby"],
            default="primary",
            help="Which server port to use (default: primary)",
        )

    def run(self, **kwargs: Any) -> int:
        """Print the resolved URL for --db, or the server-level URL."""
        cfg = self.app.config

        if self.args.db:
            url = cfg.get(f"dbs.{self.args.db}.url")
            if not url:
                self.lg.error(  # type: ignore[union-attr]
                    "no dbs entry found", extra={"name": self.args.db}
                )
                return 1
            print(url)
            return 0

        host = cfg.get("pgserver.host", "127.0.0.1") or "127.0.0.1"
        user = cfg.get("pgserver.user", "postgres") or "postgres"
        if self.args.target == "standby":
            port = cfg.get("pgserver.replica.port")
            if not port:
                self.lg.error("pgserver.replica.port not set")  # type: ignore[union-attr]
                return 1
        else:
            port = cfg.get("pgserver.port")
            if not port:
                self.lg.error("pgserver.port not set")  # type: ignore[union-attr]
                return 1
        url_host = f"[{host}]" if ":" in host and not host.startswith("[") else host
        print(f"postgresql://{quote(str(user), safe='')}@{url_host}:{port}")
        return 0


class PgTool(Tool):
    """
    Parent tool for postgres lifecycle commands.

    Grouping-only; requires an explicit subcommand. Each subcommand reads
    the resolved YAML config and execs ``appinfra/scripts/pg.sh`` under the
    ``_INFRA_PG_*`` wire protocol.
    """

    def __init__(self, parent: Traceable | None = None):
        config = ToolConfig(
            name="pg",
            help_text="PostgreSQL lifecycle commands",
            description=(
                "Manage the local PostgreSQL container. Same substrate as "
                "`make pg.server.*` — wraps appinfra/scripts/pg.sh so wheel "
                "installers get the same lifecycle without a repo clone. "
                "Config comes from the resolved YAML (--etc-dir / --config / "
                "XDG / packaged base)."
            ),
        )
        super().__init__(parent, config)

        # `status` registered first so it becomes the group default —
        # bare `appinfra pg` runs it instead of printing help.
        self.add_tool(PgStatusTool(self), default="status")
        self.add_tool(PgUpTool(self))
        self.add_tool(PgDownTool(self))
        self.add_tool(PgRebootTool(self))
        self.add_tool(PgLogsTool(self))
        self.add_tool(PgInfoTool(self))
        self.add_tool(PgUrlTool(self))
        self.add_tool(PgCleanTool(self))
        self.add_tool(PgEraseTool(self))
        self.add_tool(PgPsqlTool(self))
        self.add_tool(PgTopTool(self))

    def run(self, **kwargs: Any) -> int:
        """Dispatch to the selected sub-tool (defaults to `status`)."""
        return self.group.run(**kwargs)
