# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Type stubs for decorator API.

Provides type hints for IDE autocomplete and type checking when using
the decorator API for creating tools.
"""

from collections.abc import Callable
from typing import Any, Protocol, TypeVar, runtime_checkable

from typing_extensions import ParamSpec

P = ParamSpec("P")
T = TypeVar("T")

@runtime_checkable
class ToolContextProtocol(Protocol):
    """
    Protocol defining the context available in decorated tools.

    This protocol describes the `self` parameter that decorated tool
    functions receive, providing type hints for IDE autocomplete.

    Example:
        from infra.app.decorators import ToolContextProtocol

        @app.tool()
        def mytool(self: ToolContextProtocol):
            # IDE now knows self.lg, self.config, self.args exist
            self.lg.info("...")  # ✓ Autocomplete works
            self.config.database.host  # ✓ Autocomplete works
            self.args.file  # ✓ Autocomplete works
    """

    @property
    def lg(self) -> Any:
        """
        Logger instance derived from parent hierarchy.

        Returns:
            Logger with debug, info, warning, error methods
        """
        ...

    @property
    def config(self) -> Any:
        """
        Configuration object loaded from YAML/environment.

        Returns:
            Config object with nested attribute access
        """
        ...

    @property
    def args(self) -> Any:
        """
        Parsed command-line arguments.

        Returns:
            Namespace with argument values
        """
        ...

    @property
    def parent(self) -> ToolContextProtocol | None:
        """
        Parent tool in hierarchy (if any).

        Returns:
            Parent ToolContextProtocol or None
        """
        ...

    @property
    def name(self) -> str:
        """
        Tool name.

        Returns:
            Name of the tool
        """
        ...

    def trace_attr(self, name: str) -> Any:
        """
        Trace attribute through parent hierarchy.

        Args:
            name: Attribute name to search for

        Returns:
            Attribute value from hierarchy

        Raises:
            AttrNotFoundError: If attribute not found
        """
        ...

    def has_attr(self, name: str) -> bool:
        """
        Check if attribute exists in hierarchy.

        Args:
            name: Attribute name to check

        Returns:
            True if attribute exists
        """
        ...

    def get_attr_or_default(self, name: str, default: Any = None) -> Any:
        """
        Get attribute from hierarchy or return default.

        Args:
            name: Attribute name
            default: Default value if not found

        Returns:
            Attribute value or default
        """
        ...

class ToolFunction:
    """Container for decorated function metadata."""

    func: Callable
    name: str
    help_text: str
    description: str
    aliases: list[str]
    arguments: list[tuple]
    setup_hook: Callable | None
    configure_hook: Callable | None
    subtools: list[ToolFunction]
    default_subtool: str | None

    def __init__(
        self,
        func: Callable,
        name: str | None = ...,
        help_text: str = ...,
        description: str = ...,
        aliases: list[str] | None = ...,
    ) -> None: ...
    def argument(self, *args: Any, **kwargs: Any) -> ToolFunction: ...
    def on_setup(self, func: Callable) -> ToolFunction: ...
    def on_configure(self, func: Callable) -> ToolFunction: ...
    def subtool(
        self,
        name: str | None = ...,
        help: str = ...,
        aliases: list[str] | None = ...,
    ) -> Callable[[Callable], ToolFunction]: ...
    def to_tool_class(self) -> type: ...

class DecoratorAPI:
    """Decorator API for the app framework."""

    def __init__(self, target: Any) -> None: ...
    def tool(
        self,
        name: str | None = ...,
        help: str = ...,
        description: str = ...,
        aliases: list[str] | None = ...,
    ) -> Callable[[Callable], ToolFunction]: ...
    def argument(
        self, *args: Any, **kwargs: Any
    ) -> Callable[[ToolFunction], ToolFunction]: ...
    def get_tool_functions(self) -> list[ToolFunction]: ...
