"""
Shared helpers for detecting PG availability at test-session start.

Used by conftest.py and tests/fixtures/pg_integration.py to skip every
DB-dependent test with the same uniform reason (PG_SKIP_REASON) when PG is
unreachable. check.sh's existing display_skip_summary groups skips by exact
reason string, so a single shared reason collapses all PG skips into one
banner — no Python<->shell coupling is required.
"""

import os
import socket
from pathlib import Path
from typing import TypedDict

import pytest

from appinfra.config import Config

PG_SKIP_REASON = "pg-unavailable"
REQUIRE_PG_MARKER = "require_pg"


class PgStatus(TypedDict):
    host: str
    port: int
    available: bool


# Stash key populated by conftest.pytest_configure (host, port, available)
# and consumed by the pg_available fixture in tests/fixtures/pg_integration.py.
PG_STATUS_KEY: pytest.StashKey[PgStatus] = pytest.StashKey()


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

    Order: etc/pg.yaml `pgserver` section (with INFRA_PGSERVER_HOST/PORT env
    overrides applied by appinfra.config.Config) → env vars only with stdlib
    fallback if pg.yaml is missing.
    """
    pg_yaml = _find_upwards("etc/pg.yaml")
    if pg_yaml is not None:
        try:
            cfg = Config(str(pg_yaml))
            return str(cfg.get("pgserver.host")), int(cfg.get("pgserver.port"))
        except Exception:
            pass

    host = os.environ.get("INFRA_PGSERVER_HOST", "127.0.0.1")
    port = int(os.environ.get("INFRA_PGSERVER_PORT", "7432"))
    return host, port


def _find_upwards(relpath: str) -> Path | None:
    """Walk up from this file looking for `relpath` (e.g. 'etc/pg.yaml')."""
    here = Path(__file__).resolve()
    for parent in (here, *here.parents):
        candidate = parent / relpath
        if candidate.exists():
            return candidate
    return None
