"""Tests for ConfigWatcher - file-based hot-reload."""

from unittest.mock import MagicMock

import pytest

from appinfra.config import ConfigWatcher
from appinfra.log import LogConfigReloader
from appinfra.log.config import LogConfig
from appinfra.log.config_holder import LogConfigHolder


@pytest.fixture
def mock_logger():
    """Create a mock logger for testing."""
    logger = MagicMock()
    logger.handlers = []
    return logger


@pytest.fixture
def mock_root_logger():
    """Create a mock root logger with holder for testing."""
    config = LogConfig.from_params("info", location=0)
    holder = LogConfigHolder(config)
    logger = MagicMock()
    logger._holder = holder
    logger.handlers = []
    return logger


@pytest.mark.unit
class TestConfigWatcher:
    """Unit tests for ConfigWatcher."""

    def test_configure_sets_path(self, tmp_path, mock_logger):
        """Test configure sets config path."""
        watcher = ConfigWatcher(mock_logger, etc_dir=tmp_path)
        config_file = tmp_path / "test.yaml"
        config_file.write_text("logging:\n  level: info\n")

        result = watcher.configure("test.yaml")

        assert result is watcher  # Fluent API
        assert watcher._config_path == config_file

    def test_configure_sets_debounce(self, tmp_path, mock_logger):
        """Test configure sets debounce."""
        watcher = ConfigWatcher(mock_logger, etc_dir=tmp_path)
        config_file = tmp_path / "test.yaml"
        config_file.write_text("logging:\n  level: info\n")

        watcher.configure("test.yaml", debounce_ms=1000)

        assert watcher._debounce_ms == 1000

    def test_configure_sets_on_change(self, tmp_path, mock_logger):
        """Test configure sets on_change callback."""
        watcher = ConfigWatcher(mock_logger, etc_dir=tmp_path)
        config_file = tmp_path / "test.yaml"
        config_file.write_text("logging:\n  level: info\n")

        callback = lambda cfg: None
        watcher.configure("test.yaml", on_change=callback)

        assert watcher._on_change is callback

    def test_is_running_initially_false(self, tmp_path, mock_logger):
        """Test watcher is not running initially."""
        watcher = ConfigWatcher(mock_logger, etc_dir=tmp_path)

        assert watcher.is_running() is False

    def test_start_without_configure_raises(self, tmp_path, mock_logger):
        """Test start without configure raises ValueError (or ImportError if watchdog not installed)."""
        watcher = ConfigWatcher(mock_logger, etc_dir=tmp_path)

        # May raise ImportError if watchdog not installed, or ValueError if it is
        with pytest.raises((ValueError, ImportError)):
            watcher.start()

    def test_stop_when_not_running_does_nothing(self, tmp_path, mock_logger):
        """Test stop when not running doesn't raise."""
        watcher = ConfigWatcher(mock_logger, etc_dir=tmp_path)

        # Should not raise
        watcher.stop()
        assert watcher.is_running() is False

    def test_add_config_file_relative_path(self, tmp_path, mock_logger):
        """Test add_config_file with relative path joins with etc_dir."""
        watcher = ConfigWatcher(mock_logger, etc_dir=tmp_path)

        watcher.add_config_file("overlay.yaml")

        assert (tmp_path / "overlay.yaml").resolve() in watcher._config_paths

    def test_add_config_file_absolute_path(self, tmp_path, mock_logger):
        """Test add_config_file with absolute path uses it directly."""
        watcher = ConfigWatcher(mock_logger, etc_dir=tmp_path)
        abs_path = tmp_path / "other" / "config.yaml"

        watcher.add_config_file(str(abs_path))

        assert abs_path.resolve() in watcher._config_paths

    def test_add_config_file_deduplicates(self, tmp_path, mock_logger):
        """Test add_config_file doesn't add duplicates."""
        watcher = ConfigWatcher(mock_logger, etc_dir=tmp_path)

        watcher.add_config_file("config.yaml")
        watcher.add_config_file("config.yaml")

        assert len(watcher._config_paths) == 1

    def test_add_config_file_returns_self(self, tmp_path, mock_logger):
        """Test add_config_file returns self for chaining."""
        watcher = ConfigWatcher(mock_logger, etc_dir=tmp_path)

        result = watcher.add_config_file("config.yaml")

        assert result is watcher


