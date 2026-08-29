# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Base tool class for command-line applications.

This module provides the enhanced base tool class with better configuration.
"""

from __future__ import annotations

import argparse
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

from ...log import Logger, LoggerFactory
from ..errors import (
    LifecycleError,
    MissingLoggerError,
    MissingParentError,
    UndefGroupError,
    UndefNameError,
)
from ..tracing.traceable import Traceable
from .protocol import ToolProtocol

if TYPE_CHECKING:
    from ..core.app import App
    from .group import ToolGroup


class _PositionalFilteringParser:
    """
    Wrapper that filters out positional arguments when adding to a parser.

    Used when hoisting main tool arguments to the root parser to avoid conflicts
    with subcommand parsing. Only optional arguments (those starting with '-')
    are added to the underlying parser.
    """

    def __init__(self, parser: argparse.ArgumentParser):
        self._parser = parser

    def add_argument(self, *args: Any, **kwargs: Any) -> argparse.Action | None:
        """Add argument only if it's optional (starts with '-')."""
        if args and not str(args[0]).startswith("-"):
            # Skip positional arguments - return None (caller shouldn't rely on return)
            return None
        return self._parser.add_argument(*args, **kwargs)

    def add_argument_group(self, *args: Any, **kwargs: Any) -> argparse._ArgumentGroup:
        """Delegate to underlying parser, wrapping result to filter positionals."""
        group = self._parser.add_argument_group(*args, **kwargs)
        return _PositionalFilteringGroup(group)  # type: ignore[return-value]

    def add_mutually_exclusive_group(
        self, *args: Any, **kwargs: Any
    ) -> argparse._MutuallyExclusiveGroup:
        """Delegate to underlying parser, wrapping result to filter positionals."""
        group = self._parser.add_mutually_exclusive_group(*args, **kwargs)
        return _PositionalFilteringGroup(group)  # type: ignore[return-value]

    def __getattr__(self, name: str) -> Any:
        """Delegate unknown attributes to underlying parser."""
        return getattr(self._parser, name)


class _PositionalFilteringGroup:
    """
    Wrapper that filters out positional arguments from argument groups.

    Used by _PositionalFilteringParser to ensure positional arguments cannot
    bypass filtering by being added through argument groups.
    """

    def __init__(self, group: argparse._ArgumentGroup):
        self._group = group

    def add_argument(self, *args: Any, **kwargs: Any) -> argparse.Action | None:
        """Add argument only if it's optional (starts with '-')."""
        if args and not str(args[0]).startswith("-"):
            return None
        return self._group.add_argument(*args, **kwargs)

    def add_mutually_exclusive_group(
        self, *args: Any, **kwargs: Any
    ) -> _PositionalFilteringGroup:
        """Wrap mutually exclusive groups to maintain positional filtering."""
        return _PositionalFilteringGroup(
            self._group.add_mutually_exclusive_group(*args, **kwargs)
        )

    def __getattr__(self, name: str) -> Any:
        """Delegate unknown attributes to underlying group."""
        return getattr(self._group, name)


@dataclass
class ToolConfig:
    """Configuration for a tool."""

    name: str
    aliases: list[str] = field(default_factory=list)
    help_text: str = ""
    description: str = ""


