"""
E2E test for config file loading workflow.

This test validates the complete workflow from AppBuilder.with_config_file()
through to actual logging output, ensuring logging levels and handlers from
YAML config are correctly applied.

Tests cover:
- YAML logging settings (level, location, micros) are applied
- YAML handlers are loaded and used
- CLI args properly override YAML settings
- Custom config filename works
- Programmatic config (via builder) takes precedence over YAML
"""

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from appinfra.app.builder import AppBuilder


@pytest.mark.e2e
class TestConfigFileWorkflow:
    """E2E tests for config file loading workflow."""

    def test_yaml_logging_level_applied(self):
        """Test that logging level from YAML config is applied to the app."""
        with tempfile.TemporaryDirectory() as tmpdir:
            etc_dir = Path(tmpdir) / "etc"
            etc_dir.mkdir()

            # Create config with debug level
            (etc_dir / "app.yaml").write_text("logging:\n  level: debug\n")

            # Build app with config file from etc-dir
            app = AppBuilder("test-app").with_config_file("app.yaml").build()

            # Simulate running with --etc-dir pointing to our test directory
            with patch.object(sys, "argv", ["test", "--etc-dir", str(etc_dir)]):
                app.create_args()
                app._parsed_args = app.parser.parse_args()
                app._load_and_merge_config()

            # Verify logging level from YAML was applied
            assert app.config.logging.level == "debug"

    def test_yaml_logging_level_not_overridden_by_defaults(self):
        """Regression test: YAML logging level should not be overridden by defaults.

        Previously, App.__init__ created a default config with level='info',
        which then overrode YAML values during merge.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            etc_dir = Path(tmpdir) / "etc"
            etc_dir.mkdir()

            # Create config with non-default values
            (etc_dir / "app.yaml").write_text(
                "logging:\n  level: warning\n  location: 2\n  micros: true\n"
            )

            app = AppBuilder("test-app").with_config_file("app.yaml").build()

            with patch.object(sys, "argv", ["test", "--etc-dir", str(etc_dir)]):
                app.create_args()
                app._parsed_args = app.parser.parse_args()
                app._load_and_merge_config()

            # All YAML values should be preserved
            assert app.config.logging.level == "warning"
            assert app.config.logging.location == 2
            assert app.config.logging.micros is True

    def test_cli_args_override_yaml_config(self):
        """Test that CLI arguments take precedence over YAML config."""
        with tempfile.TemporaryDirectory() as tmpdir:
            etc_dir = Path(tmpdir) / "etc"
            etc_dir.mkdir()

            # Create config with info level
            (etc_dir / "app.yaml").write_text("logging:\n  level: info\n")

            app = AppBuilder("test-app").with_config_file("app.yaml").build()

            # Pass --log-level debug to override YAML
            with patch.object(
                sys, "argv", ["test", "--etc-dir", str(etc_dir), "--log-level", "debug"]
            ):
                app.create_args()
                app._parsed_args = app.parser.parse_args()
                app._load_and_merge_config()

            # CLI arg should win
            assert app.config.logging.level == "debug"

    def test_custom_config_filename(self):
        """Test that with_config_file(filename) loads only that file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            etc_dir = Path(tmpdir) / "etc"
            etc_dir.mkdir()

            # Create two config files
            (etc_dir / "default.yaml").write_text(
                "from_default: true\nlogging:\n  level: info\n"
            )
            (etc_dir / "custom.yaml").write_text(
                "from_custom: true\nlogging:\n  level: debug\n"
            )

            app = (
                AppBuilder("test-app")
                .with_config_file("custom.yaml")  # Load only custom.yaml
                .build()
            )

            with patch.object(sys, "argv", ["test", "--etc-dir", str(etc_dir)]):
                app.create_args()
                app._parsed_args = app.parser.parse_args()
                app._load_and_merge_config()

            # Should have loaded custom.yaml only
            assert hasattr(app.config, "from_custom")
            assert app.config.from_custom is True
            assert app.config.logging.level == "debug"

            # Should NOT have loaded default.yaml
            assert not hasattr(app.config, "from_default")

    def test_yaml_handlers_loaded(self):
        """Test that handlers defined in YAML config are loaded."""
        with tempfile.TemporaryDirectory() as tmpdir:
            etc_dir = Path(tmpdir) / "etc"
            etc_dir.mkdir()

            # Create config with custom handler
            (etc_dir / "app.yaml").write_text(
                "logging:\n"
                "  level: debug\n"
                "  handlers:\n"
                "    console:\n"
                "      type: console\n"
                "      level: debug\n"
                "      format: text\n"
            )

            app = AppBuilder("test-app").with_config_file("app.yaml").build()

            with patch.object(sys, "argv", ["test", "--etc-dir", str(etc_dir)]):
                app.create_args()
                app._parsed_args = app.parser.parse_args()
                app._load_and_merge_config()

            # Verify handlers section exists in config
            assert hasattr(app.config.logging, "handlers")
            assert hasattr(app.config.logging.handlers, "console")
            assert app.config.logging.handlers.console.type == "console"

    def test_programmatic_config_takes_precedence(self):
        """Test that config set via builder methods takes precedence over YAML."""
        with tempfile.TemporaryDirectory() as tmpdir:
            etc_dir = Path(tmpdir) / "etc"
            etc_dir.mkdir()

            # Create config with debug level
            (etc_dir / "app.yaml").write_text("logging:\n  level: debug\n")

            app = (
                AppBuilder("test-app")
                .with_config_file("app.yaml")
                .logging.with_level("error")  # Programmatic override
                .done()
                .build()
            )

            with patch.object(sys, "argv", ["test", "--etc-dir", str(etc_dir)]):
                app.create_args()
                app._parsed_args = app.parser.parse_args()
                app._load_and_merge_config()

            # Programmatic config should win over YAML
            assert app.config.logging.level == "error"

    def test_no_config_file_uses_defaults(self):
        """Test that not using with_config_file uses default config."""
        with tempfile.TemporaryDirectory() as tmpdir:
            etc_dir = Path(tmpdir) / "etc"
            etc_dir.mkdir()

            (etc_dir / "app.yaml").write_text(
                "custom_key: should_not_load\nlogging:\n  level: debug\n"
            )

            # Don't use with_config_file
            app = AppBuilder("test-app").build()

            with patch.object(sys, "argv", ["test", "--etc-dir", str(etc_dir)]):
                app.create_args()
                app._parsed_args = app.parser.parse_args()
                app._load_and_merge_config()

            # Should NOT have loaded the YAML config
            assert not hasattr(app.config, "custom_key")

    def test_default_config_file_loaded(self):
        """Test that with_config_file() without args loads infra.yaml."""
        with tempfile.TemporaryDirectory() as tmpdir:
            etc_dir = Path(tmpdir) / "etc"
            etc_dir.mkdir()
            (etc_dir / "infra.yaml").write_text(
                "default_loaded: true\nlogging:\n  level: trace\n"
            )

            # Use with_config_file() without arguments - should use infra.yaml
            app = AppBuilder("test-app").with_config_file().build()

            with patch.object(sys, "argv", ["test", "--etc-dir", str(etc_dir)]):
                app.create_args()
                app._parsed_args = app.parser.parse_args()
                app._load_and_merge_config()

            # Should have loaded infra.yaml
            assert hasattr(app.config, "default_loaded")
            assert app.config.default_loaded is True
            assert app.config.logging.level == "trace"

    def test_full_app_lifecycle_with_yaml_config(self):
        """Test complete app lifecycle with YAML config including logging setup."""
        with tempfile.TemporaryDirectory() as tmpdir:
            etc_dir = Path(tmpdir) / "etc"
            etc_dir.mkdir()

            # Create full config with logging settings
            (etc_dir / "app.yaml").write_text(
                "app_name: e2e-test\nlogging:\n  level: debug\n  location: 1\n"
            )

            app = AppBuilder("test-app").with_config_file("app.yaml").build()

            # Run app setup (without running a tool)
            with patch.object(sys, "argv", ["test", "--etc-dir", str(etc_dir)]):
                try:
                    app.setup()
                    # Verify config was loaded
                    assert app.config.app_name == "e2e-test"
                    assert app.config.logging.level == "debug"
                finally:
                    # Clean up logging handlers to avoid interference
                    if app.lifecycle.logger:
                        app.lifecycle.logger.handlers.clear()

    def test_etc_dir_from_cli_arg(self):
        """Test that --etc-dir CLI arg correctly specifies config directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create etc in a non-standard location
            custom_etc = Path(tmpdir) / "custom" / "config" / "etc"
            custom_etc.mkdir(parents=True)

            (custom_etc / "app.yaml").write_text(
                "from_custom_etc: true\nlogging:\n  level: trace\n"
            )

            app = AppBuilder("test-app").with_config_file("app.yaml").build()

            with patch.object(sys, "argv", ["test", "--etc-dir", str(custom_etc)]):
                app.create_args()
                app._parsed_args = app.parser.parse_args()
                app._load_and_merge_config()

            assert app.config.from_custom_etc is True
            assert app.config.logging.level == "trace"

    def test_missing_required_config_file_raises(self):
        """Test that missing required config file raises FileNotFoundError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            etc_dir = Path(tmpdir) / "etc"
            etc_dir.mkdir()
            # Don't create any config files

            app = AppBuilder("test-app").with_config_file("nonexistent.yaml").build()

            with patch.object(sys, "argv", ["test", "--etc-dir", str(etc_dir)]):
                app.create_args()
                app._parsed_args = app.parser.parse_args()

                # Should raise - required config file must exist
                with pytest.raises(FileNotFoundError, match="nonexistent.yaml"):
                    app._load_and_merge_config()

    def test_missing_optional_config_file_skips_silently(self):
        """Test that missing optional config file skips without error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            etc_dir = Path(tmpdir) / "etc"
            etc_dir.mkdir()
            # Don't create any config files

            app = (
                AppBuilder("test-app")
                .with_config_file("nonexistent.yaml", optional=True)
                .build()
            )

            with patch.object(sys, "argv", ["test", "--etc-dir", str(etc_dir)]):
                app.create_args()
                app._parsed_args = app.parser.parse_args()

                # Should not raise - optional config can be missing
                result = app._load_and_merge_config()

            # App should still work with default config
            assert app.config is not None
            # Warning should be stored for later logging
            assert hasattr(app, "_config_load_warnings")
            assert len(app._config_load_warnings) == 1
            assert app._config_load_warnings[0][0] == "nonexistent.yaml"

    def test_yaml_with_all_logging_options(self):
        """Test comprehensive YAML config with all logging options."""
        with tempfile.TemporaryDirectory() as tmpdir:
            etc_dir = Path(tmpdir) / "etc"
            etc_dir.mkdir()

            # Create config with all logging options
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

            app = AppBuilder("test-app").with_config_file("app.yaml").build()

            with patch.object(sys, "argv", ["test", "--etc-dir", str(etc_dir)]):
                app.create_args()
                app._parsed_args = app.parser.parse_args()
                app._load_and_merge_config()

            # Verify all options loaded correctly
            assert app.config.logging.level == "debug"
            assert app.config.logging.location == 2
            assert app.config.logging.micros is True

            # Verify handlers
            assert hasattr(app.config.logging, "handlers")
            assert app.config.logging.handlers.stdout.type == "console"
            assert app.config.logging.handlers.stdout.stream == "stdout"
            assert app.config.logging.handlers.stderr.level == "warning"

            # Verify topics
            assert hasattr(app.config.logging, "topics")

    def test_multiple_config_files_merged(self):
        """Test that multiple with_config_file() calls merge configs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            etc_dir = Path(tmpdir) / "etc"
            etc_dir.mkdir()

            # Base config
            (etc_dir / "base.yaml").write_text(
                "app_name: base-app\n"
                "feature_a: from_base\n"
                "nested:\n"
                "  key1: base_value1\n"
                "  key2: base_value2\n"
            )

            # Overlay config - overrides some values
            (etc_dir / "overlay.yaml").write_text(
                "feature_a: from_overlay\n"
                "feature_b: only_in_overlay\n"
                "nested:\n"
                "  key2: overlay_value2\n"
                "  key3: overlay_value3\n"
            )

            # Chain multiple config files
            app = (
                AppBuilder("test-app")
                .with_config_file("base.yaml")
                .with_config_file("overlay.yaml")
                .build()
            )

            with patch.object(sys, "argv", ["test", "--etc-dir", str(etc_dir)]):
                app.create_args()
                app._parsed_args = app.parser.parse_args()
                app._load_and_merge_config()

            # Values from base that weren't overridden
            assert app.config.app_name == "base-app"

            # Value overridden by overlay
            assert app.config.feature_a == "from_overlay"

            # Value only in overlay
            assert app.config.feature_b == "only_in_overlay"

            # Nested values - should deep merge
            assert app.config.nested.key1 == "base_value1"  # Only in base
            assert app.config.nested.key2 == "overlay_value2"  # Overridden
            assert app.config.nested.key3 == "overlay_value3"  # Only in overlay

    def test_multiple_config_with_optional_overlay(self):
        """Test that optional overlay config is skipped if missing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            etc_dir = Path(tmpdir) / "etc"
            etc_dir.mkdir()

            # Only create base config, not the overlay
            (etc_dir / "config.yaml").write_text(
                "from_base: true\nlogging:\n  level: info\n"
            )

            # Chain: required base + optional overlay (missing)
            app = (
                AppBuilder("test-app")
                .with_config_file("config.yaml")
                .with_config_file("env.yaml", optional=True)
                .build()
            )

            with patch.object(sys, "argv", ["test", "--etc-dir", str(etc_dir)]):
                app.create_args()
                app._parsed_args = app.parser.parse_args()
                app._load_and_merge_config()

            # Base config should be loaded
            assert app.config.from_base is True
            assert app.config.logging.level == "info"

            # Warning about missing optional config
            assert hasattr(app, "_config_load_warnings")
            assert len(app._config_load_warnings) == 1
            assert "env.yaml" in app._config_load_warnings[0][0]

    def test_absolute_path_loads_immediately(self):
        """Test that absolute path config loads immediately, not from etc-dir."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create config in a specific location (not etc-dir)
            config_path = Path(tmpdir) / "direct_config.yaml"
            config_path.write_text("direct_load: true\nlogging:\n  level: trace\n")

            # Use absolute path
            app = AppBuilder("test-app").with_config_file(str(config_path)).build()

            # Config should already be loaded (no need for etc-dir)
            assert hasattr(app.config, "direct_load")
            assert app.config.direct_load is True

    def test_from_etc_dir_false_loads_from_cwd(self):
        """Test that from_etc_dir=False loads relative to cwd."""
        import os

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create config in tmpdir
            config_path = Path(tmpdir) / "local_config.yaml"
            config_path.write_text("local_load: true\nlogging:\n  level: info\n")

            # Change to tmpdir and load with from_etc_dir=False
            old_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)
                app = (
                    AppBuilder("test-app")
                    .with_config_file("local_config.yaml", from_etc_dir=False)
                    .build()
                )

                # Config should already be loaded
                assert hasattr(app.config, "local_load")
                assert app.config.local_load is True
            finally:
                os.chdir(old_cwd)


