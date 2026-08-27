# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Help generation for CLI applications.

This module provides help generation functionality.
"""

from typing import Any


class HelpGenerator:
    """Generates help content for CLI applications."""

    def __init__(self, application: Any) -> None:
        """
        Initialize the help generator.

        Args:
            application: The application instance
        """
        self.application = application

    def generate_tool_help(self, tool_name: str) -> str | None:
        """
        Generate help text for a specific tool.

        Args:
            tool_name: Name of the tool

        Returns:
            Help text or None if tool not found
        """
        tool = self.application.registry.get_tool(tool_name)
        if not tool:
            return None

        cmd_args, cmd_kwargs = tool.cmd
        help_text = str(cmd_kwargs.get("help", ""))
        description = str(cmd_kwargs.get("description", ""))

        if description:
            return f"{help_text}\n\n{description}"
        return help_text

    def generate_tools_list(self) -> str:
        """
        Generate a list of available tools.

        Returns:
            Formatted list of tools
        """
        tools = []
        self.application.registry.list_aliases()

        for tool_name in self.application.registry.list_tools():
            tool = self.application.registry.get_tool(tool_name)
            if not tool:
                continue

            cmd_args, cmd_kwargs = tool.cmd
            help_text = cmd_kwargs.get("help", f"{tool_name} tool")

            # Add aliases to the description
            tool_aliases = cmd_kwargs.get("aliases", [])
            if tool_aliases:
                alias_str = ", ".join(tool_aliases)
                help_text += f" (aliases: {alias_str})"

            tools.append(f"  {tool_name:<15} {help_text}")

        return "\n".join(tools)

    def generate_usage_examples(self) -> list[str]:
        """
        Generate usage examples.

        Returns:
            List of usage examples
        """
        examples = []
        tool_names = self.application.registry.list_tools()

        if tool_names:
            first_tool = tool_names[0]
            examples.append(f"  {self.application.parser.prog} {first_tool}")

            # Add example with alias if available
            aliases = self.application.registry.list_aliases()
            for alias, tool_name in aliases.items():
                if tool_name == first_tool:
                    examples.append(f"  {self.application.parser.prog} {alias}")
                    break

        return examples
