# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for app/tools/group.py.

Tests key functionality including:
- ToolGroup initialization and properties
- Tool registration and validation
- Command function registration
- Argument parser integration
- Tool/command execution
"""

from unittest.mock import Mock, patch

import pytest

from appinfra.app.errors import DupToolError, MissingRunFuncError, UndefNameError
from appinfra.app.tools.group import ToolGroup

# =============================================================================
# Test ToolGroup Initialization
# =============================================================================


@pytest.mark.unit
class TestToolGroupInit:
    """Test ToolGroup initialization (lines 21-34)."""

    def test_basic_initialization(self):
        """Test basic initialization with required params (lines 30-34)."""
        parent = Mock()
        group = ToolGroup(parent, "cmd")

        assert group._parent is parent
        assert group._cmd_var == "cmd"
        assert group._default is None
        assert group._tools == {}
        assert group._funcs == {}

    def test_initialization_with_default(self):
        """Test initialization with default command (line 32)."""
        parent = Mock()
        group = ToolGroup(parent, "command", default="help")

        assert group._default == "help"


# =============================================================================
# Test lg Property
# =============================================================================


@pytest.mark.unit
class TestLgProperty:
    """Test lg property (lines 36-39)."""

    def test_returns_parent_lg(self):
        """Test lg returns parent's logger (line 39)."""
        parent = Mock()
        parent.lg = Mock(name="logger")
        group = ToolGroup(parent, "cmd")

        assert group.lg is parent.lg


# =============================================================================
# Test _set_tool
# =============================================================================


@pytest.mark.unit
class TestSetTool:
    """Test _set_tool method (lines 41-43)."""

    def test_registers_tool(self):
        """Test _set_tool registers tool by name (line 43)."""
        parent = Mock()
        group = ToolGroup(parent, "cmd")
        tool = Mock()
        tool.name = "mytool"

        group._set_tool(tool)

        assert group._tools["mytool"] is tool

    def test_overwrites_existing_tool(self):
        """Test _set_tool overwrites tool with same name."""
        parent = Mock()
        group = ToolGroup(parent, "cmd")
        tool1 = Mock(name="first")
        tool1.name = "mytool"
        tool2 = Mock(name="second")
        tool2.name = "mytool"

        group._set_tool(tool1)
        group._set_tool(tool2)

        assert group._tools["mytool"] is tool2


# =============================================================================
# Test _set_func
# =============================================================================


@pytest.mark.unit
class TestSetFunc:
    """Test _set_func method (lines 45-47)."""

    def test_registers_func(self):
        """Test _set_func registers function by key (line 47)."""
        parent = Mock()
        group = ToolGroup(parent, "cmd")
        func = Mock()

        group._set_func("mykey", func)

        assert group._funcs["mykey"] is func


# =============================================================================
# Test _check_new_tool
# =============================================================================


@pytest.mark.unit
class TestCheckNewTool:
    """Test _check_new_tool method (lines 49-63)."""

    def test_raises_undef_name_error_when_no_name(self):
        """Test raises UndefNameError when tool has no name (lines 60-61)."""
        parent = Mock()
        group = ToolGroup(parent, "cmd")
        tool = Mock()
        tool.name = None

        with pytest.raises(UndefNameError):
            group._check_new_tool(tool)

    def test_raises_dup_tool_error_when_exists(self):
        """Test raises DupToolError when tool name exists (lines 62-63)."""
        parent = Mock()
        group = ToolGroup(parent, "cmd")
        existing_tool = Mock()
        existing_tool.name = "mytool"
        group._tools["mytool"] = existing_tool

        new_tool = Mock()
        new_tool.name = "mytool"

        with pytest.raises(DupToolError):
            group._check_new_tool(new_tool)

    def test_passes_when_valid(self):
        """Test passes validation when tool is valid."""
        parent = Mock()
        group = ToolGroup(parent, "cmd")
        tool = Mock()
        tool.name = "newtool"

        # Should not raise
        group._check_new_tool(tool)


# =============================================================================
# Test _set_default
# =============================================================================


@pytest.mark.unit
class TestSetDefault:
    """Test _set_default method (lines 65-70)."""

    def test_does_nothing_when_no_default(self):
        """Test does nothing when default is None (lines 67-68)."""
        parent = Mock()
        group = ToolGroup(parent, "cmd", default=None)
        parser = Mock()

        group._set_default(parser)

        parser.set_defaults.assert_not_called()

    def test_sets_default_when_present(self):
        """Test sets default on parser (lines 69-70)."""
        parent = Mock()
        group = ToolGroup(parent, "cmd", default="help")
        parser = Mock()

        group._set_default(parser)

        parser.set_defaults.assert_called_once_with(cmd="help")


