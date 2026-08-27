# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for app/tracing/traceable.py.

Tests key functionality including:
- Traceable initialization
- Parent property and set_parent method
- trace_attr method with hierarchy lookup
- Cycle detection and depth limiting
- trace_root, has_attr, get_attr_or_default methods
"""

from unittest.mock import Mock

import pytest

from appinfra.app.constants import MAX_TRACE_DEPTH
from appinfra.app.errors import AttrNotFoundError
from appinfra.app.tracing.traceable import Traceable

# =============================================================================
# Test Traceable Initialization
# =============================================================================


@pytest.mark.unit
class TestTraceableInit:
    """Test Traceable initialization."""

    def test_init_without_parent(self):
        """Test initialization without parent."""
        traceable = Traceable()

        assert traceable._parent is None

    def test_init_with_parent(self):
        """Test initialization with parent."""
        parent = Traceable()
        child = Traceable(parent=parent)

        assert child._parent is parent


# =============================================================================
# Test parent property
# =============================================================================


@pytest.mark.unit
class TestParentProperty:
    """Test Traceable.parent property."""

    def test_returns_none_when_no_parent(self):
        """Test returns None when no parent set."""
        traceable = Traceable()

        assert traceable.parent is None

    def test_returns_parent_when_set(self):
        """Test returns parent when set."""
        parent = Traceable()
        child = Traceable(parent=parent)

        assert child.parent is parent


# =============================================================================
# Test set_parent method
# =============================================================================


@pytest.mark.unit
class TestSetParent:
    """Test Traceable.set_parent method."""

    def test_sets_parent_to_traceable(self):
        """Test sets parent to Traceable instance."""
        parent = Traceable()
        child = Traceable()

        child.set_parent(parent)

        assert child.parent is parent

    def test_sets_parent_to_none(self):
        """Test sets parent to None."""
        parent = Traceable()
        child = Traceable(parent=parent)

        child.set_parent(None)

        assert child.parent is None

    def test_raises_for_non_traceable_parent(self):
        """Test raises TypeError for non-Traceable parent."""
        traceable = Traceable()

        with pytest.raises(TypeError) as exc_info:
            traceable.set_parent("not a traceable")

        assert "Traceable instance" in str(exc_info.value)
        assert "str" in str(exc_info.value)

    def test_raises_for_dict_parent(self):
        """Test raises TypeError for dict parent."""
        traceable = Traceable()

        with pytest.raises(TypeError) as exc_info:
            traceable.set_parent({"key": "value"})

        assert "dict" in str(exc_info.value)


# =============================================================================
# Test trace_attr method
# =============================================================================


@pytest.mark.unit
class TestTraceAttr:
    """Test Traceable.trace_attr method."""

    def test_finds_local_instance_attribute(self):
        """Test finds attribute in instance __dict__."""
        traceable = Traceable()
        traceable.my_attr = "my_value"

        result = traceable.trace_attr("my_attr")

        assert result == "my_value"

    def test_finds_class_attribute(self):
        """Test finds attribute in class."""

        class MyTraceable(Traceable):
            class_attr = "class_value"

        traceable = MyTraceable()

        result = traceable.trace_attr("class_attr")

        assert result == "class_value"

    def test_finds_property(self):
        """Test finds property in class."""

        class MyTraceable(Traceable):
            @property
            def my_property(self):
                return "property_value"

        traceable = MyTraceable()

        result = traceable.trace_attr("my_property")

        assert result == "property_value"

    def test_finds_method(self):
        """Test finds method in class."""

        class MyTraceable(Traceable):
            def my_method(self):
                return "method_result"

        traceable = MyTraceable()

        result = traceable.trace_attr("my_method")

        assert callable(result)
        assert result() == "method_result"

    def test_finds_attribute_in_parent(self):
        """Test finds attribute from parent."""
        parent = Traceable()
        parent.parent_attr = "parent_value"

        child = Traceable(parent=parent)

        result = child.trace_attr("parent_attr")

        assert result == "parent_value"

    def test_finds_attribute_in_grandparent(self):
        """Test finds attribute from grandparent."""
        grandparent = Traceable()
        grandparent.grandparent_attr = "grandparent_value"

        parent = Traceable(parent=grandparent)
        child = Traceable(parent=parent)

        result = child.trace_attr("grandparent_attr")

        assert result == "grandparent_value"

    def test_prefers_local_attribute_over_parent(self):
        """Test prefers local attribute over parent's."""
        parent = Traceable()
        parent.shared_attr = "parent_value"

        child = Traceable(parent=parent)
        child.shared_attr = "child_value"

        result = child.trace_attr("shared_attr")

        assert result == "child_value"

    def test_raises_when_attribute_not_found(self):
        """Test raises AttrNotFoundError when not found."""
        traceable = Traceable()

        with pytest.raises(AttrNotFoundError) as exc_info:
            traceable.trace_attr("nonexistent")

        assert "nonexistent" in str(exc_info.value)

    def test_raises_for_circular_reference(self):
        """Test raises AttrNotFoundError for circular reference."""
        obj1 = Traceable()
        obj2 = Traceable(parent=obj1)

        # Create circular reference
        obj1._parent = obj2

        with pytest.raises(AttrNotFoundError) as exc_info:
            obj1.trace_attr("nonexistent")

        assert "circular reference" in str(exc_info.value)

    def test_raises_for_max_depth_exceeded(self):
        """Test raises AttrNotFoundError when max depth exceeded."""
        # Create chain longer than MAX_TRACE_DEPTH would be impractical
        # Instead, test with mocked depth
        traceable = Traceable()

        with pytest.raises(AttrNotFoundError) as exc_info:
            traceable.trace_attr("test", _depth=MAX_TRACE_DEPTH)

        assert "maximum trace depth" in str(exc_info.value)


