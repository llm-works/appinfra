"""
Decorator API for the appinfra.app framework.

This module provides a decorator-based API for creating tools, offering
a more concise syntax while maintaining full compatibility with the
class-based Tool architecture.

The decorators generate proper Tool subclasses, ensuring all framework
features work identically to hand-written Tool classes.

Example:
    @app.tool(name="analyze", help="Analyze data")
    @app.argument('--file', required=True)
    def analyze(self):
        self.lg.info(f"Analyzing {self.args.file}")
        return 0
"""

from __future__ import annotations

import warnings
from collections.abc import Callable
from typing import Any, Self

from .tools.base import Tool, ToolConfig

# Helper functions for tool class generation


def _build_tool_config(tool_func: ToolFunction) -> ToolConfig:
    """
    Create tool configuration from ToolFunction metadata.

    Args:
        tool_func: ToolFunction container with metadata

    Returns:
        ToolConfig instance
    """
    return ToolConfig(
        name=tool_func.name,
        help_text=tool_func.help_text,
        description=tool_func.description,
        aliases=tool_func.aliases,
    )


def _register_tool_arguments(tool_func: ToolFunction, parser) -> None:
    """
    Register all command-line arguments from @argument decorators.

    Args:
        tool_func: ToolFunction with accumulated arguments
        parser: ArgumentParser to add arguments to
    """
    for args, kwargs in tool_func.arguments:
        parser.add_argument(*args, **kwargs)


def _run_setup_hook(tool_func: ToolFunction, tool_instance, kwargs: dict) -> None:
    """
    Execute custom setup hook if provided.

    Args:
        tool_func: ToolFunction with optional setup hook
        tool_instance: Tool instance being set up
        kwargs: Setup keyword arguments
    """
    if tool_func.setup_hook:
        tool_func.setup_hook(tool_instance, **kwargs)


def _run_configure_hook(tool_func: ToolFunction, tool_instance) -> None:
    """
    Execute custom configure hook if provided.

    Args:
        tool_func: ToolFunction with optional configure hook
        tool_instance: Tool instance being configured
    """
    if tool_func.configure_hook:
        tool_func.configure_hook(tool_instance)


def _execute_tool_function(tool_func: ToolFunction, tool_instance, kwargs: dict) -> int:
    """
    Execute the tool function with proper handling of subtools and return values.

    Args:
        tool_func: ToolFunction to execute
        tool_instance: Tool instance (provides self context)
        kwargs: Execution keyword arguments

    Returns:
        Exit code (0 for success, non-zero for failure)
    """
    # Handle subtools if present
    if tool_func.subtools:
        return _handle_subtools(tool_func, tool_instance, kwargs)

    # Execute the original function
    result = tool_func.func(tool_instance)

    # Normalize return value to exit code
    return _normalize_return_value(result, tool_func.name)


def _setup_subtools(tool_func: ToolFunction, tool_instance) -> None:
    """
    Set up subtool hierarchy during tool initialization.

    Args:
        tool_func: ToolFunction with subtools
        tool_instance: Parent tool instance
    """
    if not tool_func.subtools:
        return

    # Create tool group for subcommands
    tool_instance.create_group(default=tool_func.default_subtool)

    # Register each subtool
    for subtool_func in tool_func.subtools:
        subtool_class = subtool_func.to_tool_class()
        subtool = subtool_class(parent=tool_instance)
        tool_instance.add_tool(subtool)


def _handle_subtools(tool_func: ToolFunction, tool_instance, kwargs: dict) -> int:
    """
    Execute subtool hierarchy.

    Args:
        tool_func: ToolFunction with subtools
        tool_instance: Parent tool instance
        kwargs: Execution keyword arguments

    Returns:
        Exit code from selected subtool
    """
    # Delegate execution to selected subtool
    return tool_instance.group.run(**kwargs)


def _normalize_return_value(result: Any, tool_name: str) -> int:
    """
    Convert tool function return value to valid exit code.

    Args:
        result: Return value from tool function
        tool_name: Tool name (for warning messages)

    Returns:
        Exit code: 0 for None, result if int, 0 with warning otherwise
    """
    if result is None:
        return 0

    if isinstance(result, int):
        return result

    # Warn about unexpected return type
    warnings.warn(
        f"Tool '{tool_name}' returned {type(result).__name__} "
        f"({repr(result)}), expected int or None. "
        f"Treating as exit code 0. "
        f"Please return an int exit code (0 for success, non-zero for failure) "
        f"or None (treated as 0).",
        UserWarning,
        stacklevel=2,
    )
    return 0


def _create_decorated_tool_class(tool_func: ToolFunction) -> type:
    """Create a Tool subclass from a ToolFunction."""

    class DecoratedTool(Tool):
        def __init__(self, parent=None):
            super().__init__(parent, self._create_config())

        def _create_config(self) -> ToolConfig:
            return _build_tool_config(tool_func)

        def set_args(self, parser, skip_positional: bool = False) -> None:
            _setup_subtools(tool_func, self)
            super().set_args(parser, skip_positional=skip_positional)

        def add_args(self, parser) -> None:
            _register_tool_arguments(tool_func, parser)
            super().add_args(parser)

        def setup(self, **kwargs) -> None:
            _run_setup_hook(tool_func, self, kwargs)
            super().setup(**kwargs)

        def configure(self) -> None:
            _run_configure_hook(tool_func, self)
            super().configure()

        def run(self, **kwargs) -> int:
            return _execute_tool_function(tool_func, self, kwargs)

    return DecoratedTool


