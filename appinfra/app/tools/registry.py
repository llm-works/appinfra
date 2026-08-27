# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tool registration and discovery.

This module provides centralized tool registration and discovery functionality.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from ..constants import MAX_ALIAS_COUNT, MAX_TOOL_COUNT, MAX_TOOL_NAME_LENGTH
from ..errors import DupToolError, ToolRegistrationError

if TYPE_CHECKING:
    from .base import Tool

# Helper functions for ToolRegistry.register()


def _validate_tool_name(tool_name: str) -> None:
    """Validate tool name format."""
    if not tool_name:
        raise ToolRegistrationError("", "Tool must have a name")

    if len(tool_name) > MAX_TOOL_NAME_LENGTH:
        raise ToolRegistrationError(
            tool_name,
            f"Tool name exceeds maximum length of {MAX_TOOL_NAME_LENGTH} characters",
        )

    if not re.match(r"^[a-z][a-z0-9_-]*$", tool_name):
        raise ToolRegistrationError(
            tool_name,
            "Tool name must start with a lowercase letter and contain only "
            "lowercase letters, numbers, underscores, and hyphens (e.g., 'my-tool', 'tool_1')",
        )


def _check_tool_count_limit(tools_dict: dict, tool_name: str) -> None:
    """Check maximum tool count limit."""
    if len(tools_dict) >= MAX_TOOL_COUNT:
        raise ToolRegistrationError(
            tool_name,
            f"Cannot register tool: maximum tool count ({MAX_TOOL_COUNT}) exceeded",
        )


def _validate_and_register_aliases(
    tool_name: str, aliases: list, aliases_dict: dict
) -> None:
    """Validate and register tool aliases."""
    if len(aliases) > MAX_ALIAS_COUNT:
        raise ToolRegistrationError(
            tool_name,
            f"Tool has {len(aliases)} aliases, exceeding maximum of {MAX_ALIAS_COUNT}",
        )

    for alias in aliases:
        if not re.match(r"^[a-z][a-z0-9_-]*$", alias):
            raise ToolRegistrationError(
                tool_name,
                f"Alias '{alias}' must start with a lowercase letter and contain "
                f"only lowercase letters, numbers, underscores, and hyphens",
            )

        if alias in aliases_dict:
            raise ToolRegistrationError(
                tool_name,
                f"Alias '{alias}' already registered for tool '{aliases_dict[alias]}'",
            )
        aliases_dict[alias] = tool_name


class ToolRegistry:
    """Centralized tool registration and discovery."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._aliases: dict[str, str] = {}

    def register(self, tool: Tool) -> None:
        """
        Register a tool with aliases.

        Validates that tool names and aliases are argparse-compatible:
        - Must start with a lowercase letter
        - Can contain only lowercase letters, numbers, underscores, and hyphens
        - Must not be empty or contain spaces or special characters

        Also enforces resource limits to prevent DoS attacks:
        - Maximum number of tools (MAX_TOOL_COUNT)
        - Maximum tool name length (MAX_TOOL_NAME_LENGTH)
        - Maximum number of aliases per tool (MAX_ALIAS_COUNT)

        Args:
            tool: Tool instance to register

        Raises:
            ToolRegistrationError: If tool name or alias is invalid, or resource limits exceeded
            DupToolError: If tool name is already registered
        """
        _check_tool_count_limit(self._tools, tool.name)
        _validate_tool_name(tool.name)

        if tool.name in self._tools:
            raise DupToolError(tool)

        self._tools[tool.name] = tool

        cmd_args, cmd_kwargs = tool.cmd
        aliases = cmd_kwargs.get("aliases", [])
        _validate_and_register_aliases(tool.name, aliases, self._aliases)

    def get_tool(self, name: str) -> Tool | None:
        """Get tool by name or alias."""
        # Check direct name first
        if name in self._tools:
            return self._tools[name]

        # Check aliases
        if name in self._aliases:
            actual_name = self._aliases[name]
            return self._tools[actual_name]

        return None

    def list_tools(self) -> list[str]:
        """List all registered tool names."""
        return list(self._tools.keys())

    def list_aliases(self) -> dict[str, str]:
        """List all tool aliases."""
        return self._aliases.copy()

    def clear(self) -> None:
        """Clear all registered tools."""
        self._tools.clear()
        self._aliases.clear()

    def is_registered(self, name: str) -> bool:
        """Check if a tool name or alias is registered."""
        return name in self._tools or name in self._aliases