# =============================================================================
# Test trace_root method
# =============================================================================


@pytest.mark.unit
class TestTraceRoot:
    """Test Traceable.trace_root method."""

    def test_returns_self_when_no_parent(self):
        """Test returns self when no parent."""
        traceable = Traceable()

        result = traceable.trace_root()

        assert result is traceable

    def test_returns_parent_when_one_level(self):
        """Test returns parent when one level deep."""
        parent = Traceable()
        child = Traceable(parent=parent)

        result = child.trace_root()

        assert result is parent

    def test_returns_grandparent_when_two_levels(self):
        """Test returns root when two levels deep."""
        grandparent = Traceable()
        parent = Traceable(parent=grandparent)
        child = Traceable(parent=parent)

        result = child.trace_root()

        assert result is grandparent

    def test_returns_root_in_long_chain(self):
        """Test returns root in longer chain."""
        root = Traceable()
        current = root

        for _ in range(5):
            child = Traceable(parent=current)
            current = child

        result = current.trace_root()

        assert result is root


# =============================================================================
# Test has_attr method
# =============================================================================


@pytest.mark.unit
class TestHasAttr:
    """Test Traceable.has_attr method."""

    def test_returns_true_for_existing_local_attr(self):
        """Test returns True for existing local attribute."""
        traceable = Traceable()
        traceable.existing = "value"

        assert traceable.has_attr("existing") is True

    def test_returns_true_for_existing_parent_attr(self):
        """Test returns True for existing parent attribute."""
        parent = Traceable()
        parent.parent_attr = "value"
        child = Traceable(parent=parent)

        assert child.has_attr("parent_attr") is True

    def test_returns_false_for_nonexistent_attr(self):
        """Test returns False for nonexistent attribute."""
        traceable = Traceable()

        assert traceable.has_attr("nonexistent") is False


# =============================================================================
# Test get_attr_or_default method
# =============================================================================