def _set_decorated_tool_metadata(tool_class: type, tool_func: ToolFunction) -> None:
    """
    Set proper class metadata for generated Tool subclass.

    Args:
        tool_class: Generated Tool subclass
        tool_func: ToolFunction with metadata
    """
    class_name = tool_func.name.replace("-", "_").title() + "Tool"
    tool_class.__name__ = class_name
    tool_class.__qualname__ = class_name
    tool_class.__module__ = tool_func.func.__module__
    tool_class.__doc__ = tool_func.description


# Helper functions for DecoratorAPI.tool()


def _apply_pending_arguments(tool_func: ToolFunction, func: Callable) -> None:
    """
    Apply @argument decorators that were applied before @tool decorator.

    Args:
        tool_func: ToolFunction to add arguments to
        func: Original function with _tool_arguments attribute
    """
    if hasattr(func, "_tool_arguments"):
        # Reverse list so arguments appear in natural reading order
        for arg_args, arg_kwargs in reversed(func._tool_arguments):
            tool_func.argument(*arg_args, **arg_kwargs)


def _create_tool_instance_from_func(tool_func: ToolFunction) -> Tool:
    """
    Convert ToolFunction to Tool class and instantiate.

    Args:
        tool_func: ToolFunction to convert

    Returns:
        Tool instance
    """
    tool_class = tool_func.to_tool_class()
    return tool_class()


def _register_tool_with_target(target: Any, tool_instance: Tool) -> None:
    """
    Register tool instance with an App.

    Args:
        target: App instance
        tool_instance: Tool to register

    Raises:
        TypeError: If target does not support add_tool()
    """
    if hasattr(target, "add_tool"):
        target.add_tool(tool_instance)
    else:
        raise TypeError(
            f"Cannot register tool with {type(target).__name__}. "
            f"Expected App instance with add_tool() method."
        )


class ToolFunction:
    """
    Container for a decorated function with its metadata.

    Stores the original function plus all decorator metadata (arguments,
    lifecycle hooks, subtools) before converting to a Tool class.

    This class accumulates decorator metadata through chained decorators,
    then generates a proper Tool subclass via to_tool_class().
    """

    def __init__(
        self,
        func: Callable,
        name: str | None = None,
        help_text: str = "",
        description: str = "",
        aliases: list[str] | None = None,
    ):
        """
        Initialize a tool function container.

        Args:
            func: The decorated function
            name: Tool name (defaults to function name with _ -> -)
            help_text: Short help text (defaults to first line of docstring)
            description: Long description (defaults to full docstring)
            aliases: List of tool name aliases
        """
        self.func = func
        self.name = name or func.__name__.replace("_", "-")
        self.help_text = help_text or self._extract_help(func)
        self.description = description or (func.__doc__ or "")
        self.aliases = aliases or []

        # Lifecycle hooks
        self.arguments: list[tuple] = []
        self.setup_hook: Callable | None = None
        self.configure_hook: Callable | None = None

        # Subtools for hierarchical commands
        self.subtools: list[ToolFunction] = []
        self.default_subtool: str | None = None

    @staticmethod
    def _extract_help(func: Callable) -> str:
        """Extract short help text from function docstring."""
        if not func.__doc__:
            return ""

        # Get first non-empty line
        lines = func.__doc__.strip().split("\n")
        for line in lines:
            stripped = line.strip()
            if stripped:
                return stripped
        return ""

    def argument(self, *args, **kwargs) -> Self:
        """
        Add a command-line argument to this tool.

        Args are passed directly to argparse.ArgumentParser.add_argument().

        Args:
            *args: Positional arguments for add_argument()
            **kwargs: Keyword arguments for add_argument()

        Returns:
            Self for method chaining
        """
        self.arguments.append((args, kwargs))
        return self

    def on_setup(self, func: Callable) -> Self:
        """
        Register a setup lifecycle hook.

        The setup hook is called when the tool is initialized,
        before run() is executed.

        Args:
            func: Setup function with signature (self, **kwargs)

        Returns:
            Self for method chaining

        Example:
            >>> @app.tool(name="migrate")
            ... def migrate(self):
            ...     self.db.run_migrations()
            ...     return 0
            >>>
            >>> @migrate.on_setup
            ... def setup_db(self, **kwargs):
            ...     self.db = Database(self.config.database.url)
        """
        self.setup_hook = func
        return self

    def on_configure(self, func: Callable) -> Self:
        """
        Register a configure lifecycle hook.

        The configure hook is called after setup, for post-initialization
        configuration.

        Args:
            func: Configure function with signature (self)

        Returns:
            Self for method chaining
        """
        self.configure_hook = func
        return self

    def subtool(
        self,
        name: str | None = None,
        help: str = "",
        aliases: list[str] | None = None,
    ) -> Callable:
        """
        Decorator to add a subtool to this tool.

        Creates a hierarchical command structure where this tool acts
        as a parent with subcommands.

        Example:
            @app.tool(name="db")
            def db_tool(self):
                pass

            @db_tool.subtool(name="migrate")
            def db_migrate(self):
                self.lg.info("Migrating...")

        Args:
            name: Subtool name (defaults to function name)
            help: Short help text
            aliases: List of subtool aliases

        Returns:
            Decorator function
        """

        def decorator(func: Callable) -> ToolFunction:
            subtool_func = ToolFunction(
                func=func,
                name=name,
                help_text=help,
                aliases=aliases,
            )
            # Apply any @argument decorators applied before @subtool
            _apply_pending_arguments(subtool_func, func)
            self.subtools.append(subtool_func)
            return subtool_func

        return decorator

    def to_tool_class(self) -> type:
        """
        Convert this ToolFunction to a proper Tool class.

        Generates a Tool subclass that behaves identically to hand-written
        Tool classes, with all lifecycle hooks and framework integration.

        Returns:
            Tool subclass
        """
        tool_class = _create_decorated_tool_class(self)
        _set_decorated_tool_metadata(tool_class, self)
        return tool_class