@pytest.mark.unit
class TestConfigWatcherDebounce:
    """Tests for debounce behavior."""

    def test_debounce_blocks_rapid_reloads(self, tmp_path, mock_logger):
        """Test that debounce prevents rapid reloads."""
        import time

        watcher = ConfigWatcher(mock_logger, etc_dir=tmp_path)
        config_file = tmp_path / "test.yaml"
        config_file.write_text("logging:\n  level: info\n")

        watcher.configure("test.yaml", debounce_ms=500)

        # Simulate rapid file changes
        watcher._last_reload = time.time() * 1000  # Set last reload to now

        reload_count = 0

        original_reload = watcher._reload_config

        def counting_reload():
            nonlocal reload_count
            reload_count += 1
            original_reload()

        watcher._reload_config = counting_reload

        # These should all be debounced
        watcher._on_file_changed()
        watcher._on_file_changed()
        watcher._on_file_changed()

        assert reload_count == 0  # All debounced


@pytest.mark.integration
class TestConfigWatcherIntegration:
    """Integration tests for ConfigWatcher with LogConfigReloader."""

    def test_reload_now_updates_root_logger_holder(self, tmp_path):
        """Test reload_now updates root logger's holder via LogConfigReloader."""
        import logging

        from appinfra.log.config import LogConfig
        from appinfra.log.factory import LoggerFactory

        # Clean up any existing root logger
        for name in list(logging.root.manager.loggerDict.keys()):
            if name.startswith("/"):
                del logging.root.manager.loggerDict[name]

        config_file = tmp_path / "test.yaml"
        config_file.write_text("logging:\n  level: debug\n  location: 2\n")

        # Create root logger with initial config
        initial_config = LogConfig.from_params("info", location=0)
        root_logger = LoggerFactory.create_root(initial_config)

        # Create reloader and watcher
        reloader = LogConfigReloader(root_logger)
        watcher = ConfigWatcher(lg=root_logger, etc_dir=tmp_path)
        watcher.configure("test.yaml", on_change=reloader)

        # Initial state
        assert root_logger._holder.level == 20  # INFO
        assert root_logger._holder.location == 0

        # Reload
        watcher.reload_now()

        # After reload - holder should be updated
        assert root_logger._holder.level == 10  # DEBUG
        assert root_logger._holder.location == 2

        # Cleanup
        root_logger.handlers.clear()

    def test_reload_now_updates_logger_level(self, tmp_path):
        """Test reload_now updates root logger level and child inherits via isEnabledFor."""
        import logging

        from appinfra.log.config import LogConfig
        from appinfra.log.factory import LoggerFactory

        # Clean up any existing loggers from previous tests
        for name in list(logging.root.manager.loggerDict.keys()):
            if name.startswith("/"):
                del logging.root.manager.loggerDict[name]

        # Create config file with INFO level
        config_file = tmp_path / "test.yaml"
        config_file.write_text("logging:\n  level: info\n")

        # Create root logger and child first
        config = LogConfig.from_params("info")
        root = LoggerFactory.create_root(config)
        child = LoggerFactory.create_child(root, "test_child")

        # Create reloader and watcher
        reloader = LogConfigReloader(root)
        watcher = ConfigWatcher(lg=root, etc_dir=tmp_path)
        watcher.configure("test.yaml", on_change=reloader)

        # Initial state - INFO level, DEBUG not enabled
        assert root.level == logging.INFO
        assert not root.isEnabledFor(logging.DEBUG)
        assert not child.isEnabledFor(logging.DEBUG)

        # Update config to DEBUG
        config_file.write_text("logging:\n  level: debug\n")

        # Trigger hot-reload
        watcher.reload_now()

        # After reload - root level updated, both isEnabledFor(DEBUG) return True
        assert root.level == logging.DEBUG
        assert root.isEnabledFor(logging.DEBUG)
        assert child.isEnabledFor(logging.DEBUG)

    def test_reload_restrictive_to_permissive(self, tmp_path):
        """Test hot-reload from restrictive (ERROR) to permissive (DEBUG)."""
        import logging

        from appinfra.log.config import LogConfig
        from appinfra.log.factory import LoggerFactory

        for name in list(logging.root.manager.loggerDict.keys()):
            if name.startswith("/"):
                del logging.root.manager.loggerDict[name]

        config_file = tmp_path / "test.yaml"
        config_file.write_text("logging:\n  level: error\n")

        config = LogConfig.from_params("error")
        root = LoggerFactory.create_root(config)
        child = LoggerFactory.create_child(root, "test_child")

        reloader = LogConfigReloader(root)
        watcher = ConfigWatcher(lg=root, etc_dir=tmp_path)
        watcher.configure("test.yaml", on_change=reloader)

        # Initial: ERROR level - WARNING not enabled
        assert not root.isEnabledFor(logging.WARNING)
        assert not child.isEnabledFor(logging.WARNING)

        # Hot-reload to DEBUG
        config_file.write_text("logging:\n  level: debug\n")
        watcher.reload_now()

        # Now DEBUG should be enabled
        assert root.isEnabledFor(logging.DEBUG)
        assert child.isEnabledFor(logging.DEBUG)

    def test_reload_permissive_to_restrictive(self, tmp_path):
        """Test hot-reload from permissive (DEBUG) to restrictive (ERROR)."""
        import logging

        from appinfra.log.config import LogConfig
        from appinfra.log.factory import LoggerFactory

        for name in list(logging.root.manager.loggerDict.keys()):
            if name.startswith("/"):
                del logging.root.manager.loggerDict[name]

        config_file = tmp_path / "test.yaml"
        config_file.write_text("logging:\n  level: debug\n")

        config = LogConfig.from_params("debug")
        root = LoggerFactory.create_root(config)
        child = LoggerFactory.create_child(root, "test_child")

        reloader = LogConfigReloader(root)
        watcher = ConfigWatcher(lg=root, etc_dir=tmp_path)
        watcher.configure("test.yaml", on_change=reloader)

        # Initial: DEBUG level
        assert root.isEnabledFor(logging.DEBUG)
        assert child.isEnabledFor(logging.DEBUG)

        # Hot-reload to ERROR
        config_file.write_text("logging:\n  level: error\n")
        watcher.reload_now()

        # Now WARNING should NOT be enabled
        assert not root.isEnabledFor(logging.WARNING)
        assert not child.isEnabledFor(logging.WARNING)
        assert root.isEnabledFor(logging.ERROR)
        assert child.isEnabledFor(logging.ERROR)

    def test_reload_with_deep_hierarchy(self, tmp_path):
        """Test hot-reload updates all levels in deep hierarchy."""
        import logging

        from appinfra.log.config import LogConfig
        from appinfra.log.factory import LoggerFactory

        for name in list(logging.root.manager.loggerDict.keys()):
            if name.startswith("/"):
                del logging.root.manager.loggerDict[name]

        config_file = tmp_path / "test.yaml"
        config_file.write_text("logging:\n  level: info\n")

        config = LogConfig.from_params("info")
        root = LoggerFactory.create_root(config)
        l1 = LoggerFactory.create_child(root, "l1")
        l2 = LoggerFactory.create_child(l1, "l2")
        l3 = LoggerFactory.create_child(l2, "l3")
        l4 = LoggerFactory.create_child(l3, "l4")

        reloader = LogConfigReloader(root)
        watcher = ConfigWatcher(lg=root, etc_dir=tmp_path)
        watcher.configure("test.yaml", on_change=reloader)

        # All start at INFO
        assert not l4.isEnabledFor(logging.DEBUG)

        # Hot-reload to DEBUG
        config_file.write_text("logging:\n  level: debug\n")
        watcher.reload_now()

        # All levels should now allow DEBUG
        assert root.isEnabledFor(logging.DEBUG)
        assert l1.isEnabledFor(logging.DEBUG)
        assert l2.isEnabledFor(logging.DEBUG)
        assert l3.isEnabledFor(logging.DEBUG)
        assert l4.isEnabledFor(logging.DEBUG)

    def test_reload_updates_handler_levels(self, tmp_path):
        """Test hot-reload also updates handler levels."""
        import logging

        from appinfra.log.config import LogConfig
        from appinfra.log.factory import LoggerFactory

        for name in list(logging.root.manager.loggerDict.keys()):
            if name.startswith("/"):
                del logging.root.manager.loggerDict[name]

        config_file = tmp_path / "test.yaml"
        config_file.write_text("logging:\n  level: info\n")

        config = LogConfig.from_params("info")
        root = LoggerFactory.create_root(config)

        reloader = LogConfigReloader(root)
        watcher = ConfigWatcher(lg=root, etc_dir=tmp_path)
        watcher.configure("test.yaml", on_change=reloader)

        # Check initial handler level
        assert len(root.handlers) > 0
        assert root.handlers[0].level == logging.INFO

        # Hot-reload to DEBUG
        config_file.write_text("logging:\n  level: debug\n")
        watcher.reload_now()

        # Handler level should also be updated
        assert root.handlers[0].level == logging.DEBUG

    def test_reload_now_calls_on_change(self, tmp_path, mock_logger):
        """Test reload_now calls on_change callback with config dict."""

        config_file = tmp_path / "test.yaml"
        config_file.write_text("logging:\n  level: debug\n")

        watcher = ConfigWatcher(mock_logger, etc_dir=tmp_path)

        results = []
        watcher.configure("test.yaml", on_change=lambda cfg: results.append(cfg))

        watcher.reload_now()

        assert len(results) == 1
        assert "logging" in results[0]
        assert results[0]["logging"]["level"] == "debug"

    def test_reload_handles_invalid_config(self, tmp_path, mock_logger):
        """Test reload handles invalid config gracefully."""
        config_file = tmp_path / "test.yaml"
        config_file.write_text("invalid: yaml: content: [")  # Invalid YAML

        watcher = ConfigWatcher(mock_logger, etc_dir=tmp_path)
        watcher.configure("test.yaml")

        # Should not raise
        watcher.reload_now()

        # Should log error via logger
        mock_logger.error.assert_called_once()
        call_args = mock_logger.error.call_args
        assert "failed to reload config" in call_args[0][0]
        assert "exception" in call_args[1]["extra"]

    def test_reload_without_config_path_does_nothing(self, tmp_path, mock_logger):
        """Test reload_now does nothing when config_path is None."""
        watcher = ConfigWatcher(mock_logger, etc_dir=tmp_path)
        # Don't call configure, so _config_path is None

        # Should not raise
        watcher.reload_now()

    def test_on_change_error_logged(self, tmp_path, mock_logger):
        """Test that on_change callback errors are logged."""

        config_file = tmp_path / "test.yaml"
        config_file.write_text("logging:\n  level: debug\n")

        watcher = ConfigWatcher(mock_logger, etc_dir=tmp_path)
        watcher.configure("test.yaml", on_change=lambda c: 1 / 0)  # Raises

        watcher.reload_now()

        # Should log error
        mock_logger.error.assert_called_once()
        call_args = mock_logger.error.call_args
        assert "on_change callback failed" in call_args[0][0]

    def test_on_file_changed_calls_reload_after_debounce(self, tmp_path, mock_logger):
        """Test _on_file_changed calls _reload_config when debounce passed."""

        config_file = tmp_path / "test.yaml"
        config_file.write_text("logging:\n  level: debug\n")

        watcher = ConfigWatcher(mock_logger, etc_dir=tmp_path)
        watcher.configure("test.yaml", debounce_ms=0)  # No debounce

        reload_count = 0

        original_reload = watcher._reload_config

        def counting_reload():
            nonlocal reload_count
            reload_count += 1
            original_reload()

        watcher._reload_config = counting_reload

        # Should not be debounced with debounce_ms=0
        watcher._on_file_changed()

        assert reload_count == 1


