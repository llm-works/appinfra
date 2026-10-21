# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Unit tests for LogLevelManager.

Tests pattern matching, rule precedence, specificity, and runtime updates.
"""

import logging
import threading

import pytest

pytestmark = pytest.mark.unit

from appinfra.log.level_manager import LogLevelManager


@pytest.fixture(autouse=True)
def reset_manager():
    """Reset LogLevelManager singleton before each test."""
    LogLevelManager.reset_instance()
    yield
    LogLevelManager.reset_instance()


@pytest.fixture
def manager():
    """Get fresh LogLevelManager instance."""
    return LogLevelManager.get_instance()


# =============================================================================
# Test Singleton Pattern
# =============================================================================


class TestSingleton:
    """Test singleton instance management."""

    def test_get_instance_returns_same_object(self):
        """Test that get_instance() always returns the same instance."""
        manager1 = LogLevelManager.get_instance()
        manager2 = LogLevelManager.get_instance()
        assert manager1 is manager2

    def test_reset_instance(self):
        """Test that reset_instance() creates a new instance."""
        manager1 = LogLevelManager.get_instance()
        LogLevelManager.reset_instance()
        manager2 = LogLevelManager.get_instance()
        assert manager1 is not manager2


# =============================================================================
# Test Rule Management
# =============================================================================


class TestRuleManagement:
    """Test adding and managing rules."""

    def test_add_single_rule(self, manager):
        """Test adding a single rule."""
        manager.add_rule("/infra/db/*", "debug", source="yaml", priority=1)
        rules = manager.get_rules()
        assert len(rules) == 1
        assert rules[0].pattern == "/infra/db/*"
        assert rules[0].level == "debug"
        assert rules[0].source == "yaml"
        assert rules[0].priority == 1

    def test_add_multiple_rules(self, manager):
        """Test adding multiple rules."""
        manager.add_rule("/infra/db/*", "debug", source="yaml", priority=1)
        manager.add_rule("/infra/api/*", "warning", source="yaml", priority=1)
        rules = manager.get_rules()
        assert len(rules) == 2

    def test_add_rules_from_dict(self, manager):
        """Test adding rules from dictionary."""
        rules_dict = {
            "/infra/db/*": "debug",
            "/infra/api/*": "warning",
            "/myapp/**": "info",
        }
        manager.add_rules_from_dict(rules_dict, source="yaml", priority=1)
        rules = manager.get_rules()
        assert len(rules) == 3

    def test_clear_all_rules(self, manager):
        """Test clearing all rules."""
        manager.add_rule("/infra/db/*", "debug", source="yaml", priority=1)
        manager.add_rule("/infra/api/*", "warning", source="cli", priority=5)
        manager.clear_rules()
        assert len(manager.get_rules()) == 0

    def test_clear_rules_by_source(self, manager):
        """Test clearing rules from specific source."""
        manager.add_rule("/infra/db/*", "debug", source="yaml", priority=1)
        manager.add_rule("/infra/api/*", "warning", source="cli", priority=5)
        manager.clear_rules(source="yaml")
        rules = manager.get_rules()
        assert len(rules) == 1
        assert rules[0].source == "cli"

    def test_get_rules_by_source(self, manager):
        """Test retrieving rules from specific source."""
        manager.add_rule("/infra/db/*", "debug", source="yaml", priority=1)
        manager.add_rule("/infra/api/*", "warning", source="cli", priority=5)
        yaml_rules = manager.get_rules(source="yaml")
        assert len(yaml_rules) == 1
        assert yaml_rules[0].pattern == "/infra/db/*"


# =============================================================================
# Test Pattern Matching
# =============================================================================


class TestPatternMatching:
    """Test glob pattern matching."""

    def test_pattern_starting_with_recursive_wildcard(self, manager):
        """Test pattern starting with **/ (suffix matching)."""
        manager.add_rule("/**/queries", "debug", source="yaml", priority=1)

        # Should match paths ending with /queries
        assert manager.get_effective_level("/infra/db/queries") == "debug"
        assert manager.get_effective_level("/myapp/data/queries") == "debug"

        # Should not match paths not ending with /queries
        assert manager.get_effective_level("/infra/db/pg") is None

    def test_exact_match(self, manager):
        """Test exact path matching (no wildcards)."""
        manager.add_rule("/infra/db/queries", "debug", source="yaml", priority=1)
        level = manager.get_effective_level("/infra/db/queries")
        assert level == "debug"

        # Non-matching path
        level = manager.get_effective_level("/infra/db/pg")
        assert level is None

    def test_single_wildcard_match(self, manager):
        """Test single segment wildcard (*)."""
        manager.add_rule("/infra/db/*", "debug", source="yaml", priority=1)

        # Should match single segment
        assert manager.get_effective_level("/infra/db/queries") == "debug"
        assert manager.get_effective_level("/infra/db/pg") == "debug"

        # Should not match multiple segments
        assert manager.get_effective_level("/infra/db/pg/queries") is None

    def test_recursive_wildcard_match(self, manager):
        """Test recursive wildcard (**)."""
        manager.add_rule("/infra/**", "debug", source="yaml", priority=1)

        # Should match any depth
        assert manager.get_effective_level("/infra/db") == "debug"
        assert manager.get_effective_level("/infra/db/queries") == "debug"
        assert manager.get_effective_level("/infra/db/pg/queries") == "debug"
        assert manager.get_effective_level("/infra/app/lifecycle") == "debug"

    def test_recursive_wildcard_with_suffix(self, manager):
        """Test recursive wildcard with suffix pattern."""
        manager.add_rule("/infra/**/queries", "trace", source="yaml", priority=1)

        # Should match paths ending with queries
        assert manager.get_effective_level("/infra/db/queries") == "trace"
        assert manager.get_effective_level("/infra/db/pg/queries") == "trace"

        # Should not match different endings
        assert manager.get_effective_level("/infra/db/pg") is None

    def test_pattern_with_multiple_wildcards(self, manager):
        """Test pattern with multiple * wildcards."""
        manager.add_rule("/infra/*/test/*", "debug", source="yaml", priority=1)

        assert manager.get_effective_level("/infra/db/test/unit") == "debug"
        assert manager.get_effective_level("/infra/api/test/integration") == "debug"

        # Should not match different structure
        assert manager.get_effective_level("/infra/db/production/unit") is None


# =============================================================================
# Test Pattern Specificity
# =============================================================================


class TestSpecificity:
    """Test pattern specificity calculation and resolution."""

    def test_specificity_calculation(self, manager):
        """Test specificity score calculation."""
        # Exact paths get highest specificity
        spec1 = manager._calculate_specificity("/infra/db/queries")
        assert spec1 == 30  # 3 segments * 10

        # Paths with single wildcard
        spec2 = manager._calculate_specificity("/infra/db/*")
        assert spec2 == 21  # 2 segments * 10 + 1 wildcard

        # Paths with recursive wildcard
        spec3 = manager._calculate_specificity("/infra/**")
        assert spec3 == 10  # 1 segment * 10 + 0 for **

        # Verify ordering
        assert spec1 > spec2 > spec3

    def test_most_specific_pattern_wins(self, manager):
        """Test that most specific pattern wins when multiple match."""
        # Add rules in non-specific order
        manager.add_rule("/infra/**", "info", source="yaml", priority=1)
        manager.add_rule("/infra/db/*", "debug", source="yaml", priority=1)
        manager.add_rule("/infra/db/queries", "trace", source="yaml", priority=1)

        # Most specific should win
        level = manager.get_effective_level("/infra/db/queries")
        assert level == "trace"

        # Next most specific
        level = manager.get_effective_level("/infra/db/pg")
        assert level == "debug"

        # Least specific
        level = manager.get_effective_level("/infra/api/handler")
        assert level == "info"


# =============================================================================
# Test Rule Precedence
# =============================================================================


class TestPrecedence:
    """Test rule priority precedence."""

    def test_priority_overrides_specificity(self, manager):
        """Test that higher priority wins over specificity."""
        # YAML rule (priority=1) with high specificity
        manager.add_rule("/infra/db/queries", "info", source="yaml", priority=1)

        # CLI rule (priority=5) with lower specificity
        manager.add_rule("/infra/db/*", "debug", source="cli", priority=5)

        # CLI should win due to higher priority
        level = manager.get_effective_level("/infra/db/queries")
        assert level == "debug"

    def test_api_over_cli_over_yaml(self, manager):
        """Test precedence: API (10) > CLI (5) > YAML (1)."""
        manager.add_rule("/infra/db/*", "info", source="yaml", priority=1)
        manager.add_rule("/infra/db/*", "debug", source="cli", priority=5)
        manager.add_rule("/infra/db/*", "trace", source="api", priority=10)

        # API should win
        level = manager.get_effective_level("/infra/db/queries")
        assert level == "trace"

    def test_equal_priority_uses_specificity(self, manager):
        """Test that specificity breaks ties when priority is equal."""
        manager.add_rule("/infra/**", "info", source="yaml", priority=1)
        manager.add_rule("/infra/db/*", "debug", source="yaml", priority=1)

        # More specific pattern should win
        level = manager.get_effective_level("/infra/db/queries")
        assert level == "debug"


# =============================================================================
# Test Runtime Updates
# =============================================================================


class TestRuntimeUpdates:
    """Test runtime update functionality."""

    def test_runtime_updates_disabled_by_default(self, manager):
        """Test that runtime updates are disabled by default."""
        assert not manager.is_runtime_updates_enabled()

    def test_enable_runtime_updates(self, manager):
        """Test enabling runtime updates."""
        manager.enable_runtime_updates()
        assert manager.is_runtime_updates_enabled()

    def test_disable_runtime_updates(self, manager):
        """Test disabling runtime updates."""
        manager.enable_runtime_updates()
        manager.disable_runtime_updates()
        assert not manager.is_runtime_updates_enabled()

    def test_runtime_updates_updates_existing_loggers(self, manager):
        """Test that runtime updates modify existing loggers."""
        # Create a test logger
        test_logger = logging.getLogger("/infra/db/test")
        test_logger.setLevel(logging.INFO)

        # Enable runtime updates and add rule
        manager.enable_runtime_updates()
        manager.add_rule("/infra/db/*", "debug", source="api", priority=10)

        # Logger should be updated
        # Convert to numeric level for comparison
        expected_level = getattr(logging, "DEBUG")
        assert test_logger.level == expected_level

    def test_runtime_updates_with_numeric_level(self, manager):
        """Test that runtime updates work with numeric level values."""
        # Create a test logger
        test_logger = logging.getLogger("/infra/numeric/test")
        test_logger.setLevel(logging.INFO)

        # Enable runtime updates and add rule with numeric level
        manager.enable_runtime_updates()
        manager.add_rule("/infra/numeric/*", logging.DEBUG, source="api", priority=10)

        # Logger should be updated to DEBUG level
        assert test_logger.level == logging.DEBUG

    def test_runtime_updates_with_handler(self, manager):
        """Test that runtime updates also update handler levels."""
        # Create a test logger with a handler
        test_logger = logging.getLogger("/infra/handler/test")
        test_logger.setLevel(logging.INFO)
        handler = logging.StreamHandler()
        handler.setLevel(logging.INFO)
        test_logger.addHandler(handler)

        try:
            # Enable runtime updates and add rule
            manager.enable_runtime_updates()
            manager.add_rule("/infra/handler/*", "debug", source="api", priority=10)

            # Both logger and handler should be updated
            assert test_logger.level == logging.DEBUG
            assert handler.level == logging.DEBUG
        finally:
            test_logger.removeHandler(handler)


# =============================================================================
# Test Edge Cases
# =============================================================================


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_empty_pattern_raises_error(self, manager):
        """Test that empty pattern raises ValueError."""
        with pytest.raises(ValueError, match="Pattern cannot be empty"):
            manager.add_rule("", "debug", source="yaml", priority=1)

    def test_pattern_without_leading_slash_raises_error(self, manager):
        """Test that pattern without leading slash raises ValueError."""
        with pytest.raises(ValueError, match="must start with '/'"):
            manager.add_rule("infra/db/*", "debug", source="yaml", priority=1)

    def test_no_matching_pattern_returns_none(self, manager):
        """Test that no match returns None."""
        manager.add_rule("/infra/db/*", "debug", source="yaml", priority=1)
        level = manager.get_effective_level("/other/path")
        assert level is None

    def test_set_and_get_default_level(self, manager):
        """Test setting and getting default level."""
        manager.set_default_level("warning")
        assert manager.get_default_level() == "warning"


# =============================================================================
# Test Thread Safety
# =============================================================================


class TestThreadSafety:
    """Test thread-safe operations."""

    def test_concurrent_rule_additions(self, manager):
        """Test that concurrent rule additions are thread-safe."""

        def add_rules(source, start):
            for i in range(10):
                pattern = f"/test/{source}/{i}"
                manager.add_rule(pattern, "debug", source=source, priority=1)

        threads = []
        for i in range(5):
            t = threading.Thread(target=add_rules, args=(f"source{i}", i * 10))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # Should have 50 rules total (5 threads * 10 rules each)
        rules = manager.get_rules()
        assert len(rules) == 50

    def test_concurrent_reads_and_writes(self, manager):
        """Test concurrent reads and writes."""
        manager.add_rule("/infra/**", "info", source="yaml", priority=1)

        results = []

        def read_level():
            for _ in range(100):
                level = manager.get_effective_level("/infra/db/queries")
                results.append(level)

        def write_rule():
            for i in range(10):
                manager.add_rule(f"/test/{i}", "debug", source="api", priority=10)

        threads = []
        for _ in range(3):
            threads.append(threading.Thread(target=read_level))
        for _ in range(2):
            threads.append(threading.Thread(target=write_rule))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All reads should have succeeded
        assert len(results) == 300  # 3 threads * 100 reads each


# =============================================================================
# Test Integration Scenarios
# =============================================================================


class TestIntegrationScenarios:
    """Test real-world usage scenarios."""

    def test_yaml_cli_api_precedence_scenario(self, manager):
        """Test realistic precedence scenario with all sources."""
        # YAML config
        manager.add_rules_from_dict(
            {"/infra/**": "info", "/infra/db/*": "debug"}, source="yaml", priority=1
        )

        # CLI override
        manager.add_rule("/infra/db/queries", "warning", source="cli", priority=5)

        # API override
        manager.add_rule("/infra/db/*", "trace", source="api", priority=10)

        # API should win for general DB loggers
        assert manager.get_effective_level("/infra/db/pg") == "trace"

        # But CLI is more specific for queries, and has higher priority than YAML
        # However, API has even higher priority, so API wins
        assert manager.get_effective_level("/infra/db/queries") == "trace"

    def test_complex_pattern_hierarchy(self, manager):
        """Test complex hierarchical patterns."""
        manager.add_rules_from_dict(
            {
                "/myapp/**": "warning",
                "/myapp/critical/**": "error",
                "/myapp/critical/security/*": "critical",
                "/myapp/debug/**": "debug",
            },
            source="yaml",
            priority=1,
        )

        assert manager.get_effective_level("/myapp/normal/handler") == "warning"
        assert manager.get_effective_level("/myapp/critical/processor") == "error"
        assert (
            manager.get_effective_level("/myapp/critical/security/auth") == "critical"
        )
        assert manager.get_effective_level("/myapp/debug/verbose/trace") == "debug"


# =============================================================================
# Test Serialization (for multiprocessing)
# =============================================================================


class TestSerialization:
    """Test to_dict() and from_dict() for multiprocessing support."""

    def test_to_dict_empty_manager(self, manager):
        """Test to_dict with no rules."""
        result = manager.to_dict()

        assert "rules" in result
        assert "default_level" in result
        assert result["rules"] == []
        assert result["default_level"] == logging.INFO

    def test_to_dict_with_rules(self, manager):
        """Test to_dict serializes rules correctly."""
        manager.add_rule("/worker/*", "warning", source="yaml", priority=1)
        manager.add_rule("/worker/verbose/*", "debug", source="api", priority=10)

        result = manager.to_dict()

        assert len(result["rules"]) == 2
        # Rules should be sorted by priority desc
        assert result["rules"][0]["pattern"] == "/worker/verbose/*"
        assert result["rules"][0]["level"] == "debug"
        assert result["rules"][0]["source"] == "api"
        assert result["rules"][0]["priority"] == 10
        assert result["rules"][1]["pattern"] == "/worker/*"

    def test_to_dict_includes_default_level(self, manager):
        """Test to_dict includes custom default level."""
        manager.set_default_level("error")
        result = manager.to_dict()

        assert result["default_level"] == "error"

    def test_from_dict_restores_rules(self, manager):
        """Test from_dict restores rules correctly."""
        config = {
            "rules": [
                {
                    "pattern": "/worker/*",
                    "level": "warning",
                    "source": "yaml",
                    "priority": 1,
                    "specificity": 11,
                },
            ],
            "default_level": "debug",
        }

        manager.from_dict(config)

        assert manager.get_effective_level("/worker/task1") == "warning"
        assert manager.get_default_level() == "debug"

    def test_from_dict_clears_existing_rules(self, manager):
        """Test from_dict replaces existing rules."""
        manager.add_rule("/old/*", "error", source="yaml", priority=1)

        config = {
            "rules": [
                {
                    "pattern": "/new/*",
                    "level": "info",
                    "source": "yaml",
                    "priority": 1,
                    "specificity": 11,
                },
            ],
            "default_level": logging.INFO,
        }

        manager.from_dict(config)

        # Old rule should be gone
        assert manager.get_effective_level("/old/logger") is None
        # New rule should be active
        assert manager.get_effective_level("/new/logger") == "info"

    def test_roundtrip_serialization(self, manager):
        """Test to_dict -> from_dict roundtrip preserves state."""
        manager.add_rule("/api/*", "info", source="yaml", priority=1)
        manager.add_rule("/api/auth/*", "debug", source="cli", priority=5)
        manager.set_default_level("warning")

        config = manager.to_dict()

        # Reset and restore
        LogLevelManager.reset_instance()
        new_manager = LogLevelManager.get_instance()
        new_manager.from_dict(config)

        # Verify state is preserved
        assert new_manager.get_effective_level("/api/handler") == "info"
        assert new_manager.get_effective_level("/api/auth/login") == "debug"
        assert new_manager.get_default_level() == "warning"

    def test_to_dict_is_picklable(self, manager):
        """Test to_dict output can be pickled (required for multiprocessing)."""
        import pickle

        manager.add_rule("/worker/*", "warning", source="yaml", priority=1)
        manager.set_default_level("error")

        config = manager.to_dict()
        pickled = pickle.dumps(config)
        restored = pickle.loads(pickled)

        assert restored == config