class DecoratorAPI:
    """
    Decorator API for the app framework.

    Provides @tool, @argument, and related decorators that generate
    proper Tool classes while offering a simpler syntax.

    This class is instantiated by App to provide decorator methods.

    Example:
        >>> from appinfra.app import App
        >>>
        >>> app = App("myapp")
        >>>
        >>> @app.tool(name="greet", help="Greet someone")
        ... @app.argument("--name", default="World")
        ... def greet(self):
        ...     self.lg.info(f"Hello, {self.args.name}!")
        ...     return 0
        >>>
        >>> app.run()  # CLI: myapp greet --name Alice
    """

    def __init__(self, target: Any):
        """
        Initialize decorator API.

        Args:
            target: App instance to register tools with
        """
        self._target = target
        self._tool_functions: list[ToolFunction] = []

    def tool(
        self,
        name: str | None = None,
        help: str = "",
        description: str = "",
        aliases: list[str] | None = None,
    ) -> Callable:
        """
        Decorator to register a tool from a function.

        The decorated function receives `self` as the first parameter,
        which is the generated Tool instance with full framework access:
        - self.lg: Logger
        - self.config: Configuration
        - self.args: Parsed arguments
        - self.parent: Parent tool (if any)

        Example:
            @app.tool(name="analyze", help="Analyze data")
            @app.argument('--file', required=True)
            def analyze(self):
                self.lg.info(f"Analyzing {self.args.file}")
                db_host = self.config.database.host
                return 0

        Args:
            name: Tool name (defaults to function name with _ -> -)
            help: Short help text (defaults to first line of docstring)
            description: Long description (defaults to full docstring)
            aliases: List of tool name aliases

        Returns:
            Decorator function that returns ToolFunction
        """

        def decorator(func: Callable) -> ToolFunction:
            # Create ToolFunction container
            tool_func = ToolFunction(
                func=func,
                name=name,
                help_text=help,
                description=description,
                aliases=aliases,
            )

            # Apply any @argument decorators applied before @tool
            _apply_pending_arguments(tool_func, func)

            # Convert to Tool class and instantiate
            tool_instance = _create_tool_instance_from_func(tool_func)

            # Register with app
            _register_tool_with_target(self._target, tool_instance)

            # Store ToolFunction for reference
            self._tool_functions.append(tool_func)

            # Return ToolFunction for further chaining (@subtool, etc.)
            return tool_func

        return decorator

    def argument(self, *args, **kwargs) -> Callable:
        """
        Decorator to add command-line argument to a tool.

        Wrapper around argparse.ArgumentParser.add_argument().
        Can be stacked multiple times to add multiple arguments.

        Can be applied before @tool (natural decorator order) or after
        @tool (functional chaining).

        Example (natural decorator order):
            @app.tool()
            @app.argument('--file', required=True, help='Input file')
            @app.argument('--verbose', action='store_true')
            def process(self):
                if self.args.verbose:
                    self.lg.info(f"Processing {self.args.file}")

        Example (functional chaining):
            test = app.tool(name="test")(lambda self: 0)
            test = app.argument('--file')(test)

        Args:
            *args: Positional arguments for add_argument()
            **kwargs: Keyword arguments for add_argument()

        Returns:
            Decorator function
        """

        def decorator(obj):
            if isinstance(obj, ToolFunction):
                # Applied to ToolFunction (functional chaining)
                obj.argument(*args, **kwargs)
                return obj
            else:
                # Applied to regular function (natural decorator order)
                # Store argument metadata on the function
                if not hasattr(obj, "_tool_arguments"):
                    obj._tool_arguments = []
                obj._tool_arguments.append((args, kwargs))
                return obj

        return decorator

    def get_tool_functions(self) -> list[ToolFunction]:
        """
        Get all registered tool functions.

        Returns:
            List of ToolFunction instances
        """
        return self._tool_functions.copy()