@pytest.mark.unit
class TestConfigWatcherReloadPaths:
    """Tests for reload configuration paths."""

    def test_on_file_changed_triggers_reload_after_debounce(
        self, tmp_path, mock_logger
    ):
        """Test _on_file_changed triggers reload when debounce time has passed."""

        config_file = tmp_path / "test.yaml"
        config_file.write_text("logging:\n  level: info\n")

        watcher = ConfigWatcher(mock_logger, etc_dir=tmp_path)
        watcher.configure("test.yaml", debounce_ms=0)  # No debounce
        watcher._last_reload = 0  # Reset last reload time to distant past

        reload_called = []
        original_reload = watcher._reload_config

        def tracking_reload():
            reload_called.append(True)
            original_reload()

        watcher._reload_config = tracking_reload

        # This should trigger reload since debounce=0 and last_reload=0
        watcher._on_file_changed()

        assert len(reload_called) == 1

    def test_reload_config_with_none_path_returns_early(self, tmp_path, mock_logger):
        """Test _reload_config returns early when config_path is None."""
        watcher = ConfigWatcher(mock_logger, etc_dir=tmp_path)
        # Don't configure, so _config_path is None

        # Should not raise - just return early
        watcher._reload_config()

        # No error means success

    def test_create_file_handler_matches_config_path(self, tmp_path, mock_logger):
        """Test _create_file_handler creates handler that checks correct path."""
        config_file = tmp_path / "test.yaml"
        config_file.write_text("logging:\n  level: info\n")

        watcher = ConfigWatcher(mock_logger, etc_dir=tmp_path)
        watcher.configure("test.yaml")

        handler = watcher._create_file_handler()

        # Handler should be a FileSystemEventHandler subclass
        assert handler is not None
        assert hasattr(handler, "on_modified")