class Tool(Traceable, ToolProtocol):
    """
    Enhanced base tool class with better configuration.

    Provides the foundation for building tools with argument parsing,
    logging, configuration, and subcommand support through tool groups.
    """

    def __init__(
        self, parent: Traceable | None = None, config: ToolConfig | None = None
    ):
        """
        Initialize the tool.

        Args:
            parent: Parent tool or main application instance
            config: Tool configuration (optional)
        """
        super().__init__(parent)
        self.config = config or self._create_config()
        self._logger: Logger | None = None
        self._kwargs: dict[str, Any] | None = None
        self._arg_prs: argparse.ArgumentParser | None = None
        self._group: ToolGroup | None = None
        self._initialized = False
        self._init_lock = threading.Lock()

    def _create_config(self) -> ToolConfig:
        """Create default configuration. Override in subclasses."""
        # This method should be overridden by subclasses to provide a default name
        # For now, we'll raise an error to force explicit configuration
        raise UndefNameError(cls=self.__class__)

    @property
    def name(self) -> str:
        """
        Get the tool name.

        Returns the name from config if available, otherwise raises UndefNameError.
        Subclasses can override this method to provide custom name logic.

        Returns:
            str: Tool name

        Raises:
            UndefNameError: If name is not defined in config and not overridden
        """
        if self.config and self.config.name:
            return self.config.name
        raise UndefNameError(self.__class__)

    @property
    def cmd(self) -> tuple[list[str], dict[str, Any]]:
        """
        Get command configuration for argument parsing.

        Returns:
            tuple: (command_args, command_kwargs) for argparse
        """
        return [self.name], {
            "aliases": self.config.aliases,
            "help": self.config.help_text,
            "description": self.config.description,
        }

    @property
    def group(self) -> ToolGroup:
        """
        Get the tool group for subcommands.

        Returns:
            ToolGroup: The tool group instance

        Raises:
            UndefGroupError: If no group is defined
        """
        if self._group is None:
            raise UndefGroupError(self)
        return self._group

    @property
    def lg(self) -> Logger:
        """Get the logger instance.

        Returns:
            Logger: The logger instance for this tool

        Raises:
            MissingLoggerError: If accessed before setup() is called
        """
        if self._logger is None:
            raise MissingLoggerError(
                f"Logger not initialized for tool '{self.name}'. "
                "Ensure setup() has been called before accessing lg."
            )
        return self._logger

    @property
    def args(self) -> argparse.Namespace:
        """
        Get parsed command-line arguments.

        Returns:
            argparse.Namespace: Parsed command-line arguments

        Raises:
            MissingParentError: If tool has no parent to get args from
        """
        if hasattr(self, "_parsed_args") and self._parsed_args:
            return cast(argparse.Namespace, self._parsed_args)

        if self.parent is None:
            raise MissingParentError(self.name, "args")

        if not hasattr(self.parent, "args"):
            raise MissingParentError(
                self.name, "args (parent does not have 'args' attribute)"
            )

        return cast(argparse.Namespace, self.parent.args)  # type: ignore[attr-defined]

    @property
    def kwargs(self) -> dict[str, Any] | None:
        """Get setup keyword arguments."""
        return self._kwargs

    @property
    def initialized(self) -> bool:
        """Check if the tool has been initialized."""
        return self._initialized

    @property
    def arg_prs(self) -> argparse.ArgumentParser | None:
        """Get the argument parser instance."""
        return self._arg_prs

    @property
    def app(self) -> App:
        """
        Get the root App instance by traversing the parent chain.

        This provides reliable access to the application's YAML config via
        `self.app.config`, regardless of intermediate parent objects.

        Returns:
            App: The root application instance

        Raises:
            MissingParentError: If tool is not attached to an App
        """
        from ..core.app import App

        node: Any = self
        while node is not None:
            if isinstance(node, App):
                return node
            node = getattr(node, "parent", None)
        raise MissingParentError(self.name, "app (tool is not attached to an App)")

    def set_args(
        self, parser: argparse.ArgumentParser, skip_positional: bool = False
    ) -> None:
        """
        Set up argument parser for this tool.

        Args:
            parser: The argument parser to add arguments to
            skip_positional: If True, skip positional arguments (used when hoisting
                main tool args to root parser to avoid conflict with subcommands)
        """
        self._arg_prs = parser
        if self._group is not None:
            subs = self._group.add_tool_args(parser)
            self.add_group_args(subs)
            self._group.finalize_args(parser)

        if skip_positional:
            # Use filtering wrapper to skip positional args
            wrapper = _PositionalFilteringParser(parser)
            self.add_args(wrapper)  # type: ignore[arg-type]
        else:
            self.add_args(parser)

    def add_args(self, parser: argparse.ArgumentParser) -> None:
        """
        Add arguments to the parser.

        Override this method in subclasses to add tool-specific arguments.
        """
        pass

    def add_group_args(self, subs: Any) -> None:
        """
        Add group-specific arguments.

        Override this method in subclasses to add group-specific arguments.

        Args:
            subs: Subparser action from argparse
        """
        # Automatically add commands registered via add_cmd
        if hasattr(self, "_commands"):
            for cmd_info in self._commands:
                self.group.add_cmd(
                    subs,
                    cmd_info["name"],
                    aliases=cmd_info["aliases"],
                    help=cmd_info["help_text"],
                    run_func=cmd_info["run_func"],
                )

    def setup(self, **kwargs: Any) -> None:
        """
        Set up the tool in a thread-safe manner.

        This method is protected by a lock to prevent concurrent initialization
        in multi-threaded environments.

        Args:
            **kwargs: Setup keyword arguments
        """
        with self._init_lock:
            # Prevent re-execution of setup
            if self._initialized:
                return

            self._kwargs = kwargs
            self.setup_lg()
            self.configure()

            # Automatically set up all tools in the group
            if self._group is not None:
                for tool in self._group._tools.values():
                    tool.setup(**kwargs)

            self._initialized = True

    def setup_lg(self) -> None:
        """Set up the logger for this tool."""
        try:
            if self.parent and hasattr(self.parent, "lg"):
                self._logger = LoggerFactory.derive(self.parent.lg, self.name)
            else:
                # Fallback to creating a standalone logger
                import os

                from ...log import LogConfig

                # Respect INFRA_TEST_LOGGING_LEVEL environment variable
                log_level_str = os.getenv("INFRA_TEST_LOGGING_LEVEL", "info")
                log_level: str | bool = log_level_str
                if log_level_str.lower() == "false":
                    log_level = False

                config = LogConfig.from_params(log_level)
                self._logger = LoggerFactory.create_root(config)
        except Exception as e:
            # If logger creation fails, raise a descriptive error
            raise LifecycleError(
                f"Failed to create logger for tool '{self.name}': {e}. "
                f"This may indicate missing parent logger or invalid logging configuration."
            ) from e

    def configure(self) -> None:
        """
        Configure the tool after setup.

        Override this method in subclasses to perform custom configuration.
        """
        pass

    def create_group(self, default: str | None = None) -> ToolGroup:
        """Create a tool group for subcommands."""
        from .group import ToolGroup

        self._group = ToolGroup(self, self.name + "_cmd", default)
        return self._group

    def add_tool(
        self,
        tool: Tool,
        run_func: Callable | None = None,
        default: str | None = None,
    ) -> Tool:
        """Add a tool to the group."""
        if self._group is None:
            self.create_group(default=default)
        assert self._group is not None  # create_group always sets _group
        return self._group.add_tool(tool, run_func=run_func)

    def add_cmd(
        self,
        name: str,
        run_func: Callable,
        aliases: list[str] | None = None,
        help_text: str = "",
    ) -> None:
        """
        Add a command with a run function.

        Args:
            name: Command name
            run_func: Function to execute when command is called
            aliases: List of command aliases (optional)
            help_text: Help text for the command (optional)
        """
        if self._group is None:
            self.create_group()

        # Store the command info for later use in add_group_args
        if not hasattr(self, "_commands"):
            self._commands = []

        self._commands.append(
            {
                "name": name,
                "run_func": run_func,
                "aliases": aliases or [],
                "help_text": help_text,
            }
        )

    def run(self, **kwargs: Any) -> int:
        """
        Run the tool.

        Returns:
            int: Exit code

        Raises:
            UndefGroupError: If no group is defined and tool requires one
        """
        if self._group is None:
            raise UndefGroupError(self)
        return self._group.run(**kwargs)
