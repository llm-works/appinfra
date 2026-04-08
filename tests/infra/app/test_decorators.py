"""
Tests for app/decorators.py.

Tests key functionality including:
- Helper functions for tool class generation
- ToolFunction container class
- DecoratorAPI class
- Tool registration via decorators
- Argument handling
- Lifecycle hooks
- Subtool support
"""

import warnings
from unittest.mock import Mock, patch

import pytest

from appinfra.app.decorators import (
    DecoratorAPI,
    ToolFunction,
    _apply_pending_arguments,
    _build_tool_config,
    _execute_tool_function,
    _handle_subtools,
    _normalize_return_value,
    _register_tool_arguments,
    _register_tool_with_target,
    _run_configure_hook,
    _run_setup_hook,
    _set_decorated_tool_metadata,
)
from appinfra.app.tools.base import ToolConfig

# =============================================================================
# Test Helper Functions
# =============================================================================


@pytest.mark.unit
class TestBuildToolConfig:
    """Test _build_tool_config helper."""

    def test_creates_tool_config_from_tool_function(self):
        """Test creates ToolConfig with all metadata."""
        func = Mock(__name__="test_func", __doc__="Test doc")
        tool_func = ToolFunction(
            func=func,
            name="test-tool",
            help_text="Test help",
            description="Test description",
            aliases=["t", "test"],
        )

        config = _build_tool_config(tool_func)

        assert isinstance(config, ToolConfig)
        assert config.name == "test-tool"
        assert config.help_text == "Test help"
        assert config.description == "Test description"
        assert config.aliases == ["t", "test"]


@pytest.mark.unit
class TestRegisterToolArguments:
    """Test _register_tool_arguments helper."""

    def test_registers_arguments_with_parser(self):
        """Test adds all arguments to parser."""
        func = Mock(__name__="test", __doc__="")
        tool_func = ToolFunction(func)
        tool_func.arguments = [
            (("--file",), {"required": True}),
            (("-v", "--verbose"), {"action": "store_true"}),
        ]
        parser = Mock()

        _register_tool_arguments(tool_func, parser)

        assert parser.add_argument.call_count == 2
        parser.add_argument.assert_any_call("--file", required=True)
        parser.add_argument.assert_any_call("-v", "--verbose", action="store_true")


@pytest.mark.unit
class TestRunSetupHook:
    """Test _run_setup_hook helper."""

    def test_calls_setup_hook_when_present(self):
        """Test executes setup hook function."""
        func = Mock(__name__="test", __doc__="")
        tool_func = ToolFunction(func)
        setup_hook = Mock()
        tool_func.setup_hook = setup_hook
        tool_instance = Mock()

        _run_setup_hook(tool_func, tool_instance, {"key": "value"})

        setup_hook.assert_called_once_with(tool_instance, key="value")

    def test_does_nothing_when_no_hook(self):
        """Test does nothing when no setup hook."""
        func = Mock(__name__="test", __doc__="")
        tool_func = ToolFunction(func)
        tool_instance = Mock()

        # Should not raise
        _run_setup_hook(tool_func, tool_instance, {})


@pytest.mark.unit
class TestRunConfigureHook:
    """Test _run_configure_hook helper."""

    def test_calls_configure_hook_when_present(self):
        """Test executes configure hook function."""
        func = Mock(__name__="test", __doc__="")
        tool_func = ToolFunction(func)
        configure_hook = Mock()
        tool_func.configure_hook = configure_hook
        tool_instance = Mock()

        _run_configure_hook(tool_func, tool_instance)

        configure_hook.assert_called_once_with(tool_instance)

    def test_does_nothing_when_no_hook(self):
        """Test does nothing when no configure hook."""
        func = Mock(__name__="test", __doc__="")
        tool_func = ToolFunction(func)
        tool_instance = Mock()

        # Should not raise
        _run_configure_hook(tool_func, tool_instance)


