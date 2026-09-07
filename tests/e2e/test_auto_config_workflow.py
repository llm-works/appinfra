# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
E2E test for config file loading workflow.

This test validates the complete workflow from a spec declared on the
AppBuilder config block through to actual logging output, ensuring logging
levels and handlers from YAML config are correctly applied.

Tests cover:
- YAML logging settings (level, location, micros) are applied
- YAML handlers are loaded and used
- CLI args properly override YAML settings
- The spec's filename selects which file loads
- Programmatic config (via builder) takes precedence over YAML
"""

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from appinfra.app.builder import AppBuilder


def _spec_app(etc_dir: Path, filename: str = "app.yaml") -> AppBuilder:
    """Builder whose spec names ``<etc_dir>/<filename>`` and exposes ``--etc-dir``.

    Passing ``--etc-dir <etc_dir>`` at parse time selects that file under
    precedence rule 3, independent of cwd and XDG state.
    """
    return (
        AppBuilder("test-app")
        .with_standard_args(etc_dir=True)
        .config.with_spec("test-org", "app", path=etc_dir / filename)
        .done()
    )


def _load(app, etc_dir: Path, *extra_argv: str) -> None:
    """Parse ``--etc-dir`` plus extras and run the config-loading step."""
    with patch.object(sys, "argv", ["test", "--etc-dir", str(etc_dir), *extra_argv]):
        app.create_args()
        app._parsed_args = app.parser.parse_args()
        app._load_and_merge_config()


@pytest.mark.e2e
@pytest.mark.usefixtures("clean_env")
class TestConfigFileWorkflow:
    """E2E tests for config file loading workflow."""

    def test_yaml_logging_level_applied(self):
        """Test that logging level from YAML config is applied to the app."""
        with tempfile.TemporaryDirectory() as tmpdir:
            etc_dir = Path(tmpdir) / "etc"
            etc_dir.mkdir()
            (etc_dir / "app.yaml").write_text("logging:\n  level: debug\n")

            app = _spec_app(etc_dir).build()
            _load(app, etc_dir)

            assert app.config.logging.level == "debug"

    def test_yaml_logging_level_not_overridden_by_defaults(self):
        """Regression test: YAML logging level should not be overridden by defaults.

        Previously, App.__init__ created a default config with level='info',
        which then overrode YAML values during merge.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            etc_dir = Path(tmpdir) / "etc"
            etc_dir.mkdir()
            (etc_dir / "app.yaml").write_text(
                "logging:\n  level: warning\n  location: 2\n  micros: true\n"
            )

            app = _spec_app(etc_dir).build()
            _load(app, etc_dir)

            assert app.config.logging.level == "warning"
            assert app.config.logging.location == 2
            assert app.config.logging.micros is True

    def test_cli_args_override_yaml_config(self):
        """Test that CLI arguments take precedence over YAML config."""
        with tempfile.TemporaryDirectory() as tmpdir:
            etc_dir = Path(tmpdir) / "etc"
            etc_dir.mkdir()
            (etc_dir / "app.yaml").write_text("logging:\n  level: info\n")

            app = _spec_app(etc_dir).with_standard_args(log_level=True).build()
            _load(app, etc_dir, "--log-level", "debug")

            assert app.config.logging.level == "debug"

    def test_spec_filename_selects_file(self):
        """The spec's base filename is the one file loaded from --etc-dir."""
        with tempfile.TemporaryDirectory() as tmpdir:
            etc_dir = Path(tmpdir) / "etc"
            etc_dir.mkdir()
            (etc_dir / "default.yaml").write_text(
                "from_default: true\nlogging:\n  level: info\n"
            )
            (etc_dir / "custom.yaml").write_text(
                "from_custom: true\nlogging:\n  level: debug\n"
            )

            app = _spec_app(etc_dir, "custom.yaml").build()
            _load(app, etc_dir)

            assert app.config.from_custom is True
            assert app.config.logging.level == "debug"
            assert not hasattr(app.config, "from_default")

    def test_yaml_handlers_loaded(self):
        """Test that handlers defined in YAML config are loaded."""
        with tempfile.TemporaryDirectory() as tmpdir:
            etc_dir = Path(tmpdir) / "etc"
            etc_dir.mkdir()
            (etc_dir / "app.yaml").write_text(
                "logging:\n"
                "  level: debug\n"
                "  handlers:\n"
                "    console:\n"
                "      type: console\n"
                "      level: debug\n"
                "      format: text\n"
            )

            app = _spec_app(etc_dir).build()
            _load(app, etc_dir)

            assert hasattr(app.config.logging, "handlers")
            assert hasattr(app.config.logging.handlers, "console")
            assert app.config.logging.handlers.console.type == "console"

    def test_programmatic_config_takes_precedence(self):
        """Test that config set via builder methods takes precedence over YAML."""
        with tempfile.TemporaryDirectory() as tmpdir:
            etc_dir = Path(tmpdir) / "etc"
            etc_dir.mkdir()
            (etc_dir / "app.yaml").write_text("logging:\n  level: debug\n")

            app = _spec_app(etc_dir).logging.with_level("error").done().build()
            _load(app, etc_dir)

            assert app.config.logging.level == "error"

    def test_no_spec_loads_nothing(self):
        """An app without a spec never reads a file from --etc-dir."""
        with tempfile.TemporaryDirectory() as tmpdir:
            etc_dir = Path(tmpdir) / "etc"
            etc_dir.mkdir()
            (etc_dir / "app.yaml").write_text(
                "custom_key: should_not_load\nlogging:\n  level: debug\n"
            )

            app = AppBuilder("test-app").with_standard_args(etc_dir=True).build()
            _load(app, etc_dir)

            assert not hasattr(app.config, "custom_key")
            assert app.config_path is None

    def test_packaged_base_loads_without_etc_dir(self, tmp_path, monkeypatch):
        """With no --etc-dir, project-local file or XDG overlay, the base loads."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "no-xdg"))
        monkeypatch.setenv("XDG_CONFIG_DIRS", str(tmp_path / "no-xdg-sys"))
        monkeypatch.chdir(tmp_path)
        base = tmp_path / "pkg" / "etc" / "app.yaml"
        base.parent.mkdir(parents=True)
        base.write_text("direct_load: true\nlogging:\n  level: trace\n")

        app = (
            AppBuilder("test-app")
            .config.with_spec("test-org", "app", path=base)
            .done()
            .build()
        )
        with patch.object(sys, "argv", ["test"]):
            app.create_args()
            app._parsed_args = app.parser.parse_args()
            app._load_and_merge_config()

        assert app.config.direct_load is True
        assert app.config.logging.level == "trace"
        assert app.config_path == base.resolve()

    def test_full_app_lifecycle_with_yaml_config(self):
        """Test complete app lifecycle with YAML config including logging setup."""
        with tempfile.TemporaryDirectory() as tmpdir:
            etc_dir = Path(tmpdir) / "etc"
            etc_dir.mkdir()
            (etc_dir / "app.yaml").write_text(
                "app_name: e2e-test\nlogging:\n  level: debug\n  location: 1\n"
            )

            app = _spec_app(etc_dir).build()

            with patch.object(sys, "argv", ["test", "--etc-dir", str(etc_dir)]):
                try:
                    app.setup()
                    assert app.config.app_name == "e2e-test"
                    assert app.config.logging.level == "debug"
                    assert app.config_path == (etc_dir / "app.yaml").resolve()
                finally:
                    if app.lifecycle.logger:
                        app.lifecycle.logger.handlers.clear()

    def test_etc_dir_from_cli_arg(self):
        """Test that --etc-dir CLI arg correctly specifies config directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            custom_etc = Path(tmpdir) / "custom" / "config" / "etc"
            custom_etc.mkdir(parents=True)
            (custom_etc / "app.yaml").write_text(
                "from_custom_etc: true\nlogging:\n  level: trace\n"
            )

            # The spec's base lives elsewhere; --etc-dir redirects the load.
            app = _spec_app(Path(tmpdir) / "pkg" / "etc").build()
            _load(app, custom_etc)

            assert app.config.from_custom_etc is True
            assert app.config.logging.level == "trace"

    def test_missing_config_file_raises(self):
        """A resolved file that does not exist raises FileNotFoundError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            etc_dir = Path(tmpdir) / "etc"
            etc_dir.mkdir()

            app = _spec_app(etc_dir, "nonexistent.yaml").build()

            with pytest.raises(FileNotFoundError, match="nonexistent.yaml"):
                _load(app, etc_dir)

    def test_yaml_with_all_logging_options(self):
        """Test comprehensive YAML config with all logging options."""
        with tempfile.TemporaryDirectory() as tmpdir:
            etc_dir = Path(tmpdir) / "etc"
            etc_dir.mkdir()
            (etc_dir / "app.yaml").write_text(
                "logging:\n"
                "  level: debug\n"
                "  location: 2\n"
                "  micros: true\n"
                "  handlers:\n"
                "    stdout:\n"
                "      type: console\n"
                "      level: debug\n"
                "      stream: stdout\n"
                "      format: text\n"
                "      colors: true\n"
                "    stderr:\n"
                "      type: console\n"
                "      level: warning\n"
                "      stream: stderr\n"
                "      format: text\n"
                "  topics:\n"
                "    '/db/**': debug\n"
                "    '/api/**': info\n"
            )

            app = _spec_app(etc_dir).build()
            _load(app, etc_dir)

            assert app.config.logging.level == "debug"
            assert app.config.logging.location == 2
            assert app.config.logging.micros is True

            assert hasattr(app.config.logging, "handlers")
            assert app.config.logging.handlers.stdout.type == "console"
            assert app.config.logging.handlers.stdout.stream == "stdout"
            assert app.config.logging.handlers.stderr.level == "warning"

            assert hasattr(app.config.logging, "topics")


@pytest.mark.e2e
@pytest.mark.usefixtures("clean_env")
class TestConfigSectionIncludeWorkflow:
    """E2E tests for section includes with variable resolution."""

    def test_section_include_resolves_sibling_variables(self):
        """Test that !include with section resolves ${sibling.key} variables.

        Section names use a generic `dbserver`/`dbs` rather than `pgserver` so
        the test stays independent of `INFRA_PGSERVER_*` env vars that CI sets
        — Config now (correctly) propagates env overrides into include-time
        ${var} substitution.

        Example:
            # db.yaml
            dbserver:
              port: 7632
              user: appuser
            dbs:
              main:
                url: "postgresql://${dbserver.user}:@127.0.0.1:${dbserver.port}/learn"

            # app.yaml
            learn:
              db: !include './db.yaml#dbs.main'

        Expected: db.url = "postgresql://appuser:@127.0.0.1:7632/learn"
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            etc_dir = Path(tmpdir) / "etc"
            etc_dir.mkdir()
            (etc_dir / "db.yaml").write_text(
                "dbserver:\n"
                "  port: 7632\n"
                "  user: appuser\n"
                "dbs:\n"
                "  main:\n"
                '    url: "postgresql://${dbserver.user}:@127.0.0.1:${dbserver.port}/learn"\n'
            )
            (etc_dir / "app.yaml").write_text(
                "learn:\n  db: !include './db.yaml#dbs.main'\nlogging:\n  level: info\n"
            )

            app = _spec_app(etc_dir).build()
            _load(app, etc_dir)

            assert (
                app.config.learn.db.url == "postgresql://appuser:@127.0.0.1:7632/learn"
            )

    def test_section_include_with_nested_structure(self):
        """Test section include with nested configuration structure.

        Verifies that complex nested structures with multiple variable references
        all resolve correctly when using section includes.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            etc_dir = Path(tmpdir) / "etc"
            etc_dir.mkdir()
            (etc_dir / "db.yaml").write_text(
                "defaults:\n"
                "  host: localhost\n"
                "  port: 5432\n"
                "  user: admin\n"
                "connections:\n"
                "  primary:\n"
                "    host: ${defaults.host}\n"
                "    port: ${defaults.port}\n"
                "    user: ${defaults.user}\n"
                "    pool_size: 10\n"
            )
            (etc_dir / "app.yaml").write_text(
                "database: !include './db.yaml#connections.primary'\n"
                "logging:\n"
                "  level: info\n"
            )

            app = _spec_app(etc_dir).build()
            _load(app, etc_dir)

            assert app.config.database.host == "localhost"
            assert app.config.database.port == "5432"
            assert app.config.database.user == "admin"
            assert app.config.database.pool_size == 10

    def test_document_level_section_include_resolves_vars(self):
        """Test document-level !include with section resolves variables."""
        with tempfile.TemporaryDirectory() as tmpdir:
            etc_dir = Path(tmpdir) / "etc"
            etc_dir.mkdir()
            (etc_dir / "base.yaml").write_text(
                "common:\n"
                "  version: '2.0'\n"
                "production:\n"
                "  app_version: '${common.version}'\n"
                "  debug: false\n"
            )
            (etc_dir / "app.yaml").write_text(
                "!include './base.yaml#production'\n"
                "\n"
                "name: myapp\n"
                "logging:\n"
                "  level: info\n"
            )

            app = _spec_app(etc_dir).build()
            _load(app, etc_dir)

            assert app.config.app_version == "2.0"
            assert app.config.debug is False
            assert app.config.name == "myapp"


@pytest.mark.e2e
@pytest.mark.usefixtures("clean_env")
class TestConfigIncludeErrorWorkflow:
    """E2E tests for config file include error handling workflow."""

    def test_include_error_raises(self):
        """Test that !include errors raise immediately.

        Loading fails fast on YAML errors including !include failures,
        ensuring the app doesn't run with incomplete configuration.
        """
        import yaml

        with tempfile.TemporaryDirectory() as tmpdir:
            etc_dir = Path(tmpdir) / "etc"
            etc_dir.mkdir()
            config_content = """name: test-app
