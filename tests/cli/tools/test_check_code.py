# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for app/tools/code_quality.py.

Tests CodeQualityTool parent command functionality:
- Tool initialization and configuration
- Subtool registration
- Group delegation behavior
"""

from unittest.mock import Mock

import pytest

from appinfra.cli.tools.code_quality import CodeQualityTool


@pytest.mark.unit
class TestCodeQualityToolInit:
    """Test CodeQualityTool initialization."""

    def test_basic_initialization(self):
        """Test CodeQualityTool can be created."""
        tool = CodeQualityTool()
        assert tool.config.name == "code-quality"
        assert tool.config.aliases == ["cq"]
        assert "code quality" in tool.config.help_text.lower()

    def test_has_group(self):
        """Test tool creates a group during init."""
        tool = CodeQualityTool()
        assert tool._group is not None

    def test_has_check_funcs_subtool(self):
        """Test check-funcs subtool is registered."""
        tool = CodeQualityTool()
        assert "check-funcs" in tool._group._tools

    def test_no_default_command(self):
        """Test no default subcommand is set."""
        tool = CodeQualityTool()
        assert tool._group._default is None


@pytest.mark.unit
class TestCodeQualityToolRun:
    """Test CodeQualityTool run behavior."""

    def test_run_delegates_to_group(self):
        """Test run() delegates to group.run()."""
        tool = CodeQualityTool()
        tool._group.run = Mock(return_value=0)
        # Mock args to simulate a subcommand was provided
        tool._parsed_args = Mock()
        setattr(tool._parsed_args, tool._group._cmd_var, "check-funcs")

        result = tool.run()

        assert result == 0
        tool._group.run.assert_called_once()

    def test_run_returns_group_exit_code(self):
        """Test run() returns group's exit code."""
        tool = CodeQualityTool()
        tool._group.run = Mock(return_value=42)
        # Mock args to simulate a subcommand was provided
        tool._parsed_args = Mock()
        setattr(tool._parsed_args, tool._group._cmd_var, "check-funcs")

        result = tool.run()

        assert result == 42


@pytest.mark.integration
class TestCodeQualityToolIntegration:
    """Test CodeQualityTool integration with CheckFunctionsTool."""

    def test_check_funcs_is_subtool(self):
        """Test check-funcs is registered as subtool with correct config."""
        tool = CodeQualityTool()
        subtool = tool._group.get_tool("check-funcs")
        assert subtool.name == "check-funcs"
        assert "cf" in subtool.config.aliases

    def test_subtool_has_parent(self):
        """Test subtool has reference to parent tool."""
        tool = CodeQualityTool()
        subtool = tool._group.get_tool("check-funcs")
        assert subtool.parent is tool