@pytest.mark.unit
class TestNormalizeReturnValue:
    """Test _normalize_return_value helper."""

    def test_returns_zero_for_none(self):
        """Test returns 0 when result is None."""
        result = _normalize_return_value(None, "test")
        assert result == 0

    def test_returns_int_as_is(self):
        """Test returns int result unchanged."""
        assert _normalize_return_value(0, "test") == 0
        assert _normalize_return_value(1, "test") == 1
        assert _normalize_return_value(42, "test") == 42

    def test_warns_and_returns_zero_for_other_types(self):
        """Test warns and returns 0 for non-int, non-None."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = _normalize_return_value("success", "test-tool")

            assert result == 0
            assert len(w) == 1
            assert "test-tool" in str(w[0].message)
            assert "str" in str(w[0].message)


@pytest.mark.unit
class TestExecuteToolFunction:
    """Test _execute_tool_function helper."""

    def test_executes_function_and_normalizes_result(self):
        """Test executes tool function and normalizes return value."""
        func = Mock(__name__="test", __doc__="", return_value=0)
        tool_func = ToolFunction(func)
        tool_instance = Mock()

        result = _execute_tool_function(tool_func, tool_instance, {})

        func.assert_called_once_with(tool_instance)
        assert result == 0

    def test_handles_subtools_when_present(self):
        """Test delegates to subtool handler when subtools exist."""
        func = Mock(__name__="test", __doc__="")
        tool_func = ToolFunction(func)

        # Add a subtool
        subtool_func = Mock(__name__="sub", __doc__="")
        tool_func.subtools = [ToolFunction(subtool_func)]

        tool_instance = Mock()
        tool_instance.group = Mock()
        tool_instance.group.run.return_value = 42

        with patch(
            "appinfra.app.decorators._handle_subtools", return_value=42
        ) as mock_handle:
            result = _execute_tool_function(tool_func, tool_instance, {"key": "val"})

        mock_handle.assert_called_once_with(tool_func, tool_instance, {"key": "val"})
        assert result == 42


@pytest.mark.unit
class TestHandleSubtools:
    """Test _handle_subtools helper."""

    def test_executes_group_run(self):
        """Test delegates to group.run()."""
        parent_func = Mock(__name__="parent", __doc__="")
        tool_func = ToolFunction(parent_func)
        tool_func.subtools = [Mock()]  # Has subtools

        tool_instance = Mock()
        tool_instance.group = Mock()
        tool_instance.group.run.return_value = 42

        result = _handle_subtools(tool_func, tool_instance, {"key": "val"})

        tool_instance.group.run.assert_called_once_with(key="val")
        assert result == 42


@pytest.mark.unit
class TestSetDecoratedToolMetadata:
    """Test _set_decorated_tool_metadata helper."""

    def test_sets_class_metadata(self):
        """Test sets name, qualname, module, doc on class."""
        func = Mock(__name__="test", __doc__="Test doc", __module__="my.module")
        tool_func = ToolFunction(func, name="my-tool", description="My description")

        class TestClass:
            pass

        _set_decorated_tool_metadata(TestClass, tool_func)

        assert TestClass.__name__ == "My_ToolTool"
        assert TestClass.__qualname__ == "My_ToolTool"
        assert TestClass.__module__ == "my.module"
        assert TestClass.__doc__ == "My description"


@pytest.mark.unit
class TestApplyPendingArguments:
    """Test _apply_pending_arguments helper."""

    def test_applies_arguments_from_function_attribute(self):
        """Test applies _tool_arguments from function."""
        func = Mock(__name__="test", __doc__="")
        func._tool_arguments = [
            (("--file",), {"required": True}),
            (("--verbose",), {"action": "store_true"}),
        ]
        tool_func = ToolFunction(func)

        _apply_pending_arguments(tool_func, func)

        # Arguments should be reversed and added
        assert len(tool_func.arguments) == 2

    def test_does_nothing_when_no_pending_arguments(self):
        """Test does nothing when function has no _tool_arguments."""
        func = Mock(__name__="test", __doc__="", spec=["__name__", "__doc__"])
        tool_func = ToolFunction(func)

        _apply_pending_arguments(tool_func, func)

        assert tool_func.arguments == []


@pytest.mark.unit
class TestRegisterToolWithTarget:
    """Test _register_tool_with_target helper."""

    def test_registers_with_app_add_tool(self):
        """Test registers tool using add_tool method."""
        target = Mock(spec=["add_tool"])
        tool = Mock()

        _register_tool_with_target(target, tool)

        target.add_tool.assert_called_once_with(tool)

    def test_raises_type_error_for_unknown_target(self):
        """Test raises TypeError for unsupported target type."""
        target = Mock(spec=[])  # No add_tool method
        tool = Mock()

        with pytest.raises(TypeError) as exc_info:
            _register_tool_with_target(target, tool)

        assert "Cannot register tool" in str(exc_info.value)


# =============================================================================
# Test ToolFunction Class
# =============================================================================


@pytest.mark.unit
class TestToolFunctionInit:
    """Test ToolFunction initialization."""

    def test_basic_initialization(self):
        """Test initializes with function and defaults."""

        def my_func():
            pass

        tool_func = ToolFunction(my_func)

        assert tool_func.func is my_func
        assert tool_func.name == "my-func"  # _ replaced with -
        assert tool_func.arguments == []
        assert tool_func.subtools == []

    def test_custom_name_and_metadata(self):
        """Test initializes with custom name and metadata."""

        def test():
            """Docstring here."""
            pass

        tool_func = ToolFunction(
            test,
            name="custom-name",
            help_text="Custom help",
            description="Custom desc",
            aliases=["cn"],
        )

        assert tool_func.name == "custom-name"
        assert tool_func.help_text == "Custom help"
        assert tool_func.description == "Custom desc"
        assert tool_func.aliases == ["cn"]

    def test_extracts_help_from_docstring(self):
        """Test extracts help text from docstring first line."""

        def my_tool():
            """This is the help text.

            More detailed description here.
            """
            pass

        tool_func = ToolFunction(my_tool)

        assert tool_func.help_text == "This is the help text."


@pytest.mark.unit
class TestToolFunctionExtractHelp:
    """Test ToolFunction._extract_help static method."""

    def test_returns_empty_for_no_docstring(self):
        """Test returns empty string when no docstring."""
        func = Mock(__doc__=None)
        result = ToolFunction._extract_help(func)
        assert result == ""

    def test_returns_first_line(self):
        """Test returns first non-empty line of docstring."""
        func = Mock(__doc__="First line.\nSecond line.")
        result = ToolFunction._extract_help(func)
        assert result == "First line."

    def test_skips_empty_lines(self):
        """Test skips leading empty lines."""
        func = Mock(__doc__="\n\n  Actual help text.\n")
        result = ToolFunction._extract_help(func)
        assert result == "Actual help text."


@pytest.mark.unit
class TestToolFunctionArgument:
    """Test ToolFunction.argument method."""

    def test_adds_argument(self):
        """Test adds argument to arguments list."""
        func = Mock(__name__="test", __doc__="")
        tool_func = ToolFunction(func)

        result = tool_func.argument("--file", required=True, help="Input file")

        assert result is tool_func  # Returns self for chaining
        assert len(tool_func.arguments) == 1
        assert tool_func.arguments[0] == (
            ("--file",),
            {"required": True, "help": "Input file"},
        )

    def test_chaining_multiple_arguments(self):
        """Test can chain multiple argument calls."""
        func = Mock(__name__="test", __doc__="")
        tool_func = ToolFunction(func)

        tool_func.argument("--file").argument("--verbose").argument("--output")

        assert len(tool_func.arguments) == 3


@pytest.mark.unit
class TestToolFunctionOnSetup:
    """Test ToolFunction.on_setup method."""

    def test_registers_setup_hook(self):
        """Test registers setup hook function."""
        func = Mock(__name__="test", __doc__="")
        tool_func = ToolFunction(func)

        def setup_func(self, **kwargs):
            pass

        result = tool_func.on_setup(setup_func)

        assert result is tool_func
        assert tool_func.setup_hook is setup_func


@pytest.mark.unit
class TestToolFunctionOnConfigure:
    """Test ToolFunction.on_configure method."""

    def test_registers_configure_hook(self):
        """Test registers configure hook function."""
        func = Mock(__name__="test", __doc__="")
        tool_func = ToolFunction(func)

        def configure_func(self):
            pass

        result = tool_func.on_configure(configure_func)

        assert result is tool_func
        assert tool_func.configure_hook is configure_func


@pytest.mark.unit
class TestToolFunctionSubtool:
    """Test ToolFunction.subtool decorator."""

    def test_creates_subtool_function(self):
        """Test subtool decorator creates ToolFunction for subtool."""
        parent_func = Mock(__name__="parent", __doc__="")
        tool_func = ToolFunction(parent_func, name="parent")

        @tool_func.subtool(name="child", help="Child help")
        def child_func(self):
            pass

        assert len(tool_func.subtools) == 1
        assert tool_func.subtools[0].name == "child"
        assert tool_func.subtools[0].help_text == "Child help"


@pytest.mark.unit
class TestToolFunctionToToolClass:
    """Test ToolFunction.to_tool_class method."""

    def test_generates_tool_subclass(self):
        """Test generates proper Tool subclass."""

        def my_tool(self):
            """My tool description."""
            return 0

        tool_func = ToolFunction(my_tool, name="my-tool", help_text="My help")

        tool_class = tool_func.to_tool_class()

        # Should be a class that inherits from Tool
        from appinfra.app.tools.base import Tool

        assert issubclass(tool_class, Tool)

        # Should have proper name
        assert "Tool" in tool_class.__name__

    def test_generated_class_has_correct_config(self):
        """Test generated class creates correct config."""

        def test_func(self):
            return 0

        tool_func = ToolFunction(test_func, name="test", help_text="Test help")

        tool_class = tool_func.to_tool_class()
        tool = tool_class()

        assert tool.config.name == "test"
        assert tool.config.help_text == "Test help"


# =============================================================================
# Test DecoratorAPI Class
# =============================================================================


@pytest.mark.unit
class TestDecoratorAPIInit:
    """Test DecoratorAPI initialization."""

    def test_stores_target(self):
        """Test stores target reference."""
        target = Mock()
        api = DecoratorAPI(target)

        assert api._target is target
        assert api._tool_functions == []


@pytest.mark.unit
class TestDecoratorAPITool:
    """Test DecoratorAPI.tool decorator."""

    def test_creates_and_registers_tool(self):
        """Test tool decorator creates and registers tool."""
        target = Mock(spec=["add_tool"])
        api = DecoratorAPI(target)

        @api.tool(name="test", help="Test help")
        def test_func(self):
            return 0

        # Should register tool with target
        target.add_tool.assert_called_once()

        # Should return ToolFunction
        assert isinstance(test_func, ToolFunction)
        assert test_func.name == "test"


@pytest.mark.unit
class TestDecoratorAPIArgument:
    """Test DecoratorAPI.argument decorator."""

    def test_argument_on_tool_function(self):
        """Test argument decorator on ToolFunction."""
        target = Mock(spec=["add_tool"])
        api = DecoratorAPI(target)

        func = Mock(__name__="test", __doc__="")
        tool_func = ToolFunction(func)

        result = api.argument("--file", required=True)(tool_func)

        assert result is tool_func
        assert len(tool_func.arguments) == 1

    def test_argument_on_regular_function(self):
        """Test argument decorator on regular function (before @tool)."""
        target = Mock(spec=["add_tool"])
        api = DecoratorAPI(target)

        def my_func():
            pass

        result = api.argument("--file", required=True)(my_func)

        assert result is my_func
        assert hasattr(my_func, "_tool_arguments")
        assert len(my_func._tool_arguments) == 1

    def test_stacking_arguments(self):
        """Test stacking multiple argument decorators."""
        target = Mock(spec=["add_tool"])
        api = DecoratorAPI(target)

        def my_func():
            pass

        result = api.argument("--file")(my_func)
        result = api.argument("--verbose")(result)

        assert len(my_func._tool_arguments) == 2


@pytest.mark.unit
class TestDecoratorAPIGetToolFunctions:
    """Test DecoratorAPI.get_tool_functions method."""

    def test_returns_copy_of_tool_functions(self):
        """Test returns copy of registered tool functions."""
        target = Mock(spec=["add_tool"])
        api = DecoratorAPI(target)

        @api.tool(name="test1")
        def func1(self):
            return 0

        @api.tool(name="test2")
        def func2(self):
            return 0

        result = api.get_tool_functions()

        assert len(result) == 2
        # Should be a copy
        result.append(Mock())
        assert len(api._tool_functions) == 2


# =============================================================================
# Integration Tests
# =============================================================================


@pytest.mark.integration
class TestDecoratorIntegration:
    """Integration tests for decorator-based tool creation."""

    def test_full_tool_creation_workflow(self):
        """Test complete workflow of creating tool via decorators."""
        target = Mock(spec=["add_tool"])
        api = DecoratorAPI(target)

        @api.tool(name="analyze", help="Analyze data", aliases=["a"])
        def analyze(self):
            """Analyze data files."""
            return 0

        # Verify tool was registered
        target.add_tool.assert_called_once()
        registered_tool = target.add_tool.call_args[0][0]

        # Verify tool config
        assert registered_tool.config.name == "analyze"
        assert registered_tool.config.help_text == "Analyze data"
        assert registered_tool.config.aliases == ["a"]

    def test_tool_with_arguments(self):
        """Test tool with argument decorators."""
        target = Mock(spec=["add_tool"])
        api = DecoratorAPI(target)

        @api.tool(name="process")
        @api.argument("--file", required=True)
        @api.argument("--verbose", "-v", action="store_true")
        def process(self):
            return 0

        # Arguments should be registered
        assert len(process.arguments) == 2

    def test_tool_with_lifecycle_hooks(self):
        """Test tool with setup and configure hooks."""
        target = Mock(spec=["add_tool"])
        api = DecoratorAPI(target)

        @api.tool(name="test")
        def test_tool(self):
            return 0

        @test_tool.on_setup
        def setup(self, **kwargs):
            pass

        @test_tool.on_configure
        def configure(self):
            pass

        assert test_tool.setup_hook is not None
        assert test_tool.configure_hook is not None

    def test_tool_with_subtools(self):
        """Test tool with subtool hierarchy."""
        target = Mock(spec=["add_tool"])
        api = DecoratorAPI(target)

        @api.tool(name="db")
        def db_tool(self):
            pass

        @db_tool.subtool(name="migrate", help="Run migrations")
        def migrate(self):
            return 0

        @db_tool.subtool(name="seed", help="Seed database")
        def seed(self):
            return 0

        assert len(db_tool.subtools) == 2
        assert db_tool.subtools[0].name == "migrate"
        assert db_tool.subtools[1].name == "seed"
