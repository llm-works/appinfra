"""Tests for appinfra/scripts/pg-config.sh."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PG_CONFIG_SH = REPO_ROOT / "appinfra" / "scripts" / "pg-config.sh"


def _run(tmp_path: Path, yaml_body: str, *, key: str = "pgserver") -> dict[str, str]:
    cfg = tmp_path / "etc.yaml"
    cfg.write_text(yaml_body)
    result = subprocess.run(
        ["bash", str(PG_CONFIG_SH), cfg.name, key, str(tmp_path), ""],
        capture_output=True,
        text=True,
        check=True,
    )
    out: dict[str, str] = {}
    for entry in result.stdout.strip().split("|"):
        name, _, value = entry.partition(":=")
        out[name] = value
    return out


def _run_expect_failure(
    tmp_path: Path, yaml_body: str, *, key: str = "pgserver"
) -> subprocess.CompletedProcess[str]:
    cfg = tmp_path / "etc.yaml"
    cfg.write_text(yaml_body)
    return subprocess.run(
        ["bash", str(PG_CONFIG_SH), cfg.name, key, str(tmp_path), ""],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.unit
class TestPgConfigSh:
    """YAML → Make variable rendering."""

    def test_missing_file_emits_defaults(self, tmp_path: Path) -> None:
        result = subprocess.run(
            ["bash", str(PG_CONFIG_SH), "missing.yaml", "pgserver", str(tmp_path), ""],
            capture_output=True,
            text=True,
            check=True,
        )
        vars_ = dict(
            entry.partition(":=")[::2] for entry in result.stdout.strip().split("|")
        )
        assert vars_["PG_CONTAINER_NAME"] == ""
        assert vars_["PG_REPLICA_ENABLED"] == "false"
        assert vars_["PG_MAX_CONNECTIONS"] == ""
        assert vars_["PG_AUTOVACUUM"] == ""

    def test_identity_and_replica_fields(self, tmp_path: Path) -> None:
        vars_ = _run(
            tmp_path,
            'pgserver:\n  name: pg\n  version: "16"\n  port: 5432\n'
            "  image: pgvector/pgvector:pg16\n"
            "  replica:\n    enabled: true\n    port: 5433\n",
        )
        assert vars_["PG_CONTAINER_NAME"] == "pg"
        assert vars_["PG_VERSION"] == "16"
        assert vars_["PG_PORT"] == "5432"
        assert vars_["PG_IMAGE"] == "pgvector/pgvector:pg16"
        assert vars_["PG_REPLICA_ENABLED"] == "true"
        assert vars_["PG_PORT_R"] == "5433"

    def test_empty_postgres_conf_emits_empty_knobs(self, tmp_path: Path) -> None:
        vars_ = _run(tmp_path, "pgserver:\n  name: pg\n  port: 5432\n")
        # Empty knob values let the YAML's ${PG_X:-key=default} slot fall back
        # to the postgres-default value at container start.
        for name in (
            "PG_MAX_CONNECTIONS",
            "PG_SHARED_PRELOAD_LIBRARIES",
            "PG_WORK_MEM",
            "PG_AUTOVACUUM",
        ):
            assert vars_[name] == ""

    def test_max_connections(self, tmp_path: Path) -> None:
        vars_ = _run(
            tmp_path,
            "pgserver:\n  postgres_conf:\n    max_connections: 256\n",
        )
        assert vars_["PG_MAX_CONNECTIONS"] == "max_connections=256"

    def test_autovacuum_bool(self, tmp_path: Path) -> None:
        vars_ = _run(
            tmp_path,
            "pgserver:\n  postgres_conf:\n    autovacuum: false\n",
        )
        assert vars_["PG_AUTOVACUUM"] == "autovacuum=off"

    def test_shared_preload_libraries_list(self, tmp_path: Path) -> None:
        vars_ = _run(
            tmp_path,
            "pgserver:\n  postgres_conf:\n    shared_preload_libraries:\n"
            "      - pg_stat_statements\n      - timescaledb\n",
        )
        assert (
            vars_["PG_SHARED_PRELOAD_LIBRARIES"]
            == "shared_preload_libraries=pg_stat_statements,timescaledb"
        )

    def test_work_mem_string(self, tmp_path: Path) -> None:
        vars_ = _run(
            tmp_path,
            'pgserver:\n  postgres_conf:\n    work_mem: "256MB"\n',
        )
        assert vars_["PG_WORK_MEM"] == "work_mem=256MB"

    def test_unknown_key_errors_with_supported_list(self, tmp_path: Path) -> None:
        result = _run_expect_failure(
            tmp_path,
            "pgserver:\n  postgres_conf:\n    fsync: false\n    archive_command: foo\n",
        )
        assert result.returncode != 0
        assert "unsupported key(s)" in result.stderr
        assert "fsync" in result.stderr
        assert "archive_command" in result.stderr
        # Error message includes the supported set so the user knows the contract.
        assert "max_connections" in result.stderr
        assert "shared_preload_libraries" in result.stderr
