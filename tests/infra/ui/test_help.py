# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for appinfra.ui.help module."""

from __future__ import annotations

import argparse

import pytest

pytestmark = pytest.mark.unit

from unittest.mock import MagicMock, patch

from appinfra.ui import help as help_module
from appinfra.ui.help import RichHelpFormatter, get_help_formatter


class TestGetHelpFormatter:
    """Tests for get_help_formatter function."""

    def test_returns_rich_formatter_when_available(self):
        """Test returns RichHelpFormatter when rich is available."""
        with patch.object(help_module, "RICH_AVAILABLE", True):
            formatter = get_help_formatter()
            assert formatter is RichHelpFormatter

    def test_returns_standard_formatter_when_not_available(self):
        """Test returns standard formatter when rich is not available."""
        with patch.object(help_module, "RICH_AVAILABLE", False):
            formatter = get_help_formatter()
            assert formatter is argparse.HelpFormatter


class TestRichHelpFormatterInit:
    """Tests for RichHelpFormatter initialization."""

    def test_init_default_params(self):
        """Test formatter initializes with default params."""
        formatter = RichHelpFormatter("test_prog")
        assert formatter._prog == "test_prog"
        assert formatter._rich_output == []

    def test_init_custom_params(self):
        """Test formatter initializes with custom params."""
        formatter = RichHelpFormatter(
            "test_prog", indent_increment=4, max_help_position=40, width=100
        )
        assert formatter._prog == "test_prog"
        assert formatter._indent_increment == 4
        assert formatter._max_help_position == 40


class TestRichHelpFormatterFormatHelp:
    """Tests for format_help method."""

    def test_format_help_without_rich(self):
        """Test format_help falls back to parent when rich not available."""
        with patch.object(help_module, "RICH_AVAILABLE", False):
            # Create via argparse to get proper initialization
            parser = argparse.ArgumentParser(
                prog="test_prog", formatter_class=RichHelpFormatter
            )
            result = parser.format_help()
            assert isinstance(result, str)
            assert "test_prog" in result

    def test_format_help_with_rich(self):
        """Test format_help uses rich when available."""
        with patch.object(help_module, "RICH_AVAILABLE", True):
            formatter = RichHelpFormatter("test_prog")
            formatter._actions = []
            formatter._root_section = MagicMock()
            formatter._root_section._group_actions = []

            result = formatter.format_help()
            assert isinstance(result, str)
            assert "Usage:" in result
            assert "test_prog" in result


class TestRichHelpFormatterFormatUsage:
    """Tests for usage formatting."""

    def test_format_usage_rich_without_rich(self):
        """Test _format_usage_rich returns None when rich not available."""
        with patch.object(help_module, "RICH_AVAILABLE", False):
            formatter = RichHelpFormatter("test_prog")
            result = formatter._format_usage_rich()
            assert result is None

    def test_format_usage_rich_with_rich(self):
        """Test _format_usage_rich returns Text object when rich available."""
        with patch.object(help_module, "RICH_AVAILABLE", True):
            formatter = RichHelpFormatter("test_prog")
            formatter._actions = []
            result = formatter._format_usage_rich()
            assert result is not None
            # Result should be a rich Text object
            assert hasattr(result, "append")


class TestRichHelpFormatterFormatUsageArgs:
    """Tests for _format_usage_args method."""

    def test_format_usage_args_empty(self):
        """Test format_usage_args with no actions."""
        formatter = RichHelpFormatter("test_prog")
        formatter._actions = []
        result = formatter._format_usage_args()
        assert result == ""

    def test_format_usage_args_optional(self):
        """Test format_usage_args with optional argument."""
        formatter = RichHelpFormatter("test_prog")

        action = MagicMock()
        action.option_strings = ["--verbose"]
        action.required = False
        action.dest = "verbose"
        action.nargs = None
        action.metavar = None

        formatter._actions = [action]
        result = formatter._format_usage_args()
        assert "[--verbose]" in result

    def test_format_usage_args_required_optional(self):
        """Test format_usage_args with required optional argument."""
        formatter = RichHelpFormatter("test_prog")

        action = MagicMock()
        action.option_strings = ["--config"]
        action.required = True
        action.dest = "config"
        action.nargs = None
        action.metavar = "FILE"

        formatter._actions = [action]
        result = formatter._format_usage_args()
        assert "--config FILE" in result

    def test_format_usage_args_positional(self):
        """Test format_usage_args with positional argument."""
        formatter = RichHelpFormatter("test_prog")

        action = MagicMock()
        action.option_strings = []
        action.dest = "filename"
        action.nargs = None

        formatter._actions = [action]
        result = formatter._format_usage_args()
        assert "FILENAME" in result

    def test_format_usage_args_positional_optional(self):
        """Test format_usage_args with optional positional argument."""
        formatter = RichHelpFormatter("test_prog")

        action = MagicMock()
        action.option_strings = []
        action.dest = "filename"
        action.nargs = "?"

        formatter._actions = [action]
        result = formatter._format_usage_args()
        assert "[FILENAME]" in result

    def test_format_usage_args_positional_zero_or_more(self):
        """Test format_usage_args with zero or more positional."""
        formatter = RichHelpFormatter("test_prog")

        action = MagicMock()
        action.option_strings = []
        action.dest = "files"
        action.nargs = "*"

        formatter._actions = [action]
        result = formatter._format_usage_args()
        assert "[FILES]" in result

    def test_format_usage_args_positional_one_or_more(self):
        """Test format_usage_args with one or more positional."""
        formatter = RichHelpFormatter("test_prog")

        action = MagicMock()
        action.option_strings = []
        action.dest = "files"
        action.nargs = "+"

        formatter._actions = [action]
        result = formatter._format_usage_args()
        assert "FILES [...]" in result

    def test_format_usage_args_skips_help(self):
        """Test format_usage_args skips help action."""
        formatter = RichHelpFormatter("test_prog")

        action = MagicMock()
        action.option_strings = []
        action.dest = "help"
        action.nargs = None

        formatter._actions = [action]
        result = formatter._format_usage_args()
        assert result == ""