# =============================================================================
# Test add_tool
# =============================================================================


@pytest.mark.unit
class TestAddTool:
    """Test add_tool method (lines 72-87)."""

    def test_adds_tool_without_run_func(self):
        """Test adds tool without custom run function (lines 83-84)."""
        parent = Mock()
        group = ToolGroup(parent, "cmd")
        tool = Mock()
        tool.name = "mytool"

        result = group.add_tool(tool)

        assert result is tool
        assert group._tools["mytool"] is tool
        assert "mytool" not in group._funcs

    def test_adds_tool_with_run_func(self):
        """Test adds tool with custom run function (lines 85-86)."""
        parent = Mock()
        group = ToolGroup(parent, "cmd")
        tool = Mock()
        tool.name = "mytool"
        run_func = Mock()

        result = group.add_tool(tool, run_func=run_func)

        assert result is tool
        assert group._tools["mytool"] is tool
        assert group._funcs["mytool"] is run_func

    def test_validates_tool_before_adding(self):
        """Test validates tool using _check_new_tool (line 83)."""
        parent = Mock()
        group = ToolGroup(parent, "cmd")
        tool = Mock()
        tool.name = None

        with pytest.raises(UndefNameError):
            group.add_tool(tool)


# =============================================================================
# Test get_tool
# =============================================================================


@pytest.mark.unit
class TestGetTool:
    """Test get_tool method (lines 89-93)."""

    def test_returns_tool_when_exists(self):
        """Test returns tool when found (line 93)."""
        parent = Mock()
        group = ToolGroup(parent, "cmd")
        tool = Mock()
        tool.name = "mytool"
        group._tools["mytool"] = tool

        result = group.get_tool("mytool")

        assert result is tool

    def test_raises_key_error_when_not_found(self):
        """Test raises KeyError when tool not found (line 92)."""
        parent = Mock()
        group = ToolGroup(parent, "cmd")

        with pytest.raises(KeyError) as exc_info:
            group.get_tool("nonexistent")

        assert "nonexistent" in str(exc_info.value)


# =============================================================================
# Test add_tool_args
# =============================================================================


@pytest.mark.unit
class TestAddToolArgs:
    """Test add_tool_args method (lines 95-102)."""

    def test_creates_subparsers(self):
        """Test creates subparsers with cmd_var (line 97)."""
        parent = Mock()
        group = ToolGroup(parent, "command")
        parser = Mock()
        parser.add_subparsers.return_value = Mock()

        group.add_tool_args(parser)

        parser.add_subparsers.assert_called_once_with(dest="command")

    def test_adds_parser_for_each_tool(self):
        """Test adds parser for each tool (lines 98-101)."""
        parent = Mock()
        group = ToolGroup(parent, "cmd")
        parser = Mock()
        subs = Mock()
        parser.add_subparsers.return_value = subs
        parser.formatter_class = "MyFormatter"

        tool1 = Mock()
        tool1.name = "tool1"
        tool1.cmd = (["tool1"], {"help": "Tool 1"})
        tool2 = Mock()
        tool2.name = "tool2"
        tool2.cmd = (["tool2"], {"help": "Tool 2"})

        group._tools = {"tool1": tool1, "tool2": tool2}

        group.add_tool_args(parser)

        assert subs.add_parser.call_count == 2


# =============================================================================
# Test add_cmd
# =============================================================================


@pytest.mark.unit
class TestAddCmd:
    """Test add_cmd method (lines 104-118)."""

    def test_raises_missing_run_func_error(self):
        """Test raises MissingRunFuncError when no run_func (lines 107-108)."""
        parent = Mock()
        group = ToolGroup(parent, "cmd")
        subs = Mock()

        with pytest.raises(MissingRunFuncError):
            group.add_cmd(subs, "mycommand", help="My command")

    def test_registers_command_function(self):
        """Test registers the run function (line 110)."""
        parent = Mock()
        group = ToolGroup(parent, "cmd")
        subs = Mock()
        run_func = Mock()

        group.add_cmd(subs, "mycommand", run_func=run_func)

        assert group._funcs["mycommand"] is run_func

    def test_registers_aliases(self):
        """Test registers aliases (lines 112-116)."""
        parent = Mock()
        group = ToolGroup(parent, "cmd")
        subs = Mock()
        run_func = Mock()

        group.add_cmd(subs, "mycommand", aliases=["mc", "m"], run_func=run_func)

        assert group._funcs["mycommand"] is run_func
        assert group._funcs["mc"] is run_func
        assert group._funcs["m"] is run_func

    def test_raises_value_error_for_duplicate_alias(self):
        """Test raises ValueError for duplicate alias (lines 114-115)."""
        parent = Mock()
        group = ToolGroup(parent, "cmd")
        subs = Mock()
        run_func = Mock()

        # Register first command
        group._funcs["mc"] = Mock()

        with pytest.raises(ValueError) as exc_info:
            group.add_cmd(subs, "mycommand", aliases=["mc"], run_func=run_func)

        assert "mc" in str(exc_info.value)

    def test_calls_subs_add_parser(self):
        """Test calls subs.add_parser (line 118)."""
        parent = Mock()
        group = ToolGroup(parent, "cmd")
        subs = Mock()
        run_func = Mock()

        group.add_cmd(subs, "mycommand", help="My command", run_func=run_func)

        subs.add_parser.assert_called_once_with("mycommand", help="My command")