@pytest.mark.e2e
class TestConfigSectionIncludeWorkflow:
    """E2E tests for section includes with variable resolution."""

    def test_section_include_resolves_sibling_variables(self):
        """Test that !include with section resolves ${sibling.key} variables.

        This is the main use case from the ticket: when including a section from
        a file, variables referencing other sections in that file should resolve.

        Example:
            # pg.yaml
            pgserver:
              port: 7632
              user: postgres
            dbs:
              main:
                url: "postgresql://${pgserver.user}:@127.0.0.1:${pgserver.port}/learn"

            # app.yaml
            learn:
              db: !include './pg.yaml#dbs.main'

        Expected: db.url = "postgresql://postgres:@127.0.0.1:7632/learn"
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            etc_dir = Path(tmpdir) / "etc"
            etc_dir.mkdir()

            # Create pg.yaml with sibling sections
            (etc_dir / "pg.yaml").write_text(
                "pgserver:\n"
                "  port: 7632\n"
                "  user: postgres\n"
                "dbs:\n"
                "  main:\n"
                '    url: "postgresql://${pgserver.user}:@127.0.0.1:${pgserver.port}/learn"\n'
            )

            # Create main config that includes a section
            (etc_dir / "app.yaml").write_text(
                "learn:\n  db: !include './pg.yaml#dbs.main'\nlogging:\n  level: info\n"
            )

            app = AppBuilder("test-app").with_config_file("app.yaml").build()

            with patch.object(sys, "argv", ["test", "--etc-dir", str(etc_dir)]):
                app.create_args()
                app._parsed_args = app.parser.parse_args()
                app._load_and_merge_config()

            # Verify sibling variables were resolved
            assert (
                app.config.learn.db.url == "postgresql://postgres:@127.0.0.1:7632/learn"
            )

    def test_section_include_with_nested_structure(self):
        """Test section include with nested configuration structure.

        Verifies that complex nested structures with multiple variable references
        all resolve correctly when using section includes.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            etc_dir = Path(tmpdir) / "etc"
            etc_dir.mkdir()

            # Create config with nested structure and multiple var references
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

            app = AppBuilder("test-app").with_config_file("app.yaml").build()

            with patch.object(sys, "argv", ["test", "--etc-dir", str(etc_dir)]):
                app.create_args()
                app._parsed_args = app.parser.parse_args()
                app._load_and_merge_config()

            # All sibling variables should be resolved
            assert app.config.database.host == "localhost"
            assert app.config.database.port == "5432"
            assert app.config.database.user == "admin"
            assert app.config.database.pool_size == 10

    def test_document_level_section_include_resolves_vars(self):
        """Test document-level !include with section resolves variables."""
        with tempfile.TemporaryDirectory() as tmpdir:
            etc_dir = Path(tmpdir) / "etc"
            etc_dir.mkdir()

            # Create base config with multiple sections
            (etc_dir / "base.yaml").write_text(
                "common:\n"
                "  version: '2.0'\n"
                "production:\n"
                "  app_version: '${common.version}'\n"
                "  debug: false\n"
            )

            # Document-level include with section selector
            (etc_dir / "app.yaml").write_text(
                "!include './base.yaml#production'\n"
                "\n"
                "name: myapp\n"
                "logging:\n"
                "  level: info\n"
            )

            app = AppBuilder("test-app").with_config_file("app.yaml").build()

            with patch.object(sys, "argv", ["test", "--etc-dir", str(etc_dir)]):
                app.create_args()
                app._parsed_args = app.parser.parse_args()
                app._load_and_merge_config()

            # Variable should be resolved
            assert app.config.app_version == "2.0"
            assert app.config.debug is False
            assert app.config.name == "myapp"


