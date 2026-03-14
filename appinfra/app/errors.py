"""
Enhanced error classes for the appinfra.app package.

This module provides comprehensive error handling with better error messages
and more specific exception types for different failure scenarios.
"""

from typing import Any


class InfraAppError(Exception):
    """Base exception for appinfra.app package."""

    pass


class UndefNameError(InfraAppError):
    """Raised when a tool name is not defined."""

    def __init__(self, cls: Any | None = None, tool: Any | None = None) -> None:
        self.cls = cls
        self.tool = tool
        if cls:
            super().__init__(f"Tool class {cls.__name__} must define a name property")
        elif tool:
            super().__init__(f"Tool {tool} must have a name")
        else:
            super().__init__("Tool name is not defined")


class UndefGroupError(InfraAppError):
    """Raised when a tool group is not defined."""

    def __init__(self, tool: Any) -> None:
        self.tool = tool
        super().__init__(f"Tool '{tool.name}' requires a group but none is defined")


class NoSubToolsError(InfraAppError):
    """Raised when no sub-tools are available."""

    def __init__(self) -> None:
        super().__init__("No sub-tools are available")


class DupToolError(InfraAppError):
    """Raised when attempting to register a duplicate tool."""

    def __init__(self, tool: Any) -> None:
        self.tool = tool
        super().__init__(f"Tool '{tool.name}' is already registered")


class MissingRunFuncError(InfraAppError):
    """Raised when a run function is missing for a command."""

    def __init__(self, cmd: str) -> None:
        self.cmd = cmd
        super().__init__(f"Command '{cmd}' requires a run_func parameter")


class AttrNotFoundError(InfraAppError):
    """Raised when an attribute is not found in the hierarchy."""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"Attribute '{name}' not found in hierarchy")


class ToolRegistrationError(InfraAppError):
    """Raised when tool registration fails."""

    def __init__(self, tool_name: str, reason: str):
        self.tool_name = tool_name
        self.reason = reason
        super().__init__(f"Failed to register tool '{tool_name}': {reason}")


class ConfigError(InfraAppError):
    """Raised when configuration is invalid."""

    def __init__(self, message: str):
        super().__init__(f"Configuration error: {message}")


class LifecycleError(InfraAppError):
    """Raised when lifecycle operations fail."""

    def __init__(self, message: str):
        super().__init__(f"Lifecycle error: {message}")


class AppError(InfraAppError):
    """Raised when application-level operations fail."""

    def __init__(self, message: str):
        super().__init__(f"Application error: {message}")


class CommandError(InfraAppError):
    """Raised when command execution fails."""

    def __init__(self, message: str):
        super().__init__(f"Command error: {message}")


class MissingLoggerError(InfraAppError):
    """Raised when logger object is missing."""

    def __init__(self, message: str):
        super().__init__(f"Missing logger error: {message}")


class MissingParentError(InfraAppError):
    """Raised when accessing parent-dependent resources without a parent."""

    def __init__(self, tool_name: str, property_name: str):
        self.tool_name = tool_name
        self.property_name = property_name
        super().__init__(
            f"Tool '{tool_name}' cannot access '{property_name}' without a parent. "
            f"Tools need a parent (usually an App instance) to access shared resources. "
            f"For testing, provide a mock parent: "
            f"tool = MyTool(parent=MockApp(args={{'key': 'value'}}))"
        )
