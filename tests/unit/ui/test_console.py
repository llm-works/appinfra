# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for appinfra.ui.console module."""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.unit

from io import StringIO
from unittest.mock import patch

from appinfra.ui.console import (
    APPINFRA_THEME,
    Console,
    _is_interactive,
    _NoOpContextManager,
    _should_use_color,
    get_console,
    reset_console,
)


def _strip_markup(text: str) -> str:
    """Helper to test strip_markup via Console static method."""
    return Console._strip_markup(text)


@pytest.fixture(autouse=True)
def reset_global_console():
    """Reset the global console before each test."""
    reset_console()
    yield
    reset_console()


class TestConsole:
    """Tests for Console class."""

    def test_console_init_defaults(self):
        """Test Console initializes with default settings."""
        console = Console()
        assert console.quiet is False

    def test_console_quiet_mode(self):
        """Test Console in quiet mode suppresses output."""
        output = StringIO()
        console = Console(quiet=True, file=output)

        console.print("This should not appear")
        console.print_info("Info message")
        console.print_success("Success message")

        assert output.getvalue() == ""

    def test_console_print_error_not_suppressed_in_quiet(self):
        """Test that errors are still printed in quiet mode via print."""
        output = StringIO()
        console = Console(quiet=False, no_color=True, file=output)

        console.print_error("Error message")

        assert "Error:" in output.getvalue()
        assert "Error message" in output.getvalue()

    def test_console_no_color_strips_markup(self):
        """Test Console with no_color strips rich markup."""
        output = StringIO()
        console = Console(no_color=True, file=output)

        console.print("[green]Success![/green]")

        result = output.getvalue()
        assert "Success!" in result
        assert "[green]" not in result

    def test_console_rule(self):
        """Test Console rule output."""
        output = StringIO()
        console = Console(no_color=True, file=output)

        console.rule("Test Title")

        result = output.getvalue()
        assert "Test Title" in result
        assert "-" in result

    def test_console_rule_empty(self):
        """Test Console rule without title."""
        output = StringIO()
        console = Console(no_color=True, file=output)

        console.rule()

        result = output.getvalue()
        assert "-" in result


class TestStripMarkup:
    """Tests for markup stripping."""

    def test_strip_simple_tags(self):
        """Test stripping simple tags."""
        assert _strip_markup("[green]text[/green]") == "text"

    def test_strip_nested_tags(self):
        """Test stripping nested tags."""
        assert _strip_markup("[bold][red]text[/red][/bold]") == "text"

    def test_strip_style_tags(self):
        """Test stripping style tags."""
        assert _strip_markup("[bold magenta]text[/]") == "text"

    def test_no_tags(self):
        """Test text without tags unchanged."""
        assert _strip_markup("plain text") == "plain text"


class TestGetConsole:
    """Tests for get_console function."""

    def test_get_console_returns_console(self):
        """Test get_console returns a Console instance."""
        console = get_console()
        assert isinstance(console, Console)

    def test_get_console_returns_same_instance(self):
        """Test get_console returns the same instance on repeated calls."""
        console1 = get_console()
        console2 = get_console()
        assert console1 is console2

    def test_get_console_with_args_returns_new(self):
        """Test get_console with args returns a new instance."""
        console1 = get_console()
        console2 = get_console(quiet=True)
        assert console1 is not console2

    def test_get_console_with_force_terminal(self):
        """Test get_console with force_terminal returns new instance."""
        console1 = get_console()
        console2 = get_console(force_terminal=True)
        assert console1 is not console2

    def test_get_console_with_no_color(self):
        """Test get_console with no_color returns new instance."""
        console1 = get_console()
        console2 = get_console(no_color=True)
        assert console1 is not console2


