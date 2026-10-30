# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for app/builder/tool.py.

Tests key functionality including:
- ToolBuilder class and fluent API
- BuiltTool execution and subcommands
- FunctionTool wrapping
- Factory function create_function_tool
"""

from unittest.mock import Mock

import pytest

from appinfra.app.builder.tool import (
    BuiltTool,
    FunctionTool,
    ToolBuilder,
    create_function_tool,
)
from appinfra.app.tools.base import ToolConfig

# =============================================================================
# Test ToolBuilder Initialization
# =============================================================================


@pytest.mark.unit
class TestToolBuilderInit:
    """Test ToolBuilder initialization (lines 17-33)."""

    def test_basic_initialization(self):
        """Test basic initialization (lines 24-33)."""
        builder = ToolBuilder("mytool")

        assert builder._name == "mytool"
        assert builder._aliases == []
        assert builder._help_text == ""
        assert builder._description == ""
        assert builder._args == []
        assert builder._subcommands == []
        assert builder._run_func is None
        assert builder._setup_func is None
        assert builder._parent is None
        assert builder._group_default is None


# =============================================================================
# Test ToolBuilder Builder Methods
# =============================================================================


@pytest.mark.unit
class TestToolBuilderMethods:
    """Test ToolBuilder fluent methods."""

    def test_with_alias(self):
        """Test with_alias adds alias (lines 35-38)."""
        builder = ToolBuilder("mytool")

        result = builder.with_alias("mt")

        assert "mt" in builder._aliases
        assert result is builder

    def test_with_aliases(self):
        """Test with_aliases adds multiple aliases (lines 40-43)."""
        builder = ToolBuilder("mytool")

        result = builder.with_aliases("mt", "m", "tool")

        assert builder._aliases == ["mt", "m", "tool"]
        assert result is builder

    def test_with_help(self):
        """Test with_help sets help text (lines 45-48)."""
        builder = ToolBuilder("mytool")

        result = builder.with_help("This is help text")

        assert builder._help_text == "This is help text"
        assert result is builder

    def test_with_description(self):
        """Test with_description sets description (lines 50-53)."""
        builder = ToolBuilder("mytool")

        result = builder.with_description("Detailed description")

        assert builder._description == "Detailed description"
        assert result is builder

    def test_with_argument(self):
        """Test with_argument adds argument (lines 55-58)."""
        builder = ToolBuilder("mytool")

        result = builder.with_argument("--verbose", "-v", action="store_true")

        assert len(builder._args) == 1
        assert builder._args[0] == (("--verbose", "-v"), {"action": "store_true"})
        assert result is builder

    def test_with_subcommand(self):
        """Test with_subcommand adds subcommand (lines 60-63)."""
        builder = ToolBuilder("mytool")
        sub_builder = ToolBuilder("subtool")

        result = builder.with_subcommand("sub", sub_builder)

        assert len(builder._subcommands) == 1
        assert builder._subcommands[0] == ("sub", sub_builder)
        assert result is builder

    def test_with_run_function(self):
        """Test with_run_function sets run function (lines 65-68)."""
        builder = ToolBuilder("mytool")
        func = Mock()

        result = builder.with_run_function(func)

        assert builder._run_func is func
        assert result is builder

    def test_with_setup_function(self):
        """Test with_setup_function sets setup function (lines 70-73)."""
        builder = ToolBuilder("mytool")
        func = Mock()

        result = builder.with_setup_function(func)

        assert builder._setup_func is func
        assert result is builder

    def test_with_parent(self):
        """Test with_parent sets parent (lines 75-78)."""
        builder = ToolBuilder("mytool")
        parent = Mock()

        result = builder.with_parent(parent)

        assert builder._parent is parent
        assert result is builder

    def test_with_group_default(self):
        """Test with_group_default sets default (lines 80-83)."""
        builder = ToolBuilder("mytool")

        result = builder.with_group_default("help")

        assert builder._group_default == "help"
        assert result is builder


# =============================================================================
# Test ToolBuilder build
# =============================================================================


@pytest.mark.unit
class TestToolBuilderBuild:
    """Test ToolBuilder build method (lines 85-113)."""

    def test_build_creates_built_tool(self):
        """Test build creates BuiltTool instance (lines 96-102)."""
        builder = ToolBuilder("mytool")

        result = builder.build()

        assert isinstance(result, BuiltTool)
        assert result.name == "mytool"

    def test_build_creates_config(self):
        """Test build creates ToolConfig (lines 88-93)."""
        builder = (
            ToolBuilder("mytool")
            .with_alias("mt")
            .with_help("Help text")
            .with_description("Description")
        )

        result = builder.build()

        assert result.config.name == "mytool"
        assert "mt" in result.config.aliases
        assert result.config.help_text == "Help text"
        assert result.config.description == "Description"

    def test_build_adds_arguments(self):
        """Test build adds arguments (lines 105-106)."""
        builder = (
            ToolBuilder("mytool")
            .with_argument("--verbose", "-v", action="store_true")
            .with_argument("--output", "-o", type=str)
        )

        result = builder.build()

        assert len(result._custom_args) == 2

    def test_build_with_run_and_setup_functions(self):
        """Test build passes run and setup functions (lines 99-100)."""
        run_func = Mock()
        setup_func = Mock()
        builder = (
            ToolBuilder("mytool")
            .with_run_function(run_func)
            .with_setup_function(setup_func)
        )

        result = builder.build()

        assert result._run_func is run_func
        assert result._setup_func is setup_func


# =============================================================================
# Test BuiltTool Initialization
# =============================================================================


@pytest.mark.unit
class TestBuiltToolInit:
    """Test BuiltTool initialization (lines 119-142)."""

    def test_basic_initialization(self):
        """Test basic initialization (lines 137-142)."""
        config = ToolConfig(name="test")
        tool = BuiltTool(config=config)

        assert tool._run_func is None
        assert tool._setup_func is None
        assert tool._group_default is None
        assert tool._custom_args == []
        assert tool._sub_tools == []

    def test_initialization_with_all_params(self):
        """Test initialization with all parameters."""
        config = ToolConfig(name="test")
        parent = Mock()
        run_func = Mock()
        setup_func = Mock()

        tool = BuiltTool(
            parent=parent,
            config=config,
            run_func=run_func,
            setup_func=setup_func,
            group_default="help",
        )

        assert tool._parent is parent
        assert tool._run_func is run_func
        assert tool._setup_func is setup_func
        assert tool._group_default == "help"


# =============================================================================
# Test BuiltTool name Property
# =============================================================================


@pytest.mark.unit
class TestBuiltToolName:
    """Test BuiltTool name property (lines 144-147)."""

    def test_returns_name_from_config(self):
        """Test returns name from config (line 147)."""
        config = ToolConfig(name="mytool")
        tool = BuiltTool(config=config)

        assert tool.name == "mytool"

    def test_returns_name_from_config_with_parent(self):
        """Test returns name when parent is set."""
        config = ToolConfig(name="childtool")
        parent = Mock()
        tool = BuiltTool(parent=parent, config=config)

        assert tool.name == "childtool"


# =============================================================================
# Test BuiltTool add_argument
# =============================================================================


@pytest.mark.unit
class TestBuiltToolAddArgument:
    """Test BuiltTool add_argument method (lines 149-151)."""

    def test_adds_argument(self):
        """Test adds argument to custom_args (line 151)."""
        config = ToolConfig(name="test")
        tool = BuiltTool(config=config)

        tool.add_argument("--verbose", "-v", action="store_true")

        assert len(tool._custom_args) == 1
        assert tool._custom_args[0] == (("--verbose", "-v"), {"action": "store_true"})


# =============================================================================
# Test BuiltTool add_tool
# =============================================================================


@pytest.mark.unit
class TestBuiltToolAddTool:
    """Test BuiltTool add_tool method (lines 153-158)."""

    def test_adds_sub_tool(self):
        """Test adds tool to sub_tools (line 155)."""
        config = ToolConfig(name="parent")
        parent_tool = BuiltTool(config=config)
        sub_config = ToolConfig(name="child")
        sub_tool = BuiltTool(config=sub_config)

        parent_tool.add_tool(sub_tool)

        assert sub_tool in parent_tool._sub_tools

    def test_creates_group_if_none(self):
        """Test creates group if None (lines 156-157)."""
        config = ToolConfig(name="parent")
        parent_tool = BuiltTool(config=config, group_default="help")
        sub_config = ToolConfig(name="child")
        sub_tool = BuiltTool(config=sub_config)

        assert parent_tool._group is None
        parent_tool.add_tool(sub_tool)

        assert parent_tool._group is not None


# =============================================================================
# Test BuiltTool add_args
# =============================================================================


@pytest.mark.unit
class TestBuiltToolAddArgs:
    """Test BuiltTool add_args method (lines 160-163)."""

    def test_adds_args_to_parser(self):
        """Test adds arguments to parser (lines 162-163)."""
        config = ToolConfig(name="test")
        tool = BuiltTool(config=config)
        tool._custom_args = [
            (("--verbose", "-v"), {"action": "store_true"}),
            (("--output",), {"type": str}),
        ]
        parser = Mock()

        tool.add_args(parser)

        assert parser.add_argument.call_count == 2


# =============================================================================
# Test BuiltTool setup
# =============================================================================


@pytest.mark.unit
class TestBuiltToolSetup:
    """Test BuiltTool setup method (lines 165-175)."""

    def test_calls_custom_setup_func(self):
        """Test calls custom setup function (lines 170-171)."""
        config = ToolConfig(name="test")
        setup_func = Mock()
        tool = BuiltTool(config=config, setup_func=setup_func)

        tool.setup(param="value")

        setup_func.assert_called_once_with(tool, param="value")

    def test_sets_up_sub_tools(self):
        """Test sets up sub-tools (lines 174-175)."""
        config = ToolConfig(name="parent")
        tool = BuiltTool(config=config)
        sub_tool = Mock()
        tool._sub_tools = [sub_tool]

        tool.setup(param="value")

        sub_tool.setup.assert_called_once_with(param="value")


# =============================================================================
# Test BuiltTool run
# =============================================================================


@pytest.mark.unit
class TestBuiltToolRun:
    """Test BuiltTool run method (lines 177-186)."""

    def test_calls_run_func_when_provided(self):
        """Test calls run function when provided (lines 179-180)."""
        config = ToolConfig(name="test")
        run_func = Mock(return_value=42)
        tool = BuiltTool(config=config, run_func=run_func)

        result = tool.run(param="value")

        run_func.assert_called_once_with(tool, param="value")
        assert result == 42

    def test_runs_group_when_no_run_func(self):
        """Test runs group when no run function (lines 181-182)."""
        config = ToolConfig(name="test")
        tool = BuiltTool(config=config)
        tool._group = Mock()
        tool._group.run.return_value = 0

        result = tool.run(param="value")

        tool._group.run.assert_called_once_with(param="value")
        assert result == 0

    def test_returns_zero_as_default(self):
        """Test returns 0 as default (lines 184-186)."""
        config = ToolConfig(name="test")
        tool = BuiltTool(config=config)
        # Set up the logger directly (normally set during setup())
        tool._logger = Mock()
        # Default behavior (no run_func, no group) logs and returns 0

        result = tool.run()

        assert result == 0
        # Verify it logged the run
        tool._logger.info.assert_called()


# =============================================================================
# Test FunctionTool
# =============================================================================


@pytest.mark.unit
class TestFunctionTool:
    """Test FunctionTool class (lines 189-223)."""

    def test_initialization(self):
        """Test initialization (lines 192-219)."""
        func = Mock()
        tool = FunctionTool(
            name="mytool",
            func=func,
            aliases=["mt", "m"],
            help_text="Help",
            description="Description",
        )

        assert tool.config.name == "mytool"
        assert "mt" in tool.config.aliases
        assert tool.config.help_text == "Help"
        assert tool.config.description == "Description"
        assert tool._func is func

    def test_initialization_defaults(self):
        """Test initialization with defaults."""
        func = Mock()
        tool = FunctionTool(name="mytool", func=func)

        assert tool.config.aliases == []
        assert tool.config.help_text == ""
        assert tool.config.description == ""

    def test_run_calls_function(self):
        """Test run calls wrapped function (lines 221-223)."""
        func = Mock(return_value=42)
        tool = FunctionTool(name="mytool", func=func)

        result = tool.run(param="value", other=123)

        func.assert_called_once_with(param="value", other=123)
        assert result == 42


# =============================================================================
# Test create_function_tool
# =============================================================================


@pytest.mark.unit
class TestCreateFunctionTool:
    """Test create_function_tool function (lines 226-248)."""

    def test_creates_tool_builder(self):
        """Test creates ToolBuilder (line 238)."""
        func = Mock()
        builder = create_function_tool("mytool", func)

        assert isinstance(builder, ToolBuilder)
        assert builder._name == "mytool"

    def test_sets_run_function(self):
        """Test sets run function (line 239)."""
        func = Mock()
        builder = create_function_tool("mytool", func)

        assert builder._run_func is not None

    def test_handles_aliases(self):
        """Test handles aliases kwarg (lines 241-242)."""
        func = Mock()
        builder = create_function_tool("mytool", func, aliases=["mt", "m"])

        assert builder._aliases == ["mt", "m"]

    def test_handles_help(self):
        """Test handles help kwarg (lines 243-244)."""
        func = Mock()
        builder = create_function_tool("mytool", func, help="Help text")

        assert builder._help_text == "Help text"

    def test_handles_description(self):
        """Test handles description kwarg (lines 245-246)."""
        func = Mock()
        builder = create_function_tool("mytool", func, description="Description")

        assert builder._description == "Description"

    def test_built_tool_runs_function(self):
        """Test built tool runs the original function."""
        called_with = []

        def my_func(**kwargs):
            called_with.append(kwargs)
            return 42

        builder = create_function_tool("mytool", my_func)
        tool = builder.build()
        result = tool.run(param="value")

        assert result == 42
        assert called_with == [{"param": "value"}]


# =============================================================================
# Integration Tests
# =============================================================================


@pytest.mark.integration
class TestToolBuilderIntegration:
    """Test ToolBuilder integration scenarios."""

    def test_full_tool_building_workflow(self):
        """Test complete tool building workflow."""
        run_called = []
        setup_called = []

        def my_run(tool, **kwargs):
            run_called.append((tool.name, kwargs))
            return 0

        def my_setup(tool, **kwargs):
            setup_called.append((tool.name, kwargs))

        tool = (
            ToolBuilder("analyze")
            .with_alias("a")
            .with_help("Analyze data")
            .with_description("Performs detailed analysis")
            .with_argument("--verbose", "-v", action="store_true")
            .with_run_function(my_run)
            .with_setup_function(my_setup)
            .build()
        )

        # Setup
        tool.setup(config_path="/etc/config")
        assert setup_called == [("analyze", {"config_path": "/etc/config"})]

        # Run
        result = tool.run(input_file="data.csv")
        assert result == 0
        assert run_called == [("analyze", {"input_file": "data.csv"})]

    def test_chained_method_calls(self):
        """Test all methods return builder for chaining."""
        func = Mock()
        parent = Mock()

        # All methods should be chainable
        tool = (
            ToolBuilder("mytool")
            .with_alias("mt")
            .with_aliases("m", "tool")
            .with_help("Help")
            .with_description("Description")
            .with_argument("--flag", action="store_true")
            .with_run_function(func)
            .with_setup_function(func)
            .with_parent(parent)
            .with_group_default("help")
            .build()
        )

        assert tool.name == "mytool"
        assert "mt" in tool.config.aliases
        assert "m" in tool.config.aliases

    def test_function_tool_integration(self):
        """Test FunctionTool works correctly."""
        results = []

        def process_data(input_file=None, output_file=None, **kwargs):
            results.append({"in": input_file, "out": output_file})
            return 0

        tool = FunctionTool(
            name="process",
            func=process_data,
            aliases=["p"],
            help_text="Process data files",
        )

        result = tool.run(input_file="in.csv", output_file="out.csv")

        assert result == 0
        assert results == [{"in": "in.csv", "out": "out.csv"}]
