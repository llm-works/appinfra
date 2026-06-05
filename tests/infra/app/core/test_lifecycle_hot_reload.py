"""Tests for lifecycle manager hot-reload functionality."""

import sys
from unittest.mock import MagicMock, patch

import pytest

from appinfra.app.core.lifecycle import LifecycleManager
from appinfra.dot_dict import DotDict


@pytest.fixture
def lifecycle_manager():
    """Create a lifecycle manager with mock application."""
    app = MagicMock()
    app._etc_dir = None
    app._config_file = None
    app._config_watcher = None
    return LifecycleManager(app)


@pytest.fixture
def mock_config_with_hot_reload():
    """Create config with hot_reload enabled."""
    return DotDict(
        logging=DotDict(
            level="info",
            hot_reload=DotDict(
                enabled=True,
                debounce_ms=500,
            ),
        )
    )


@pytest.fixture
def mock_config_without_hot_reload():
    """Create config without hot_reload."""
    return DotDict(logging=DotDict(level="info"))


@pytest.mark.unit
class TestGetHotReloadConfig:
    """Tests for _get_hot_reload_config method."""

    def test_returns_none_when_no_logging_section(self, lifecycle_manager):
        """Test returns None when config has no logging section."""
        config = DotDict()

        result = lifecycle_manager._get_hot_reload_config(config)

        assert result is None

    def test_returns_none_when_no_hot_reload_section(
        self, lifecycle_manager, mock_config_without_hot_reload
    ):
        """Test returns None when logging has no hot_reload section."""
        result = lifecycle_manager._get_hot_reload_config(
            mock_config_without_hot_reload
        )

        assert result is None

    def test_returns_none_when_hot_reload_disabled(self, lifecycle_manager):
        """Test returns None when hot_reload.enabled is False."""
        config = DotDict(logging=DotDict(hot_reload=DotDict(enabled=False)))

        result = lifecycle_manager._get_hot_reload_config(config)

        assert result is None

    def test_returns_config_when_enabled(
        self, lifecycle_manager, mock_config_with_hot_reload
    ):
        """Test returns hot_reload config when enabled."""
        result = lifecycle_manager._get_hot_reload_config(mock_config_with_hot_reload)

        assert result is not None
        assert result.enabled is True
        assert result.debounce_ms == 500


@pytest.mark.unit
class TestResolveHotReloadConfig:
    """Tests for _resolve_hot_reload_config method."""

    def test_returns_tuple_from_application(self, lifecycle_manager):
        """Test returns (etc_dir, config_file) tuple from application."""
        lifecycle_manager.application._etc_dir = "/etc/myapp"
        lifecycle_manager.application._config_file = "config.yaml"

        result = lifecycle_manager._resolve_hot_reload_config()

        assert result == ("/etc/myapp", "config.yaml")

    def test_returns_none_when_no_config(self, lifecycle_manager):
        """Test returns None when application has no etc_dir/config_file."""
        lifecycle_manager.application._etc_dir = None
        lifecycle_manager.application._config_file = None

        result = lifecycle_manager._resolve_hot_reload_config()

        assert result is None


