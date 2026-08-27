# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for logger factory.

Tests key functionality including:
- create_root method
- Logger already exists branch
- create_child method
- derive method
- Hot-reload of location via holder
"""

import collections
import logging

import pytest

from appinfra.log.config import LogConfig
from appinfra.log.config_holder import LogConfigHolder
from appinfra.log.factory import LoggerFactory

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def log_config():
    """Create basic log configuration."""
    return LogConfig(level=logging.DEBUG, location=0, micros=False, colors=False)


@pytest.fixture
def unique_logger_name():
    """Generate unique logger name to avoid collisions."""
    import uuid

    return f"test_logger_{uuid.uuid4().hex[:8]}"


@pytest.fixture(autouse=True)
def cleanup_loggers():
    """Clean up loggers after each test."""
    yield
    # Clean up any test loggers created
    to_remove = [
        name
        for name in logging.root.manager.loggerDict
        if name.startswith("test_") or name.startswith("/")
    ]
    for name in to_remove:
        if name in logging.root.manager.loggerDict:
            lg = logging.getLogger(name)
            lg.handlers.clear()


# =============================================================================
# Test create_root method - Line 35
# =============================================================================


@pytest.mark.unit
class TestCreateRoot:
    """Test create_root method."""

    def test_create_root_basic(self, log_config):
        """Test create_root creates root logger (line 35)."""
        logger = LoggerFactory.create_root(log_config)

        assert logger is not None
        assert logger.name == "/"

        # Cleanup
        logger.handlers.clear()


# =============================================================================
# Test logger already exists branch - Lines 64-66
# =============================================================================


@pytest.mark.unit
class TestLoggerExists:
    """Test logger already exists branch."""

    def test_create_returns_existing_logger_when_registered(
        self, log_config, unique_logger_name
    ):
        """Test create returns existing logger if in manager (lines 64-66)."""
        # First, manually register a logger in the manager to trigger the branch
        existing_logger = logging.getLogger(unique_logger_name)

        # Now call LoggerFactory.create - should hit the "already exists" branch
        logger = LoggerFactory.create(unique_logger_name, log_config)

        # Should return the existing logger (or at least not crash)
        assert logger.name == unique_logger_name

        # Cleanup
        existing_logger.handlers.clear()
        if hasattr(logger, "handlers"):
            logger.handlers.clear()


# =============================================================================
# Test create_child method - Lines 107-122
# =============================================================================


@pytest.mark.unit
class TestCreateChild:
    """Test create_child method."""

    def test_create_child_from_parent(self, log_config, unique_logger_name):
        """Test create_child creates properly named child (lines 107-122)."""
        parent = LoggerFactory.create(unique_logger_name, log_config)

        child = LoggerFactory.create_child(parent, "child")

        assert child is not None
        assert child.name == f"{unique_logger_name}/child"

        # Cleanup
        parent.handlers.clear()
        child.handlers.clear()

    def test_create_child_from_root(self, log_config):
        """Test create_child from root logger."""
        root = LoggerFactory.create_root(log_config)

        child = LoggerFactory.create_child(root, "root_child")

        assert child.name == "/root_child"

        # Cleanup
        root.handlers.clear()
        child.handlers.clear()

    def test_create_child_inherits_config(self, log_config, unique_logger_name):
        """Test create_child inherits parent configuration."""
        parent = LoggerFactory.create(unique_logger_name, log_config)

        child = LoggerFactory.create_child(parent, "config_child")

        assert child.get_level() == parent.get_level()
        assert child.location == parent.location
        assert child.micros == parent.micros

        # Cleanup
        parent.handlers.clear()
        child.handlers.clear()


# =============================================================================
# Test derive method - Lines 136-155
# =============================================================================


@pytest.mark.unit
class TestDerive:
    """Test derive method."""

    def test_derive_with_single_tag(self, log_config, unique_logger_name):
        """Test derive with single tag string (lines 136-155)."""
        parent = LoggerFactory.create(unique_logger_name, log_config)

        derived = LoggerFactory.derive(parent, "tag1")

        assert derived.name == f"{unique_logger_name}/tag1"

        # Cleanup
        parent.handlers.clear()
        derived.handlers.clear()

    def test_derive_with_multiple_tags(self, log_config, unique_logger_name):
        """Test derive with list of tags."""
        parent = LoggerFactory.create(unique_logger_name, log_config)

        derived = LoggerFactory.derive(parent, ["tag1", "tag2", "tag3"])

        assert derived.name == f"{unique_logger_name}/tag1/tag2/tag3"

        # Cleanup
        parent.handlers.clear()
        derived.handlers.clear()

    def test_derive_from_root(self, log_config):
        """Test derive from root logger."""
        root = LoggerFactory.create_root(log_config)

        derived = LoggerFactory.derive(root, "derived_tag")

        # Root is "/" so derived name starts with /
        assert derived.name == "/derived_tag"

        # Cleanup
        root.handlers.clear()
        derived.handlers.clear()

    def test_derive_inherits_config(self, log_config, unique_logger_name):
        """Test derived logger inherits configuration."""
        parent = LoggerFactory.create(unique_logger_name, log_config)

        derived = LoggerFactory.derive(parent, ["service", "component"])

        assert derived.get_level() == parent.get_level()
        assert derived.location == parent.location

        # Cleanup
        parent.handlers.clear()
        derived.handlers.clear()


# =============================================================================
# Test Integration Scenarios
# =============================================================================


@pytest.mark.integration
class TestFactoryIntegration:
    """Test factory integration scenarios."""

    def test_full_logger_hierarchy(self, log_config, unique_logger_name):
        """Test creating a full logger hierarchy."""
        # Create root
        root = LoggerFactory.create(unique_logger_name, log_config)

        # Create children
        child1 = LoggerFactory.create_child(root, "service_a")
        child2 = LoggerFactory.create_child(root, "service_b")

        # Derive from children
        derived1 = LoggerFactory.derive(child1, ["component", "subcomponent"])

        # Verify hierarchy
        assert child1.name == f"{unique_logger_name}/service_a"
        assert child2.name == f"{unique_logger_name}/service_b"
        assert derived1.name == f"{unique_logger_name}/service_a/component/subcomponent"

        # Cleanup
        for lg in [root, child1, child2, derived1]:
            lg.handlers.clear()

    def test_factory_with_extra_fields(self, log_config, unique_logger_name):
        """Test factory with extra fields."""
        extra = {"service": "api", "version": "1.0"}
        logger = LoggerFactory.create(
            f"{unique_logger_name}_extra", log_config, extra=extra
        )

        assert logger is not None
        # Extra fields are stored on the logger
        assert logger._extra == extra

        # Cleanup
        logger.handlers.clear()

    def test_factory_with_ordered_dict_extra(self, log_config, unique_logger_name):
        """Test factory with OrderedDict extra fields."""
        extra = collections.OrderedDict([("first", 1), ("second", 2)])
        logger = LoggerFactory.create(
            f"{unique_logger_name}_ordered", log_config, extra=extra
        )

        assert logger._extra == extra

        # Cleanup
        logger.handlers.clear()


# =============================================================================
# Test Hot-Reload of Location via Holder
# =============================================================================


@pytest.mark.unit
class TestLoggerHolderHotReload:
    """Test that logger location is hot-reloadable via registry.

    Note: location and micros are global settings read from the registry's
    default config. This enables hot-reload - all loggers read from the
    same source.
    """

    def test_logger_has_holder_set(self, unique_logger_name):
        """Test that created loggers have holder set."""
        config = LogConfig(level=logging.DEBUG, location=2, micros=False, colors=False)
        logger = LoggerFactory.create(unique_logger_name, config)

        assert logger._holder is not None
        assert isinstance(logger._holder, LogConfigHolder)

        # Cleanup
        logger.handlers.clear()

    def test_logger_location_reads_from_holder(self, unique_logger_name):
        """Test location property reads from holder."""
        config = LogConfig(level=logging.DEBUG, location=3, micros=False, colors=False)
        logger = LoggerFactory.create(unique_logger_name, config)

        # Logger reads location from holder
        assert logger.location == logger._holder.location
        assert logger.location == 3

        # Cleanup
        logger.handlers.clear()

    def test_logger_location_updates_on_holder_update(self, unique_logger_name):
        """Test location property updates when holder is updated."""
        config = LogConfig(level=logging.DEBUG, location=2, micros=False, colors=False)
        logger = LoggerFactory.create(unique_logger_name, config)

        # Initial location from holder
        assert logger.location == 2

        # Update the holder with new config
        new_config = LogConfig(
            level=logging.DEBUG, location=5, micros=False, colors=False
        )
        logger._holder.update(new_config)

        # Logger location should now reflect the new value
        assert logger.location == 5

        # Cleanup
        logger.handlers.clear()

    def test_child_logger_shares_holder_with_root(self, unique_logger_name):
        """Test child loggers share holder with root for consistent hot-reload."""
        config = LogConfig(level=logging.DEBUG, location=2, micros=False, colors=False)
        parent = LoggerFactory.create(unique_logger_name, config)
        child = LoggerFactory.create_child(parent, "child")

        # Both should have the same holder
        assert child._holder is parent._holder

        # Cleanup
        parent.handlers.clear()
        child.handlers.clear()

    def test_derived_logger_shares_holder_with_root(self, unique_logger_name):
        """Test derived loggers share holder with root for consistent hot-reload."""
        config = LogConfig(level=logging.DEBUG, location=2, micros=False, colors=False)
        parent = LoggerFactory.create(unique_logger_name, config)
        derived = LoggerFactory.derive(parent, ["service", "component"])

        # Both should have the same holder
        assert derived._holder is parent._holder

        # Cleanup
        parent.handlers.clear()
        derived.handlers.clear()

    def test_holder_update_affects_all_loggers_in_hierarchy(self, unique_logger_name):
        """Test holder update affects parent and all derived loggers."""
        config = LogConfig(level=logging.DEBUG, location=1, micros=False, colors=False)
        parent = LoggerFactory.create(unique_logger_name, config)
        child = LoggerFactory.create_child(parent, "child")
        derived = LoggerFactory.derive(parent, ["service", "component"])

        # All read location from shared holder
        assert parent.location == 1
        assert child.location == 1
        assert derived.location == 1

        # Update holder (shared by all)
        new_config = LogConfig(
            level=logging.DEBUG, location=4, micros=False, colors=False
        )
        parent._holder.update(new_config)

        # All should now show location=4 (they share the same holder)
        assert parent.location == 4
        assert child.location == 4
        assert derived.location == 4

        # Cleanup
        for lg in [parent, child, derived]:
            lg.handlers.clear()