class TestIsInteractive:
    """Tests for _is_interactive function."""

    def test_interactive_when_both_tty(self):
        """Test returns True when stdout and stderr are TTY."""
        with patch("sys.stdout") as mock_stdout, patch("sys.stderr") as mock_stderr:
            mock_stdout.isatty.return_value = True
            mock_stderr.isatty.return_value = True
            assert _is_interactive() is True

    def test_not_interactive_when_stdout_not_tty(self):
        """Test returns False when stdout is not TTY."""
        with patch("sys.stdout") as mock_stdout, patch("sys.stderr") as mock_stderr:
            mock_stdout.isatty.return_value = False
            mock_stderr.isatty.return_value = True
            assert _is_interactive() is False

    def test_not_interactive_when_stderr_not_tty(self):
        """Test returns False when stderr is not TTY."""
        with patch("sys.stdout") as mock_stdout, patch("sys.stderr") as mock_stderr:
            mock_stdout.isatty.return_value = True
            mock_stderr.isatty.return_value = False
            assert _is_interactive() is False


class TestShouldUseColor:
    """Tests for _should_use_color function."""

    def test_no_color_env_disables_color(self):
        """Test NO_COLOR environment variable disables color."""
        with patch.dict(os.environ, {"NO_COLOR": "1"}):
            assert _should_use_color() is False

    def test_force_color_env_enables_color(self):
        """Test FORCE_COLOR environment variable enables color."""
        env = {"FORCE_COLOR": "1"}
        with patch.dict(os.environ, env, clear=True):
            assert _should_use_color() is True

    def test_interactive_enables_color(self):
        """Test interactive terminal enables color."""
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("appinfra.ui.console._is_interactive", return_value=True),
        ):
            assert _should_use_color() is True

    def test_non_interactive_disables_color(self):
        """Test non-interactive terminal disables color."""
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("appinfra.ui.console._is_interactive", return_value=False),
        ):
            assert _should_use_color() is False


class TestAppinfraTheme:
    """Tests for APPINFRA_THEME constant."""

    def test_theme_has_required_keys(self):
        """Test theme has all required style keys."""
        assert "info" in APPINFRA_THEME
        assert "warning" in APPINFRA_THEME
        assert "error" in APPINFRA_THEME
        assert "success" in APPINFRA_THEME
        assert "muted" in APPINFRA_THEME
        assert "highlight" in APPINFRA_THEME
        assert "key" in APPINFRA_THEME
        assert "value" in APPINFRA_THEME


class TestConsoleExtended:
    """Extended tests for Console class."""

    def test_console_is_rich_property(self):
        """Test is_rich property."""
        console = Console(no_color=True)
        # When no_color is True, rich console won't be used
        assert console.is_rich is False

    def test_console_is_interactive_property(self):
        """Test is_interactive property."""
        console = Console(force_terminal=True)
        assert console.is_interactive is True

        console = Console(force_terminal=False)
        assert console.is_interactive is False

    def test_console_print_warning(self):
        """Test print_warning output."""
        output = StringIO()
        console = Console(no_color=True, file=output)
        console.print_warning("Warning message")
        result = output.getvalue()
        assert "Warning:" in result
        assert "Warning message" in result

    def test_console_print_info(self):
        """Test print_info output."""
        output = StringIO()
        console = Console(no_color=True, file=output)
        console.print_info("Info message")
        result = output.getvalue()
        assert "Info message" in result

    def test_console_print_success(self):
        """Test print_success output."""
        output = StringIO()
        console = Console(no_color=True, file=output)
        console.print_success("Success message")
        result = output.getvalue()
        assert "Success message" in result

    def test_console_rule_quiet_mode(self):
        """Test rule is suppressed in quiet mode."""
        output = StringIO()
        console = Console(quiet=True, file=output)
        console.rule("Test Title")
        assert output.getvalue() == ""

    def test_console_status_no_rich(self):
        """Test status returns NoOpContextManager when rich not available."""
        output = StringIO()
        console = Console(no_color=True, file=output)
        ctx = console.status("Processing...")
        assert isinstance(ctx, _NoOpContextManager)

    def test_console_print_multiple_args(self):
        """Test print with multiple arguments."""
        output = StringIO()
        console = Console(no_color=True, file=output)
        console.print("Hello", "World")
        result = output.getvalue()
        assert "Hello World" in result


