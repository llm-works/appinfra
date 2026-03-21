"""
Tool group management for organizing related tools and commands.

This module provides ToolGroup class for managing collections of related tools
and commands within a parent tool, enabling hierarchical command structures.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast

from ..errors import DupToolError, MissingRunFuncError, UndefNameError
from ..server.base import get_server_routes

if TYPE_CHECKING:
    from .base import Tool


class ToolGroup:
    """
    Manages a group of related tools and commands within a parent tool.

    Provides functionality to organize tools hierarchically, handle command
    routing, and manage both tool-based and function-based commands.
    """

    def __init__(self, parent: Any, cmd_var: str, default: str | None = None):
        """
        Initialize the tool group.

        Args:
            parent: Parent tool instance
            cmd_var: Command variable name for argument parsing
            default: Default command to run if none specified
        """
        self._parent = parent
        self._cmd_var = cmd_var
        self._default = default
        self._tools: dict[str, Tool] = {}
        self._funcs: dict[str, Callable] = {}

    @property
    def lg(self) -> Any:
        """Get the logger from the parent tool."""
        return self._parent.lg

    def _set_tool(self, tool: Tool) -> None:
        """Register a tool in the group."""
        self._tools[tool.name] = tool

    def _set_func(self, key: str, func: Callable) -> None:
        """Register a command function."""
        self._funcs[key] = func

    def _check_new_tool(self, tool: Tool) -> None:
        """
        Validate a new tool before registration.

        Args:
            tool: Tool to validate

        Raises:
            UndefNameError: If tool has no name
            DupToolError: If tool name already exists
        """
        if tool.name is None:
            raise UndefNameError(tool=tool)
        if tool.name in self._tools:
            raise DupToolError(tool)

    def _set_default(self, parser: Any) -> None:
        """Set default command for argument parser."""
        if self._default is None:
            return
        kwargs = {self._cmd_var: self._default}
        parser.set_defaults(**kwargs)

    def add_tool(self, tool: Tool, run_func: Callable | None = None) -> Tool:
        """
        Add a tool to the group with optional custom run function.

        Args:
            tool: Tool instance to add
            run_func: Optional custom function to run instead of tool.run()

        Returns:
            Tool: The added tool instance
        """
        self._check_new_tool(tool)
        self._set_tool(tool)
        if run_func is not None:
            self._set_func(tool.name, run_func)
        return tool

    def get_tool(self, name: str) -> Tool:
        """Get a tool by name."""
        if name not in self._tools:
            raise KeyError(f"Tool '{name}' not found in group")
        return self._tools[name]

    def add_tool_args(self, parser: Any) -> Any:
        """Add argument parsers for tools in the group."""
        subs = parser.add_subparsers(dest=self._cmd_var)
        for tool in self._tools.values():
            args, kwargs = tool.cmd
            kwargs |= {"formatter_class": parser.formatter_class}
            tool.set_args(subs.add_parser(*args, **kwargs))
        return subs

    def add_cmd(self, subs: Any, *args: Any, **kwargs: Any) -> Any:
        """Add a command function to the group."""
        run_func = kwargs.pop("run_func", None)
        if run_func is None:
            raise MissingRunFuncError(args[0])

        self._set_func(args[0], run_func)

        if "aliases" in kwargs:
            for alias in kwargs["aliases"]:
                if alias in self._funcs:
                    raise ValueError(f"Alias '{alias}' already registered")
                self._set_func(alias, run_func)

        return subs.add_parser(*args, **kwargs)

    def finalize_args(self, parser: Any) -> None:
        """Finalize argument parser setup."""
        self._set_default(parser)

    def _is_tool_selected(self, args: Any, tool: Tool) -> bool:
        """Check if a tool is selected by the arguments."""
        arg = getattr(args, self._cmd_var, None)
        if arg is None:
            return False

        cmd_args, cmd_kwargs = tool.cmd
        return arg in cmd_args or (
            "aliases" in cmd_kwargs and arg in cmd_kwargs["aliases"]
        )

    def run(self, **kwargs: Any) -> int:
        """
        Run the selected tool or command.

        Returns:
            int: Exit code (0 for success, 127 for command not found, or tool's exit code)
        """
        # First check for tool execution
        for tool in self._tools.values():
            run, result = self._check_run_tool(tool, **kwargs)
            if run:
                assert result is not None  # _check_run_tool returns int when run=True
                return result

        # Then check for function execution
        args = self._parent.trace_attr("args")
        cmd = getattr(args, self._cmd_var, None)

        # No subcommand provided - show help
        if cmd is None:
            if self._parent.arg_prs:
                self._parent.arg_prs.print_help()
            return 0

        if cmd in self._funcs:
            self.lg.trace("running cmd...", extra={"cmd": cmd})
            result = cast(int, self._funcs[cmd]())
            self.lg.debug("cmd completed", extra={"cmd": cmd})
            return result

        # No command found - use exit code 127 (command not found, Unix convention)
        self.lg.error("command not found", extra={"command": cmd})
        return 127

    def _check_run_tool(self, tool: Tool, **kwargs: Any) -> tuple[bool, int | None]:
        """Check if a tool should be run and execute it."""
        if not self._is_tool_selected(self._parent.args, tool):
            return False, None

        self.lg.debug("running subtool...", extra={"tool": tool.name})

        if tool.name in self._funcs:
            self.lg.trace2("using passed run func", extra={"tool": tool.name})
            result = self._funcs[tool.name]()
        else:
            self.lg.trace2("using tool run func", extra={"tool": tool.name})
            result = tool.run(**kwargs)

        self.lg.debug("subtool completed", extra={"tool": tool.name})
        return True, result

    def get_server_routes(self) -> Any:
        """Get server routes from tools in the group."""
        return get_server_routes(list(self._tools.values()))
