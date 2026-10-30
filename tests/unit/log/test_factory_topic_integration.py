# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Integration tests for LoggerFactory with topic-based levels.

Tests that LoggerFactory.create() respects topic-based level overrides.
"""

import logging

import pytest

from appinfra.log import LogConfig, LoggerFactory, LogLevelManager


@pytest.fixture(autouse=True)
def reset_manager():
    """Reset LogLevelManager and clear loggers before each test."""
    LogLevelManager.reset_instance()

    # Clear all loggers from logging module
    logging.root.manager.loggerDict.clear()

    yield

    LogLevelManager.reset_instance()
    logging.root.manager.loggerDict.clear()


@pytest.fixture
def log_config():
    """Create a basic log config."""
    return LogConfig.from_params("info", location=0, micros=False)


class TestLoggerFactoryTopicIntegration:
    """Test LoggerFactory integration with topic-based levels."""

    def test_logger_without_topic_rule(self, log_config):
        """Test logger creation without topic rules uses config level."""
        logger = LoggerFactory.create("/test/logger", log_config)
        assert logger.level == logging.INFO

    def test_logger_with_exact_topic_match(self, log_config):
        """Test logger creation with exact topic match."""
        manager = LogLevelManager.get_instance()
        manager.add_rule("/test/logger", "debug", source="yaml", priority=1)

        logger = LoggerFactory.create("/test/logger", log_config)
        assert logger.level == logging.DEBUG

    def test_logger_with_wildcard_match(self, log_config):
        """Test logger creation with wildcard pattern match."""
        manager = LogLevelManager.get_instance()
        manager.add_rule("/test/*", "debug", source="yaml", priority=1)

        logger = LoggerFactory.create("/test/logger", log_config)
        assert logger.level == logging.DEBUG

    def test_logger_with_recursive_wildcard_match(self, log_config):
        """Test logger creation with recursive wildcard match."""
        manager = LogLevelManager.get_instance()
        manager.add_rule("/test/**", "trace", source="yaml", priority=1)

        logger = LoggerFactory.create("/test/deep/nested/logger", log_config)
        # TRACE is custom level = 5
        assert logger.level == 5

    def test_logger_with_no_match_uses_config_level(self, log_config):
        """Test logger creation with no matching pattern uses config level."""
        manager = LogLevelManager.get_instance()
        manager.add_rule("/other/**", "debug", source="yaml", priority=1)

        logger = LoggerFactory.create("/test/logger", log_config)
        assert logger.level == logging.INFO  # Uses config level

    def test_logger_with_multiple_patterns_uses_most_specific(self, log_config):
        """Test that most specific pattern wins."""
        manager = LogLevelManager.get_instance()
        manager.add_rule("/test/**", "info", source="yaml", priority=1)
        manager.add_rule("/test/specific/*", "debug", source="yaml", priority=1)
        manager.add_rule("/test/specific/logger", "trace", source="yaml", priority=1)

        logger = LoggerFactory.create("/test/specific/logger", log_config)
        assert logger.level == 5  # TRACE (most specific)

    def test_logger_with_cli_override(self, log_config):
        """Test that CLI priority overrides YAML."""
        manager = LogLevelManager.get_instance()
        manager.add_rule("/test/*", "info", source="yaml", priority=1)
        manager.add_rule("/test/*", "debug", source="cli", priority=5)

        logger = LoggerFactory.create("/test/logger", log_config)
        assert logger.level == logging.DEBUG  # CLI wins

    def test_logger_with_api_override(self, log_config):
        """Test that API priority overrides all."""
        manager = LogLevelManager.get_instance()
        manager.add_rule("/test/*", "info", source="yaml", priority=1)
        manager.add_rule("/test/*", "debug", source="cli", priority=5)
        manager.add_rule("/test/*", "trace", source="api", priority=10)

        logger = LoggerFactory.create("/test/logger", log_config)
        assert logger.level == 5  # TRACE from API

    def test_logger_handler_level_matches_effective_level(self, log_config):
        """Test that handler level is set to effective level."""
        manager = LogLevelManager.get_instance()
        manager.add_rule("/test/*", "debug", source="yaml", priority=1)

        logger = LoggerFactory.create("/test/logger", log_config)

        # Logger level should be DEBUG
        assert logger.level == logging.DEBUG

        # Handler level should also be DEBUG
        assert len(logger.handlers) > 0
        for handler in logger.handlers:
            assert handler.level == logging.DEBUG

    def test_infra_logger_hierarchy(self, log_config):
        """Test realistic /infra logger hierarchy."""
        manager = LogLevelManager.get_instance()
        manager.add_rules_from_dict(
            {"/infra/**": "info", "/infra/db/*": "debug", "/infra/db/queries": "trace"},
            source="yaml",
            priority=1,
        )

        # Test general infra logger
        infra_logger = LoggerFactory.create("/infra", log_config)
        assert infra_logger.level == logging.INFO

        # Test DB logger
        db_logger = LoggerFactory.create("/infra/db/pg", log_config)
        assert db_logger.level == logging.DEBUG

        # Test queries logger (most specific)
        queries_logger = LoggerFactory.create("/infra/db/queries", log_config)
        assert queries_logger.level == 5  # TRACE

    def test_numeric_level_in_topic_rule(self, log_config):
        """Test that numeric levels work in topic rules."""
        manager = LogLevelManager.get_instance()
        manager.add_rule("/test/*", logging.WARNING, source="yaml", priority=1)

        logger = LoggerFactory.create("/test/logger", log_config)
        assert logger.level == logging.WARNING
