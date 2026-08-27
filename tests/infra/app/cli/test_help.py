# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for app/cli/help.py.

Tests key functionality including:
- HelpGenerator class methods
- Tool help generation
- Tools list generation
- Usage examples generation
"""

from unittest.mock import Mock

import pytest

from appinfra.app.cli.help import HelpGenerator

# =============================================================================
# Test HelpGenerator Initialization
# =============================================================================


@pytest.mark.unit
class TestHelpGeneratorInit:
    """Test HelpGenerator initialization."""

    def test_basic_initialization(self):
        """Test basic initialization."""
        app = Mock()
        generator = HelpGenerator(app)

        assert generator.application is app


# =============================================================================
# Test generate_tool_help
# =============================================================================


@pytest.mark.unit
class TestGenerateToolHelp:
    """Test generate_tool_help method (lines 23-43)."""

    def test_returns_none_for_unknown_tool(self):
        """Test returns None when tool not found (lines 33-35)."""
        app = Mock()
        app.registry.get_tool.return_value = None
        generator = HelpGenerator(app)

        result = generator.generate_tool_help("nonexistent")

        assert result is None

    def test_returns_help_text_only(self):
        """Test returns help text when no description (lines 37-43)."""
        app = Mock()
        tool = Mock()
        tool.cmd = (["test"], {"help": "Test tool help", "description": ""})
        app.registry.get_tool.return_value = tool
        generator = HelpGenerator(app)

        result = generator.generate_tool_help("test")

        assert result == "Test tool help"

    def test_returns_help_with_description(self):
        """Test returns help with description (lines 41-42)."""
        app = Mock()
        tool = Mock()
        tool.cmd = (
            ["test"],
            {"help": "Test help", "description": "Detailed description"},
        )
        app.registry.get_tool.return_value = tool
        generator = HelpGenerator(app)

        result = generator.generate_tool_help("test")

        assert result == "Test help\n\nDetailed description"


# =============================================================================
# Test generate_tools_list
# =============================================================================


@pytest.mark.unit
class TestGenerateToolsList:
    """Test generate_tools_list method (lines 45-71)."""

    def test_empty_tools_list(self):
        """Test with no tools."""
        app = Mock()
        app.registry.list_tools.return_value = []
        app.registry.list_aliases.return_value = {}
        generator = HelpGenerator(app)

        result = generator.generate_tools_list()

        assert result == ""

    def test_single_tool_no_aliases(self):
        """Test with single tool without aliases (lines 55-61)."""
        app = Mock()
        app.registry.list_tools.return_value = ["tool1"]
        app.registry.list_aliases.return_value = {}
        tool = Mock()
        tool.cmd = (["tool1"], {"help": "Tool 1 help", "aliases": []})
        app.registry.get_tool.return_value = tool
        generator = HelpGenerator(app)

        result = generator.generate_tools_list()

        assert "tool1" in result
        assert "Tool 1 help" in result

    def test_tool_with_aliases(self):
        """Test tool with aliases (lines 64-67)."""
        app = Mock()
        app.registry.list_tools.return_value = ["tool1"]
        app.registry.list_aliases.return_value = {"t1": "tool1"}
        tool = Mock()
        tool.cmd = (["tool1"], {"help": "Tool 1 help", "aliases": ["t1", "t"]})
        app.registry.get_tool.return_value = tool
        generator = HelpGenerator(app)

        result = generator.generate_tools_list()

        assert "tool1" in result
        assert "aliases: t1, t" in result

    def test_skips_none_tool(self):
        """Test skips when get_tool returns None (lines 57-58)."""
        app = Mock()
        app.registry.list_tools.return_value = ["tool1", "tool2"]
        app.registry.list_aliases.return_value = {}
        app.registry.get_tool.side_effect = [
            None,
            Mock(cmd=(["tool2"], {"help": "Tool 2"})),
        ]
        generator = HelpGenerator(app)

        result = generator.generate_tools_list()

        assert "tool1" not in result
        assert "tool2" in result

    def test_multiple_tools(self):
        """Test with multiple tools."""
        app = Mock()
        app.registry.list_tools.return_value = ["tool1", "tool2"]
        app.registry.list_aliases.return_value = {}

        def get_tool(name):
            if name == "tool1":
                return Mock(cmd=(["tool1"], {"help": "First tool", "aliases": []}))
            elif name == "tool2":
                return Mock(cmd=(["tool2"], {"help": "Second tool", "aliases": []}))
            return None

        app.registry.get_tool.side_effect = get_tool
        generator = HelpGenerator(app)

        result = generator.generate_tools_list()

        assert "tool1" in result
        assert "tool2" in result
        assert "First tool" in result
        assert "Second tool" in result


# =============================================================================
# Test generate_usage_examples
# =============================================================================


@pytest.mark.unit
class TestGenerateUsageExamples:
    """Test generate_usage_examples method (lines 73-94)."""

    def test_empty_tools(self):
        """Test with no tools (line 83)."""
        app = Mock()
        app.registry.list_tools.return_value = []
        generator = HelpGenerator(app)

        result = generator.generate_usage_examples()

        assert result == []

    def test_single_tool_no_aliases(self):
        """Test with single tool, no aliases (lines 83-85)."""
        app = Mock()
        app.registry.list_tools.return_value = ["mytool"]
        app.registry.list_aliases.return_value = {}
        app.parser.prog = "myapp"
        generator = HelpGenerator(app)

        result = generator.generate_usage_examples()

        assert len(result) == 1
        assert "myapp mytool" in result[0]

    def test_tool_with_matching_alias(self):
        """Test with tool that has matching alias (lines 88-92)."""
        app = Mock()
        app.registry.list_tools.return_value = ["mytool"]
        app.registry.list_aliases.return_value = {"mt": "mytool"}
        app.parser.prog = "myapp"
        generator = HelpGenerator(app)

        result = generator.generate_usage_examples()

        assert len(result) == 2
        assert "myapp mytool" in result[0]
        assert "myapp mt" in result[1]

    def test_multiple_tools_uses_first(self):
        """Test uses first tool for examples."""
        app = Mock()
        app.registry.list_tools.return_value = ["first", "second"]
        app.registry.list_aliases.return_value = {}
        app.parser.prog = "myapp"
        generator = HelpGenerator(app)

        result = generator.generate_usage_examples()

        assert len(result) == 1
        assert "myapp first" in result[0]

    def test_alias_for_different_tool_not_included(self):
        """Test alias for different tool is not included."""
        app = Mock()
        app.registry.list_tools.return_value = ["first", "second"]
        app.registry.list_aliases.return_value = {
            "s": "second"
        }  # Alias for second, not first
        app.parser.prog = "myapp"
        generator = HelpGenerator(app)

        result = generator.generate_usage_examples()

        # Only the first tool example, no alias since alias is for second
        assert len(result) == 1
        assert "myapp first" in result[0]


# =============================================================================
# Integration Tests
# =============================================================================


@pytest.mark.integration
class TestHelpGeneratorIntegration:
    """Test HelpGenerator integration scenarios."""

    def test_full_help_generation_workflow(self):
        """Test complete help generation workflow."""
        app = Mock()
        app.parser.prog = "testapp"

        # Setup tools
        tool1 = Mock(
            cmd=(
                ["analyze"],
                {
                    "help": "Analyze data",
                    "description": "Deep analysis",
                    "aliases": ["a"],
                },
            )
        )
        tool2 = Mock(
            cmd=(
                ["report"],
                {"help": "Generate reports", "description": "", "aliases": []},
            )
        )

        def get_tool(name):
            if name == "analyze":
                return tool1
            elif name == "report":
                return tool2
            return None

        app.registry.list_tools.return_value = ["analyze", "report"]
        app.registry.list_aliases.return_value = {"a": "analyze"}
        app.registry.get_tool.side_effect = get_tool

        generator = HelpGenerator(app)

        # Test tool help
        analyze_help = generator.generate_tool_help("analyze")
        assert "Analyze data" in analyze_help
        assert "Deep analysis" in analyze_help

        # Test tools list
        tools_list = generator.generate_tools_list()
        assert "analyze" in tools_list
        assert "report" in tools_list

        # Test usage examples
        examples = generator.generate_usage_examples()
        assert len(examples) == 2  # Tool + alias