database: !include "./missing-db.yaml"
logging:
  level: info
"""
            (etc_dir / "app.yaml").write_text(config_content)

            app = _spec_app(etc_dir).build()

            with pytest.raises(yaml.YAMLError) as exc_info:
                _load(app, etc_dir)

            error_str = str(exc_info.value)
            assert "missing-db.yaml" in error_str
            assert "line 2" in error_str

    def test_document_level_include_error_raises(self):
        """Test that document-level !include errors raise."""
        import yaml

        with tempfile.TemporaryDirectory() as tmpdir:
            etc_dir = Path(tmpdir) / "etc"
            etc_dir.mkdir()
            config_content = """!include "./missing-base.yaml"

name: test-app
"""
            (etc_dir / "app.yaml").write_text(config_content)

            app = _spec_app(etc_dir).build()

            with pytest.raises(yaml.YAMLError) as exc_info:
                _load(app, etc_dir)

            error_str = str(exc_info.value)
            assert "missing-base.yaml" in error_str
            # Document-level include should have line 1
            assert "line 1" in error_str


@pytest.mark.e2e
@pytest.mark.usefixtures("clean_env")
class TestLogOutputCliOverrides:
    """E2E tests for --log-json and --no-log-colors CLI overrides."""

    def test_log_json_overrides_yaml_text_format(self):
        """Test that --log-json CLI arg overrides YAML text format to JSON."""
        from appinfra.log.builder.console import ConsoleHandlerConfig

        with tempfile.TemporaryDirectory() as tmpdir:
            etc_dir = Path(tmpdir) / "etc"
            etc_dir.mkdir()
            (etc_dir / "app.yaml").write_text(
                "logging:\n"
                "  level: info\n"
                "  handlers:\n"
                "    console:\n"
                "      type: console\n"
                "      level: info\n"
                "      format: text\n"
                "      colors: true\n"
            )

            app = _spec_app(etc_dir).with_standard_args(log_json=True).build()

            with patch.object(
                sys, "argv", ["test", "--etc-dir", str(etc_dir), "--log-json"]
            ):
                try:
                    app.setup()

                    registry = app.lifecycle._handler_registry
                    handlers = list(registry.iter_enabled_handlers())
                    assert len(handlers) >= 1

                    console_handlers = [
                        h for h in handlers if isinstance(h, ConsoleHandlerConfig)
                    ]
                    assert len(console_handlers) >= 1
                    assert console_handlers[0].format == "json"
                finally:
                    if app.lifecycle.logger:
                        app.lifecycle.logger.handlers.clear()

    def test_no_log_colors_overrides_yaml_colors(self):
        """Test that --no-log-colors CLI arg disables colors in YAML config."""
        from appinfra.log.builder.console import ConsoleHandlerConfig

        with tempfile.TemporaryDirectory() as tmpdir:
            etc_dir = Path(tmpdir) / "etc"
            etc_dir.mkdir()
            (etc_dir / "app.yaml").write_text(
                "logging:\n"
                "  level: info\n"
                "  handlers:\n"
                "    console:\n"
                "      type: console\n"
                "      level: info\n"
                "      format: text\n"
                "      colors: true\n"
            )

            app = _spec_app(etc_dir).with_standard_args(log_colors=True).build()

            with patch.object(
                sys, "argv", ["test", "--etc-dir", str(etc_dir), "--no-log-colors"]
            ):
                try:
                    app.setup()

                    registry = app.lifecycle._handler_registry
                    handlers = list(registry.iter_enabled_handlers())
                    console_handlers = [
                        h for h in handlers if isinstance(h, ConsoleHandlerConfig)
                    ]
                    assert len(console_handlers) >= 1
                    assert console_handlers[0].colors is False
                finally:
                    if app.lifecycle.logger:
                        app.lifecycle.logger.handlers.clear()

    def test_log_json_and_no_log_colors_together(self):
        """Test using both --log-json and --no-log-colors together."""
        from appinfra.log.builder.console import ConsoleHandlerConfig

        with tempfile.TemporaryDirectory() as tmpdir:
            etc_dir = Path(tmpdir) / "etc"
            etc_dir.mkdir()
            (etc_dir / "app.yaml").write_text(
                "logging:\n"
                "  level: info\n"
                "  handlers:\n"
                "    console:\n"
                "      type: console\n"
                "      level: info\n"
                "      format: text\n"
                "      colors: true\n"
            )

            app = (
                _spec_app(etc_dir)
                .with_standard_args(log_json=True, log_colors=True)
                .build()
            )

            with patch.object(
                sys,
                "argv",
                ["test", "--etc-dir", str(etc_dir), "--log-json", "--no-log-colors"],
            ):
                try:
                    app.setup()

                    registry = app.lifecycle._handler_registry
                    handlers = list(registry.iter_enabled_handlers())
                    console_handlers = [
                        h for h in handlers if isinstance(h, ConsoleHandlerConfig)
                    ]
                    assert len(console_handlers) >= 1
                    assert console_handlers[0].format == "json"
                finally:
                    if app.lifecycle.logger:
                        app.lifecycle.logger.handlers.clear()

    def test_cli_overrides_multiple_handlers(self):
        """Test that CLI args override settings in multiple console handlers."""
        from appinfra.log.builder.console import ConsoleHandlerConfig

        with tempfile.TemporaryDirectory() as tmpdir:
            etc_dir = Path(tmpdir) / "etc"
            etc_dir.mkdir()
            (etc_dir / "app.yaml").write_text(
                "logging:\n"
                "  level: info\n"
                "  handlers:\n"
                "    stdout:\n"
                "      type: console\n"
                "      level: info\n"
                "      stream: stdout\n"
                "      format: text\n"
                "      colors: true\n"
                "    stderr:\n"
                "      type: console\n"
                "      level: error\n"
                "      stream: stderr\n"
                "      format: text\n"
                "      colors: true\n"
            )

            app = _spec_app(etc_dir).with_standard_args(log_json=True).build()

            with patch.object(
                sys, "argv", ["test", "--etc-dir", str(etc_dir), "--log-json"]
            ):
                try:
                    app.setup()

                    registry = app.lifecycle._handler_registry
                    handlers = list(registry.iter_enabled_handlers())
                    console_handlers = [
                        h for h in handlers if isinstance(h, ConsoleHandlerConfig)
                    ]
                    assert len(console_handlers) == 2

                    for handler in console_handlers:
                        assert handler.format == "json"
                finally:
                    if app.lifecycle.logger:
                        app.lifecycle.logger.handlers.clear()

    def test_default_handler_respects_log_json(self):
        """Test that --log-json works when no handlers are configured in YAML."""
        from appinfra.log.builder.console import ConsoleHandlerConfig

        with tempfile.TemporaryDirectory() as tmpdir:
            etc_dir = Path(tmpdir) / "etc"
            etc_dir.mkdir()
            (etc_dir / "app.yaml").write_text("logging:\n  level: info\n")

            app = _spec_app(etc_dir).with_standard_args(log_json=True).build()

            with patch.object(
                sys, "argv", ["test", "--etc-dir", str(etc_dir), "--log-json"]
            ):
                try:
                    app.setup()

                    registry = app.lifecycle._handler_registry
                    handlers = list(registry.iter_enabled_handlers())
                    assert len(handlers) >= 1

                    console_handlers = [
                        h for h in handlers if isinstance(h, ConsoleHandlerConfig)
                    ]
                    assert len(console_handlers) >= 1
                    assert console_handlers[0].format == "json"
                finally:
                    if app.lifecycle.logger:
                        app.lifecycle.logger.handlers.clear()

    def test_default_handler_respects_no_log_colors(self):
        """Test that --no-log-colors works when no handlers are configured in YAML."""
        from appinfra.log.builder.console import ConsoleHandlerConfig

        with tempfile.TemporaryDirectory() as tmpdir:
            etc_dir = Path(tmpdir) / "etc"
            etc_dir.mkdir()
            (etc_dir / "app.yaml").write_text("logging:\n  level: info\n")

            app = _spec_app(etc_dir).with_standard_args(log_colors=True).build()

            with patch.object(
                sys, "argv", ["test", "--etc-dir", str(etc_dir), "--no-log-colors"]
            ):
                try:
                    app.setup()

                    registry = app.lifecycle._handler_registry
                    handlers = list(registry.iter_enabled_handlers())
                    console_handlers = [
                        h for h in handlers if isinstance(h, ConsoleHandlerConfig)
                    ]
                    assert len(console_handlers) >= 1
                    assert console_handlers[0].colors is False
                finally:
                    if app.lifecycle.logger:
                        app.lifecycle.logger.handlers.clear()