@pytest.mark.unit
class TestGetAttrOrDefault:
    """Test Traceable.get_attr_or_default method."""

    def test_returns_attribute_when_found(self):
        """Test returns attribute value when found."""
        traceable = Traceable()
        traceable.my_attr = "my_value"

        result = traceable.get_attr_or_default("my_attr", "default")

        assert result == "my_value"

    def test_returns_parent_attribute_when_found(self):
        """Test returns parent attribute value when found."""
        parent = Traceable()
        parent.parent_attr = "parent_value"
        child = Traceable(parent=parent)

        result = child.get_attr_or_default("parent_attr", "default")

        assert result == "parent_value"

    def test_returns_default_when_not_found(self):
        """Test returns default value when not found."""
        traceable = Traceable()

        result = traceable.get_attr_or_default("nonexistent", "my_default")

        assert result == "my_default"

    def test_returns_none_when_not_found_and_no_default(self):
        """Test returns None when not found and no default specified."""
        traceable = Traceable()

        result = traceable.get_attr_or_default("nonexistent")

        assert result is None


# =============================================================================
# Integration Tests
# =============================================================================


@pytest.mark.integration
class TestTraceableIntegration:
    """Integration tests for Traceable."""

    def test_hierarchical_configuration(self):
        """Test hierarchical configuration pattern."""

        class Config(Traceable):
            def __init__(self, parent=None, **settings):
                super().__init__(parent)
                for key, value in settings.items():
                    setattr(self, key, value)

        # Root config with defaults
        root_config = Config(
            debug=False,
            log_level="INFO",
            timeout=30,
        )

        # Environment config inherits from root
        dev_config = Config(
            parent=root_config,
            debug=True,
            log_level="DEBUG",
        )

        # App config inherits from environment
        app_config = Config(
            parent=dev_config,
            app_name="MyApp",
        )

        # Local overrides root
        assert app_config.trace_attr("debug") is True
        assert app_config.trace_attr("log_level") == "DEBUG"

        # Inherited from root
        assert app_config.trace_attr("timeout") == 30

        # Local only
        assert app_config.trace_attr("app_name") == "MyApp"

        # Root finding
        assert app_config.trace_root() is root_config

        # Attribute checking
        assert app_config.has_attr("timeout") is True
        assert app_config.has_attr("unknown") is False

        # Default values
        assert app_config.get_attr_or_default("unknown", 42) == 42

    def test_tool_hierarchy_pattern(self):
        """Test tool parent-child pattern used in the framework."""

        class Tool(Traceable):
            def __init__(self, name, parent=None):
                super().__init__(parent)
                self.name = name

            @property
            def args(self):
                # Try to find args in hierarchy
                return self.get_attr_or_default("_args")

            @property
            def logger(self):
                # Try to find logger in hierarchy
                return self.get_attr_or_default("_logger")

        # Parent tool with shared resources
        parent_tool = Tool("parent")
        parent_tool._args = {"verbose": True}
        parent_tool._logger = Mock()

        # Child tool inherits resources
        child_tool = Tool("child", parent=parent_tool)

        # Child accesses parent's args via hierarchy
        assert child_tool.args == {"verbose": True}

        # Child accesses parent's logger via hierarchy
        assert child_tool.logger is parent_tool._logger

        # Child can override by setting local attribute
        child_tool._args = {"verbose": False}
        assert child_tool.args == {"verbose": False}

    def test_dynamic_parent_reassignment(self):
        """Test changing parent dynamically."""

        class Node(Traceable):
            def __init__(self, value, parent=None):
                super().__init__(parent)
                self.value = value

        root_a = Node("A")
        root_a.shared = "from_A"

        root_b = Node("B")
        root_b.shared = "from_B"

        node = Node("child", parent=root_a)

        # Initially inherits from A
        assert node.trace_attr("shared") == "from_A"
        assert node.trace_root() is root_a

        # Reassign to B
        node.set_parent(root_b)

        # Now inherits from B
        assert node.trace_attr("shared") == "from_B"
        assert node.trace_root() is root_b

        # Detach completely
        node.set_parent(None)

        assert node.parent is None
        assert node.trace_root() is node
        assert node.has_attr("shared") is False
