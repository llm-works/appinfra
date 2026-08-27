# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for AppBuilder integration with topic-based logging.

This module tests that LoggingConfigurer methods properly integrate with
AppBuilder and LogLevelManager.
"""

import logging

import pytest

from appinfra.app.builder import AppBuilder
from appinfra.log import LogConfig, LoggerFactory, LogLevelManager


@pytest.fixture(autouse=True)
def reset_manager():
    """Reset LogLevelManager and clear loggers before each test."""
    LogLevelManager.reset_instance()
    logging.root.manager.loggerDict.clear()
    yield
    LogLevelManager.reset_instance()
    logging.root.manager.loggerDict.clear()


class TestAppBuilderTopicLogging:
    """Test AppBuilder integration with topic-based logging API."""

    def test_with_topic_level_single(self):
        """Test with_topic_level() sets a single topic rule."""
        # Build app with single topic level
        app = (
            AppBuilder("test-app")
            .logging.with_topic_level("/infra/db/*", "debug")
            .done()
            .build()
        )

        # Verify rule was added
        manager = LogLevelManager.get_instance()
        level = manager.get_effective_level("/infra/db/queries")

        assert level == "debug"

    def test_with_topic_levels_multiple(self):
        """Test with_topic_levels() sets multiple topic rules."""
        # Build app with multiple topic levels
        app = (
            AppBuilder("test-app")
            .logging.with_topic_levels(
                {"/infra/db/*": "debug", "/infra/api/*": "warning", "/myapp/**": "info"}
            )
            .done()
            .build()
        )

        # Verify all rules were added
        manager = LogLevelManager.get_instance()

        assert manager.get_effective_level("/infra/db/pg") == "debug"
        assert manager.get_effective_level("/infra/api/rest") == "warning"
        assert manager.get_effective_level("/myapp/service/auth") == "info"

    def test_with_runtime_updates_enabled(self):
        """Test with_runtime_updates(True) enables runtime updates."""
        # Build app with runtime updates enabled
        app = AppBuilder("test-app").logging.with_runtime_updates(True).done().build()

        # Verify runtime updates are enabled
        manager = LogLevelManager.get_instance()
        assert manager.is_runtime_updates_enabled() is True

    def test_with_runtime_updates_disabled(self):
        """Test with_runtime_updates(False) disables runtime updates."""
        # First enable, then disable
        app = (
            AppBuilder("test-app")
            .logging.with_runtime_updates(True)
            .with_runtime_updates(False)
            .done()
            .build()
        )

        # Verify runtime updates are disabled
        manager = LogLevelManager.get_instance()
        assert manager.is_runtime_updates_enabled() is False

    def test_chaining_topic_methods(self):
        """Test method chaining with topic methods."""
        # Chain multiple topic methods
        app = (
            AppBuilder("test-app")
            .logging.with_level("info")
            .with_topic_level("/infra/db/*", "debug")
            .with_topic_level("/infra/api/*", "warning")
            .with_runtime_updates(True)
            .done()
            .build()
        )

        # Verify all settings applied
        manager = LogLevelManager.get_instance()

        assert manager.get_effective_level("/infra/db/pg") == "debug"
        assert manager.get_effective_level("/infra/api/rest") == "warning"
        assert manager.is_runtime_updates_enabled() is True

    def test_api_priority_over_yaml(self):
        """Test that API rules (priority=10) override YAML (priority=1)."""
        manager = LogLevelManager.get_instance()

        # Simulate YAML rule
        manager.add_rule("/test/*", "info", source="yaml", priority=1)

        # Add API rule via AppBuilder
        app = (
            AppBuilder("test-app")
            .logging.with_topic_level("/test/*", "debug")
            .done()
            .build()
        )

        # API rule should win
        level = manager.get_effective_level("/test/foo")
        assert level == "debug"

    def test_api_priority_over_cli(self):
        """Test that API rules (priority=10) override CLI (priority=5)."""
        manager = LogLevelManager.get_instance()

        # Simulate CLI rule
        manager.add_rule("/test/*", "warning", source="cli", priority=5)

        # Add API rule via AppBuilder
        app = (
            AppBuilder("test-app")
            .logging.with_topic_level("/test/*", "debug")
            .done()
            .build()
        )

        # API rule should win
        level = manager.get_effective_level("/test/foo")
        assert level == "debug"

    def test_logger_factory_respects_api_levels(self):
        """Test that LoggerFactory uses API-configured topic levels."""
        # Configure via AppBuilder
        app = (
            AppBuilder("test-app")
            .logging.with_topic_levels(
                {"/infra/db/*": "debug", "/infra/api/*": "trace"}
            )
            .done()
            .build()
        )

        # Create loggers
        log_config = LogConfig.from_params("info", location=0, micros=False)
        db_logger = LoggerFactory.create("/infra/db/queries", log_config)
        api_logger = LoggerFactory.create("/infra/api/rest", log_config)

        # Verify levels
        assert db_logger.level == logging.DEBUG
        assert api_logger.level == 5  # TRACE = 5

    def test_runtime_updates_apply_to_existing_loggers(self):
        """Test that runtime updates modify existing loggers."""
        # Enable runtime updates
        app = AppBuilder("test-app").logging.with_runtime_updates(True).done().build()

        # Create logger using standard logging (which registers in loggerDict)
        # Note: LoggerFactory creates custom logger instances that may not be
        # registered in the global logger dict, so we use logging.getLogger here
        logger = logging.getLogger("/infra/db/queries")
        logger.setLevel(logging.INFO)

        # Initially should be INFO
        assert logger.level == logging.INFO

        # Add topic rule at runtime
        manager = LogLevelManager.get_instance()
        manager.add_rule("/infra/db/*", "debug", source="api", priority=10)

        # Logger should be updated to DEBUG
        assert logger.level == logging.DEBUG

    def test_with_topic_levels_empty_dict(self):
        """Test with_topic_levels() with empty dictionary."""
        # Should not raise error
        app = AppBuilder("test-app").logging.with_topic_levels({}).done().build()

        # No rules should be added
        manager = LogLevelManager.get_instance()
        rules = manager.get_rules(source="api")
        assert len(rules) == 0

    def test_combining_with_other_logging_methods(self):
        """Test topic methods work with other logging methods."""
        builder = AppBuilder("test-app")

        app = (
            builder.logging.with_level("info")
            .with_location(2)
            .with_micros(True)
            .with_topic_levels({"/infra/**": "debug", "/myapp/*": "warning"})
            .done()
            .build()
        )

        # Verify topic rules
        manager = LogLevelManager.get_instance()
        assert manager.get_effective_level("/infra/db/pg") == "debug"
        assert manager.get_effective_level("/myapp/service") == "warning"

        # Verify other logging config is preserved in builder
        # (App object doesn't expose _logging_config, but builder does)
        assert builder._logging_config is not None
        assert builder._logging_config.level == "info"
        assert builder._logging_config.location == 2
        assert builder._logging_config.micros is True

    def test_multiple_calls_to_with_topic_level(self):
        """Test multiple calls to with_topic_level() accumulate rules."""
        app = (
            AppBuilder("test-app")
            .logging.with_topic_level("/pattern1/*", "debug")
            .with_topic_level("/pattern2/*", "warning")
            .with_topic_level("/pattern3/**", "error")
            .done()
            .build()
        )

        # All rules should be present
        manager = LogLevelManager.get_instance()
        rules = manager.get_rules(source="api")
        assert len(rules) == 3

        # Verify each rule
        assert manager.get_effective_level("/pattern1/foo") == "debug"
        assert manager.get_effective_level("/pattern2/bar") == "warning"
        assert manager.get_effective_level("/pattern3/baz/qux") == "error"

    def test_pattern_validation_in_api(self):
        """Test that invalid patterns raise errors."""
        with pytest.raises(ValueError, match="Pattern must start with '/'"):
            app = (
                AppBuilder("test-app")
                .logging.with_topic_level("invalid_pattern", "debug")
                .done()
                .build()
            )

    def test_builder_returns_self_for_chaining(self):
        """Test that all methods return self for chaining."""
        builder = AppBuilder("test-app")
        configurer = builder.logging

        # Each method should return LoggingConfigurer
        assert configurer.with_topic_level("/test/*", "debug") is configurer
        assert configurer.with_topic_levels({}) is configurer
        assert configurer.with_runtime_updates(True) is configurer

    def test_done_returns_app_builder(self):
        """Test that done() returns the AppBuilder."""
        builder = AppBuilder("test-app")
        returned = builder.logging.with_topic_level("/test/*", "debug").done()

        assert returned is builder
