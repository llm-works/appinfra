# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tool protocol interface definition.

This module provides an abstract base class that defines the interface
for command-line tools, ensuring consistent behavior across different
tool implementations.
"""

import argparse
from abc import ABC, abstractmethod
from typing import Any


class ToolProtocol(ABC):
    """
    Abstract base class defining the interface for command-line tools.

    Provides a standard interface that tool classes must implement,
    ensuring consistent behavior and enabling polymorphism across different
    tool implementations. This interface defines the core methods and
    properties that all tools must support.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """
        Get the tool name.

        Returns:
            str: Tool name
        """
        pass

    @property
    @abstractmethod
    def cmd(self) -> tuple[list[str], dict[str, Any]]:
        """
        Get command configuration for argument parsing.

        Returns:
            tuple: (command_args, command_kwargs) for argparse
        """
        pass

    @abstractmethod
    def add_args(self, parser: argparse.ArgumentParser) -> None:
        """
        Add arguments to the parser.

        Args:
            parser: Argument parser instance
        """
        pass

    @abstractmethod
    def setup(self, **kwargs: Any) -> None:
        """
        Set up the tool.

        Args:
            **kwargs: Setup keyword arguments
        """
        pass

    @abstractmethod
    def run(self, **kwargs: Any) -> Any:
        """
        Run the tool.

        Args:
            **kwargs: Runtime keyword arguments

        Returns:
            Any: Tool execution result
        """
        pass

    @property
    def lg(self) -> Any:
        """
        Get the logger instance.

        Returns:
            Logger instance
        """
        pass

    @property
    def args(self) -> Any:
        """
        Get parsed command-line arguments.

        Returns:
            Parsed arguments
        """
        pass

    @property
    def kwargs(self) -> Any:
        """
        Get setup keyword arguments.

        Returns:
            Setup keyword arguments
        """
        pass

    @property
    @abstractmethod
    def initialized(self) -> bool:
        """
        Check if the tool has been initialized.

        Returns:
            bool: True if initialized, False otherwise
        """
        pass

    @property
    def arg_prs(self) -> Any:
        """
        Get the argument parser instance.

        Returns:
            Argument parser instance
        """
        pass