# =============================================================================
# Test Watching Included Files
# =============================================================================


@pytest.mark.unit
class TestConfigWatcherIncludedFiles:
    """Tests for watching included configuration files."""

    def test_get_source_files_from_config_includes_all_files(
        self, tmp_path, mock_logger
    ):
        """Test _get_source_files_from_config returns main and included files."""
        # Create included logging config
        logging_file = tmp_path / "logging.yaml"
        logging_file.write_text("level: debug\n")

        # Create main config with include
        config_file = tmp_path / "config.yaml"
        config_file.write_text('logging: !include "./logging.yaml"\napp: test\n')

        watcher = ConfigWatcher(mock_logger, etc_dir=tmp_path)
        watcher.configure("config.yaml")

        source_files = watcher._get_source_files_from_config()

        assert config_file.resolve() in source_files
        assert logging_file.resolve() in source_files
        assert len(source_files) == 2

    def test_get_source_files_from_config_fallback_on_error(
        self, tmp_path, mock_logger
    ):
        """Test _get_source_files_from_config returns main file on error."""
        config_file = tmp_path / "config.yaml"
        # Don't create the file - will cause error

        watcher = ConfigWatcher(mock_logger, etc_dir=tmp_path)
        watcher._config_paths = [config_file]  # Set directly without loading

        source_files = watcher._get_source_files_from_config()

        # Should fall back to just the main config file
        assert config_file in source_files

    def test_watched_files_includes_all_source_files(self, tmp_path, mock_logger):
        """Test that _watched_files is populated with all source files on start."""

        # Create included file
        logging_file = tmp_path / "logging.yaml"
        logging_file.write_text("level: info\n")

        # Create main config
        config_file = tmp_path / "config.yaml"
        config_file.write_text('logging: !include "./logging.yaml"\n')

        watcher = ConfigWatcher(mock_logger, etc_dir=tmp_path)
        watcher.configure("config.yaml")

        # Before start, _watched_files should be empty
        assert len(watcher._watched_files) == 0

        # Start will populate _watched_files
        watcher.start()

        try:
            assert config_file.resolve() in watcher._watched_files
            assert logging_file.resolve() in watcher._watched_files
        finally:
            watcher.stop()

    def test_stop_clears_watched_files(self, tmp_path, mock_logger):
        """Test that stop() clears _watched_files and _watched_dirs."""

        config_file = tmp_path / "config.yaml"
        config_file.write_text("logging:\n  level: info\n")

        watcher = ConfigWatcher(mock_logger, etc_dir=tmp_path)
        watcher.configure("config.yaml")
        watcher.start()

        # Should have watched files
        assert len(watcher._watched_files) > 0

        watcher.stop()

        # Should be cleared
        assert len(watcher._watched_files) == 0
        assert len(watcher._watched_dirs) == 0

    def test_reload_updates_watched_files(self, tmp_path, mock_logger):
        """Test that reload updates _watched_files when includes change."""

        # Create initial include
        logging_file = tmp_path / "logging.yaml"
        logging_file.write_text("level: info\n")

        # Create main config
        config_file = tmp_path / "config.yaml"
        config_file.write_text('logging: !include "./logging.yaml"\n')

        watcher = ConfigWatcher(mock_logger, etc_dir=tmp_path)
        watcher.configure("config.yaml")

        # Manually set watched files (simulating start())
        watcher._watched_files = {config_file.resolve(), logging_file.resolve()}

        # Create a new include file
        new_logging_file = tmp_path / "new_logging.yaml"
        new_logging_file.write_text("level: debug\n")

        # Update config to use new include
        config_file.write_text('logging: !include "./new_logging.yaml"\n')

        # Trigger reload
        watcher._reload_config()

        # _watched_files should now include the new file
        assert new_logging_file.resolve() in watcher._watched_files

    def test_file_handler_triggers_on_included_file_change(self, tmp_path, mock_logger):
        """Test that file handler triggers reload when included file changes."""
        from unittest.mock import MagicMock

        # Create included file
        logging_file = tmp_path / "logging.yaml"
        logging_file.write_text("level: info\n")

        # Create main config
        config_file = tmp_path / "config.yaml"
        config_file.write_text('logging: !include "./logging.yaml"\n')

        watcher = ConfigWatcher(mock_logger, etc_dir=tmp_path)
        watcher.configure("config.yaml", debounce_ms=0)
        watcher._watched_files = {config_file.resolve(), logging_file.resolve()}
        watcher._last_reload = 0

        # Mock the reload method
        reload_calls = []
        original_reload = watcher._reload_config
        watcher._reload_config = lambda: reload_calls.append(True)

        try:
            handler = watcher._create_file_handler()

            # Create mock event for included file modification
            mock_event = MagicMock()
            mock_event.is_directory = False
            mock_event.src_path = str(logging_file)

            # Trigger handler
            handler.on_modified(mock_event)

            # Should have triggered reload
            assert len(reload_calls) == 1
        finally:
            watcher._reload_config = original_reload

    def test_watches_multiple_directories(self, tmp_path, mock_logger):
        """Test that watcher can watch files in multiple directories."""

        # Create subdirectory for includes
        sub_dir = tmp_path / "includes"
        sub_dir.mkdir()

        # Create included file in subdirectory
        logging_file = sub_dir / "logging.yaml"
        logging_file.write_text("level: info\n")

        # Create main config in root
        config_file = tmp_path / "config.yaml"
        config_file.write_text('logging: !include "./includes/logging.yaml"\n')

        watcher = ConfigWatcher(mock_logger, etc_dir=tmp_path)
        watcher.configure("config.yaml")
        watcher.start()

        try:
            # Should watch both directories
            assert tmp_path in watcher._watched_dirs
            assert sub_dir in watcher._watched_dirs
        finally:
            watcher.stop()