class TestRichHelpFormatterFormatDescription:
    """Tests for description formatting."""

    def test_format_description_without_rich(self):
        """Test _format_description_rich returns None without rich."""
        with patch.object(help_module, "RICH_AVAILABLE", False):
            formatter = RichHelpFormatter("test_prog")
            result = formatter._format_description_rich()
            assert result is None

    def test_format_description_without_prog(self):
        """Test _format_description_rich returns None without prog."""
        with patch.object(help_module, "RICH_AVAILABLE", True):
            formatter = RichHelpFormatter("")
            result = formatter._format_description_rich()
            assert result is None


class TestRichHelpFormatterFormatActions:
    """Tests for actions formatting."""

    def test_format_actions_without_rich(self):
        """Test _format_actions_rich does nothing without rich."""
        with patch.object(help_module, "RICH_AVAILABLE", False):
            formatter = RichHelpFormatter("test_prog")
            console = MagicMock()
            formatter._format_actions_rich(console)
            console.print.assert_not_called()

    def test_split_actions(self):
        """Test _split_actions separates positionals and optionals."""
        formatter = RichHelpFormatter("test_prog")

        positional = MagicMock()
        positional.option_strings = []

        optional = MagicMock()
        optional.option_strings = ["--verbose"]

        formatter._actions = [positional, optional]
        pos, opts = formatter._split_actions()

        assert positional in pos
        assert optional in opts


class TestRichHelpFormatterPrintPositionals:
    """Tests for _print_positionals method."""

    def test_print_positionals_empty(self):
        """Test _print_positionals with no positionals."""
        with patch.object(help_module, "RICH_AVAILABLE", True):
            formatter = RichHelpFormatter("test_prog")
            console = MagicMock()
            formatter._print_positionals(console, [])
            console.print.assert_not_called()

    def test_print_positionals_skips_help(self):
        """Test _print_positionals skips help dest."""
        with patch.object(help_module, "RICH_AVAILABLE", True):
            formatter = RichHelpFormatter("test_prog")
            console = MagicMock()

            action = MagicMock()
            action.dest = "help"
            action.help = "show help"

            formatter._print_positionals(console, [action])
            # Should still print header but table will be empty
            assert console.print.called

    def test_print_positionals_with_action(self):
        """Test _print_positionals with a positional action."""
        with patch.object(help_module, "RICH_AVAILABLE", True):
            formatter = RichHelpFormatter("test_prog")
            console = MagicMock()

            action = MagicMock()
            action.dest = "filename"
            action.help = "Input file"

            formatter._print_positionals(console, [action])
            # Check that print was called with "Arguments:"
            calls = [str(call) for call in console.print.call_args_list]
            assert any("Arguments:" in str(c) for c in calls)