@pytest.mark.e2e
class TestConfigIncludeErrorWorkflow:
    """E2E tests for config file include error handling workflow."""

    def test_include_error_raises_for_required_config(self):
        """Test that !include errors raise immediately for required config files.

        Required config files (optional=False) should fail fast on YAML errors
        including !include failures, ensuring the app doesn't run with incomplete
        configuration.
        """
        import yaml

        with tempfile.TemporaryDirectory() as tmpdir:
            etc_dir = Path(tmpdir) / "etc"
            etc_dir.mkdir()

            # Create config with a !include that references a missing file
            config_content = """name: test-app
database: !include "./missing-db.yaml"
logging:
  level: info
"""
            (etc_dir / "app.yaml").write_text(config_content)

            # Build app with required config file (default)
            app = AppBuilder("test-app").with_config_file("app.yaml").build()

            with patch.object(sys, "argv", ["test", "--etc-dir", str(etc_dir)]):
                app.create_args()
                app._parsed_args = app.parser.parse_args()

                # Load config - this should RAISE for required configs
                with pytest.raises(yaml.YAMLError) as exc_info:
                    app._load_and_merge_config()

                # Error should include location info
                error_str = str(exc_info.value)
                assert "missing-db.yaml" in error_str
                assert "line 2" in error_str

    def test_include_error_logged_for_optional_config(self):
        """Test that !include errors are logged (not raised) for optional config files.

        Optional config files should store errors and continue, allowing
        the app to run with partial configuration while warning the user.
        """
        from unittest.mock import MagicMock

        with tempfile.TemporaryDirectory() as tmpdir:
            etc_dir = Path(tmpdir) / "etc"
            etc_dir.mkdir()

            # Create config with a !include that references a missing file
            config_content = """name: test-app
database: !include "./missing-db.yaml"
logging:
  level: info
"""
            (etc_dir / "app.yaml").write_text(config_content)

            # Build app with OPTIONAL config file
            app = (
                AppBuilder("test-app")
                .with_config_file("app.yaml", optional=True)
                .build()
            )

            with patch.object(sys, "argv", ["test", "--etc-dir", str(etc_dir)]):
                app.create_args()
                app._parsed_args = app.parser.parse_args()

                # Load config - should store error, not raise
                app._load_and_merge_config()

                # Verify error was stored
                assert hasattr(app, "_config_load_errors")
                assert len(app._config_load_errors) == 1
                filename, error = app._config_load_errors[0]
                assert filename == "app.yaml"
                assert "missing-db.yaml" in str(error)
                # Error should include location info
                assert "line 2" in str(error)

                # Initialize lifecycle to get logger
                app.lifecycle.initialize(app.config)

                # Mock the logger to capture the warning
                mock_logger = MagicMock()
                app.lifecycle._logger = mock_logger

                # Log the config loading results - this should log the stored error
                app._log_config_loading(None)

                # Verify warning was logged with correct info
                mock_logger.warning.assert_called_once()
                call_args = mock_logger.warning.call_args
                assert call_args[0][0] == "failed to load config file"
                assert call_args[1]["extra"]["file"] == "app.yaml"
                assert "missing-db.yaml" in str(call_args[1]["extra"]["exception"])

    def test_document_level_include_error_raises_for_required(self):
        """Test that document-level !include errors raise for required configs."""
        import yaml

        with tempfile.TemporaryDirectory() as tmpdir:
            etc_dir = Path(tmpdir) / "etc"
            etc_dir.mkdir()

            # Document-level include (at column 0)
            config_content = """!include "./missing-base.yaml"

name: test-app
"""
            (etc_dir / "app.yaml").write_text(config_content)

            app = AppBuilder("test-app").with_config_file("app.yaml").build()

            with patch.object(sys, "argv", ["test", "--etc-dir", str(etc_dir)]):
                app.create_args()
                app._parsed_args = app.parser.parse_args()

                # Should raise for required config
                with pytest.raises(yaml.YAMLError) as exc_info:
                    app._load_and_merge_config()

                # Verify error includes location info
                error_str = str(exc_info.value)
                assert "missing-base.yaml" in error_str
                # Document-level include should have line 1
                assert "line 1" in error_str


