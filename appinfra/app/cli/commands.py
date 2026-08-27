# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Command handling for CLI applications.

This module provides command routing and execution functionality.
"""

from typing import Any

from ..errors import CommandError


class CommandHandler:
    """Handles command routing and execution."""

    def __init__(self, application: Any) -> None:
        """
        Initialize the command handler.

        Args:
            application: The application instance
        """
        self.application = application
        self._subparsers: Any | None = None

    def setup_subcommands(self) -> None:
        """Set up subcommand parsers for registered tools."""
        if not self.application.registry.list_tools():
            return

        self._subparsers = self.application.parser.add_subparsers(dest="tool")

        for tool_name in self.application.registry.list_tools():
            tool = self.application.registry.get_tool(tool_name)
            if not tool:
                continue

            cmd_args, cmd_kwargs = tool.cmd
            cmd_kwargs |= {"formatter_class": self.application.parser.formatter_class}

            sub_parser = self._subparsers.add_parser(*cmd_args, **cmd_kwargs)
            tool.set_args(sub_parser)

        # Set main tool as argparse default (runs when no subcommand specified)
        if self.application._main_tool:
            main_tool = self.application.registry.get_tool(self.application._main_tool)
            if main_tool:
                # Add main tool's args to root parser so they work without subcommand.
                # Skip positional args to avoid conflict with subcommand parsing -
                # positional args on root would be consumed before the subcommand name.
                main_tool.set_args(self.application.parser.parser, skip_positional=True)
            self.application.parser.parser.set_defaults(
                tool=self.application._main_tool
            )

    def execute_command(self, tool_name: str, **kwargs: Any) -> int:
        """
        Execute a command.

        Args:
            tool_name: Name of the tool to execute
            **kwargs: Additional execution parameters

        Returns:
            int: Exit code

        Raises:
            CommandError: If command execution fails
        """
        tool = self.application.registry.get_tool(tool_name)
        if not tool:
            raise CommandError(f"Tool '{tool_name}' not found")

        try:
            result = tool.run(**kwargs)
            return int(result) if result is not None else 0
        except Exception as e:
            raise CommandError(f"Failed to execute tool '{tool_name}': {e}") from e

    def list_commands(self) -> dict[str, str]:
        """
        List available commands with their descriptions.

        Returns:
            Dict mapping command names to descriptions
        """
        commands = {}
        for tool_name in self.application.registry.list_tools():
            tool = self.application.registry.get_tool(tool_name)
            if tool:
                cmd_args, cmd_kwargs = tool.cmd
                description = cmd_kwargs.get("help", f"{tool_name} tool")
                commands[tool_name] = description
        return commands