# =============================================================================
# Test Section Callbacks
# =============================================================================


@pytest.mark.unit
class TestConfigWatcherSectionCallbacks:
    """Tests for section-specific callbacks."""

    def test_add_section_callback(self, tmp_path, mock_logger):
        """Test add_section_callback registers a callback."""
        config_file = tmp_path / "test.yaml"
        config_file.write_text("logging:\n  level: info\n")

        watcher = ConfigWatcher(mock_logger, etc_dir=tmp_path)
        watcher.configure("test.yaml")

        callback = lambda x: None
        watcher.add_section_callback("database.options", callback)

        assert "database.options" in watcher._section_callbacks
        assert callback in watcher._section_callbacks["database.options"]

    def test_add_multiple_callbacks_same_section(self, tmp_path, mock_logger):
        """Test adding multiple callbacks for the same section."""
        config_file = tmp_path / "test.yaml"
        config_file.write_text("logging:\n  level: info\n")

        watcher = ConfigWatcher(mock_logger, etc_dir=tmp_path)
        watcher.configure("test.yaml")

        callback1 = lambda x: None
        callback2 = lambda x: None
        watcher.add_section_callback("database", callback1)
        watcher.add_section_callback("database", callback2)

        assert len(watcher._section_callbacks["database"]) == 2
        assert callback1 in watcher._section_callbacks["database"]
        assert callback2 in watcher._section_callbacks["database"]

    def test_remove_section_callback(self, tmp_path, mock_logger):
        """Test remove_section_callback unregisters a callback."""
        config_file = tmp_path / "test.yaml"
        config_file.write_text("logging:\n  level: info\n")

        watcher = ConfigWatcher(mock_logger, etc_dir=tmp_path)
        watcher.configure("test.yaml")

        callback = lambda x: None
        watcher.add_section_callback("database", callback)
        assert "database" in watcher._section_callbacks

        watcher.remove_section_callback("database", callback)

        # Section should be removed when empty
        assert "database" not in watcher._section_callbacks

    def test_remove_section_callback_not_found(self, tmp_path, mock_logger):
        """Test remove_section_callback with non-existent callback doesn't raise."""
        config_file = tmp_path / "test.yaml"
        config_file.write_text("logging:\n  level: info\n")

        watcher = ConfigWatcher(mock_logger, etc_dir=tmp_path)
        watcher.configure("test.yaml")

        # Should not raise
        watcher.remove_section_callback("nonexistent", lambda x: None)

    def test_section_callbacks_called_on_reload(self, tmp_path, mock_logger):
        """Test section callbacks are called when config reloads."""

        config_file = tmp_path / "test.yaml"
        config_file.write_text(
            "logging:\n  level: info\ndatabase:\n  host: localhost\n  port: 5432\n"
        )

        watcher = ConfigWatcher(mock_logger, etc_dir=tmp_path)
        watcher.configure("test.yaml")

        results = []
        watcher.add_section_callback("database", lambda db: results.append(db.host))

        watcher.reload_now()

        assert len(results) == 1
        assert results[0] == "localhost"

    def test_section_callbacks_receive_correct_value(self, tmp_path, mock_logger):
        """Test section callbacks receive the correct section value."""

        config_file = tmp_path / "test.yaml"
        config_file.write_text(
            """
logging:
  level: info
proxy:
  plugins:
    myplugin:
      options:
        threshold: 100
        enabled: true
"""
        )

        watcher = ConfigWatcher(mock_logger, etc_dir=tmp_path)
        watcher.configure("test.yaml")

        results = []
        watcher.add_section_callback(
            "proxy.plugins.myplugin.options",
            lambda opts: results.append((opts.threshold, opts.enabled)),
        )

        watcher.reload_now()

        assert len(results) == 1
        assert results[0] == (100, True)

    def test_section_callback_missing_section_not_called(self, tmp_path, mock_logger):
        """Test section callback is not called if section doesn't exist."""

        config_file = tmp_path / "test.yaml"
        config_file.write_text("logging:\n  level: info\n")

        watcher = ConfigWatcher(mock_logger, etc_dir=tmp_path)
        watcher.configure("test.yaml")

        results = []
        watcher.add_section_callback("nonexistent.section", lambda x: results.append(x))

        watcher.reload_now()

        # Callback should not have been called
        assert len(results) == 0

    def test_section_callback_error_isolated(self, tmp_path, mock_logger):
        """Test section callback errors don't break other callbacks."""

        config_file = tmp_path / "test.yaml"
        config_file.write_text("logging:\n  level: info\ndatabase:\n  host: test\n")

        watcher = ConfigWatcher(mock_logger, etc_dir=tmp_path)
        watcher.configure("test.yaml")

        results = []
        watcher.add_section_callback("database", lambda x: results.append("first"))
        watcher.add_section_callback("database", lambda x: 1 / 0)  # Raises
        watcher.add_section_callback("database", lambda x: results.append("third"))

        watcher.reload_now()

        # First and third should run despite error in second
        assert results == ["first", "third"]

    def test_section_callback_with_nested_path(self, tmp_path, mock_logger):
        """Test section callback with deeply nested path."""

        config_file = tmp_path / "test.yaml"
        config_file.write_text(
            """
logging:
  level: info
app:
  services:
    api:
      timeout: 30
"""
        )

        watcher = ConfigWatcher(mock_logger, etc_dir=tmp_path)
        watcher.configure("test.yaml")

        results = []
        watcher.add_section_callback(
            "app.services.api", lambda api: results.append(api.timeout)
        )

        watcher.reload_now()

        assert results == [30]

    def test_section_callback_path_through_non_dict(self, tmp_path, mock_logger):
        """Test section callback when path goes through a non-dict value."""
        config_file = tmp_path / "test.yaml"
        config_file.write_text("logging:\n  level: info\n")

        watcher = ConfigWatcher(mock_logger, etc_dir=tmp_path)
        watcher.configure("test.yaml")

        results = []
        # "level" is a string, not a dict, so "level.nested" should not find anything
        watcher.add_section_callback(
            "logging.level.nested", lambda x: results.append(x)
        )

        watcher.reload_now()

        # Callback should not be called (path goes through non-dict)
        assert results == []