@pytest.mark.unit
class TestStartHotReloadWatcher:
    """Tests for _start_hot_reload_watcher method."""

    def test_does_nothing_when_no_hot_reload_config(
        self, lifecycle_manager, mock_config_without_hot_reload
    ):
        """Test does nothing when hot_reload is not configured."""
        lifecycle_manager._start_hot_reload_watcher(mock_config_without_hot_reload)

        # Watcher should not be created
        assert lifecycle_manager.application._config_watcher is None

    def test_warns_when_no_config_path(self, lifecycle_manager):
        """Test warns when hot_reload enabled but no config path."""
        config = DotDict(
            logging=DotDict(hot_reload=DotDict(enabled=True))  # No config_path
        )
        lifecycle_manager._lifecycle_logger = MagicMock()
        lifecycle_manager.application._etc_dir = None
        lifecycle_manager.application._config_file = None

        lifecycle_manager._start_hot_reload_watcher(config)

        lifecycle_manager._lifecycle_logger.warning.assert_called_once()

    def test_warns_when_watchdog_not_installed(
        self, lifecycle_manager, mock_config_with_hot_reload
    ):
        """Test warns when watchdog is not installed."""
        lifecycle_manager._lifecycle_logger = MagicMock()

        # Mock the import to raise ImportError
        with patch.dict(
            sys.modules,
            {"appinfra.config": None},  # type: ignore[dict-item]
        ):
            lifecycle_manager._configure_and_start_watcher(
                mock_config_with_hot_reload.logging.hot_reload,
                "/etc/myapp",
                "config.yaml",
            )

        lifecycle_manager._lifecycle_logger.warning.assert_called_once()
        assert "watchdog not installed" in str(
            lifecycle_manager._lifecycle_logger.warning.call_args
        )

    def test_logs_error_on_exception(
        self, lifecycle_manager, mock_config_with_hot_reload
    ):
        """Test logs error when watcher fails to start."""
        lifecycle_manager._lifecycle_logger = MagicMock()

        with patch("appinfra.config.ConfigWatcher") as mock_watcher_class:
            mock_watcher_class.return_value.start.side_effect = RuntimeError(
                "Test error"
            )
            lifecycle_manager._configure_and_start_watcher(
                mock_config_with_hot_reload.logging.hot_reload,
                "/etc/myapp",
                "config.yaml",
            )

        lifecycle_manager._lifecycle_logger.error.assert_called_once()


@pytest.mark.unit
class TestStopHotReloadWatcher:
    """Tests for _stop_hot_reload_watcher method."""

    def test_stops_running_watcher(self, lifecycle_manager):
        """Test stops watcher when it's running."""
        lifecycle_manager._lifecycle_logger = MagicMock()

        mock_watcher = MagicMock()
        mock_watcher.is_running.return_value = True
        lifecycle_manager.application._config_watcher = mock_watcher

        lifecycle_manager._stop_hot_reload_watcher()

        mock_watcher.stop.assert_called_once()
        lifecycle_manager._lifecycle_logger.debug.assert_called()
        assert lifecycle_manager.application._config_watcher is None

    def test_does_nothing_when_not_running(self, lifecycle_manager):
        """Test does nothing when watcher is not running."""
        lifecycle_manager._lifecycle_logger = MagicMock()

        mock_watcher = MagicMock()
        mock_watcher.is_running.return_value = False
        lifecycle_manager.application._config_watcher = mock_watcher

        lifecycle_manager._stop_hot_reload_watcher()

        mock_watcher.stop.assert_not_called()

    def test_does_nothing_when_no_watcher(self, lifecycle_manager):
        """Test does nothing when no watcher exists."""
        lifecycle_manager.application._config_watcher = None

        # Should not raise
        lifecycle_manager._stop_hot_reload_watcher()

    def test_logs_error_on_exception(self, lifecycle_manager):
        """Test logs error on other exceptions."""
        lifecycle_manager._lifecycle_logger = MagicMock()

        mock_watcher = MagicMock()
        mock_watcher.is_running.side_effect = RuntimeError("Test error")
        lifecycle_manager.application._config_watcher = mock_watcher

        lifecycle_manager._stop_hot_reload_watcher()

        lifecycle_manager._lifecycle_logger.error.assert_called_once()


@pytest.mark.integration
class TestHotReloadYamlOnlyIntegration:
    """Integration tests for hot-reload with YAML-only configuration."""

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

        # Build app with just with_config_file(), no with_hot_reload()
        app = (
            AppBuilder("test-app")
            .with_config_file(str(config_file), from_etc_dir=False)
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

        This tests whether .logging.with_hot_reload(True) works when YAML
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
            .with_config_file(str(config_file), from_etc_dir=False)
            .logging.with_hot_reload(True)
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
            .with_config_file(str(config_file), from_etc_dir=False)
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
        """Test YAML-only hot-reload with from_etc_dir=True (default behavior)."""
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

        # Build app with from_etc_dir=True (default)
        app = (
            AppBuilder("test-app")
            .with_config_file("config.yaml")  # Default: from_etc_dir=True
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
