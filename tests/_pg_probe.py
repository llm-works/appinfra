"""
Shared helpers for detecting PG availability at test-session start.

Used by conftest.py and tests/fixtures/pg_integration.py to give every
DB-dependent test a single uniform skip reason when PG is unreachable,
so the end-of-run summary can collapse them into one banner line
instead of hundreds of per-test SKIPPED entries.
"""

import os
import socket
from pathlib import Path

import pytest

PG_SKIP_REASON = "pg-unavailable"
REQUIRE_PG_MARKER = "require_pg"

# Stash key populated by conftest.pytest_configure (host, port, available)
# and consumed by the terminal-summary banner and the pg_available fixture.
PG_STATUS_KEY: pytest.StashKey = pytest.StashKey()


def probe(host: str, port: int, timeout: float = 0.5) -> bool:
    """TCP-only liveness probe — does not authenticate, just confirms port is open."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def resolve_pgserver_endpoint() -> tuple[str, int]:
    """
    Resolve the PG host:port the test suite will try to connect to.

    Order: INFRA_PGSERVER_HOST/PORT env vars → etc/pg.yaml `pgserver` section →
    fallback to 127.0.0.1:5432. Reads pg.yaml directly with PyYAML so this can
    run inside pytest_configure (before the appinfra.config machinery is needed).
    """
    host = os.environ.get("INFRA_PGSERVER_HOST")
    port_env = os.environ.get("INFRA_PGSERVER_PORT")
    if host and port_env:
        return host, int(port_env)

    pg_yaml = _find_upwards("etc/pg.yaml")
    if pg_yaml is not None:
        try:
            import yaml

            with pg_yaml.open() as f:
                data = yaml.safe_load(f) or {}
            pgserver = data.get("pgserver", {}) or {}
            host = host or pgserver.get("host", "127.0.0.1")
            port = int(port_env) if port_env else int(pgserver.get("port", 5432))
            return host, port
        except Exception:
            pass

    return host or "127.0.0.1", int(port_env) if port_env else 5432


def _find_upwards(relpath: str) -> Path | None:
    """Walk up from this file looking for `relpath` (e.g. 'etc/pg.yaml')."""
    here = Path(__file__).resolve()
    for parent in (here, *here.parents):
        candidate = parent / relpath
        if candidate.exists():
            return candidate
    return None
