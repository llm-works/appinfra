# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

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
import sys
from pathlib import Path
from typing import TypedDict
from urllib.parse import urlparse

import pytest

from appinfra.config import Config

PG_SKIP_REASON = "pg-unavailable"
REQUIRE_PG_MARKER = "require_pg"

# Default endpoint used when neither etc/pg.yaml nor INFRA_PGSERVER_* env vars
# are present. Matches the canonical port in etc/pg.yaml so a fresh checkout
# probes the right place. Kept in one spot so the two values can't drift.
DEFAULT_PG_HOST = "127.0.0.1"
DEFAULT_PG_PORT = 7432


class PgStatus(TypedDict):
    host: str
    port: int
    available: bool


# Stash key populated by conftest.pytest_configure (host, port, available)
# and consumed by the pg_available fixture in tests/fixtures/pg_integration.py.
PG_STATUS_KEY: pytest.StashKey[PgStatus] = pytest.StashKey()


def probe(host: str, port: int, timeout: float = 2.0) -> bool:
    """TCP-only liveness probe — does not authenticate, just confirms port is open.

    Default timeout is generous on purpose: a reachable host accepts a TCP
    connection in single-digit ms, so a higher ceiling costs nothing on the
    happy path but protects against false negatives on loaded CI runners or
    high-latency networks (VPNs).
    """
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def resolve_pgserver_endpoint() -> tuple[str, int]:
    """
    Resolve the PG host:port the test suite will try to connect to.

    Parses `dbs.unittest.url` from etc/infra.yaml so the probe targets the
    exact endpoint the tests will use. This avoids divergence between
    "probe sees pgserver.host=postgres" and "tests connect to a URL that
    still has 127.0.0.1 baked in" if the Config substitution pipeline ever
    drifts again.

    Order:
      1. etc/infra.yaml → parse `dbs.unittest.url` (env overrides applied by
         appinfra.config.Config + appinfra.yaml's env-aware substitution).
      2. INFRA_PGSERVER_HOST / INFRA_PGSERVER_PORT env vars.
      3. Hardcoded defaults (DEFAULT_PG_HOST / DEFAULT_PG_PORT).
    """
    infra_yaml = _find_upwards("etc/infra.yaml")
    if infra_yaml is not None:
        try:
            cfg = Config(str(infra_yaml))
            url = cfg.get("dbs.unittest.url")
            if url:
                parsed = urlparse(str(url))
                if parsed.hostname:
                    return parsed.hostname, (
                        parsed.port if parsed.port is not None else DEFAULT_PG_PORT
                    )
        except Exception as e:
            # infra.yaml exists but couldn't be parsed (malformed YAML, missing
            # dbs.unittest.url, unparseable URL). Surface it so the silent
            # fall-through to env defaults isn't a mystery.
            print(
                f"warning: failed to read {infra_yaml} for PG probe ({e!r}); "
                "falling back to INFRA_PGSERVER_HOST/PORT or defaults",
                file=sys.stderr,
            )

    host = os.environ.get("INFRA_PGSERVER_HOST", DEFAULT_PG_HOST)
    try:
        port = int(os.environ.get("INFRA_PGSERVER_PORT", str(DEFAULT_PG_PORT)))
    except ValueError:
        port = DEFAULT_PG_PORT
    return host, port


def _find_upwards(relpath: str) -> Path | None:
    """Walk up from this file looking for `relpath` (e.g. 'etc/pg.yaml').

    The walk stops at the project root (the directory containing pyproject.toml)
    so a nested-workspace layout cannot resolve to an unrelated ancestor's file.
    """
    here = Path(__file__).resolve()
    for parent in (here, *here.parents):
        candidate = parent / relpath
        if candidate.exists():
            return candidate
        if (parent / "pyproject.toml").exists():
            return None
    return None