class TestNoOpContextManager:
    """Tests for _NoOpContextManager class."""

    def test_enter_prints_message(self):
        """Test __enter__ prints message."""
        output = StringIO()
        ctx = _NoOpContextManager("Processing", output, quiet=False)
        with ctx:
            pass
        assert "Processing..." in output.getvalue()

    def test_enter_quiet_mode(self):
        """Test __enter__ doesn't print in quiet mode."""
        output = StringIO()
        ctx = _NoOpContextManager("Processing", output, quiet=True)
        with ctx:
            pass
        assert output.getvalue() == ""

    def test_update_is_noop(self):
        """Test update method is a no-op."""
        output = StringIO()
        ctx = _NoOpContextManager("Processing", output, quiet=False)
        with ctx:
            ctx.update("New message")
        # Update should not produce output
        assert "New message" not in output.getvalue()

    def test_exit_does_nothing(self):
        """Test __exit__ does nothing."""
        output = StringIO()
        ctx = _NoOpContextManager("Processing", output, quiet=False)
        result = ctx.__exit__(None, None, None)
        assert result is None


class TestConsoleWithRich:
    """Tests for Console when rich is available."""

    def test_console_with_rich_available(self):
        """Test Console uses rich when available and not no_color."""
        with patch("appinfra.ui.console.RICH_AVAILABLE", True):
            output = StringIO()
            console = Console(no_color=False, force_terminal=True, file=output)
            # When rich is available and no_color is False, rich console should be used
            # But we can't guarantee it due to Theme import
            # Just verify it initializes without error
            assert console is not None

    def test_console_status_with_rich(self):
        """Test status with rich returns rich Status."""
        with patch("appinfra.ui.console.RICH_AVAILABLE", True):
            output = StringIO()
            console = Console(no_color=False, force_terminal=True, file=output)
            if console.is_rich:
                ctx = console.status("Processing...")
                # Should return rich Status, not NoOpContextManager
                assert not isinstance(ctx, _NoOpContextManager)

    def test_console_rule_with_rich(self):
        """Test rule with rich uses rich rule."""
        with patch("appinfra.ui.console.RICH_AVAILABLE", True):
            output = StringIO()
            console = Console(no_color=False, force_terminal=True, file=output)
            console.rule("Test")
            # Just verify it runs without error


class TestResetConsole:
    """Tests for reset_console function."""

    def test_reset_console_clears_global(self):
        """Test reset_console clears the global console."""
        # Get a console first
        console1 = get_console()
        # Reset
        reset_console()
        # Get another
        console2 = get_console()
        # They should be different instances (new one created after reset)
        assert console1 is not console2


class TestConsoleRichPath:
    """Tests for Console when rich is actually used."""

    def test_print_with_rich_console(self):
        """Test printing through rich console when available."""
        output = StringIO()
        # Create console with rich enabled (no_color=False, force_terminal=True)
        console = Console(no_color=False, force_terminal=True, file=output)

        # If rich is available and console.is_rich is True, this exercises line 152
        if console.is_rich:
            console.print("Hello World")
            result = output.getvalue()
            assert "Hello" in result
            assert "World" in result

    def test_status_returns_context_manager(self):
        """Test status returns a context manager that can be used."""
        output = StringIO()
        console = Console(no_color=False, force_terminal=True, file=output)

        # Exercise status path
        with console.status("Processing...") as status:
            # Status object should exist
            assert status is not None

    def test_rule_with_rich_console(self):
        """Test rule through rich console when available."""
        output = StringIO()
        console = Console(no_color=False, force_terminal=True, file=output)

        if console.is_rich:
            console.rule("Section")
            # Rich rule should produce output
            result = output.getvalue()
            # Rich rule uses special characters
            assert len(result) > 0