# =============================================================================
# Test finalize_args
# =============================================================================


@pytest.mark.unit
class TestFinalizeArgs:
    """Test finalize_args method (lines 120-122)."""

    def test_calls_set_default(self):
        """Test calls _set_default (line 122)."""
        parent = Mock()
        group = ToolGroup(parent, "cmd", default="help")
        parser = Mock()

        group.finalize_args(parser)

        parser.set_defaults.assert_called_once_with(cmd="help")


# =============================================================================
# Test _is_tool_selected
# =============================================================================


@pytest.mark.unit
class TestIsToolSelected:
    """Test _is_tool_selected method (lines 124-133)."""

    def test_returns_false_when_no_arg(self):
        """Test returns False when cmd_var not in args (lines 126-128)."""
        parent = Mock()
        group = ToolGroup(parent, "cmd")
        args = Mock(spec=[])  # No attributes
        tool = Mock()
        tool.cmd = (["mytool"], {})

        result = group._is_tool_selected(args, tool)

        assert result is False

    def test_returns_true_when_matches_name(self):
        """Test returns True when arg matches tool name (line 131)."""
        parent = Mock()
        group = ToolGroup(parent, "cmd")
        args = Mock()
        args.cmd = "mytool"
        tool = Mock()
        tool.cmd = (["mytool"], {})

        result = group._is_tool_selected(args, tool)

        assert result is True

    def test_returns_true_when_matches_alias(self):
        """Test returns True when arg matches alias (line 132)."""
        parent = Mock()
        group = ToolGroup(parent, "cmd")
        args = Mock()
        args.cmd = "mt"
        tool = Mock()
        tool.cmd = (["mytool"], {"aliases": ["mt", "m"]})

        result = group._is_tool_selected(args, tool)

        assert result is True

    def test_returns_false_when_no_match(self):
        """Test returns False when no match."""
        parent = Mock()
        group = ToolGroup(parent, "cmd")
        args = Mock()
        args.cmd = "other"
        tool = Mock()
        tool.cmd = (["mytool"], {"aliases": ["mt"]})

        result = group._is_tool_selected(args, tool)

        assert result is False


# =============================================================================
# Test run
# =============================================================================


@pytest.mark.unit
class TestRun:
    """Test run method (lines 135-158)."""

    def test_runs_selected_tool(self):
        """Test runs selected tool (lines 143-146)."""
        parent = Mock()
        parent.lg = Mock()
        parent.args = Mock()
        parent.args.cmd = "mytool"
        group = ToolGroup(parent, "cmd")

        tool = Mock()
        tool.name = "mytool"
        tool.cmd = (["mytool"], {})
        tool.run.return_value = 0
        group._tools["mytool"] = tool

        result = group.run()

        assert result == 0

    def test_runs_registered_function(self):
        """Test runs registered function when no tool matches (lines 152-154)."""
        parent = Mock()
        parent.lg = Mock()
        parent.trace_attr.return_value = Mock(cmd="mycommand")
        group = ToolGroup(parent, "cmd")
        run_func = Mock(return_value=42)
        group._funcs["mycommand"] = run_func

        result = group.run()

        run_func.assert_called_once()
        assert result == 42

    def test_returns_127_when_no_command(self):
        """Test returns 127 when command not found (lines 156-158)."""
        parent = Mock()
        parent.lg = Mock()
        parent.trace_attr.return_value = Mock(cmd="unknown")
        group = ToolGroup(parent, "cmd")

        result = group.run()

        assert result == 127
        parent.lg.error.assert_called()


# =============================================================================
# Test _check_run_tool
# =============================================================================


