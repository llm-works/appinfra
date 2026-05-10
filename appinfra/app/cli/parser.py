"""
Argument parsing logic for CLI applications.

This module provides dedicated argument parsing with better organization.
"""

import argparse
from typing import IO, Any

from ..args import DefaultsHelpFormatter


class CLIParser:
    """Dedicated argument parser with better organization."""

    def __init__(self, formatter_class: type[argparse.HelpFormatter] | None = None):
        """
        Initialize the CLI parser.

        Args:
            formatter_class: Custom formatter class for help output
        """
        self.formatter_class: type[argparse.HelpFormatter] = (
            formatter_class or DefaultsHelpFormatter
        )
        self.parser: argparse.ArgumentParser | None = None
        self.subparsers: dict[str, argparse.ArgumentParser] = {}

    def create_parser(self, add_help: bool = True) -> argparse.ArgumentParser:
        """Create the main argument parser."""
        self.parser = argparse.ArgumentParser(
            formatter_class=self.formatter_class, add_help=add_help
        )
        return self.parser

    def add_argument(self, *args: Any, **kwargs: Any) -> argparse.Action:
        """Add an argument to the main parser."""
        if not self.parser:
            raise RuntimeError("Parser not created. Call create_parser() first.")
        return self.parser.add_argument(*args, **kwargs)

    def add_subparsers(self, dest: str, **kwargs: Any) -> argparse._SubParsersAction:
        """Add subparsers to the main parser."""
        if not self.parser:
            raise RuntimeError("Parser not created. Call create_parser() first.")
        return self.parser.add_subparsers(dest=dest, **kwargs)

    def parse_args(self, args: list[str] | None = None) -> argparse.Namespace:
        """Parse command line arguments."""
        if not self.parser:
            raise RuntimeError("Parser not created. Call create_parser() first.")
        return self.parser.parse_args(args)

    def print_help(self, file: IO[str] | None = None) -> None:
        """Print help message."""
        if not self.parser:
            raise RuntimeError("Parser not created. Call create_parser() first.")
        self.parser.print_help(file=file)

    def print_usage(self, file: IO[str] | None = None) -> None:
        """Print usage message."""
        if not self.parser:
            raise RuntimeError("Parser not created. Call create_parser() first.")
        self.parser.print_usage(file=file)

    def error(self, message: str) -> None:
        """Print error message and exit."""
        if not self.parser:
            raise RuntimeError("Parser not created. Call create_parser() first.")
        self.parser.error(message)
