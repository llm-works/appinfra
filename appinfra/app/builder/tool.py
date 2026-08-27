# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tool builder for the AppBuilder framework.

This module provides a fluent API for building tools with subcommands,
arguments, and custom functionality.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Self, cast

from ..tools.base import Tool, ToolConfig
from ..tracing.traceable import Traceable


class ToolBuilder:
    """Builder for creating tools with fluent API."""

    def __init__(self, name: str):
        """
        Initialize the tool builder.

        Args:
            name: Tool name
        """
        self._name = name
        self._aliases: list[str] = []
        self._help_text = ""
        self._description = ""
        self._args: list[tuple] = []
        self._subcommands: list[tuple[str, ToolBuilder]] = []
        self._run_func: Callable | None = None
        self._setup_func: Callable | None = None
        self._parent: Traceable | None = None
        self._group_default: str | None = None

    def with_alias(self, alias: str) -> Self:
        """Add an alias for the tool."""
        self._aliases.append(alias)
        return self

    def with_aliases(self, *aliases: str) -> Self:
        """Add multiple aliases for the tool."""
        self._aliases.extend(aliases)
        return self

    def with_help(self, text: str) -> Self:
        """Set the help text for the tool."""
        self._help_text = text
        return self

    def with_description(self, desc: str) -> Self:
        """Set the description for the tool."""
        self._description = desc
        return self

    def with_argument(self, *args: Any, **kwargs: Any) -> Self:
        """Add a command-line argument to the tool."""
        self._args.append((args, kwargs))
        return self

    def with_subcommand(self, name: str, builder: ToolBuilder) -> Self:
        """Add a subcommand to the tool."""
        self._subcommands.append((name, builder))
        return self

    def with_run_function(self, func: Callable) -> Self:
        """Set the run function for the tool."""
        self._run_func = func
        return self

    def with_setup_function(self, func: Callable) -> Self:
        """Set the setup function for the tool."""
        self._setup_func = func
        return self

    def with_parent(self, parent: Traceable) -> Self:
        """Set the parent for the tool."""
        self._parent = parent
        return self

    def with_group_default(self, default: str) -> Self:
        """Set the default subcommand for tool groups."""
        self._group_default = default
        return self

    def build(self) -> Tool:
        """Build the tool with all configured options."""
        # Create tool configuration
        config = ToolConfig(
            name=self._name,
            aliases=self._aliases,
            help_text=self._help_text,
            description=self._description,
        )

        # Create the tool
        tool = BuiltTool(
            parent=self._parent,
            config=config,
            run_func=self._run_func,
            setup_func=self._setup_func,
            group_default=self._group_default,
        )

        # Add arguments
        for args, kwargs in self._args:
            tool.add_argument(*args, **kwargs)

        # Add subcommands
        for subcommand_name, subcommand_builder in self._subcommands:
            subcommand_tool = subcommand_builder.with_parent(tool).build()
            tool.add_tool(subcommand_tool)

        return tool


class BuiltTool(Tool):
    """Tool implementation built by ToolBuilder."""

    def __init__(
        self,
        parent: Traceable | None = None,
        config: ToolConfig | None = None,
        run_func: Callable | None = None,
        setup_func: Callable | None = None,
        group_default: str | None = None,
    ):
        """
        Initialize the built tool.

        Args:
            parent: Parent traceable object
            config: Tool configuration
            run_func: Custom run function
            setup_func: Custom setup function
            group_default: Default subcommand for groups
        """
        super().__init__(parent, config)
        self._run_func = run_func
        self._setup_func = setup_func
        self._group_default = group_default
        self._custom_args: list[tuple] = []
        self._sub_tools: list[Tool] = []

    @property
    def name(self) -> str:
        """Get the tool name from config."""
        return self.config.name if self.config else "unknown"

    def add_argument(self, *args: Any, **kwargs: Any) -> None:
        """Add a command-line argument."""
        self._custom_args.append((args, kwargs))

    def add_tool(self, tool: Tool) -> None:  # type: ignore[override]
        """Add a sub-tool."""
        self._sub_tools.append(tool)
        if self._group is None:
            self.create_group(self._group_default)
        assert self._group is not None  # create_group always sets _group
        self._group.add_tool(tool)

    def add_args(self, parser: Any) -> None:
        """Add arguments to the parser."""
        for args, kwargs in self._custom_args:
            parser.add_argument(*args, **kwargs)

    def setup(self, **kwargs: Any) -> None:
        """Set up the tool."""
        super().setup(**kwargs)

        # Call custom setup function if provided
        if self._setup_func:
            self._setup_func(self, **kwargs)

        # Set up sub-tools
        for sub_tool in self._sub_tools:
            sub_tool.setup(**kwargs)

    def run(self, **kwargs: Any) -> int:
        """Run the tool."""
        if self._run_func:
            return cast(int, self._run_func(self, **kwargs))
        elif self._group:
            return self._group.run(**kwargs)
        else:
            # Default behavior - just log that the tool ran
            self.lg.info(f"running {self.name}...")
            return 0


class FunctionTool(Tool):
    """Tool that wraps a simple function."""

    def __init__(
        self,
        name: str,
        func: Callable,
        parent: Traceable | None = None,
        aliases: list[str] | None = None,
        help_text: str = "",
        description: str = "",
    ):
        """
        Initialize the function tool.

        Args:
            name: Tool name
            func: Function to execute
            parent: Parent traceable object
            aliases: Tool aliases
            help_text: Help text
            description: Tool description
        """
        config = ToolConfig(
            name=name,
            aliases=aliases or [],
            help_text=help_text,
            description=description,
        )
        super().__init__(parent, config)
        self._func = func

    def run(self, **kwargs: Any) -> int:
        """Run the wrapped function."""
        return cast(int, self._func(**kwargs))


def create_function_tool(name: str, func: Callable, **kwargs: Any) -> ToolBuilder:
    """
    Create a tool builder for a simple function.

    Args:
        name: Tool name
        func: Function to execute
        **kwargs: Additional tool configuration

    Returns:
        ToolBuilder: Configured tool builder
    """
    builder = ToolBuilder(name)
    builder.with_run_function(lambda self, **kw: func(**kw))

    if "aliases" in kwargs:
        builder.with_aliases(*kwargs["aliases"])
    if "help" in kwargs:
        builder.with_help(kwargs["help"])
    if "description" in kwargs:
        builder.with_description(kwargs["description"])

    return builder


def create_tool_builder(name: str) -> ToolBuilder:
    """
    Create a new tool builder.

    Args:
        name: Name of the tool

    Returns:
        ToolBuilder instance

    Example:
        tool = create_tool_builder("mytool").with_help("My tool").build()
    """
    return ToolBuilder(name)
