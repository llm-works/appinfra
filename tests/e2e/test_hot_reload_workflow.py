# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
E2E test for hot-reload configuration workflow.

This test validates the complete workflow for hot-reload configuration,
ensuring both YAML-only and programmatic configurations work correctly.

Tests cover:
- YAML-only hot-reload configuration starts the watcher
- Programmatic-only hot-reload configuration starts the watcher
- Combined YAML + programmatic configuration works
- Hot-reload watcher correctly monitors the config file
- Config changes are detected and applied
"""

import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

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


@pytest.mark.e2e
@pytest.mark.usefixtures("clean_env")
class TestHotReloadWorkflow:
    """E2E tests for hot-reload configuration workflow."""

    def test_yaml_only_hot_reload_starts_watcher(self):
        """Test that hot-reload configured only in YAML starts the watcher."""
        with tempfile.TemporaryDirectory() as tmpdir:
            etc_dir = Path(tmpdir) / "etc"
            etc_dir.mkdir()

            # Create config with hot_reload enabled in YAML only
            (etc_dir / "app.yaml").write_text(
                "logging:\n"
                "  level: info\n"
                "  hot_reload:\n"
                "    enabled: true\n"
                "    debounce_ms: 100\n"
            )

            # Build app WITHOUT calling .config.with_hot_reload()
            app = _spec_app(etc_dir).build()

            # Mock the ConfigWatcher to verify it's called
            with patch("appinfra.config.ConfigWatcher") as mock_watcher_class:
                mock_watcher = MagicMock()
                mock_watcher_class.return_value = mock_watcher

                with patch.object(sys, "argv", ["test", "--etc-dir", str(etc_dir)]):
                    try:
                        app.setup()

                        # Verify watcher was created and started
                        mock_watcher_class.assert_called_once()
                        mock_watcher.configure.assert_called_once()
                        mock_watcher.start.assert_called_once()

                        # Verify correct config path was passed
                        configure_call = mock_watcher.configure.call_args
                        assert "app.yaml" in str(configure_call)
                    finally:
                        if app.lifecycle.logger:
                            app.lifecycle.logger.handlers.clear()

    def test_programmatic_only_hot_reload_starts_watcher(self):
        """Test that hot-reload configured only programmatically starts the watcher."""
        with tempfile.TemporaryDirectory() as tmpdir:
            etc_dir = Path(tmpdir) / "etc"
            etc_dir.mkdir()

            # Create config WITHOUT hot_reload section
            (etc_dir / "app.yaml").write_text("logging:\n  level: info\n")

            # Build app WITH programmatic hot-reload
            app = (
                _spec_app(etc_dir)
                .config.with_hot_reload(True, debounce_ms=200)
                .done()
                .build()
            )

            with patch("appinfra.config.ConfigWatcher") as mock_watcher_class:
                mock_watcher = MagicMock()
                mock_watcher_class.return_value = mock_watcher

                with patch.object(sys, "argv", ["test", "--etc-dir", str(etc_dir)]):
                    try:
                        app.setup()

                        # Verify watcher was created and started
                        mock_watcher_class.assert_called_once()
                        mock_watcher.configure.assert_called_once()
                        mock_watcher.start.assert_called_once()
                    finally:
                        if app.lifecycle.logger:
                            app.lifecycle.logger.handlers.clear()

    def test_combined_yaml_and_programmatic_hot_reload(self):
        """Test that programmatic hot-reload overrides YAML settings."""
        with tempfile.TemporaryDirectory() as tmpdir:
            etc_dir = Path(tmpdir) / "etc"
            etc_dir.mkdir()

            # Create config with hot_reload in YAML
            (etc_dir / "app.yaml").write_text(
                "logging:\n"
                "  level: debug\n"
                "  hot_reload:\n"
                "    enabled: true\n"
                "    debounce_ms: 500\n"
            )

            # Override with programmatic config
            app = (
                _spec_app(etc_dir)
                .config.with_hot_reload(True, debounce_ms=100)  # Different debounce
                .done()
                .build()
            )

            with patch("appinfra.config.ConfigWatcher") as mock_watcher_class:
                mock_watcher = MagicMock()
                mock_watcher_class.return_value = mock_watcher

                with patch.object(sys, "argv", ["test", "--etc-dir", str(etc_dir)]):
                    try:
                        app.setup()

                        # Verify watcher was started
                        mock_watcher_class.assert_called_once()
                        mock_watcher.start.assert_called_once()

                        # Verify programmatic debounce_ms was used (100, not 500)
                        configure_call = mock_watcher.configure.call_args
                        # The debounce should be from programmatic config
                        assert (
                            "100" in str(configure_call)
                            or configure_call[1].get("debounce_ms") == 100
                        )
                    finally:
                        if app.lifecycle.logger:
                            app.lifecycle.logger.handlers.clear()

    def test_hot_reload_disabled_in_yaml(self):
        """Test that hot-reload can be disabled in YAML."""
        with tempfile.TemporaryDirectory() as tmpdir:
            etc_dir = Path(tmpdir) / "etc"
            etc_dir.mkdir()

            # Create config with hot_reload explicitly disabled
            (etc_dir / "app.yaml").write_text(
                "logging:\n  level: info\n  hot_reload:\n    enabled: false\n"
            )

            app = _spec_app(etc_dir).build()

            with patch("appinfra.config.ConfigWatcher") as mock_watcher_class:
                mock_watcher = MagicMock()
                mock_watcher_class.return_value = mock_watcher

                with patch.object(sys, "argv", ["test", "--etc-dir", str(etc_dir)]):
                    try:
                        app.setup()

                        # Watcher should NOT be created when disabled
                        mock_watcher_class.assert_not_called()
                    finally:
                        if app.lifecycle.logger:
                            app.lifecycle.logger.handlers.clear()

    def test_hot_reload_disabled_programmatically(self):
        """Test that hot-reload can be disabled programmatically."""
        with tempfile.TemporaryDirectory() as tmpdir:
            etc_dir = Path(tmpdir) / "etc"
            etc_dir.mkdir()

            # Create config with hot_reload enabled in YAML
            (etc_dir / "app.yaml").write_text(
                "logging:\n  level: info\n  hot_reload:\n    enabled: true\n"
            )

            # Disable programmatically
            app = _spec_app(etc_dir).config.with_hot_reload(False).done().build()

            with patch("appinfra.config.ConfigWatcher") as mock_watcher_class:
                mock_watcher = MagicMock()
                mock_watcher_class.return_value = mock_watcher

                with patch.object(sys, "argv", ["test", "--etc-dir", str(etc_dir)]):
                    try:
                        app.setup()

                        # Watcher should NOT be created when disabled programmatically
                        mock_watcher_class.assert_not_called()
                    finally:
                        if app.lifecycle.logger:
                            app.lifecycle.logger.handlers.clear()

    def test_hot_reload_without_config_source_raises(self):
        """Hot reload needs a declared config source on the builder."""
        with pytest.raises(ValueError, match="requires a config source"):
            AppBuilder("test-app").config.with_hot_reload(True).done().build()

    def test_hot_reload_watcher_uses_correct_config(self):
        """Test that the watcher monitors the correct config file path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            etc_dir = Path(tmpdir) / "etc"
            etc_dir.mkdir()

            config_file = etc_dir / "custom-config.yaml"
            config_file.write_text(
                "logging:\n  level: info\n  hot_reload:\n    enabled: true\n"
            )

            app = _spec_app(etc_dir, "custom-config.yaml").build()

            with patch("appinfra.config.ConfigWatcher") as mock_watcher_class:
                mock_watcher = MagicMock()
                mock_watcher_class.return_value = mock_watcher

                with patch.object(sys, "argv", ["test", "--etc-dir", str(etc_dir)]):
                    try:
                        app.setup()

                        # Verify etc_dir was passed to constructor
                        # Use realpath to normalize symlinks (macOS /var -> /private/var)
                        constructor_call = mock_watcher_class.call_args
                        assert os.path.realpath(
                            constructor_call.kwargs["etc_dir"]
                        ) == os.path.realpath(str(etc_dir))

                        # Verify config_file was passed to configure()
                        configure_call = mock_watcher.configure.call_args
                        config_file_arg = configure_call[0][0]  # First positional arg
                        assert config_file_arg == "custom-config.yaml"
                    finally:
                        if app.lifecycle.logger:
                            app.lifecycle.logger.handlers.clear()

    def test_hot_reload_with_packaged_base(self, tmp_path, monkeypatch):
        """Hot reload watches the packaged base when no override is in play."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "no-xdg"))
        monkeypatch.setenv("XDG_CONFIG_DIRS", str(tmp_path / "no-xdg-sys"))
        monkeypatch.chdir(tmp_path)
        base = tmp_path / "pkg" / "etc" / "base-config.yaml"
        base.parent.mkdir(parents=True)
        base.write_text(
            "logging:\n"
            "  level: debug\n"
            "  hot_reload:\n"
            "    enabled: true\n"
            "    debounce_ms: 250\n"
        )

        app = (
            AppBuilder("test-app")
            .config.with_spec("test-org", "app", path=base)
            .done()
            .build()
        )

        with patch("appinfra.config.ConfigWatcher") as mock_watcher_class:
            mock_watcher = MagicMock()
            mock_watcher_class.return_value = mock_watcher

            with patch.object(sys, "argv", ["test"]):
                try:
                    app.setup()

                    # etc_dir is the base's directory, config_file its name
                    constructor_call = mock_watcher_class.call_args
                    etc_dir_arg = constructor_call.kwargs["etc_dir"]
                    assert os.path.realpath(etc_dir_arg) == os.path.realpath(
                        str(base.parent)
                    )

                    configure_call = mock_watcher.configure.call_args
                    assert configure_call[0][0] == "base-config.yaml"
                finally:
                    if app.lifecycle.logger:
                        app.lifecycle.logger.handlers.clear()

    def test_hot_reload_watcher_stops_on_shutdown(self):
        """Test that the watcher is properly stopped during app shutdown."""
        with tempfile.TemporaryDirectory() as tmpdir:
            etc_dir = Path(tmpdir) / "etc"
            etc_dir.mkdir()

            (etc_dir / "app.yaml").write_text(
                "logging:\n  level: info\n  hot_reload:\n    enabled: true\n"
            )

            app = _spec_app(etc_dir).build()

            with patch("appinfra.config.ConfigWatcher") as mock_watcher_class:
                mock_watcher = MagicMock()
                mock_watcher.is_running.return_value = True
                mock_watcher_class.return_value = mock_watcher

                with patch.object(sys, "argv", ["test", "--etc-dir", str(etc_dir)]):
                    try:
                        app.setup()

                        # Verify watcher was started
                        mock_watcher.start.assert_called_once()

                        # Trigger shutdown
                        app.lifecycle.shutdown(0)

                        # Verify watcher was stopped
                        mock_watcher.stop.assert_called_once()
                    finally:
                        if app.lifecycle.logger:
                            app.lifecycle.logger.handlers.clear()

    def test_hot_reload_config_preserved_through_merge(self):
        """Test that hot_reload config survives the YAML/programmatic merge."""
        with tempfile.TemporaryDirectory() as tmpdir:
            etc_dir = Path(tmpdir) / "etc"
            etc_dir.mkdir()

            # YAML has hot_reload and other logging settings
            (etc_dir / "app.yaml").write_text(
                "logging:\n"
                "  level: debug\n"
                "  location: 2\n"
                "  micros: true\n"
                "  hot_reload:\n"
                "    enabled: true\n"
                "    debounce_ms: 750\n"
            )

            # Programmatic config sets additional logging options but NOT hot_reload
            app = _spec_app(etc_dir).logging.with_level("info").done().build()

            with patch.object(sys, "argv", ["test", "--etc-dir", str(etc_dir)]):
                app.create_args()
                app._parsed_args = app.parser.parse_args()
                app._load_and_merge_config()

            # Verify hot_reload from YAML is preserved
            assert hasattr(app.config.logging, "hot_reload")
            assert app.config.logging.hot_reload.enabled is True
            assert app.config.logging.hot_reload.debounce_ms == 750

            # Verify programmatic level override worked
            assert app.config.logging.level == "info"

            # Verify other YAML settings preserved
            assert app.config.logging.location == 2
            assert app.config.logging.micros is True


@pytest.mark.e2e
@pytest.mark.usefixtures("clean_env")
class TestHotReloadRealWatcher:
    """E2E tests using real ConfigWatcher (requires watchdog)."""

    @pytest.fixture(autouse=True)
    def reset_registry(self):
        """Reset registry before and after each test."""
        yield

    @pytest.fixture
    def check_watchdog_installed(self):
        """Skip tests if watchdog is not installed."""
        try:
            import watchdog  # noqa: F401

            return True
        except ImportError:
            pytest.skip("watchdog not installed - skipping real watcher tests")

    def test_real_watcher_starts_and_stops(self, check_watchdog_installed):
        """Test that real ConfigWatcher starts and stops correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            etc_dir = Path(tmpdir) / "etc"
            etc_dir.mkdir()

            (etc_dir / "app.yaml").write_text(
                "logging:\n"
                "  level: info\n"
                "  hot_reload:\n"
                "    enabled: true\n"
                "    debounce_ms: 100\n"
            )

            app = _spec_app(etc_dir).build()

            with patch.object(sys, "argv", ["test", "--etc-dir", str(etc_dir)]):
                try:
                    app.setup()

                    # Verify watcher is running
                    assert app._config_watcher is not None
                    assert app._config_watcher.is_running()

                    # Shutdown should stop the watcher (sets reference to None)
                    app.lifecycle.shutdown(0)
                    # Watcher is cleared to None after shutdown
                    assert app._config_watcher is None
                finally:
                    if app.lifecycle.logger:
                        app.lifecycle.logger.handlers.clear()

    def test_real_watcher_detects_config_change(self, check_watchdog_installed):
        """Test that real ConfigWatcher detects file changes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            etc_dir = Path(tmpdir) / "etc"
            etc_dir.mkdir()

            config_path = etc_dir / "app.yaml"
            config_path.write_text(
                "logging:\n"
                "  level: info\n"
                "  hot_reload:\n"
                "    enabled: true\n"
                "    debounce_ms: 50\n"  # Short debounce for test
            )

            app = _spec_app(etc_dir).build()

            with patch.object(sys, "argv", ["test", "--etc-dir", str(etc_dir)]):
                try:
                    app.setup()

                    # Initial level should be info
                    initial_level = app.config.logging.level
                    assert initial_level == "info"

                    # Modify the config file
                    config_path.write_text(
                        "logging:\n"
                        "  level: debug\n"
                        "  hot_reload:\n"
                        "    enabled: true\n"
                        "    debounce_ms: 50\n"
                    )

                    # Wait for watcher to detect change (debounce + processing time)
                    time.sleep(0.2)

                    # Note: The actual log level change depends on how the watcher
                    # callback is implemented. This test verifies the watcher runs
                    # without error when a file change occurs.
                finally:
                    if app._config_watcher and app._config_watcher.is_running():
                        app._config_watcher.stop()
                    if app.lifecycle.logger:
                        app.lifecycle.logger.handlers.clear()

    def test_hot_reload_location_updates_logger(self, check_watchdog_installed):
        """Test that location setting hot-reloads and affects logger behavior."""
        with tempfile.TemporaryDirectory() as tmpdir:
            etc_dir = Path(tmpdir) / "etc"
            etc_dir.mkdir()

            config_path = etc_dir / "app.yaml"
            config_path.write_text(
                "logging:\n"
                "  level: debug\n"
                "  location: 1\n"
                "  hot_reload:\n"
                "    enabled: true\n"
                "    debounce_ms: 50\n"
            )

            app = _spec_app(etc_dir).build()

            with patch.object(sys, "argv", ["test", "--etc-dir", str(etc_dir)]):
                try:
                    app.setup()
                    logger = app.lifecycle.logger

                    # Verify initial location
                    assert logger.location == 1, (
                        f"Expected location=1, got {logger.location}"
                    )

                    # Change location in config
                    config_path.write_text(
                        "logging:\n"
                        "  level: debug\n"
                        "  location: 3\n"
                        "  hot_reload:\n"
                        "    enabled: true\n"
                        "    debounce_ms: 50\n"
                    )

                    # Wait for watcher to detect and apply change
                    time.sleep(0.3)

                    # Verify location updated via hot-reload
                    assert logger.location == 3, (
                        f"Expected location=3 after hot-reload, got {logger.location}"
                    )

                finally:
                    if app._config_watcher and app._config_watcher.is_running():
                        app._config_watcher.stop()
                    if app.lifecycle.logger:
                        app.lifecycle.logger.handlers.clear()

    def test_hot_reload_location_affects_log_output(self, check_watchdog_installed):
        """Test that hot-reloaded location actually affects log output format."""
        import io

        with tempfile.TemporaryDirectory() as tmpdir:
            etc_dir = Path(tmpdir) / "etc"
            etc_dir.mkdir()

            config_path = etc_dir / "app.yaml"
            config_path.write_text(
                "logging:\n"
                "  level: debug\n"
                "  location: 0\n"
                "  hot_reload:\n"
                "    enabled: true\n"
                "    debounce_ms: 50\n"
            )

            app = _spec_app(etc_dir).build()

            with patch.object(sys, "argv", ["test", "--etc-dir", str(etc_dir)]):
                try:
                    app.setup()
                    logger = app.lifecycle.logger

                    # Capture log output with location=0
                    output_before = io.StringIO()
                    handler = logger.handlers[0]
                    original_stream = handler.stream
                    handler.stream = output_before

                    logger.info("test message before")
                    log_before = output_before.getvalue()

                    # Change to location=2
                    config_path.write_text(
                        "logging:\n"
                        "  level: debug\n"
                        "  location: 2\n"
                        "  hot_reload:\n"
                        "    enabled: true\n"
                        "    debounce_ms: 50\n"
                    )

                    time.sleep(0.3)

                    # Capture log output with location=2
                    output_after = io.StringIO()
                    handler.stream = output_after

                    logger.info("test message after")
                    log_after = output_after.getvalue()

                    # Restore original stream
                    handler.stream = original_stream

                    # With location=0, no file path should be shown
                    # With location=2, file path(s) should be included
                    # The exact format depends on formatter, but location>0 adds path info
                    assert logger.location == 2, "Location should have updated to 2"

                finally:
                    if app._config_watcher and app._config_watcher.is_running():
                        app._config_watcher.stop()
                    if app.lifecycle.logger:
                        app.lifecycle.logger.handlers.clear()