@pytest.mark.e2e
class TestLogOutputCliOverrides:
    """E2E tests for --log-json and --no-log-colors CLI overrides."""

    def test_log_json_overrides_yaml_text_format(self):
        """Test that --log-json CLI arg overrides YAML text format to JSON."""
        from appinfra.log.builder.console import ConsoleHandlerConfig

        with tempfile.TemporaryDirectory() as tmpdir:
            etc_dir = Path(tmpdir) / "etc"
            etc_dir.mkdir()

            # Create config with text format handler
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

            app = AppBuilder("test-app").with_config_file("app.yaml").build()

            # Pass --log-json to override YAML format
            with patch.object(
                sys, "argv", ["test", "--etc-dir", str(etc_dir), "--log-json"]
            ):
                try:
                    app.setup()

                    # Verify the handler was overridden to JSON format
                    # The handler_registry tracks all handlers
                    registry = app.lifecycle._handler_registry
                    handlers = list(registry.iter_enabled_handlers())
                    assert len(handlers) >= 1

                    # Find console handler and verify JSON format
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

            # Create config with colors enabled
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

            app = AppBuilder("test-app").with_config_file("app.yaml").build()

            # Pass --no-log-colors to override YAML colors
            with patch.object(
                sys, "argv", ["test", "--etc-dir", str(etc_dir), "--no-log-colors"]
            ):
                try:
                    app.setup()

                    # Verify the handler was overridden to no colors
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

            # Create config with text format and colors
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

            app = AppBuilder("test-app").with_config_file("app.yaml").build()

            # Pass both flags
            with patch.object(
                sys,
                "argv",
                ["test", "--etc-dir", str(etc_dir), "--log-json", "--no-log-colors"],
            ):
                try:
                    app.setup()

                    # Verify JSON format wins (colors don't apply to JSON anyway)
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

            # Create config with multiple console handlers
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

            app = AppBuilder("test-app").with_config_file("app.yaml").build()

            # Pass --log-json to override both handlers
            with patch.object(
                sys, "argv", ["test", "--etc-dir", str(etc_dir), "--log-json"]
            ):
                try:
                    app.setup()

                    # Verify all console handlers were overridden to JSON
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

            # Create minimal config without handlers
            (etc_dir / "app.yaml").write_text("logging:\n  level: info\n")

            app = AppBuilder("test-app").with_config_file("app.yaml").build()

            # Pass --log-json - should apply to default handler
            with patch.object(
                sys, "argv", ["test", "--etc-dir", str(etc_dir), "--log-json"]
            ):
                try:
                    app.setup()

                    # Verify default handler uses JSON format
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

            # Create minimal config without handlers
            (etc_dir / "app.yaml").write_text("logging:\n  level: info\n")

            app = AppBuilder("test-app").with_config_file("app.yaml").build()

            # Pass --no-log-colors - should apply to default handler
            with patch.object(
                sys, "argv", ["test", "--etc-dir", str(etc_dir), "--no-log-colors"]
            ):
                try:
                    app.setup()

                    # Verify default handler has colors disabled
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
