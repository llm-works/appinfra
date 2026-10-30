# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for app/cli/commands.py.

Tests key functionality including:
- CommandHandler initialization
- Subcommand setup
- Command execution
- Command listing
"""

from unittest.mock import Mock

import pytest

from appinfra.app.cli.commands import CommandHandler
from appinfra.app.errors import CommandError

# =============================================================================
# Test CommandHandler Initialization
# =============================================================================


@pytest.mark.unit
class TestCommandHandlerInit:
    """Test CommandHandler initialization."""

    def test_stores_application(self):
        """Test stores application reference."""
        app = Mock()
        handler = CommandHandler(app)

        assert handler.application is app
        assert handler._subparsers is None


# =============================================================================
# Test setup_subcommands
# =============================================================================


@pytest.mark.unit
class TestSetupSubcommands:
    """Test CommandHandler.setup_subcommands method."""

    def test_does_nothing_when_no_tools(self):
        """Test does nothing when registry has no tools."""
        app = Mock()
        app.registry.list_tools.return_value = []
        handler = CommandHandler(app)

        handler.setup_subcommands()

        app.parser.add_subparsers.assert_not_called()
        assert handler._subparsers is None

    def test_creates_subparsers_for_tools(self):
        """Test creates subparsers for registered tools."""
        app = Mock()
        app._main_tool = None  # Explicitly set to skip main tool logic
        app.registry.list_tools.return_value = ["tool1", "tool2"]

        tool1 = Mock()
        tool1.cmd = (["tool1"], {"help": "Tool 1 help"})
        tool2 = Mock()
        tool2.cmd = (["tool2"], {"help": "Tool 2 help"})

        app.registry.get_tool.side_effect = lambda name: {
            "tool1": tool1,
            "tool2": tool2,
        }[name]

        subparsers = Mock()
        app.parser.add_subparsers.return_value = subparsers
        app.parser.formatter_class = "FormatterClass"

        handler = CommandHandler(app)
        handler.setup_subcommands()

        app.parser.add_subparsers.assert_called_once_with(dest="tool")
        assert subparsers.add_parser.call_count == 2
        assert tool1.set_args.called
        assert tool2.set_args.called

    def test_skips_none_tools(self):
        """Test skips tools that return None from registry."""
        app = Mock()
        app._main_tool = None  # Explicitly set to skip main tool logic
        app.registry.list_tools.return_value = ["exists", "missing"]

        existing_tool = Mock()
        existing_tool.cmd = (["exists"], {"help": "Exists"})

        # get_tool returns None for "missing"
        app.registry.get_tool.side_effect = lambda name: (
            existing_tool if name == "exists" else None
        )

        subparsers = Mock()
        app.parser.add_subparsers.return_value = subparsers
        app.parser.formatter_class = "FormatterClass"

        handler = CommandHandler(app)
        handler.setup_subcommands()

        # Should only add parser for existing tool
        assert subparsers.add_parser.call_count == 1

    def test_sets_up_main_tool_defaults(self):
        """Test sets up main tool defaults when _main_tool is set."""
        app = Mock()
        app._main_tool = "main"
        app.registry.list_tools.return_value = ["main", "other"]

        main_tool = Mock()
        main_tool.cmd = (["main"], {"help": "Main tool"})
        other_tool = Mock()
        other_tool.cmd = (["other"], {"help": "Other tool"})

        app.registry.get_tool.side_effect = lambda name: {
            "main": main_tool,
            "other": other_tool,
        }[name]

        subparsers = Mock()
        app.parser.add_subparsers.return_value = subparsers
        app.parser.formatter_class = "FormatterClass"

        handler = CommandHandler(app)
        handler.setup_subcommands()

        # Should add main tool's args to root parser (skip_positional=True)
        main_tool.set_args.assert_any_call(app.parser.parser, skip_positional=True)
        # Should set defaults on root parser
        app.parser.parser.set_defaults.assert_called_once_with(tool="main")


# =============================================================================
# Test execute_command
# =============================================================================


@pytest.mark.unit
class TestExecuteCommand:
    """Test CommandHandler.execute_command method."""

    def test_executes_tool_and_returns_result(self):
        """Test executes tool.run() and returns result."""
        app = Mock()
        tool = Mock()
        tool.run.return_value = 0
        app.registry.get_tool.return_value = tool

        handler = CommandHandler(app)
        result = handler.execute_command("mytool", arg1="value1")

        app.registry.get_tool.assert_called_once_with("mytool")
        tool.run.assert_called_once_with(arg1="value1")
        assert result == 0

    def test_raises_command_error_when_tool_not_found(self):
        """Test raises CommandError when tool doesn't exist."""
        app = Mock()
        app.registry.get_tool.return_value = None

        handler = CommandHandler(app)

        with pytest.raises(CommandError) as exc_info:
            handler.execute_command("nonexistent")

        assert "nonexistent" in str(exc_info.value)
        assert "not found" in str(exc_info.value)

    def test_wraps_execution_errors_in_command_error(self):
        """Test wraps tool execution errors in CommandError."""
        app = Mock()
        tool = Mock()
        tool.run.side_effect = ValueError("Something went wrong")
        app.registry.get_tool.return_value = tool

        handler = CommandHandler(app)

        with pytest.raises(CommandError) as exc_info:
            handler.execute_command("mytool")

        assert "Failed to execute" in str(exc_info.value)
        assert "mytool" in str(exc_info.value)
        assert exc_info.value.__cause__ is not None


