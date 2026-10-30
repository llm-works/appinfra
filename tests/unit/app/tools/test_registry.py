# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for app/tools/registry.py.

Tests key functionality including:
- Tool name validation
- Tool count limits
- Alias validation and registration
- ToolRegistry class methods
"""

from unittest.mock import Mock

import pytest

from appinfra.app.constants import MAX_ALIAS_COUNT, MAX_TOOL_COUNT, MAX_TOOL_NAME_LENGTH
from appinfra.app.errors import DupToolError, ToolRegistrationError
from appinfra.app.tools.registry import (
    ToolRegistry,
    _check_tool_count_limit,
    _validate_and_register_aliases,
    _validate_tool_name,
)

# =============================================================================
# Test _validate_tool_name
# =============================================================================


@pytest.mark.unit
class TestValidateToolName:
    """Test _validate_tool_name helper function."""

    def test_accepts_valid_simple_name(self):
        """Test accepts simple lowercase name."""
        _validate_tool_name("mytool")  # Should not raise

    def test_accepts_name_with_numbers(self):
        """Test accepts name with numbers."""
        _validate_tool_name("tool1")  # Should not raise

    def test_accepts_name_with_underscore(self):
        """Test accepts name with underscore."""
        _validate_tool_name("my_tool")  # Should not raise

    def test_accepts_name_with_hyphen(self):
        """Test accepts name with hyphen."""
        _validate_tool_name("my-tool")  # Should not raise

    def test_rejects_empty_name(self):
        """Test rejects empty string."""
        with pytest.raises(ToolRegistrationError) as exc_info:
            _validate_tool_name("")

        assert "must have a name" in str(exc_info.value)

    def test_rejects_name_exceeding_max_length(self):
        """Test rejects name longer than MAX_TOOL_NAME_LENGTH."""
        long_name = "a" * (MAX_TOOL_NAME_LENGTH + 1)

        with pytest.raises(ToolRegistrationError) as exc_info:
            _validate_tool_name(long_name)

        assert "exceeds maximum length" in str(exc_info.value)

    def test_rejects_name_starting_with_number(self):
        """Test rejects name starting with number."""
        with pytest.raises(ToolRegistrationError) as exc_info:
            _validate_tool_name("1tool")

        assert "must start with a lowercase letter" in str(exc_info.value)

    def test_rejects_name_starting_with_uppercase(self):
        """Test rejects name starting with uppercase."""
        with pytest.raises(ToolRegistrationError) as exc_info:
            _validate_tool_name("Tool")

        assert "must start with a lowercase letter" in str(exc_info.value)

    def test_rejects_name_with_spaces(self):
        """Test rejects name with spaces."""
        with pytest.raises(ToolRegistrationError) as exc_info:
            _validate_tool_name("my tool")

        assert "must start with a lowercase letter" in str(exc_info.value)

    def test_rejects_name_with_special_chars(self):
        """Test rejects name with special characters."""
        with pytest.raises(ToolRegistrationError) as exc_info:
            _validate_tool_name("my@tool")

        assert "must start with a lowercase letter" in str(exc_info.value)


# =============================================================================
# Test _check_tool_count_limit
# =============================================================================


@pytest.mark.unit
class TestCheckToolCountLimit:
    """Test _check_tool_count_limit helper function."""

    def test_passes_when_under_limit(self):
        """Test passes when tool count is under limit."""
        tools_dict = {"tool1": Mock(), "tool2": Mock()}

        _check_tool_count_limit(tools_dict, "newtool")  # Should not raise

    def test_passes_when_at_limit_minus_one(self):
        """Test passes when at limit minus one."""
        tools_dict = {f"tool{i}": Mock() for i in range(MAX_TOOL_COUNT - 1)}

        _check_tool_count_limit(tools_dict, "newtool")  # Should not raise

    def test_raises_when_at_limit(self):
        """Test raises when tool count equals limit."""
        tools_dict = {f"tool{i}": Mock() for i in range(MAX_TOOL_COUNT)}

        with pytest.raises(ToolRegistrationError) as exc_info:
            _check_tool_count_limit(tools_dict, "newtool")

        assert "maximum tool count" in str(exc_info.value)


# =============================================================================
# Test _validate_and_register_aliases
# =============================================================================


@pytest.mark.unit
class TestValidateAndRegisterAliases:
    """Test _validate_and_register_aliases helper function."""

    def test_registers_valid_aliases(self):
        """Test registers valid aliases."""
        aliases_dict = {}
        aliases = ["a", "b", "c"]

        _validate_and_register_aliases("mytool", aliases, aliases_dict)

        assert aliases_dict == {"a": "mytool", "b": "mytool", "c": "mytool"}

    def test_accepts_alias_with_numbers(self):
        """Test accepts alias with numbers."""
        aliases_dict = {}

        _validate_and_register_aliases("mytool", ["alias1"], aliases_dict)

        assert aliases_dict == {"alias1": "mytool"}

    def test_accepts_alias_with_hyphen(self):
        """Test accepts alias with hyphen."""
        aliases_dict = {}

        _validate_and_register_aliases("mytool", ["my-alias"], aliases_dict)

        assert aliases_dict == {"my-alias": "mytool"}

    def test_raises_when_too_many_aliases(self):
        """Test raises when alias count exceeds limit."""
        aliases_dict = {}
        aliases = [f"alias{i}" for i in range(MAX_ALIAS_COUNT + 1)]

        with pytest.raises(ToolRegistrationError) as exc_info:
            _validate_and_register_aliases("mytool", aliases, aliases_dict)

        assert f"exceeding maximum of {MAX_ALIAS_COUNT}" in str(exc_info.value)

    def test_raises_for_invalid_alias_format(self):
        """Test raises for alias with invalid format."""
        aliases_dict = {}

        with pytest.raises(ToolRegistrationError) as exc_info:
            _validate_and_register_aliases("mytool", ["Invalid"], aliases_dict)

        assert "must start with a lowercase letter" in str(exc_info.value)

    def test_raises_for_alias_starting_with_number(self):
        """Test raises for alias starting with number."""
        aliases_dict = {}

        with pytest.raises(ToolRegistrationError) as exc_info:
            _validate_and_register_aliases("mytool", ["1alias"], aliases_dict)

        assert "must start with a lowercase letter" in str(exc_info.value)

    def test_raises_for_duplicate_alias(self):
        """Test raises when alias already registered."""
        aliases_dict = {"existing": "othertool"}

        with pytest.raises(ToolRegistrationError) as exc_info:
            _validate_and_register_aliases("mytool", ["existing"], aliases_dict)

        assert "already registered" in str(exc_info.value)
        assert "othertool" in str(exc_info.value)


# =============================================================================
# Test ToolRegistry.__init__
# =============================================================================


@pytest.mark.unit
class TestToolRegistryInit:
    """Test ToolRegistry initialization."""

    def test_initializes_empty_tools_dict(self):
        """Test initializes with empty tools dict."""
        registry = ToolRegistry()

        assert registry._tools == {}

    def test_initializes_empty_aliases_dict(self):
        """Test initializes with empty aliases dict."""
        registry = ToolRegistry()

        assert registry._aliases == {}


# =============================================================================
# Test ToolRegistry.register
# =============================================================================


@pytest.mark.unit
class TestToolRegistryRegister:
    """Test ToolRegistry.register method."""

    def test_registers_tool(self):
        """Test registers tool successfully."""
        registry = ToolRegistry()
        tool = Mock()
        tool.name = "mytool"
        tool.cmd = (["mytool"], {"help": "My tool"})

        registry.register(tool)

        assert "mytool" in registry._tools
        assert registry._tools["mytool"] is tool

    def test_registers_tool_with_aliases(self):
        """Test registers tool and its aliases."""
        registry = ToolRegistry()
        tool = Mock()
        tool.name = "mytool"
        tool.cmd = (["mytool"], {"aliases": ["mt", "m"]})

        registry.register(tool)

        assert registry._aliases == {"mt": "mytool", "m": "mytool"}

    def test_raises_for_duplicate_tool(self):
        """Test raises DupToolError for duplicate tool name."""
        registry = ToolRegistry()
        tool1 = Mock()
        tool1.name = "mytool"
        tool1.cmd = (["mytool"], {})

        tool2 = Mock()
        tool2.name = "mytool"
        tool2.cmd = (["mytool"], {})

        registry.register(tool1)

        with pytest.raises(DupToolError):
            registry.register(tool2)


# =============================================================================
# Test ToolRegistry.get_tool
# =============================================================================


@pytest.mark.unit
class TestToolRegistryGetTool:
    """Test ToolRegistry.get_tool method."""

    def test_returns_tool_by_name(self):
        """Test returns tool by direct name."""
        registry = ToolRegistry()
        tool = Mock()
        tool.name = "mytool"
        tool.cmd = (["mytool"], {})
        registry.register(tool)

        result = registry.get_tool("mytool")

        assert result is tool

    def test_returns_tool_by_alias(self):
        """Test returns tool by alias."""
        registry = ToolRegistry()
        tool = Mock()
        tool.name = "mytool"
        tool.cmd = (["mytool"], {"aliases": ["mt"]})
        registry.register(tool)

        result = registry.get_tool("mt")

        assert result is tool

    def test_returns_none_for_unknown_name(self):
        """Test returns None for unknown tool name."""
        registry = ToolRegistry()

        result = registry.get_tool("nonexistent")

        assert result is None


# =============================================================================
# Test ToolRegistry.list_tools
# =============================================================================


@pytest.mark.unit
class TestToolRegistryListTools:
    """Test ToolRegistry.list_tools method."""

    def test_returns_empty_list_when_no_tools(self):
        """Test returns empty list when no tools registered."""
        registry = ToolRegistry()

        result = registry.list_tools()

        assert result == []

    def test_returns_all_tool_names(self):
        """Test returns list of all tool names."""
        registry = ToolRegistry()
        for name in ["alpha", "beta", "gamma"]:
            tool = Mock()
            tool.name = name
            tool.cmd = ([name], {})
            registry.register(tool)

        result = registry.list_tools()

        assert set(result) == {"alpha", "beta", "gamma"}


# =============================================================================
# Test ToolRegistry.list_aliases
# =============================================================================


@pytest.mark.unit
class TestToolRegistryListAliases:
    """Test ToolRegistry.list_aliases method."""

    def test_returns_empty_dict_when_no_aliases(self):
        """Test returns empty dict when no aliases."""
        registry = ToolRegistry()

        result = registry.list_aliases()

        assert result == {}

    def test_returns_copy_of_aliases(self):
        """Test returns copy of aliases dict."""
        registry = ToolRegistry()
        tool = Mock()
        tool.name = "mytool"
        tool.cmd = (["mytool"], {"aliases": ["mt"]})
        registry.register(tool)

        result = registry.list_aliases()

        assert result == {"mt": "mytool"}
        # Verify it's a copy
        result["new"] = "value"
        assert "new" not in registry._aliases


# =============================================================================
# Test ToolRegistry.clear
# =============================================================================


@pytest.mark.unit
class TestToolRegistryClear:
    """Test ToolRegistry.clear method."""

    def test_clears_all_tools(self):
        """Test clears all registered tools."""
        registry = ToolRegistry()
        tool = Mock()
        tool.name = "mytool"
        tool.cmd = (["mytool"], {})
        registry.register(tool)

        registry.clear()

        assert registry._tools == {}

    def test_clears_all_aliases(self):
        """Test clears all aliases."""
        registry = ToolRegistry()
        tool = Mock()
        tool.name = "mytool"
        tool.cmd = (["mytool"], {"aliases": ["mt", "m"]})
        registry.register(tool)

        registry.clear()

        assert registry._aliases == {}


# =============================================================================
# Test ToolRegistry.is_registered
# =============================================================================


@pytest.mark.unit
class TestToolRegistryIsRegistered:
    """Test ToolRegistry.is_registered method."""

    def test_returns_true_for_registered_tool(self):
        """Test returns True for registered tool name."""
        registry = ToolRegistry()
        tool = Mock()
        tool.name = "mytool"
        tool.cmd = (["mytool"], {})
        registry.register(tool)

        assert registry.is_registered("mytool") is True

    def test_returns_true_for_registered_alias(self):
        """Test returns True for registered alias."""
        registry = ToolRegistry()
        tool = Mock()
        tool.name = "mytool"
        tool.cmd = (["mytool"], {"aliases": ["mt"]})
        registry.register(tool)

        assert registry.is_registered("mt") is True

    def test_returns_false_for_unregistered_name(self):
        """Test returns False for unregistered name."""
        registry = ToolRegistry()

        assert registry.is_registered("unknown") is False


# =============================================================================
# Integration Tests
# =============================================================================


@pytest.mark.integration
class TestToolRegistryIntegration:
    """Integration tests for ToolRegistry."""

    def test_full_registration_workflow(self):
        """Test complete tool registration workflow."""
        registry = ToolRegistry()

        # Register multiple tools with aliases
        tool1 = Mock()
        tool1.name = "analyze"
        tool1.cmd = (["analyze"], {"aliases": ["a", "an"]})

        tool2 = Mock()
        tool2.name = "report"
        tool2.cmd = (["report"], {"aliases": ["r", "rep"]})

        registry.register(tool1)
        registry.register(tool2)

        # Verify tools
        assert registry.list_tools() == ["analyze", "report"]

        # Verify aliases
        aliases = registry.list_aliases()
        assert aliases == {
            "a": "analyze",
            "an": "analyze",
            "r": "report",
            "rep": "report",
        }

        # Lookup by name and alias
        assert registry.get_tool("analyze") is tool1
        assert registry.get_tool("a") is tool1
        assert registry.get_tool("report") is tool2
        assert registry.get_tool("rep") is tool2

        # Check registration status
        assert registry.is_registered("analyze") is True
        assert registry.is_registered("r") is True
        assert registry.is_registered("unknown") is False

        # Clear and verify
        registry.clear()
        assert registry.list_tools() == []
        assert registry.list_aliases() == {}

    def test_error_handling_workflow(self):
        """Test error handling for invalid registrations."""
        registry = ToolRegistry()

        # Invalid tool name
        tool = Mock()
        tool.name = "Invalid Tool"
        tool.cmd = (["Invalid Tool"], {})

        with pytest.raises(ToolRegistrationError):
            registry.register(tool)

        # Tool name too long
        tool.name = "a" * (MAX_TOOL_NAME_LENGTH + 1)
        tool.cmd = ([tool.name], {})

        with pytest.raises(ToolRegistrationError):
            registry.register(tool)

        # Valid registration followed by duplicate
        tool1 = Mock()
        tool1.name = "valid"
        tool1.cmd = (["valid"], {})

        tool2 = Mock()
        tool2.name = "valid"
        tool2.cmd = (["valid"], {})

        registry.register(tool1)
        with pytest.raises(DupToolError):
            registry.register(tool2)
