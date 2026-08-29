# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for app/tools/base.py.

Tests key functionality including:
- ToolConfig dataclass
- Tool initialization
- Tool properties (name, cmd, group, lg, args, kwargs, initialized, arg_prs)
- Tool lifecycle methods (setup, setup_lg, configure)
- Tool group management (create_group, add_tool, add_cmd)
- Tool execution (run)
"""

import argparse
from unittest.mock import Mock, patch

import pytest

from appinfra.app.errors import (
    LifecycleError,
    MissingLoggerError,
    MissingParentError,
    UndefGroupError,
    UndefNameError,
)
from appinfra.app.tools.base import Tool, ToolConfig

# =============================================================================
# Test ToolConfig
# =============================================================================


@pytest.mark.unit
class TestToolConfig:
    """Test ToolConfig dataclass."""

    def test_basic_creation(self):
        """Test creating config with just name."""
        config = ToolConfig(name="test")

        assert config.name == "test"
        assert config.aliases == []
        assert config.help_text == ""
        assert config.description == ""

    def test_full_creation(self):
        """Test creating config with all fields."""
        config = ToolConfig(
            name="analyze",
            aliases=["a", "an"],
            help_text="Analyze data",
            description="Detailed description",
        )

        assert config.name == "analyze"
        assert config.aliases == ["a", "an"]
        assert config.help_text == "Analyze data"
        assert config.description == "Detailed description"


# =============================================================================
# Helper: Concrete Tool Implementation
# =============================================================================


class ConcreteTool(Tool):
    """Concrete implementation for testing."""

    def _create_config(self) -> ToolConfig:
        return ToolConfig(name="concrete")


class ConfiglessTool(Tool):
    """Tool without _create_config override."""

    pass


# =============================================================================
# Test Tool Initialization
# =============================================================================


@pytest.mark.unit
class TestToolInit:
    """Test Tool initialization."""

    def test_init_with_config(self):
        """Test initialization with explicit config."""
        config = ToolConfig(name="test", help_text="Test tool")
        tool = ConcreteTool(config=config)

        assert tool.config is config
        assert tool._logger is None
        assert tool._kwargs is None
        assert tool._group is None
        assert tool._initialized is False

    def test_init_calls_create_config_when_no_config(self):
        """Test initialization calls _create_config when config not provided."""
        tool = ConcreteTool()

        assert tool.config.name == "concrete"

    def test_init_raises_when_no_create_config_override(self):
        """Test raises UndefNameError when _create_config not overridden."""
        with pytest.raises(UndefNameError):
            ConfiglessTool()


# =============================================================================
# Test name Property
# =============================================================================


@pytest.mark.unit
class TestToolNameProperty:
    """Test Tool.name property."""

    def test_returns_config_name(self):
        """Test returns name from config."""
        config = ToolConfig(name="my-tool")
        tool = ConcreteTool(config=config)

        assert tool.name == "my-tool"

    def test_raises_when_config_name_empty(self):
        """Test raises UndefNameError when config name is empty."""
        config = ToolConfig(name="")
        tool = ConcreteTool(config=config)

        with pytest.raises(UndefNameError):
            _ = tool.name


# =============================================================================
# Test cmd Property
# =============================================================================


@pytest.mark.unit
class TestToolCmdProperty:
    """Test Tool.cmd property."""

    def test_returns_command_configuration(self):
        """Test returns proper command args and kwargs."""
        config = ToolConfig(
            name="analyze",
            aliases=["a"],
            help_text="Analyze data",
            description="Full description",
        )
        tool = ConcreteTool(config=config)

        cmd_args, cmd_kwargs = tool.cmd

        assert cmd_args == ["analyze"]
        assert cmd_kwargs["aliases"] == ["a"]
        assert cmd_kwargs["help"] == "Analyze data"
        assert cmd_kwargs["description"] == "Full description"


# =============================================================================
# Test group Property
# =============================================================================


@pytest.mark.unit
class TestToolGroupProperty:
    """Test Tool.group property."""

    def test_raises_when_no_group(self):
        """Test raises UndefGroupError when group not set."""
        tool = ConcreteTool()

        with pytest.raises(UndefGroupError):
            _ = tool.group

    def test_returns_group_when_set(self):
        """Test returns group when set."""
        tool = ConcreteTool()
        mock_group = Mock()
        tool._group = mock_group

        assert tool.group is mock_group


# =============================================================================
# Test lg Property
# =============================================================================


@pytest.mark.unit
class TestToolLgProperty:
    """Test Tool.lg property."""

    def test_raises_error_before_setup(self):
        """Test raises MissingLoggerError when accessed before setup."""
        tool = ConcreteTool()

        with pytest.raises(MissingLoggerError) as exc_info:
            _ = tool.lg

        assert "concrete" in str(exc_info.value)
        assert "setup()" in str(exc_info.value)

    def test_returns_logger_when_set(self):
        """Test returns logger when set."""
        tool = ConcreteTool()
        mock_logger = Mock()
        tool._logger = mock_logger

        assert tool.lg is mock_logger


# =============================================================================
# Test args Property
# =============================================================================


@pytest.mark.unit
class TestToolArgsProperty:
    """Test Tool.args property."""

    def test_returns_parsed_args_when_set(self):
        """Test returns _parsed_args when set."""
        tool = ConcreteTool()
        parsed = argparse.Namespace(file="test.txt")
        tool._parsed_args = parsed

        assert tool.args is parsed

    def test_raises_when_no_parent(self):
        """Test raises MissingParentError when no parent."""
        tool = ConcreteTool()

        with pytest.raises(MissingParentError):
            _ = tool.args

    def test_raises_when_parent_has_no_args(self):
        """Test raises MissingParentError when parent lacks args."""
        parent = Mock(spec=[])  # No args attribute
        tool = ConcreteTool(parent=parent)

        with pytest.raises(MissingParentError):
            _ = tool.args

    def test_returns_parent_args(self):
        """Test returns args from parent."""
        parent = Mock()
        parent.args = argparse.Namespace(verbose=True)
        tool = ConcreteTool(parent=parent)

        assert tool.args.verbose is True


# =============================================================================
# Test kwargs Property
# =============================================================================


@pytest.mark.unit
class TestToolKwargsProperty:
    """Test Tool.kwargs property."""

    def test_returns_none_initially(self):
        """Test returns None when kwargs not set."""
        tool = ConcreteTool()

        assert tool.kwargs is None

    def test_returns_kwargs_after_setup(self):
        """Test returns kwargs after setup."""
        tool = ConcreteTool()
        tool._kwargs = {"key": "value"}

        assert tool.kwargs == {"key": "value"}


# =============================================================================
# Test initialized Property
# =============================================================================


@pytest.mark.unit
class TestToolInitializedProperty:
    """Test Tool.initialized property."""

    def test_returns_false_initially(self):
        """Test returns False initially."""
        tool = ConcreteTool()

        assert tool.initialized is False

    def test_returns_true_after_setup(self):
        """Test returns True after setup."""
        tool = ConcreteTool()
        tool._initialized = True

        assert tool.initialized is True


# =============================================================================
# Test arg_prs Property
# =============================================================================


@pytest.mark.unit
class TestToolArgPrsProperty:
    """Test Tool.arg_prs property."""

    def test_returns_none_initially(self):
        """Test returns None when parser not set."""
        tool = ConcreteTool()

        assert tool.arg_prs is None

    def test_returns_parser_when_set(self):
        """Test returns parser when set."""
        tool = ConcreteTool()
        parser = argparse.ArgumentParser()
        tool._arg_prs = parser

        assert tool.arg_prs is parser


# =============================================================================
# Test _PositionalFilteringParser
# =============================================================================


@pytest.mark.unit
class TestPositionalFilteringParser:
    """Test _PositionalFilteringParser wrapper."""

    def test_adds_optional_arguments(self):
        """Test adds arguments starting with dash."""
        from appinfra.app.tools.base import _PositionalFilteringParser

        parser = argparse.ArgumentParser()
        wrapper = _PositionalFilteringParser(parser)

        wrapper.add_argument("--verbose", action="store_true")
        wrapper.add_argument("-p", "--port", type=int)

        # Parse to verify args were added
        ns = parser.parse_args(["--verbose", "--port", "8080"])
        assert ns.verbose is True
        assert ns.port == 8080

    def test_skips_positional_arguments(self):
        """Test skips arguments not starting with dash (positional)."""
        from appinfra.app.tools.base import _PositionalFilteringParser

        parser = argparse.ArgumentParser()
        wrapper = _PositionalFilteringParser(parser)

        result = wrapper.add_argument("filename", help="Input file")
        wrapper.add_argument("--verbose", action="store_true")

        assert result is None  # Positional was skipped

        # Parser should only have --verbose, not filename
        ns = parser.parse_args(["--verbose"])
        assert ns.verbose is True
        assert not hasattr(ns, "filename")

    def test_delegates_add_argument_group(self):
        """Test delegates add_argument_group and filters positionals in group."""
        from appinfra.app.tools.base import _PositionalFilteringParser

        parser = argparse.ArgumentParser()
        wrapper = _PositionalFilteringParser(parser)

        group = wrapper.add_argument_group("Options")
        group.add_argument("--test", help="Test arg")
        result = group.add_argument("positional", help="Should be skipped")

        assert result is None  # Positional was skipped
        ns = parser.parse_args(["--test", "value"])
        assert ns.test == "value"
        assert not hasattr(ns, "positional")

    def test_delegates_add_mutually_exclusive_group(self):
        """Test delegates add_mutually_exclusive_group and filters positionals."""
        from appinfra.app.tools.base import _PositionalFilteringParser

        parser = argparse.ArgumentParser()
        wrapper = _PositionalFilteringParser(parser)

        group = wrapper.add_mutually_exclusive_group()
        group.add_argument("--a", action="store_true")
        group.add_argument("--b", action="store_true")

        ns = parser.parse_args(["--a"])
        assert ns.a is True
        assert ns.b is False

    def test_delegates_unknown_attributes_via_getattr(self):
        """Test delegates unknown attributes to underlying parser."""
        from appinfra.app.tools.base import _PositionalFilteringParser

        parser = argparse.ArgumentParser(description="Test parser")
        wrapper = _PositionalFilteringParser(parser)

        # Access attributes that exist on the underlying parser
        assert wrapper.description == "Test parser"

        # Access methods that exist on the underlying parser
        wrapper.set_defaults(foo="bar")
        ns = parser.parse_args([])
        assert ns.foo == "bar"


# =============================================================================
# Test _PositionalFilteringGroup
# =============================================================================


@pytest.mark.unit
class TestPositionalFilteringGroup:
    """Test _PositionalFilteringGroup wrapper."""

    def test_adds_optional_arguments(self):
        """Test adds arguments starting with dash."""
        from appinfra.app.tools.base import _PositionalFilteringGroup

        parser = argparse.ArgumentParser()
        raw_group = parser.add_argument_group("Options")
        wrapper = _PositionalFilteringGroup(raw_group)

        wrapper.add_argument("--verbose", action="store_true")
        wrapper.add_argument("-p", "--port", type=int)

        ns = parser.parse_args(["--verbose", "--port", "8080"])
        assert ns.verbose is True
        assert ns.port == 8080

    def test_skips_positional_arguments(self):
        """Test skips arguments not starting with dash (positional)."""
        from appinfra.app.tools.base import _PositionalFilteringGroup

        parser = argparse.ArgumentParser()
        raw_group = parser.add_argument_group("Options")
        wrapper = _PositionalFilteringGroup(raw_group)

        result = wrapper.add_argument("filename", help="Input file")
        wrapper.add_argument("--verbose", action="store_true")

        assert result is None  # Positional was skipped

        ns = parser.parse_args(["--verbose"])
        assert ns.verbose is True
        assert not hasattr(ns, "filename")

    def test_delegates_unknown_attributes(self):
        """Test delegates unknown attributes to underlying group."""
        from appinfra.app.tools.base import _PositionalFilteringGroup

        parser = argparse.ArgumentParser()
        raw_group = parser.add_argument_group("TestGroup")
        wrapper = _PositionalFilteringGroup(raw_group)

        # Access title attribute from underlying group
        assert wrapper.title == "TestGroup"

    def test_mutually_exclusive_group_filters_positionals(self):
        """Test mutually exclusive groups within argument groups filter positionals."""
        from appinfra.app.tools.base import _PositionalFilteringGroup

        parser = argparse.ArgumentParser()
        raw_group = parser.add_argument_group("Options")
        wrapper = _PositionalFilteringGroup(raw_group)

        # Create mutually exclusive group from within argument group
        mutex = wrapper.add_mutually_exclusive_group()

        # Should be wrapped
        assert isinstance(mutex, _PositionalFilteringGroup)

        # Add positional - should be skipped
        result = mutex.add_argument("positional", nargs="?", help="Should be skipped")
        mutex.add_argument("--opt-a", action="store_true")
        mutex.add_argument("--opt-b", action="store_true")

        assert result is None  # Positional was skipped
        ns = parser.parse_args(["--opt-a"])
        assert ns.opt_a is True
        assert ns.opt_b is False
        assert not hasattr(ns, "positional")


# =============================================================================
# Test set_args Method
# =============================================================================


@pytest.mark.unit
class TestToolSetArgs:
    """Test Tool.set_args method."""

    def test_stores_parser(self):
        """Test stores parser reference."""
        tool = ConcreteTool()
        parser = argparse.ArgumentParser()

        tool.set_args(parser)

        assert tool._arg_prs is parser

    def test_calls_add_args(self):
        """Test calls add_args with parser."""
        tool = ConcreteTool()
        tool.add_args = Mock()
        parser = argparse.ArgumentParser()

        tool.set_args(parser)

        tool.add_args.assert_called_once_with(parser)

    def test_handles_group_when_present(self):
        """Test handles tool group when present."""
        tool = ConcreteTool()
        mock_group = Mock()
        mock_group.add_tool_args.return_value = Mock()
        tool._group = mock_group
        tool.add_group_args = Mock()
        tool.add_args = Mock()
        parser = argparse.ArgumentParser()

        tool.set_args(parser)

        mock_group.add_tool_args.assert_called_once_with(parser)
        tool.add_group_args.assert_called_once()
        mock_group.finalize_args.assert_called_once_with(parser)

    def test_skip_positional_uses_filtering_wrapper(self):
        """Test skip_positional=True uses _PositionalFilteringParser."""

        class ToolWithPositional(Tool):
            def _create_config(self):
                return ToolConfig(name="test")

            def add_args(self, parser):
                parser.add_argument("target", help="Target path")
                parser.add_argument("--verbose", action="store_true")

        tool = ToolWithPositional()
        parser = argparse.ArgumentParser()

        tool.set_args(parser, skip_positional=True)

        # Parser should only have --verbose, not target
        ns = parser.parse_args(["--verbose"])
        assert ns.verbose is True
        assert not hasattr(ns, "target")

    def test_skip_positional_false_adds_all_args(self):
        """Test skip_positional=False (default) adds all args including positional."""

        class ToolWithPositional(Tool):
            def _create_config(self):
                return ToolConfig(name="test")

            def add_args(self, parser):
                parser.add_argument("target", help="Target path")
                parser.add_argument("--verbose", action="store_true")

        tool = ToolWithPositional()
        parser = argparse.ArgumentParser()

        tool.set_args(parser, skip_positional=False)

        # Parser should have both target and --verbose
        ns = parser.parse_args(["/tmp/file", "--verbose"])
        assert ns.target == "/tmp/file"
        assert ns.verbose is True


# =============================================================================
# Test add_group_args Method
# =============================================================================


@pytest.mark.unit
class TestToolAddGroupArgs:
    """Test Tool.add_group_args method."""

    def test_adds_registered_commands(self):
        """Test adds commands registered via add_cmd."""
        tool = ConcreteTool()
        mock_group = Mock()
        tool._group = mock_group
        tool._commands = [
            {
                "name": "cmd1",
                "aliases": ["c1"],
                "help_text": "Command 1",
                "run_func": lambda: 0,
            },
            {"name": "cmd2", "aliases": [], "help_text": "", "run_func": lambda: 1},
        ]
        subs = Mock()

        tool.add_group_args(subs)

        assert mock_group.add_cmd.call_count == 2


# =============================================================================
# Test setup Method
# =============================================================================


@pytest.mark.unit
class TestToolSetup:
    """Test Tool.setup method."""

    def test_sets_kwargs(self):
        """Test stores kwargs."""
        tool = ConcreteTool()
        tool.setup_lg = Mock()
        tool.configure = Mock()

        tool.setup(key="value")

        assert tool._kwargs == {"key": "value"}

    def test_calls_setup_lg_and_configure(self):
        """Test calls setup_lg and configure."""
        tool = ConcreteTool()
        tool.setup_lg = Mock()
        tool.configure = Mock()

        tool.setup()

        tool.setup_lg.assert_called_once()
        tool.configure.assert_called_once()

    def test_sets_initialized_flag(self):
        """Test sets _initialized to True."""
        tool = ConcreteTool()
        tool.setup_lg = Mock()
        tool.configure = Mock()

        tool.setup()

        assert tool._initialized is True

    def test_prevents_double_initialization(self):
        """Test prevents re-execution of setup."""
        tool = ConcreteTool()
        tool.setup_lg = Mock()
        tool.configure = Mock()

        tool.setup()
        tool.setup()  # Second call

        # Should only be called once
        assert tool.setup_lg.call_count == 1

    def test_sets_up_group_tools(self):
        """Test sets up all tools in group."""
        tool = ConcreteTool()
        tool.setup_lg = Mock()
        tool.configure = Mock()

        subtool = Mock()
        mock_group = Mock()
        mock_group._tools = {"sub": subtool}
        tool._group = mock_group

        tool.setup(key="value")

        subtool.setup.assert_called_once_with(key="value")


# =============================================================================
# Test setup_lg Method
# =============================================================================


@pytest.mark.unit
class TestToolSetupLg:
    """Test Tool.setup_lg method."""

    def test_derives_logger_from_parent(self):
        """Test derives logger from parent when available."""
        parent = Mock()
        parent.lg = Mock()
        tool = ConcreteTool(parent=parent)

        with patch("appinfra.app.tools.base.LoggerFactory") as MockFactory:
            mock_logger = Mock()
            MockFactory.derive.return_value = mock_logger

            tool.setup_lg()

            MockFactory.derive.assert_called_once_with(parent.lg, "concrete")
            assert tool._logger is mock_logger

    def test_creates_standalone_logger_when_no_parent(self):
        """Test creates standalone logger when no parent."""
        tool = ConcreteTool()

        with patch("appinfra.app.tools.base.LoggerFactory") as MockFactory:
            with patch("appinfra.log.LogConfig") as MockLogConfig:
                mock_logger = Mock()
                MockFactory.create_root.return_value = mock_logger
                mock_config = Mock()
                MockLogConfig.from_params.return_value = mock_config

                tool.setup_lg()

                MockFactory.create_root.assert_called_once_with(mock_config)

    def test_raises_lifecycle_error_on_failure(self):
        """Test raises LifecycleError when logger creation fails."""
        parent = Mock()
        parent.lg = Mock()
        tool = ConcreteTool(parent=parent)

        with patch("appinfra.app.tools.base.LoggerFactory") as MockFactory:
            MockFactory.derive.side_effect = Exception("Logger error")

            with pytest.raises(LifecycleError) as exc_info:
                tool.setup_lg()

            assert "Failed to create logger" in str(exc_info.value)


# =============================================================================
# Test create_group Method
# =============================================================================


@pytest.mark.unit
class TestToolCreateGroup:
    """Test Tool.create_group method."""

    def test_creates_tool_group(self):
        """Test creates ToolGroup instance."""
        tool = ConcreteTool()

        with patch("appinfra.app.tools.group.ToolGroup") as MockToolGroup:
            mock_group = Mock()
            MockToolGroup.return_value = mock_group

            result = tool.create_group()

            MockToolGroup.assert_called_once_with(tool, "concrete_cmd", None)
            assert result is mock_group
            assert tool._group is mock_group

    def test_creates_group_with_default(self):
        """Test creates group with default subtool."""
        tool = ConcreteTool()

        with patch("appinfra.app.tools.group.ToolGroup") as MockToolGroup:
            tool.create_group(default="help")

            MockToolGroup.assert_called_once_with(tool, "concrete_cmd", "help")


# =============================================================================
# Test add_tool Method
# =============================================================================


@pytest.mark.unit
class TestToolAddTool:
    """Test Tool.add_tool method."""

    def test_creates_group_if_not_exists(self):
        """Test creates group if not already set."""
        tool = ConcreteTool()
        subtool = Mock()

        with patch("appinfra.app.tools.group.ToolGroup") as MockToolGroup:
            mock_group = Mock()
            mock_group.add_tool.return_value = subtool
            MockToolGroup.return_value = mock_group

            tool.add_tool(subtool, default="help")

            # Group should have been created
            MockToolGroup.assert_called_once()
            mock_group.add_tool.assert_called_once()

    def test_adds_tool_to_existing_group(self):
        """Test adds tool to existing group."""
        tool = ConcreteTool()
        mock_group = Mock()
        tool._group = mock_group
        subtool = Mock()
        run_func = Mock()

        tool.add_tool(subtool, run_func=run_func)

        mock_group.add_tool.assert_called_once_with(subtool, run_func=run_func)


# =============================================================================
# Test add_cmd Method
# =============================================================================


@pytest.mark.unit
class TestToolAddCmd:
    """Test Tool.add_cmd method."""

    def test_creates_group_if_not_exists(self):
        """Test creates group if not already set."""
        tool = ConcreteTool()

        with patch("appinfra.app.tools.group.ToolGroup") as MockToolGroup:
            mock_group = Mock()
            MockToolGroup.return_value = mock_group

            tool.add_cmd("test", lambda: 0)

            # Group should have been created
            MockToolGroup.assert_called_once()

    def test_stores_command_info(self):
        """Test stores command information."""
        tool = ConcreteTool()
        mock_group = Mock()
        tool._group = mock_group
        run_func = lambda: 0

        tool.add_cmd("test", run_func, aliases=["t"], help_text="Test command")

        assert hasattr(tool, "_commands")
        assert len(tool._commands) == 1
        cmd = tool._commands[0]
        assert cmd["name"] == "test"
        assert cmd["aliases"] == ["t"]
        assert cmd["help_text"] == "Test command"
        assert cmd["run_func"] is run_func

    def test_handles_empty_aliases(self):
        """Test handles no aliases."""
        tool = ConcreteTool()
        mock_group = Mock()
        tool._group = mock_group

        tool.add_cmd("test", lambda: 0)

        assert tool._commands[0]["aliases"] == []


# =============================================================================
# Test run Method
# =============================================================================


@pytest.mark.unit
class TestToolRun:
    """Test Tool.run method."""

    def test_raises_when_no_group(self):
        """Test raises UndefGroupError when no group."""
        tool = ConcreteTool()

        with pytest.raises(UndefGroupError):
            tool.run()

    def test_delegates_to_group_run(self):
        """Test delegates execution to group."""
        tool = ConcreteTool()
        mock_group = Mock()
        mock_group.run.return_value = 42
        tool._group = mock_group

        result = tool.run(key="value")

        mock_group.run.assert_called_once_with(key="value")
        assert result == 42


# =============================================================================
# Integration Tests
# =============================================================================


@pytest.mark.integration
class TestToolIntegration:
    """Integration tests for Tool class."""

    def test_full_tool_lifecycle(self):
        """Test complete tool lifecycle."""

        class MyTool(Tool):
            def _create_config(self):
                return ToolConfig(
                    name="mytool",
                    aliases=["mt"],
                    help_text="My tool",
                )

            def add_args(self, parser):
                parser.add_argument("--verbose", action="store_true")

        tool = MyTool()

        # Check initial state
        assert tool.name == "mytool"
        assert tool.initialized is False

        # Setup
        with patch("appinfra.app.tools.base.LoggerFactory") as MockFactory:
            mock_logger = Mock()
            MockFactory.create_root.return_value = mock_logger
            with patch("appinfra.log.LogConfig"):
                tool.setup()

        assert tool.initialized is True
        assert tool.lg is not None

    def test_tool_with_subtools(self):
        """Test tool with subtool hierarchy."""
        parent = ConcreteTool()
        parent._logger = Mock()

        # Create subtool
        class SubTool(Tool):
            def _create_config(self):
                return ToolConfig(name="sub")

        subtool = SubTool(parent=parent)

        # Add subtool
        with patch("appinfra.app.tools.group.ToolGroup") as MockToolGroup:
            mock_group = Mock()
            MockToolGroup.return_value = mock_group
            mock_group.add_tool.return_value = subtool

            parent.add_tool(subtool)

        assert parent._group is not None