# =============================================================================
# Test list_commands
# =============================================================================


@pytest.mark.unit
class TestListCommands:
    """Test CommandHandler.list_commands method."""

    def test_returns_empty_dict_when_no_tools(self):
        """Test returns empty dict when no tools registered."""
        app = Mock()
        app.registry.list_tools.return_value = []

        handler = CommandHandler(app)
        result = handler.list_commands()

        assert result == {}

    def test_returns_commands_with_descriptions(self):
        """Test returns dict of command names to descriptions."""
        app = Mock()
        app.registry.list_tools.return_value = ["analyze", "report"]

        analyze_tool = Mock()
        analyze_tool.cmd = (["analyze"], {"help": "Analyze data"})

        report_tool = Mock()
        report_tool.cmd = (["report"], {"help": "Generate report"})

        app.registry.get_tool.side_effect = lambda name: {
            "analyze": analyze_tool,
            "report": report_tool,
        }[name]

        handler = CommandHandler(app)
        result = handler.list_commands()

        assert result == {
            "analyze": "Analyze data",
            "report": "Generate report",
        }

    def test_uses_default_description_when_no_help(self):
        """Test uses default description when help not provided."""
        app = Mock()
        app.registry.list_tools.return_value = ["mytool"]

        tool = Mock()
        tool.cmd = (["mytool"], {})  # No help key

        app.registry.get_tool.return_value = tool

        handler = CommandHandler(app)
        result = handler.list_commands()

        assert result["mytool"] == "mytool tool"

    def test_skips_none_tools(self):
        """Test skips tools that return None from registry."""
        app = Mock()
        app.registry.list_tools.return_value = ["exists", "missing"]

        existing_tool = Mock()
        existing_tool.cmd = (["exists"], {"help": "Exists"})

        app.registry.get_tool.side_effect = lambda name: (
            existing_tool if name == "exists" else None
        )

        handler = CommandHandler(app)
        result = handler.list_commands()

        assert "exists" in result
        assert "missing" not in result


# =============================================================================
# Integration Tests
# =============================================================================


@pytest.mark.integration
class TestCommandHandlerIntegration:
    """Integration tests for CommandHandler."""

    def test_full_workflow(self):
        """Test complete command registration and execution workflow."""
        # Setup application mock
        app = Mock()
        app._main_tool = None  # Explicitly set to skip main tool logic

        # Setup tools
        tool1 = Mock()
        tool1.cmd = (["analyze"], {"help": "Analyze data", "aliases": ["a"]})
        tool1.run.return_value = 0

        tool2 = Mock()
        tool2.cmd = (["report"], {"help": "Generate report"})
        tool2.run.return_value = 1

        app.registry.list_tools.return_value = ["analyze", "report"]
        app.registry.get_tool.side_effect = lambda name: {
            "analyze": tool1,
            "report": tool2,
        }.get(name)

        subparsers = Mock()
        app.parser.add_subparsers.return_value = subparsers
        app.parser.formatter_class = "Formatter"

        # Create handler
        handler = CommandHandler(app)

        # Setup subcommands
        handler.setup_subcommands()

        # List commands
        commands = handler.list_commands()
        assert len(commands) == 2

        # Execute commands
        result1 = handler.execute_command("analyze")
        result2 = handler.execute_command("report")

        assert result1 == 0
        assert result2 == 1

    def test_error_handling_workflow(self):
        """Test error handling in command execution."""
        app = Mock()
        app.registry.get_tool.return_value = None

        handler = CommandHandler(app)

        # Should raise CommandError for missing tool
        with pytest.raises(CommandError):
            handler.execute_command("missing")

        # Setup tool that raises
        failing_tool = Mock()
        failing_tool.run.side_effect = RuntimeError("Oops")
        app.registry.get_tool.return_value = failing_tool

        with pytest.raises(CommandError) as exc_info:
            handler.execute_command("failing")

        assert "Failed to execute" in str(exc_info.value)