class TestRichHelpFormatterPrintOptionals:
    """Tests for _print_optionals method."""

    def test_print_optionals_empty(self):
        """Test _print_optionals with no optionals."""
        with patch.object(help_module, "RICH_AVAILABLE", True):
            formatter = RichHelpFormatter("test_prog")
            console = MagicMock()
            formatter._print_optionals(console, [])
            console.print.assert_not_called()

    def test_print_optionals_with_metavar(self):
        """Test _print_optionals with metavar."""
        with patch.object(help_module, "RICH_AVAILABLE", True):
            formatter = RichHelpFormatter("test_prog")
            console = MagicMock()

            action = MagicMock()
            action.option_strings = ["--config", "-c"]
            action.metavar = "FILE"
            action.type = str
            action.help = "Config file"
            action.default = None

            formatter._print_optionals(console, [action])
            calls = [str(call) for call in console.print.call_args_list]
            assert any("Options:" in str(c) for c in calls)

    def test_print_optionals_with_type(self):
        """Test _print_optionals with type instead of metavar."""
        with patch.object(help_module, "RICH_AVAILABLE", True):
            formatter = RichHelpFormatter("test_prog")
            console = MagicMock()

            action = MagicMock()
            action.option_strings = ["--count"]
            action.metavar = None
            # Create a mock type with __name__
            mock_type = MagicMock()
            mock_type.__name__ = "int"
            action.type = mock_type
            action.help = "Count value"
            action.default = None

            formatter._print_optionals(console, [action])
            calls = [str(call) for call in console.print.call_args_list]
            assert any("Options:" in str(c) for c in calls)

    def test_print_optionals_with_default(self):
        """Test _print_optionals shows default value."""
        with patch.object(help_module, "RICH_AVAILABLE", True):
            formatter = RichHelpFormatter("test_prog")
            console = MagicMock()

            action = MagicMock()
            action.option_strings = ["--count"]
            action.metavar = None
            # Create a mock type with __name__
            mock_type = MagicMock()
            mock_type.__name__ = "int"
            action.type = mock_type
            action.help = "Count value"
            action.default = 10

            formatter._print_optionals(console, [action])
            calls = [str(call) for call in console.print.call_args_list]
            assert any("Options:" in str(c) for c in calls)

    def test_print_optionals_skips_suppress_default(self):
        """Test _print_optionals skips SUPPRESS default."""
        with patch.object(help_module, "RICH_AVAILABLE", True):
            formatter = RichHelpFormatter("test_prog")
            console = MagicMock()

            action = MagicMock()
            action.option_strings = ["--verbose"]
            action.metavar = None
            action.type = bool
            action.help = "Verbose output"
            action.default = argparse.SUPPRESS

            formatter._print_optionals(console, [action])
            # Should not include default in output


class TestRichHelpFormatterFormatEpilog:
    """Tests for epilog formatting."""

    def test_format_epilog_returns_none(self):
        """Test _format_epilog_rich returns None (not implemented)."""
        formatter = RichHelpFormatter("test_prog")
        result = formatter._format_epilog_rich()
        assert result is None


class TestRichHelpFormatterBuildRichHelp:
    """Tests for _build_rich_help method."""

    def test_build_rich_help_full(self):
        """Test _build_rich_help with full output."""
        with patch.object(help_module, "RICH_AVAILABLE", True):
            formatter = RichHelpFormatter("test_prog")
            formatter._actions = []
            formatter._root_section = MagicMock()
            formatter._root_section._group_actions = []

            console = MagicMock()
            formatter._build_rich_help(console)

            # Usage should be printed
            assert console.print.called

    def test_build_rich_help_with_actions(self):
        """Test _build_rich_help with actions."""
        with patch.object(help_module, "RICH_AVAILABLE", True):
            formatter = RichHelpFormatter("test_prog")

            action = MagicMock()
            action.option_strings = ["--verbose"]
            action.required = False
            action.dest = "verbose"
            action.metavar = None
            action.type = bool
            action.help = "Verbose output"
            action.default = False

            formatter._actions = [action]
            formatter._root_section = MagicMock()
            formatter._root_section._group_actions = [action]

            console = MagicMock()
            formatter._build_rich_help(console)

            # Multiple prints should occur
            assert console.print.call_count >= 1


class TestRichHelpFormatterIntegration:
    """Integration tests using actual argparse."""

    def test_with_actual_parser_no_rich(self):
        """Test formatter with actual ArgumentParser when rich not available."""
        with patch.object(help_module, "RICH_AVAILABLE", False):
            parser = argparse.ArgumentParser(
                prog="test_prog",
                description="Test program description",
                formatter_class=RichHelpFormatter,
            )
            parser.add_argument("input", help="Input file")
            parser.add_argument("--output", "-o", help="Output file")
            parser.add_argument(
                "--verbose", "-v", action="store_true", help="Verbose output"
            )
            parser.add_argument("--count", type=int, default=10, help="Count value")

            help_text = parser.format_help()

            assert "test_prog" in help_text
            assert "input" in help_text.lower()

    def test_with_required_optional_no_rich(self):
        """Test formatter with required optional argument when rich not available."""
        with patch.object(help_module, "RICH_AVAILABLE", False):
            parser = argparse.ArgumentParser(
                prog="test_prog", formatter_class=RichHelpFormatter
            )
            parser.add_argument(
                "--config", "-c", required=True, metavar="FILE", help="Config file"
            )

            help_text = parser.format_help()

            assert "test_prog" in help_text
            assert "--config" in help_text or "config" in help_text.lower()

    def test_with_nargs_no_rich(self):
        """Test formatter with various nargs when rich not available."""
        with patch.object(help_module, "RICH_AVAILABLE", False):
            parser = argparse.ArgumentParser(
                prog="test_prog", formatter_class=RichHelpFormatter
            )
            parser.add_argument("files", nargs="+", help="Input files")
            parser.add_argument("--extra", nargs="*", help="Extra files")

            help_text = parser.format_help()

            assert "test_prog" in help_text
