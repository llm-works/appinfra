# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for cli/tools/pg_tool.py.

Covers the YAML → ``_INFRA_PG_*`` wire-protocol projection, per-verb env
and arg mapping, PgUrlTool URL computation, and PgTool subtool
registration.
"""

from argparse import Namespace
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from appinfra.cli.tools.pg_tool import (
    PgCleanTool,
    PgDownTool,
    PgEraseTool,
    PgInfoTool,
    PgLogsTool,
    PgPsqlTool,
    PgRebootTool,
    PgStatusTool,
    PgTool,
    PgTopTool,
    PgUpTool,
    PgUrlTool,
    _detect_runtime_env,
    _exec_pg,
    _pg_script_path,
    _project_env,
    _project_postgres_conf,
    _render_conf_value,
    _resolve_image,
)
from appinfra.dot_dict import DotDict

# =============================================================================
# _render_conf_value — postgres_conf value serialization
# =============================================================================


@pytest.mark.unit
class TestRenderConfValue:
    """Test postgres_conf value rendering."""

    def test_bool_true_renders_on(self):
        assert _render_conf_value("autovacuum", True) == "autovacuum=on"

    def test_bool_false_renders_off(self):
        assert _render_conf_value("autovacuum", False) == "autovacuum=off"

    def test_list_joined_with_commas(self):
        assert (
            _render_conf_value("shared_preload_libraries", ["a", "b"])
            == "shared_preload_libraries=a,b"
        )

    def test_scalar_int(self):
        assert _render_conf_value("max_connections", 500) == "max_connections=500"

    def test_scalar_string(self):
        assert _render_conf_value("work_mem", "16MB") == "work_mem=16MB"


# =============================================================================
# _resolve_image — image / version → resolved image
# =============================================================================


@pytest.mark.unit
class TestResolveImage:
    """Test container image resolution."""

    def test_explicit_image_wins(self):
        assert _resolve_image("pgvector/pgvector:pg18", 17) == "pgvector/pgvector:pg18"

    def test_version_produces_qualified_default(self):
        assert _resolve_image("", 18) == "docker.io/postgres:18"

    def test_empty_when_neither_set(self):
        assert _resolve_image("", "") == ""


# =============================================================================
# _project_postgres_conf — whitelist + rendering
# =============================================================================


@pytest.mark.unit
class TestProjectPostgresConf:
    """Test postgres_conf whitelist and rendering."""

    def test_supported_keys_render(self):
        knobs = _project_postgres_conf(
            {"max_connections": 500, "shared_preload_libraries": ["pg_stat_statements"]}
        )
        assert knobs["MAX_CONNECTIONS"] == "max_connections=500"
        assert knobs["SHARED_PRELOAD_LIBRARIES"] == (
            "shared_preload_libraries=pg_stat_statements"
        )

    def test_unknown_key_raises(self):
        with pytest.raises(ValueError, match="unsupported key"):
            _project_postgres_conf({"nonsense": 1})

    def test_null_value_raises(self):
        with pytest.raises(ValueError, match="null"):
            _project_postgres_conf({"max_connections": None})

    def test_non_dict_raises(self):
        with pytest.raises(ValueError, match="mapping"):
            _project_postgres_conf([1, 2, 3])

    def test_empty_returns_empty(self):
        assert _project_postgres_conf({}) == {}


# =============================================================================
# _project_env — full projection matches Makefile.pg
# =============================================================================


@pytest.mark.unit
class TestProjectEnv:
    """Test config → _INFRA_PG_* env projection."""

    def _cfg(self, **overrides):
        base = {
            "name": "test-pg",
            "version": 18,
            "port": 25432,
            "host": "127.0.0.1",
            "user": "postgres",
            "image": "",
            "replica": {"enabled": False, "port": ""},
            "postgres_conf": {},
        }
        base.update(overrides)
        return DotDict({"pgserver": base})

    def test_minimal_projection(self):
        env = _project_env(self._cfg())
        assert env["_INFRA_PG_CONTAINER_NAME"] == "test-pg"
        assert env["_INFRA_PG_VERSION"] == "18"
        assert env["_INFRA_PG_PORT"] == "25432"
        assert env["_INFRA_PG_HOST"] == "127.0.0.1"
        assert env["_INFRA_PG_USER"] == "postgres"
        assert env["_INFRA_PG_REPLICA_ENABLED"] == "false"
        assert env["_INFRA_PG_IMAGE"] == "docker.io/postgres:18"

    def test_replica_enabled(self):
        env = _project_env(self._cfg(replica={"enabled": True, "port": 25433}))
        assert env["_INFRA_PG_REPLICA_ENABLED"] == "true"
        assert env["_INFRA_PG_PORT_R"] == "25433"

    def test_explicit_image_overrides_version(self):
        env = _project_env(self._cfg(image="pgvector/pgvector:pg18"))
        assert env["_INFRA_PG_IMAGE"] == "pgvector/pgvector:pg18"

    def test_postgres_conf_flows_through(self):
        env = _project_env(
            self._cfg(postgres_conf={"max_connections": 500, "work_mem": "16MB"})
        )
        assert env["_INFRA_PG_MAX_CONNECTIONS"] == "max_connections=500"
        assert env["_INFRA_PG_WORK_MEM"] == "work_mem=16MB"

    def test_host_defaults_when_missing(self):
        cfg = self._cfg()
        del cfg["pgserver"]["host"]
        env = _project_env(cfg)
        assert env["_INFRA_PG_HOST"] == "127.0.0.1"


# =============================================================================
# _pg_script_path & _exec_pg
# =============================================================================


@pytest.mark.unit
class TestExec:
    """Test pg.sh location + exec."""

    def test_pg_script_path_resolves_under_package(self):
        p = _pg_script_path()
        assert p.name == "pg.sh"
        assert p.parent.name == "scripts"
        assert p.exists()

    def test_detect_runtime_honors_explicit_env(self, monkeypatch):
        monkeypatch.setenv("INFRA_CONTAINER_CMD", "docker")
        assert _detect_runtime_env() == {}

    def test_detect_runtime_prefers_podman(self, monkeypatch):
        monkeypatch.delenv("INFRA_CONTAINER_CMD", raising=False)
        monkeypatch.delenv("INFRA_COMPOSE_CMD", raising=False)
        with patch(
            "appinfra.cli.tools.pg_tool.shutil.which",
            side_effect=lambda name: f"/usr/bin/{name}" if name == "podman" else None,
        ):
            env = _detect_runtime_env()
        assert env == {
            "INFRA_CONTAINER_CMD": "podman",
            "INFRA_COMPOSE_CMD": "podman compose",
        }

    def test_detect_runtime_falls_back_to_docker(self, monkeypatch):
        monkeypatch.delenv("INFRA_CONTAINER_CMD", raising=False)
        monkeypatch.delenv("INFRA_COMPOSE_CMD", raising=False)
        with patch(
            "appinfra.cli.tools.pg_tool.shutil.which",
            side_effect=lambda name: f"/usr/bin/{name}" if name == "docker" else None,
        ):
            env = _detect_runtime_env()
        assert env["INFRA_CONTAINER_CMD"] == "docker"
        assert env["INFRA_COMPOSE_CMD"] == "docker compose"

    def test_detect_runtime_empty_when_neither_present(self, monkeypatch):
        monkeypatch.delenv("INFRA_CONTAINER_CMD", raising=False)
        with patch("appinfra.cli.tools.pg_tool.shutil.which", return_value=None):
            assert _detect_runtime_env() == {}

    def test_exec_pg_calls_subprocess_with_env(self):
        cfg = DotDict(
            {
                "pgserver": {
                    "name": "n",
                    "version": 18,
                    "port": 25432,
                    "user": "postgres",
                    "host": "127.0.0.1",
                    "postgres_conf": {},
                }
            }
        )
        with patch("appinfra.cli.tools.pg_tool.subprocess.call") as mock_call:
            mock_call.return_value = 0
            rc = _exec_pg(
                cfg, "up", extra_args=["-x"], extra_env={"_INFRA_PG_MODE": "single"}
            )
        assert rc == 0
        args, kwargs = mock_call.call_args
        cmd = args[0]
        assert cmd[1] == "up"
        assert cmd[2] == "-x"
        env = kwargs["env"]
        assert env["_INFRA_PG_CONTAINER_NAME"] == "n"
        assert env["_INFRA_PG_MODE"] == "single"


# =============================================================================
# Per-verb _extra_env / _extra_args mappings
# =============================================================================


@pytest.mark.unit
class TestVerbTools:
    """Test that each verb tool maps flags to the right env/args."""

    def test_up_default_env(self):
        t = PgUpTool()
        t._parsed_args = Namespace(repl=False, no_wait=False, timeout=None)
        assert t._extra_env() == {"_INFRA_PG_MODE": "single", "_INFRA_PG_WAIT": "1"}

    def test_up_repl_and_no_wait(self):
        t = PgUpTool()
        t._parsed_args = Namespace(repl=True, no_wait=True, timeout=None)
        assert t._extra_env() == {"_INFRA_PG_MODE": "repl", "_INFRA_PG_WAIT": "0"}

    def test_up_with_timeout(self):
        t = PgUpTool()
        t._parsed_args = Namespace(repl=False, no_wait=False, timeout=60)
        env = t._extra_env()
        assert env["_INFRA_PG_WAIT_TIMEOUT"] == "60"

    def test_down_no_wait(self):
        t = PgDownTool()
        t._parsed_args = Namespace(no_wait=True, timeout=None)
        assert t._extra_env() == {"_INFRA_PG_WAIT": "0"}

    def test_down_with_timeout(self):
        t = PgDownTool()
        t._parsed_args = Namespace(no_wait=False, timeout=45)
        env = t._extra_env()
        assert env["_INFRA_PG_WAIT_TIMEOUT"] == "45"

    def test_reboot_wait_default(self):
        t = PgRebootTool()
        t._parsed_args = Namespace(no_wait=False, timeout=None)
        assert t._extra_env() == {"_INFRA_PG_WAIT": "1"}

    def test_reboot_with_timeout(self):
        t = PgRebootTool()
        t._parsed_args = Namespace(no_wait=False, timeout=90)
        env = t._extra_env()
        assert env["_INFRA_PG_WAIT_TIMEOUT"] == "90"

    def test_info_short_flag(self):
        t = PgInfoTool()
        t._parsed_args = Namespace(short=True)
        assert t._extra_args() == ["--short"]

    def test_info_full_when_not_short(self):
        t = PgInfoTool()
        t._parsed_args = Namespace(short=False)
        assert t._extra_args() == []

    def test_status_always_short(self):
        t = PgStatusTool()
        assert t._extra_args() == ["--short"]

    def test_clean_projects_db_list(self):
        t = PgCleanTool()
        t._parsed_args = Namespace(db=["a", "b"])
        assert t._extra_env() == {"_INFRA_PG_DATABASES": "a b"}

    def test_psql_target_primary_by_default(self):
        t = PgPsqlTool()
        t._parsed_args = Namespace(target="primary")
        assert t._extra_args() == ["--target", "primary"]

    def test_psql_target_standby(self):
        t = PgPsqlTool()
        t._parsed_args = Namespace(target="standby")
        assert t._extra_args() == ["--target", "standby"]

    def test_psql_shell_alias(self):
        assert "shell" in PgPsqlTool().config.aliases

    def test_logs_and_top_have_no_flags(self):
        assert PgLogsTool()._extra_args() == []
        assert PgLogsTool()._extra_env() == {}
        assert PgTopTool()._extra_args() == []


# =============================================================================
# PgEraseTool — preview + confirmation gate
# =============================================================================


_ERASE_CFG = DotDict(
    {
        "pgserver": {
            "name": "test-pg",
            "version": 18,
            "port": 25432,
            "user": "postgres",
            "host": "127.0.0.1",
            "image": "docker.io/pgvector/pgvector:pg18",
            "postgres_conf": {},
        }
    }
)


def _erase_tool(yes: bool = False, cfg: DotDict = _ERASE_CFG) -> PgEraseTool:
    """Build a PgEraseTool with faked args + faked app.config."""
    t = PgEraseTool()
    t._parsed_args = Namespace(yes=yes)
    t._logger = MagicMock()
    fake_app = SimpleNamespace(config=cfg, _loaded_config_paths=["/tmp/etc/infra.yaml"])
    patch.object(PgEraseTool, "app", new=property(lambda s: fake_app)).start()
    return t


@pytest.mark.unit
class TestPgErasePreview:
    """Preview rendering — reflects live runtime state without touching it."""

    def test_preview_lists_only_existing_resources(self):
        from appinfra.cli.tools.pg_tool import _build_erase_preview

        with (
            patch("appinfra.cli.tools.pg_tool._container_status") as cs,
            patch("appinfra.cli.tools.pg_tool._resource_exists") as re,
        ):
            cs.side_effect = lambda rt, n: "Up 2 hours" if n == "test-pg" else None
            re.side_effect = lambda rt, kind, n: (
                n
                in {
                    "test-pg_pgdata",
                    "test-pg_default",
                }
            )
            out = _build_erase_preview("podman", "test-pg", "img:tag", "/etc/x")

        assert "test-pg (Up 2 hours)" in out
        assert "test-pg-primary" not in out  # doesn't exist → skipped
        assert "test-pg_pgdata" in out
        assert "test-pg_pgdata_primary" not in out
        assert "test-pg_default" in out
        assert "img:tag (NOT touched)" in out
        assert "/etc/x" in out

    def test_preview_all_missing_shows_none(self):
        from appinfra.cli.tools.pg_tool import _build_erase_preview

        with (
            patch("appinfra.cli.tools.pg_tool._container_status", return_value=None),
            patch("appinfra.cli.tools.pg_tool._resource_exists", return_value=False),
        ):
            out = _build_erase_preview("podman", "test-pg", "", "")

        assert "containers: (none)" in out
        assert "volumes:    (none)" in out
        assert "networks:   (none)" in out
        assert "(none configured) (NOT touched)" in out
        assert "(not tracked)" in out

    def test_container_status_uses_anchored_regex(self):
        """`test-pg` query must not match `test-pg-primary`."""
        from appinfra.cli.tools.pg_tool import _container_status

        with patch("appinfra.cli.tools.pg_tool._run_query") as q:
            q.return_value = SimpleNamespace(stdout="", returncode=0)
            _container_status("podman", "test-pg")
            cmd = q.call_args.args[0]
            assert "name=^test-pg$" in cmd

    def test_resource_exists_uses_inspect(self):
        """Portability check — `inspect` works on both podman and docker."""
        from appinfra.cli.tools.pg_tool import _resource_exists

        with patch("appinfra.cli.tools.pg_tool._run_query") as q:
            q.return_value = SimpleNamespace(returncode=0)
            _resource_exists("docker", "volume", "v")
            assert q.call_args.args[0] == ["docker", "volume", "inspect", "v"]

    def test_config_source_extracts_full_path_from_tuple(self):
        """_loaded_config_paths entries are (etc_dir, name, full_path)
        tuples; the preview must show the full path, not the raw tuple."""
        from appinfra.cli.tools.pg_tool import _config_source_path

        app = SimpleNamespace(
            _loaded_config_paths=[("/x/etc", "infra.yaml", "/x/etc/infra.yaml")]
        )
        assert _config_source_path(app) == "/x/etc/infra.yaml"

    def test_config_source_empty_when_no_paths(self):
        from appinfra.cli.tools.pg_tool import _config_source_path

        assert _config_source_path(SimpleNamespace()) == ""
        assert _config_source_path(SimpleNamespace(_loaded_config_paths=[])) == ""


@pytest.mark.unit
class TestPgEraseConfirmation:
    """Confirmation gate — bypass paths, prompt paths, refusal paths."""

    def teardown_method(self, method):
        patch.stopall()

    def test_yes_flag_skips_prompt_and_calls_exec(self):
        t = _erase_tool(yes=True)
        with patch("appinfra.cli.tools.pg_tool._exec_pg", return_value=0) as ex:
            rc = t.run()
        assert rc == 0
        ex.assert_called_once()
        assert ex.call_args.args[1] == "erase"

    def test_empty_pgserver_name_returns_2(self, capsys):
        cfg = DotDict({"pgserver": {"name": "", "port": 25432, "user": "p"}})
        t = _erase_tool(cfg=cfg)
        rc = t.run()
        assert rc == 2
        assert "pgserver.name is empty" in capsys.readouterr().err

    def test_non_tty_without_yes_refuses_with_exit_2(self, capsys):
        t = _erase_tool(yes=False)
        with (
            patch(
                "appinfra.cli.tools.pg_tool._resolve_preview_runtime",
                return_value="podman",
            ),
            patch("appinfra.cli.tools.pg_tool._container_status", return_value=None),
            patch("appinfra.cli.tools.pg_tool._resource_exists", return_value=False),
            patch("appinfra.cli.tools.pg_tool.sys.stdin") as stdin,
            patch("appinfra.cli.tools.pg_tool._exec_pg") as ex,
        ):
            stdin.isatty.return_value = False
            rc = t.run()

        assert rc == 2
        assert "refusing without --yes on non-tty" in capsys.readouterr().err
        ex.assert_not_called()

    def test_tty_confirm_string_erase_proceeds(self):
        t = _erase_tool(yes=False)
        with (
            patch(
                "appinfra.cli.tools.pg_tool._resolve_preview_runtime",
                return_value="podman",
            ),
            patch("appinfra.cli.tools.pg_tool._container_status", return_value=None),
            patch("appinfra.cli.tools.pg_tool._resource_exists", return_value=False),
            patch("appinfra.cli.tools.pg_tool.sys.stdin") as stdin,
            patch("builtins.input", return_value="erase"),
            patch("appinfra.cli.tools.pg_tool._exec_pg", return_value=0) as ex,
        ):
            stdin.isatty.return_value = True
            rc = t.run()

        assert rc == 0
        ex.assert_called_once()

    def test_tty_wrong_confirm_aborts_with_exit_1(self, capsys):
        t = _erase_tool(yes=False)
        with (
            patch(
                "appinfra.cli.tools.pg_tool._resolve_preview_runtime",
                return_value="podman",
            ),
            patch("appinfra.cli.tools.pg_tool._container_status", return_value=None),
            patch("appinfra.cli.tools.pg_tool._resource_exists", return_value=False),
            patch("appinfra.cli.tools.pg_tool.sys.stdin") as stdin,
            patch("builtins.input", return_value="y"),
            patch("appinfra.cli.tools.pg_tool._exec_pg") as ex,
        ):
            stdin.isatty.return_value = True
            rc = t.run()

        assert rc == 1
        assert "aborted" in capsys.readouterr().err
        ex.assert_not_called()

    def test_no_runtime_available_falls_through_to_pg_sh(self):
        """When podman/docker missing, preview is skipped and pg.sh runs its
        own pre-flight — the CLI does not duplicate the install message."""
        t = _erase_tool(yes=False)
        with (
            patch(
                "appinfra.cli.tools.pg_tool._resolve_preview_runtime", return_value=None
            ),
            patch("appinfra.cli.tools.pg_tool._exec_pg", return_value=2) as ex,
        ):
            rc = t.run()
        assert rc == 2
        ex.assert_called_once()


# =============================================================================
# PgUrlTool.run — URL computation
# =============================================================================


@pytest.mark.unit
class TestPgUrlTool:
    """Test URL computation for --db and server-level cases."""

    def _run(self, cfg, **args):
        """Build a PgUrlTool with faked args + faked app.config, run it."""
        t = PgUrlTool()
        defaults = {"db": None, "target": "primary"}
        defaults.update(args)
        t._parsed_args = Namespace(**defaults)
        t._logger = MagicMock()
        fake_app = SimpleNamespace(config=DotDict(cfg))
        with patch.object(PgUrlTool, "app", new=property(lambda s: fake_app)):
            return t.run()

    def test_server_url_primary(self, capsys):
        cfg = {"pgserver": {"host": "h", "user": "u", "port": 5555}}
        rc = self._run(cfg)
        assert rc == 0
        assert capsys.readouterr().out.strip() == "postgresql://u@h:5555"

    def test_server_url_standby(self, capsys):
        cfg = {
            "pgserver": {
                "host": "h",
                "user": "u",
                "port": 5555,
                "replica": {"port": 5556},
            }
        }
        rc = self._run(cfg, target="standby")
        assert rc == 0
        assert capsys.readouterr().out.strip() == "postgresql://u@h:5556"

    def test_server_url_standby_missing_returns_1(self):
        cfg = {"pgserver": {"host": "h", "user": "u", "port": 5555}}
        assert self._run(cfg, target="standby") == 1

    def test_server_url_primary_missing_returns_1(self):
        cfg = {"pgserver": {"host": "h", "user": "u"}}
        assert self._run(cfg, target="primary") == 1

    def test_db_url_lookup(self, capsys):
        cfg = {"dbs": {"main": {"url": "postgresql://x/main"}}}
        rc = self._run(cfg, db="main")
        assert rc == 0
        assert capsys.readouterr().out.strip() == "postgresql://x/main"

    def test_db_url_missing_returns_1(self):
        assert self._run({"dbs": {}}, db="nope") == 1

    def test_server_url_ipv6_host_bracketed(self, capsys):
        cfg = {"pgserver": {"host": "::1", "user": "u", "port": 5555}}
        rc = self._run(cfg)
        assert rc == 0
        assert capsys.readouterr().out.strip() == "postgresql://u@[::1]:5555"

    def test_server_url_user_percent_encoded(self, capsys):
        cfg = {"pgserver": {"host": "h", "user": "user@domain", "port": 5555}}
        rc = self._run(cfg)
        assert rc == 0
        assert capsys.readouterr().out.strip() == "postgresql://user%40domain@h:5555"


# =============================================================================
# PgTool — grouping tool
# =============================================================================


@pytest.mark.unit
class TestPgTool:
    """Test PgTool subtool registration and defaults."""

    def test_all_verbs_registered(self):
        t = PgTool()
        names = set(t.group._tools.keys())
        expected = {
            "status",
            "up",
            "down",
            "reboot",
            "logs",
            "info",
            "url",
            "clean",
            "erase",
            "psql",
            "top",
        }
        assert expected.issubset(names)

    def test_default_subtool_is_status(self):
        t = PgTool()
        assert t.group._default == "status"

    def test_help_and_description(self):
        t = PgTool()
        assert t.name == "pg"
        assert t.config.description