@pytest.mark.unit
class TestConfigWatcherMultiConfig:
    """Tests for multi-config file scenarios."""

    def test_reload_skips_unchanged_config(self, tmp_path, mock_logger):
        """Test reload skips callbacks when config content unchanged."""
        config_file = tmp_path / "test.yaml"
        config_file.write_text("logging:\n  level: debug\n")

        watcher = ConfigWatcher(mock_logger, etc_dir=tmp_path)
        call_count = 0

        def counting_callback(cfg):
            nonlocal call_count
            call_count += 1

        watcher.configure("test.yaml", on_change=counting_callback)

        # First reload should call callback
        watcher.reload_now()
        assert call_count == 1

        # Second reload with same content should skip (unchanged)
        watcher.reload_now()
        assert call_count == 1  # Still 1, not called again

        # Change content, should call again
        config_file.write_text("logging:\n  level: info\n")
        watcher.reload_now()
        assert call_count == 2

    def test_reload_handles_missing_overlay_file(self, tmp_path, mock_logger):
        """Test reload handles missing overlay file gracefully."""
        base_file = tmp_path / "base.yaml"
        base_file.write_text("logging:\n  level: info\n")

        watcher = ConfigWatcher(mock_logger, etc_dir=tmp_path)
        watcher.add_config_file("base.yaml")
        watcher.add_config_file("missing.yaml")  # This file doesn't exist
        watcher.configure("base.yaml")

        results = []
        watcher.configure("base.yaml", on_change=lambda c: results.append(c))

        # Should not raise, should skip missing file
        watcher.reload_now()

        # Should still get base config
        assert len(results) == 1
        assert results[0]["logging"]["level"] == "info"

        # Should log debug about missing file
        mock_logger.debug.assert_called()

    def test_reload_with_all_files_missing(self, tmp_path, mock_logger):
        """Test reload does nothing when all config files are missing."""
        watcher = ConfigWatcher(mock_logger, etc_dir=tmp_path)
        watcher.add_config_file("missing1.yaml")
        watcher.add_config_file("missing2.yaml")
        watcher.configure("missing1.yaml")

        results = []
        watcher.configure("missing1.yaml", on_change=lambda c: results.append(c))

        # Should not raise, callback should not be called (empty merged dict)
        watcher.reload_now()

        assert results == []
