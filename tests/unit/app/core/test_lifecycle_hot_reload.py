# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

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

    def test_forwards_origin_to_watcher(
        self, lifecycle_manager, mock_config_with_hot_reload
    ):
        """Test that app._origin is passed to ConfigWatcher on create."""
        from pathlib import Path

        lifecycle_manager._lifecycle_logger = MagicMock()
        lifecycle_manager._logger = MagicMock()
        lifecycle_manager.application._origin = Path("/pkg/etc")

        with patch("appinfra.config.ConfigWatcher") as mock_watcher_class:
            lifecycle_manager._configure_and_start_watcher(
                mock_config_with_hot_reload.logging.hot_reload,
                "/pkg/etc",
                "myapp.yaml",
            )

        mock_watcher_class.assert_called_once()
        kwargs = mock_watcher_class.call_args.kwargs
        assert kwargs["origin"] == Path("/pkg/etc")

    def test_forwards_no_origin_when_unset(
        self, lifecycle_manager, mock_config_with_hot_reload
    ):
        """Test that origin defaults to None when app hasn't set it."""
        lifecycle_manager._lifecycle_logger = MagicMock()
        lifecycle_manager._logger = MagicMock()
        # MagicMock fixture returns a Mock for any attr; force None here.
        lifecycle_manager.application._origin = None

        with patch("appinfra.config.ConfigWatcher") as mock_watcher_class:
            lifecycle_manager._configure_and_start_watcher(
                mock_config_with_hot_reload.logging.hot_reload,
                "/etc/myapp",
                "config.yaml",
            )

        kwargs = mock_watcher_class.call_args.kwargs
        assert kwargs["origin"] is None


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
