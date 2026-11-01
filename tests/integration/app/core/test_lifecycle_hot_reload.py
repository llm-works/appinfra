# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for lifecycle hot-reload with apps built from YAML config files."""

from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.usefixtures("clean_env")
class TestHotReloadYamlOnlyIntegration:
    """Integration tests for hot-reload with YAML-only configuration."""

    @pytest.fixture(autouse=True)
    def isolate_resolution(self, tmp_path, monkeypatch):
        """Keep the spec's base the winning file: no XDG overlay, no walk-up hit."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "no-xdg"))
        monkeypatch.setenv("XDG_CONFIG_DIRS", str(tmp_path / "no-xdg-sys"))
        monkeypatch.chdir(tmp_path)

    def test_yaml_only_hot_reload_detects_config(self, tmp_path):
        """
        Hot-reload should work with YAML configuration alone.

        This is a regression test for the bug where YAML-only config
        was silently ignored and required redundant programmatic config.
        """
        from appinfra.app.builder import AppBuilder

        # Create temp YAML with hot_reload enabled
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            """
logging:
  level: info
  hot_reload:
    enabled: true
    debounce_ms: 500
"""
        )

        # Build app with just a spec, no with_hot_reload()
        app = (
            AppBuilder("test-app")
            .config.with_spec("test-org", "config", path=config_file)
            .done()
            .build()
        )

        # Mock parsed args to avoid argparse trying to parse pytest args
        app._parsed_args = MagicMock()
        app._parsed_args.etc_dir = None
        app._parsed_args.config = None
        app._parsed_args.log_level = None
        app._parsed_args.log_location = None
        app._parsed_args.log_micros = None
        app._parsed_args.quiet = False
        app._parsed_args.default_tool = None
        app._parsed_args.tool = None

        # Mock the parser to return our mocked args
        app.parser.parse_args = MagicMock(return_value=app._parsed_args)

        # After setup, verify hot_reload config is detected
        # We mock the watcher to avoid needing watchdog installed
        with patch("appinfra.config.ConfigWatcher") as mock_watcher_class:
            mock_watcher = MagicMock()
            mock_watcher_class.return_value = mock_watcher

            # Run setup (this triggers config loading and lifecycle.initialize)
            app.setup()

            # Verify: watcher was created and started
            mock_watcher_class.assert_called_once()
            mock_watcher.configure.assert_called_once()
            mock_watcher.start.assert_called_once()

            # Verify config file was passed correctly (filename only, not full path)
            configure_args = mock_watcher.configure.call_args
            assert "config.yaml" in str(configure_args)

    def test_programmatic_only_hot_reload(self, tmp_path):
        """
        Test programmatic-only hot-reload (no hot_reload in YAML).

        This tests whether .config.with_hot_reload(True) works when YAML
        doesn't have the hot_reload section.
        """
        from appinfra.app.builder import AppBuilder

        # Create YAML without hot_reload section
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            """
logging:
  level: info
"""
        )

        # Build app with programmatic hot-reload
        app = (
            AppBuilder("test-app")
            .config.with_spec("test-org", "config", path=config_file)
            .with_hot_reload(True)
            .done()
            .build()
        )

        # Mock parsed args
        app._parsed_args = MagicMock()
        app._parsed_args.etc_dir = None
        app._parsed_args.config = None
        app._parsed_args.log_level = None
        app._parsed_args.log_location = None
        app._parsed_args.log_micros = None
        app._parsed_args.quiet = False
        app._parsed_args.default_tool = None
        app._parsed_args.tool = None

        app.parser.parse_args = MagicMock(return_value=app._parsed_args)

        with patch("appinfra.config.ConfigWatcher") as mock_watcher_class:
            mock_watcher = MagicMock()
            mock_watcher_class.return_value = mock_watcher

            app.setup()

            # Verify: watcher was created and started
            mock_watcher_class.assert_called_once()
            mock_watcher.configure.assert_called_once()
            mock_watcher.start.assert_called_once()

    def test_yaml_hot_reload_config_preserved_after_merge(self, tmp_path):
        """Verify hot_reload section survives config merging."""
        from appinfra.app.builder import AppBuilder

        # Create temp YAML with hot_reload enabled
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            """
logging:
  level: debug
  hot_reload:
    enabled: true
    debounce_ms: 1000
"""
        )

        # Build app with config file
        app = (
            AppBuilder("test-app")
            .config.with_spec("test-org", "config", path=config_file)
            .done()
            .build()
        )

        # Manually trigger config loading (partial setup)
        app._parsed_args = MagicMock()
        app._parsed_args.etc_dir = None
        app._parsed_args.config = None
        app._parsed_args.log_level = None
        app._parsed_args.log_location = None
        app._parsed_args.log_micros = None
        app._parsed_args.quiet = False
        app._parsed_args.default_tool = None

        # Load and merge config
        app._load_and_merge_config()

        # Assert: hot_reload section exists in merged config
        assert hasattr(app.config, "logging"), "Config should have logging section"
        assert hasattr(app.config.logging, "hot_reload"), (
            "logging should have hot_reload section"
        )
        assert app.config.logging.hot_reload.enabled is True, (
            "hot_reload.enabled should be True"
        )
        assert app.config.logging.hot_reload.debounce_ms == 1000, (
            "hot_reload.debounce_ms should be 1000"
        )

    def test_yaml_only_with_etc_dir_hot_reload(self, tmp_path):
        """Test YAML-only hot-reload with the file selected via --etc-dir."""
        from appinfra.app.builder import AppBuilder

        # Create etc directory with config
        etc_dir = tmp_path / "etc"
        etc_dir.mkdir()
        config_file = etc_dir / "config.yaml"
        config_file.write_text(
            """
logging:
  level: info
  hot_reload:
    enabled: true
    debounce_ms: 500
"""
        )

        # The spec's base lives elsewhere; --etc-dir redirects the load.
        app = (
            AppBuilder("test-app")
            .cli(etc_dir=True)
            .config.with_spec(
                "test-org", "config", path=tmp_path / "pkg" / "config.yaml"
            )
            .done()
            .build()
        )

        # Mock parsed args to specify etc_dir
        app._parsed_args = MagicMock()
        app._parsed_args.etc_dir = str(etc_dir)
        app._parsed_args.config = None
        app._parsed_args.log_level = None
        app._parsed_args.log_location = None
        app._parsed_args.log_micros = None
        app._parsed_args.quiet = False
        app._parsed_args.default_tool = None
        app._parsed_args.tool = None

        app.parser.parse_args = MagicMock(return_value=app._parsed_args)

        with patch("appinfra.config.ConfigWatcher") as mock_watcher_class:
            mock_watcher = MagicMock()
            mock_watcher_class.return_value = mock_watcher

            app.setup()

            # Verify: watcher was created and started
            mock_watcher_class.assert_called_once()
            mock_watcher.configure.assert_called_once()
            mock_watcher.start.assert_called_once()
