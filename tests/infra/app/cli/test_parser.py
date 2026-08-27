# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for app/cli/parser.py.

Tests key functionality including:
- CLIParser initialization
- Parser creation
- Argument handling
- Subparser support
- Help and usage output
- Error handling
"""

import argparse
from io import StringIO

import pytest

from appinfra.app.args import DefaultsHelpFormatter
from appinfra.app.cli.parser import CLIParser

# =============================================================================
# Test CLIParser Initialization
# =============================================================================


@pytest.mark.unit
class TestCLIParserInit:
    """Test CLIParser initialization."""

    def test_default_formatter_class(self):
        """Test uses DefaultsHelpFormatter by default."""
        cli_parser = CLIParser()

        assert cli_parser.formatter_class is DefaultsHelpFormatter

    def test_custom_formatter_class(self):
        """Test accepts custom formatter class."""

        class CustomFormatter(argparse.HelpFormatter):
            pass

        cli_parser = CLIParser(formatter_class=CustomFormatter)

        assert cli_parser.formatter_class is CustomFormatter

    def test_parser_initially_none(self):
        """Test parser is None before create_parser."""
        cli_parser = CLIParser()

        assert cli_parser.parser is None

    def test_subparsers_initially_empty(self):
        """Test subparsers dict is empty initially."""
        cli_parser = CLIParser()

        assert cli_parser.subparsers == {}


# =============================================================================
# Test create_parser
# =============================================================================


@pytest.mark.unit
class TestCreateParser:
    """Test CLIParser.create_parser method."""

    def test_creates_argument_parser(self):
        """Test creates an ArgumentParser instance."""
        cli_parser = CLIParser()

        result = cli_parser.create_parser()

        assert isinstance(result, argparse.ArgumentParser)

    def test_stores_parser_internally(self):
        """Test stores created parser in self.parser."""
        cli_parser = CLIParser()

        result = cli_parser.create_parser()

        assert cli_parser.parser is result

    def test_uses_formatter_class(self):
        """Test uses configured formatter class."""

        class TestFormatter(argparse.HelpFormatter):
            pass

        cli_parser = CLIParser(formatter_class=TestFormatter)
        parser = cli_parser.create_parser()

        assert parser.formatter_class is TestFormatter

    def test_returns_same_parser_on_multiple_calls(self):
        """Test create_parser replaces existing parser."""
        cli_parser = CLIParser()

        parser1 = cli_parser.create_parser()
        parser2 = cli_parser.create_parser()

        # Each call creates a new parser
        assert parser1 is not parser2
        assert cli_parser.parser is parser2


# =============================================================================
# Test add_argument
# =============================================================================


@pytest.mark.unit
class TestAddArgument:
    """Test CLIParser.add_argument method."""

    def test_adds_positional_argument(self):
        """Test adds positional argument to parser."""
        cli_parser = CLIParser()
        cli_parser.create_parser()

        cli_parser.add_argument("filename")

        # Should be able to parse with the argument
        args = cli_parser.parse_args(["test.txt"])
        assert args.filename == "test.txt"

    def test_adds_optional_argument(self):
        """Test adds optional argument to parser."""
        cli_parser = CLIParser()
        cli_parser.create_parser()

        cli_parser.add_argument("--verbose", "-v", action="store_true")

        args = cli_parser.parse_args(["--verbose"])
        assert args.verbose is True

    def test_adds_argument_with_default(self):
        """Test adds argument with default value."""
        cli_parser = CLIParser()
        cli_parser.create_parser()

        cli_parser.add_argument("--count", type=int, default=10)

        args = cli_parser.parse_args([])
        assert args.count == 10

    def test_returns_action_object(self):
        """Test returns argparse Action object."""
        cli_parser = CLIParser()
        cli_parser.create_parser()

        result = cli_parser.add_argument("--test")

        assert isinstance(result, argparse.Action)

    def test_raises_when_parser_not_created(self):
        """Test raises RuntimeError when parser not created."""
        cli_parser = CLIParser()

        with pytest.raises(RuntimeError) as exc_info:
            cli_parser.add_argument("--test")

        assert "Parser not created" in str(exc_info.value)


# =============================================================================
# Test add_subparsers
# =============================================================================


@pytest.mark.unit
class TestAddSubparsers:
    """Test CLIParser.add_subparsers method."""

    def test_creates_subparsers_action(self):
        """Test creates SubParsersAction object."""
        cli_parser = CLIParser()
        cli_parser.create_parser()

        result = cli_parser.add_subparsers(dest="command")

        assert isinstance(result, argparse._SubParsersAction)

    def test_subparsers_with_dest(self):
        """Test subparsers dest is set correctly."""
        cli_parser = CLIParser()
        cli_parser.create_parser()
        subparsers = cli_parser.add_subparsers(dest="cmd")

        # Add a subparser
        subparsers.add_parser("run")

        args = cli_parser.parse_args(["run"])
        assert args.cmd == "run"

    def test_raises_when_parser_not_created(self):
        """Test raises RuntimeError when parser not created."""
        cli_parser = CLIParser()

        with pytest.raises(RuntimeError) as exc_info:
            cli_parser.add_subparsers(dest="command")

        assert "Parser not created" in str(exc_info.value)


# =============================================================================
# Test parse_args
# =============================================================================


@pytest.mark.unit
class TestParseArgs:
    """Test CLIParser.parse_args method."""

    def test_parses_provided_args(self):
        """Test parses list of argument strings."""
        cli_parser = CLIParser()
        cli_parser.create_parser()
        cli_parser.add_argument("--name", required=True)
        cli_parser.add_argument("--count", type=int, default=1)

        result = cli_parser.parse_args(["--name", "test", "--count", "5"])

        assert result.name == "test"
        assert result.count == 5

    def test_returns_namespace(self):
        """Test returns argparse.Namespace object."""
        cli_parser = CLIParser()
        cli_parser.create_parser()

        result = cli_parser.parse_args([])

        assert isinstance(result, argparse.Namespace)

    def test_raises_when_parser_not_created(self):
        """Test raises RuntimeError when parser not created."""
        cli_parser = CLIParser()

        with pytest.raises(RuntimeError) as exc_info:
            cli_parser.parse_args([])

        assert "Parser not created" in str(exc_info.value)


# =============================================================================
# Test print_help
# =============================================================================


@pytest.mark.unit
class TestPrintHelp:
    """Test CLIParser.print_help method."""

    def test_prints_help_to_stdout_by_default(self):
        """Test prints help message to stdout."""
        cli_parser = CLIParser()
        cli_parser.create_parser()
        cli_parser.add_argument("--verbose", help="Enable verbose output")

        output = StringIO()
        cli_parser.print_help(file=output)

        help_text = output.getvalue()
        assert "--verbose" in help_text
        assert "Enable verbose output" in help_text

    def test_prints_to_custom_file(self):
        """Test prints help to custom file object."""
        cli_parser = CLIParser()
        cli_parser.create_parser()

        custom_file = StringIO()
        cli_parser.print_help(file=custom_file)

        assert len(custom_file.getvalue()) > 0

    def test_raises_when_parser_not_created(self):
        """Test raises RuntimeError when parser not created."""
        cli_parser = CLIParser()

        with pytest.raises(RuntimeError) as exc_info:
            cli_parser.print_help()

        assert "Parser not created" in str(exc_info.value)


# =============================================================================
# Test print_usage
# =============================================================================


@pytest.mark.unit
class TestPrintUsage:
    """Test CLIParser.print_usage method."""

    def test_prints_usage_message(self):
        """Test prints usage message."""
        cli_parser = CLIParser()
        cli_parser.create_parser()
        cli_parser.add_argument("filename")

        output = StringIO()
        cli_parser.print_usage(file=output)

        usage_text = output.getvalue()
        assert "usage:" in usage_text.lower()
        assert "filename" in usage_text

    def test_raises_when_parser_not_created(self):
        """Test raises RuntimeError when parser not created."""
        cli_parser = CLIParser()

        with pytest.raises(RuntimeError) as exc_info:
            cli_parser.print_usage()

        assert "Parser not created" in str(exc_info.value)


# =============================================================================
# Test error
# =============================================================================


@pytest.mark.unit
class TestError:
    """Test CLIParser.error method."""

    def test_raises_when_parser_not_created(self):
        """Test raises RuntimeError when parser not created."""
        cli_parser = CLIParser()

        with pytest.raises(RuntimeError) as exc_info:
            cli_parser.error("test error")

        assert "Parser not created" in str(exc_info.value)

    def test_calls_parser_error(self):
        """Test delegates to parser.error method."""
        cli_parser = CLIParser()
        cli_parser.create_parser()

        # parser.error() exits, so we catch SystemExit
        with pytest.raises(SystemExit):
            cli_parser.error("test error message")


# =============================================================================
# Integration Tests
# =============================================================================


@pytest.mark.integration
class TestCLIParserIntegration:
    """Integration tests for CLIParser."""

    def test_full_cli_workflow(self):
        """Test complete CLI parsing workflow."""
        cli_parser = CLIParser()
        cli_parser.create_parser()

        # Add various argument types
        cli_parser.add_argument("input", help="Input file")
        cli_parser.add_argument("--output", "-o", help="Output file")
        cli_parser.add_argument("--verbose", "-v", action="store_true")
        cli_parser.add_argument("--count", type=int, default=1)

        # Parse arguments
        args = cli_parser.parse_args(
            ["input.txt", "-o", "output.txt", "-v", "--count", "10"]
        )

        assert args.input == "input.txt"
        assert args.output == "output.txt"
        assert args.verbose is True
        assert args.count == 10

    def test_subcommand_workflow(self):
        """Test CLI with subcommands."""
        cli_parser = CLIParser()
        cli_parser.create_parser()
        cli_parser.add_argument("--verbose", "-v", action="store_true")

        subparsers = cli_parser.add_subparsers(dest="command")

        # Add 'run' subcommand
        run_parser = subparsers.add_parser("run", help="Run the application")
        run_parser.add_argument("--config", "-c", default="config.yaml")

        # Add 'test' subcommand
        test_parser = subparsers.add_parser("test", help="Run tests")
        test_parser.add_argument("--coverage", action="store_true")

        # Parse 'run' command
        args1 = cli_parser.parse_args(["-v", "run", "-c", "custom.yaml"])
        assert args1.verbose is True
        assert args1.command == "run"
        assert args1.config == "custom.yaml"

        # Parse 'test' command
        args2 = cli_parser.parse_args(["test", "--coverage"])
        assert args2.command == "test"
        assert args2.coverage is True

    def test_help_output_contains_all_arguments(self):
        """Test help output includes all defined arguments."""
        cli_parser = CLIParser()
        cli_parser.create_parser()
        cli_parser.add_argument("--alpha", help="Alpha option")
        cli_parser.add_argument("--beta", help="Beta option")
        cli_parser.add_argument("--gamma", help="Gamma option")

        output = StringIO()
        cli_parser.print_help(file=output)

        help_text = output.getvalue()
        assert "--alpha" in help_text
        assert "Alpha option" in help_text
        assert "--beta" in help_text
        assert "Beta option" in help_text
        assert "--gamma" in help_text
        assert "Gamma option" in help_text