@pytest.mark.unit
class TestCheckRunTool:
    """Test _check_run_tool method (lines 160-172)."""

    def test_returns_false_when_not_selected(self):
        """Test returns (False, None) when tool not selected (lines 162-163)."""
        parent = Mock()
        parent.lg = Mock()
        parent.args = Mock(cmd="other")
        group = ToolGroup(parent, "cmd")
        tool = Mock()
        tool.name = "mytool"
        tool.cmd = (["mytool"], {})

        run, result = group._check_run_tool(tool)

        assert run is False
        assert result is None

    def test_runs_custom_func_when_registered(self):
        """Test runs custom func when registered (lines 167-169)."""
        parent = Mock()
        parent.lg = Mock()
        parent.args = Mock(cmd="mytool")
        group = ToolGroup(parent, "cmd")

        tool = Mock()
        tool.name = "mytool"
        tool.cmd = (["mytool"], {})

        custom_func = Mock(return_value=99)
        group._funcs["mytool"] = custom_func

        run, result = group._check_run_tool(tool)

        assert run is True
        assert result == 99
        custom_func.assert_called_once()

    def test_runs_tool_run_when_no_func(self):
        """Test runs tool.run when no custom func (lines 170-172)."""
        parent = Mock()
        parent.lg = Mock()
        parent.args = Mock(cmd="mytool")
        group = ToolGroup(parent, "cmd")

        tool = Mock()
        tool.name = "mytool"
        tool.cmd = (["mytool"], {})
        tool.run.return_value = 0

        run, result = group._check_run_tool(tool)

        assert run is True
        assert result == 0
        tool.run.assert_called_once()


# =============================================================================
# Test get_server_routes
# =============================================================================


@pytest.mark.unit
class TestGetServerRoutes:
    """Test get_server_routes method (lines 174-176)."""

    @patch("appinfra.app.tools.group.get_server_routes")
    def test_calls_get_server_routes_with_tools(self, mock_get_routes):
        """Test calls get_server_routes with tools (line 176)."""
        parent = Mock()
        group = ToolGroup(parent, "cmd")
        tool1 = Mock()
        tool1.name = "tool1"
        tool2 = Mock()
        tool2.name = "tool2"
        group._tools = {"tool1": tool1, "tool2": tool2}
        mock_get_routes.return_value = ["/route1", "/route2"]

        result = group.get_server_routes()

        mock_get_routes.assert_called_once()
        assert result == ["/route1", "/route2"]


# =============================================================================
# Integration Tests
# =============================================================================


@pytest.mark.integration
class TestToolGroupIntegration:
    """Test ToolGroup integration scenarios."""

    def test_full_tool_registration_workflow(self):
        """Test complete tool registration and lookup."""
        parent = Mock()
        parent.lg = Mock()
        group = ToolGroup(parent, "cmd", default="help")

        # Create and add tools
        tool1 = Mock()
        tool1.name = "analyze"
        tool2 = Mock()
        tool2.name = "report"

        group.add_tool(tool1)
        group.add_tool(tool2, run_func=lambda: 0)

        # Verify registration
        assert group.get_tool("analyze") is tool1
        assert group.get_tool("report") is tool2
        assert "report" in group._funcs
        assert "analyze" not in group._funcs

    def test_command_function_workflow(self):
        """Test command function registration and execution."""
        parent = Mock()
        parent.lg = Mock()
        parent.trace_attr.return_value = Mock(cmd="greet")
        group = ToolGroup(parent, "cmd")

        # Register command
        subs = Mock()
        called = []

        def greet_func():
            called.append("greet")
            return 0

        group.add_cmd(subs, "greet", aliases=["g", "hello"], run_func=greet_func)

        # Test execution via main command
        result = group.run()

        assert result == 0
        assert called == ["greet"]

    def test_tool_selection_with_aliases(self):
        """Test tool selection works with aliases."""
        parent = Mock()
        parent.lg = Mock()
        group = ToolGroup(parent, "cmd")

        tool = Mock()
        tool.name = "analyze"
        tool.cmd = (["analyze"], {"aliases": ["a", "an"]})
        group._tools["analyze"] = tool

        # Test with main name
        args = Mock(cmd="analyze")
        assert group._is_tool_selected(args, tool) is True

        # Test with alias
        args = Mock(cmd="a")
        assert group._is_tool_selected(args, tool) is True

        args = Mock(cmd="an")
        assert group._is_tool_selected(args, tool) is True

        # Test with non-matching
        args = Mock(cmd="other")
        assert group._is_tool_selected(args, tool) is False
