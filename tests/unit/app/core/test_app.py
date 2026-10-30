# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for app/core/app.py.

Tests key functionality including:
- App initialization and properties
- Tool registration and management
- Argument parsing and setup
- Lifecycle management
- Main execution flow
"""

import argparse
import logging
import os
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from appinfra.app.core.app import App
from appinfra.app.core.config import ConfigLoader
from appinfra.app.tools.base import Tool, ToolConfig
from appinfra.dot_dict import DotDict
from appinfra.yaml import deep_merge
from tests.helpers.fork import forks_in_xdist_worker


def create_test_tool(name: str, aliases: list = None):
    """Helper to create a properly configured test tool."""

    class TestTool(Tool):
        def run(self, args):
            return 0

    config = ToolConfig(name=name, aliases=aliases or [])
    return TestTool(config=config)


# =============================================================================
# Test App Initialization
# =============================================================================


class TestAppInit:
    """Test App initialization (lines 46-55)."""

    def test_default_initialization(self):
        """Test App initializes with defaults."""
        app = App()

        assert app.config is not None
        assert app.registry is not None
        assert app.parser is not None
        assert app.command_handler is not None
        assert app.lifecycle is not None
        assert app._parsed_args is None
        assert app._decorators is not None

    def test_initialization_with_config(self):
        """Test App initializes with provided config."""
        config = DotDict(custom="value", logging=DotDict(level="debug"))
        app = App(config=config)

        assert app.config.custom == "value"
        assert app.config.logging.level == "debug"

    def test_initialization_traceable_parent(self):
        """Test App inherits from Traceable."""
        app = App()

        # Should have Traceable methods
        assert hasattr(app, "set_parent")
        assert hasattr(app, "parent")


# =============================================================================
# Test Tool Registration
# =============================================================================


class TestAddTool:
    """Test add_tool method (lines 65-68)."""

    def test_add_tool_sets_parent(self):
        """Test add_tool sets app as tool's parent."""
        app = App()
        tool = create_test_tool("test_tool")

        app.add_tool(tool)

        assert tool.parent is app

    def test_add_tool_preserves_existing_parent(self):
        """Test add_tool preserves tool's existing parent."""
        from appinfra.app.tracing.traceable import Traceable

        app = App()
        existing_parent = Traceable()  # Must be a real Traceable
        tool = create_test_tool("test_tool")
        tool.set_parent(existing_parent)

        app.add_tool(tool)

        # Parent should still be the existing parent
        assert tool.parent is existing_parent

    def test_add_tool_registers_in_registry(self):
        """Test add_tool registers tool in registry."""
        app = App()
        tool = create_test_tool("simple_test")
        app.add_tool(tool)

        assert "simple_test" in app.registry.list_tools()


# =============================================================================
# Test Main Tool
# =============================================================================


class TestSetMainTool:
    """Test set_main_tool method."""

    def test_set_main_tool(self):
        """Test set_main_tool sets the main tool name."""
        app = App()

        app.set_main_tool("run")

        assert app._main_tool == "run"

    def test_set_main_tool_twice_raises(self):
        """Test set_main_tool raises if called twice."""
        app = App()
        app.set_main_tool("run")

        with pytest.raises(ValueError, match="Main tool already set"):
            app.set_main_tool("other")

    def test_main_tool_default_is_none(self):
        """Test _main_tool defaults to None."""
        app = App()

        assert app._main_tool is None


# =============================================================================
# Test Create Methods
# =============================================================================


class TestCreateTools:
    """Test create_tools method (line 85)."""

    def test_create_tools_does_nothing_by_default(self):
        """Test create_tools is a no-op by default."""
        app = App()

        # Should not raise
        app.create_tools()

        # No tools registered
        assert len(app.registry.list_tools()) == 0


class TestCreateArgs:
    """Test create_args method (lines 93-94)."""

    def test_create_args_creates_parser(self):
        """Test create_args creates the argument parser."""
        app = App()

        app.create_args()

        # Parser should now have internal parser created
        assert app.parser.parser is not None


class TestAddArgs:
    """Test add_args method (line 98)."""

    def test_add_args_calls_add_default_args(self):
        """Test add_args calls add_default_args."""
        app = App()
        app.parser.create_parser()

        with patch.object(app, "add_default_args") as mock_add_default:
            app.add_args()
            mock_add_default.assert_called_once()


class TestAddDefaultArgs:
    """Test add_default_args method (line 102)."""

    def test_add_default_args_calls_log_args(self):
        """Test add_default_args calls add_log_default_args."""
        app = App()
        app.parser.create_parser()

        with patch.object(app, "add_log_default_args") as mock_log_args:
            app.add_default_args()
            mock_log_args.assert_called_once()


class TestAddLogDefaultArgs:
    """Test add_log_default_args method (lines 106-122)."""

    def test_add_log_default_args_adds_log_level(self):
        """Test log-level argument is added when enabled."""
        app = App()
        app._standard_args["log_level"] = True
        app.parser.create_parser()

        app.add_log_default_args()

        # Parse with --log-level
        args = app.parser.parse_args(["--log-level", "debug"])
        assert args.log_level == "debug"

    def test_add_log_default_args_adds_log_location(self):
        """Test log-location argument is added when enabled."""
        app = App()
        app._standard_args["log_location"] = True
        app.parser.create_parser()

        app.add_log_default_args()

        args = app.parser.parse_args(["--log-location", "2"])
        assert args.log_location == 2

    def test_add_log_default_args_adds_log_micros(self):
        """Test log-micros argument is added when enabled."""
        app = App()
        app._standard_args["log_micros"] = True
        app.parser.create_parser()

        app.add_log_default_args()

        args = app.parser.parse_args(["--log-micros"])
        assert args.log_micros is True

    def test_add_log_default_args_adds_quiet(self):
        """Test quiet argument is added when enabled."""
        app = App()
        app._standard_args["quiet"] = True
        app.parser.create_parser()

        app.add_log_default_args()

        args = app.parser.parse_args(["--quiet"])
        assert args.quiet is True

    def test_add_log_default_args_short_flags(self):
        """Test short flags work when enabled."""
        app = App()
        app._standard_args["log_level"] = True
        app._standard_args["quiet"] = True
        app.parser.create_parser()

        app.add_log_default_args()

        args = app.parser.parse_args(["-l", "warning", "-q"])
        assert args.log_level == "warning"
        assert args.quiet is True


# =============================================================================
# Test Configure
# =============================================================================


class TestConfigure:
    """Test configure method (line 197)."""

    def test_configure_does_nothing_by_default(self):
        """Test configure is a no-op by default."""
        app = App()

        # Should not raise
        app.configure()


# =============================================================================
# Test Setup
# =============================================================================


class TestSetup:
    """Test setup method (lines 201-228)."""

    def test_setup_initializes_components(self):
        """Test setup initializes all components."""
        app = App()
        mock_logger = Mock()
        app.lifecycle._logger = mock_logger

        with (
            patch.object(app, "create_tools") as mock_create_tools,
            patch.object(app, "create_args") as mock_create_args,
            patch.object(app.command_handler, "setup_subcommands") as mock_subcommands,
            patch.object(
                app.parser,
                "parse_args",
                return_value=argparse.Namespace(
                    tool=None,
                    quiet=False,
                    log_level="info",
                    log_location=None,
                    log_micros=None,
                ),
            ) as mock_parse,
            patch.object(app.lifecycle, "initialize") as mock_init,
            patch.object(app, "configure") as mock_configure,
        ):
            # Disable print_help to prevent system exit
            with patch.object(app.parser, "print_help"), patch("sys.exit"):
                app.setup()

            mock_create_tools.assert_called_once()
            mock_create_args.assert_called_once()
            mock_subcommands.assert_called_once()
            mock_parse.assert_called_once()
            mock_init.assert_called_once()
            mock_configure.assert_called_once()

    def test_setup_sets_parsed_args(self):
        """Test setup sets _parsed_args."""
        app = App()
        mock_logger = Mock()
        app.lifecycle._logger = mock_logger
        mock_args = argparse.Namespace(
            tool="test",
            quiet=False,
            log_level="info",
            log_location=None,
            log_micros=None,
        )

        with (
            patch.object(app, "create_tools"),
            patch.object(app, "create_args"),
            patch.object(app.command_handler, "setup_subcommands"),
            patch.object(app.parser, "parse_args", return_value=mock_args),
            patch.object(app.lifecycle, "initialize"),
            patch.object(app, "configure"),
        ):
            app.setup()

        assert app._parsed_args == mock_args

    def test_setup_prints_help_when_no_tool(self):
        """Test setup prints help when no tool selected and tools exist (lines 225-226)."""
        app = App()
        mock_logger = Mock()
        app.lifecycle._logger = mock_logger

        # Add a tool so list_tools returns something
        tool = create_test_tool("test_tool")
        app.registry.register(tool)

        with (
            patch.object(app, "create_tools"),
            patch.object(app, "create_args"),
            patch.object(app.command_handler, "setup_subcommands"),
            patch.object(
                app.parser,
                "parse_args",
                return_value=argparse.Namespace(
                    tool=None,
                    quiet=False,
                    log_level="info",
                    log_location=None,
                    log_micros=None,
                ),
            ),
            patch.object(app.lifecycle, "initialize"),
            patch.object(app, "configure"),
            patch.object(app.parser, "print_help") as mock_print_help,
            patch("sys.exit") as mock_exit,
        ):
            app.setup()

        mock_print_help.assert_called_once()
        mock_exit.assert_called_once_with(0)


# =============================================================================
# Test Run No Tool
# =============================================================================


class TestRunNoTool:
    """Test run_no_tool method (lines 239-240)."""

    def test_run_no_tool_returns_error(self):
        """Test run_no_tool logs error and returns 1."""
        app = App()
        app.lifecycle._logger = Mock()

        result = app.run_no_tool()

        assert result == 1
        app.lifecycle._logger.error.assert_called()


# =============================================================================
# Test Main
# =============================================================================


class TestMain:
    """Test main method (lines 252-271)."""

    def test_main_calls_setup_and_run(self):
        """Test main calls setup and run."""
        app = App()

        with (
            patch.object(app, "setup") as mock_setup,
            patch.object(app, "run", return_value=0) as mock_run,
        ):
            result = app.main()

        mock_setup.assert_called_once()
        mock_run.assert_called_once()
        assert result == 0

    @pytest.mark.integration
    def test_main_handles_keyboard_interrupt(self):
        """Test main handles KeyboardInterrupt."""
        import time as std_time

        app = App()
        app.lifecycle._logger = Mock()
        app.lifecycle._lifecycle_logger = Mock()
        app.lifecycle._start_time = std_time.monotonic()

        with patch.object(app, "setup", side_effect=KeyboardInterrupt):
            result = app.main()

        assert result == 130  # Standard SIGINT exit code

    def test_main_handles_keyboard_interrupt_without_logger(self):
        """Test main handles KeyboardInterrupt without initialized logger."""
        app = App()
        app.lifecycle._logger = None

        with patch.object(app, "setup", side_effect=KeyboardInterrupt):
            result = app.main()

        assert result == 130

    @pytest.mark.integration
    def test_main_handles_exception(self):
        """Test main handles exceptions."""
        import time as std_time

        app = App()
        app.lifecycle._logger = Mock()
        app.lifecycle._lifecycle_logger = Mock()
        app.lifecycle._start_time = std_time.monotonic()

        with (
            patch.object(app, "setup", side_effect=ValueError("test error")),
            patch.object(app.lifecycle, "finalize"),
            pytest.raises(ValueError, match="test error"),
        ):
            app.main()

    def test_main_reraises_exception_before_logger_exists(self):
        """A failure inside setup() propagates as is; no logger exists yet to report it."""
        app = App()
        app.lifecycle._logger = None

        with (
            patch.object(app, "setup", side_effect=ValueError("test error")),
            pytest.raises(ValueError, match="test error"),
        ):
            app.main()

        assert app.lifecycle.logger is None

    @pytest.mark.integration
    def test_bare_run_without_tools_reaches_run_no_tool(self):
        """A bare run of an app with no tools ends in run_no_tool, not a crash.

        argparse only creates the ``tool`` dest when subparsers exist, and
        CommandHandler skips them for an empty registry.
        """
        app = App()

        with (
            patch.object(sys, "argv", ["zero-tool-app"]),
            patch("appinfra.app.core.shutdown.signal.signal"),
        ):
            result = app.main()

        assert result == 1

    @pytest.mark.integration
    def test_bare_run_without_tools_uses_run_no_tool_override(self):
        """run_no_tool is the override hook for an app that registers no tools."""

        class NoToolApp(App):
            def run_no_tool(self) -> int:
                return 0

        app = NoToolApp()

        with (
            patch.object(sys, "argv", ["zero-tool-app"]),
            patch("appinfra.app.core.shutdown.signal.signal"),
        ):
            result = app.main()

        assert result == 0


# =============================================================================
# Test Run
# =============================================================================


class TestRun:
    """Test run method (lines 275-277)."""

    def test_run_executes_and_finalizes(self):
        """Test run calls _run and shutdown."""
        app = App()

        with (
            patch.object(app, "_run", return_value=0) as mock_internal_run,
            patch.object(app.lifecycle, "shutdown", return_value=0) as mock_shutdown,
        ):
            result = app.run()

        mock_internal_run.assert_called_once()
        mock_shutdown.assert_called_once_with(0)
        assert result == 0


# =============================================================================
# Test Internal Run
# =============================================================================


class TestInternalRun:
    """Test _run method (lines 282-300)."""

    def test_run_executes_tool(self):
        """Test _run executes selected tool."""
        app = App()
        tool = create_test_tool("executable")
        app.add_tool(tool)
        app._parsed_args = argparse.Namespace(tool="executable")
        app.lifecycle._logger = Mock()

        with (
            patch.object(app.lifecycle, "setup_tool") as mock_setup,
            patch.object(
                app.lifecycle, "execute_tool", return_value=42
            ) as mock_execute,
        ):
            result = app._run()

        mock_setup.assert_called_once()
        mock_execute.assert_called_once()
        assert result == 42

    def test_run_resolves_alias(self):
        """Test _run resolves tool aliases."""
        app = App()
        tool = create_test_tool("original", aliases=["alias1"])
        app.add_tool(tool)
        app._parsed_args = argparse.Namespace(tool="alias1")
        app.lifecycle._logger = Mock()

        with (
            patch.object(app.lifecycle, "setup_tool"),
            patch.object(app.lifecycle, "execute_tool", return_value=0),
        ):
            result = app._run()

        assert result == 0

    def test_run_no_tool_mode(self):
        """Test _run handles no tool selected."""
        app = App()
        app._parsed_args = argparse.Namespace(tool=None)
        app.lifecycle._logger = Mock()

        with patch.object(app, "run_no_tool", return_value=5) as mock_no_tool:
            result = app._run()

        mock_no_tool.assert_called_once()
        assert result == 5

    def test_run_tool_not_found(self):
        """Test _run handles tool not found."""
        app = App()
        app._parsed_args = argparse.Namespace(tool="nonexistent")
        app.lifecycle._logger = Mock()

        result = app._run()

        assert result == 1
        app.lifecycle._logger.error.assert_called()


# =============================================================================
# Test Decorator API
# =============================================================================


class TestToolDecorator:
    """Test tool decorator (line 324)."""

    def test_tool_decorator_returns_callable(self):
        """Test tool decorator returns a callable."""
        app = App()

        decorator = app.tool(name="decorated")

        assert callable(decorator)

    def test_tool_decorator_registers_tool(self):
        """Test tool decorator registers function as tool."""
        app = App()

        @app.tool(name="my_tool", help="My tool help")
        def my_tool_func(self):
            return 0

        # Tool should be registered
        assert "my_tool" in app.registry.list_tools()


class TestArgumentDecorator:
    """Test argument decorator (line 343)."""

    def test_argument_property_returns_callable(self):
        """Test argument property returns a callable."""
        app = App()

        decorator = app.argument

        assert callable(decorator)


# =============================================================================
# Test Properties
# =============================================================================


class TestArgsProperty:
    """Test args property (line 348)."""

    def test_args_returns_parsed_args(self):
        """Test args property returns _parsed_args."""
        app = App()
        mock_args = argparse.Namespace(foo="bar")
        app._parsed_args = mock_args

        assert app.args == mock_args

    def test_args_returns_none_before_parsing(self):
        """Test args returns None before parsing."""
        app = App()

        assert app.args is None


class TestLgProperty:
    """Test lg property (line 353)."""

    def test_lg_returns_lifecycle_logger(self):
        """Test lg property returns lifecycle logger."""
        app = App()
        mock_logger = Mock()
        app.lifecycle._logger = mock_logger

        assert app.lg == mock_logger


# =============================================================================
# Integration Tests
# =============================================================================


class TestAppIntegration:
    """Test App integration scenarios."""

    @pytest.mark.integration
    def test_full_app_lifecycle(self):
        """Test complete app lifecycle with tool execution."""
        app = App()
        tool = create_test_tool("integration")
        app.add_tool(tool)

        # Setup with mocked command line
        with patch("sys.argv", ["test", "integration"]):
            app.create_args()
            app.command_handler.setup_subcommands()
            app._parsed_args = app.parser.parse_args()

            # Apply config
            app.config = ConfigLoader.from_args(app._parsed_args, app.config)
            app.lifecycle.initialize(app.config)

            # Run
            with (
                patch.object(app.lifecycle, "setup_tool"),
                patch.object(app.lifecycle, "execute_tool", return_value=0),
                patch.object(app.lifecycle, "finalize"),
            ):
                result = app.run()

            assert result == 0

    def test_custom_app_subclass(self):
        """Test custom App subclass with overridden methods."""

        class CustomApp(App):
            def create_tools(self):
                self.add_tool(create_test_tool("custom"))

            def configure(self):
                self.custom_configured = True

        app = CustomApp()
        mock_logger = Mock()
        app.lifecycle._logger = mock_logger

        with (
            patch.object(
                app.parser,
                "parse_args",
                return_value=argparse.Namespace(
                    tool="custom",
                    quiet=False,
                    log_level="info",
                    log_location=None,
                    log_micros=None,
                ),
            ),
            patch.object(app.lifecycle, "initialize"),
            patch.object(app.command_handler, "setup_subcommands"),
        ):
            app.create_args()
            app.setup()

        assert "custom" in app.registry.list_tools()
        assert app.custom_configured is True

    def test_decorator_based_tool_creation(self):
        """Test creating tools via decorators."""
        app = App()

        @app.tool(name="decorated_tool", help="A decorated tool")
        def my_decorated_tool(self):
            return 0

        assert "decorated_tool" in app.registry.list_tools()

        # Get the tool and verify it's properly set up
        tool = app.registry.get_tool("decorated_tool")
        assert tool is not None
        assert tool.name == "decorated_tool"


# =============================================================================
# Test --etc-dir Argument and Auto-loading
# =============================================================================


class TestEtcDirArgument:
    """Test --etc-dir command-line argument parsing and handling."""

    def test_etc_dir_argument_exists(self):
        """Test that --etc-dir argument is added when enabled."""
        app = App()
        app._standard_args["etc_dir"] = True
        app.create_args()

        # Parse with --etc-dir
        with patch.object(sys, "argv", ["test", "--etc-dir", "/custom/etc"]):
            app._parsed_args = app.parser.parse_args()

        assert hasattr(app._parsed_args, "etc_dir")
        assert app._parsed_args.etc_dir == "/custom/etc"

    def test_etc_dir_default_is_none(self):
        """Test that --etc-dir defaults to None (auto-detect)."""
        app = App()
        app._standard_args["etc_dir"] = True
        app.create_args()

        with patch.object(sys, "argv", ["test"]):
            app._parsed_args = app.parser.parse_args()

        assert hasattr(app._parsed_args, "etc_dir")
        assert app._parsed_args.etc_dir is None

    def test_etc_dir_stored_in_config(self):
        """Test that etc_dir is stored in config after parsing."""
        app = App()
        app._standard_args["etc_dir"] = True
        app.create_args()

        with patch.object(sys, "argv", ["test", "--etc-dir", "/custom/etc"]):
            app._parsed_args = app.parser.parse_args()

        # Apply args to config
        app.config = ConfigLoader.from_args(app._parsed_args, app.config)

        assert hasattr(app.config, "etc_dir")
        assert app.config.etc_dir == "/custom/etc"


class TestConfigWatcherProperty:
    """Test App.config_watcher property."""

    def test_config_watcher_returns_none_by_default(self):
        """Test that config_watcher is None when not enabled."""
        app = App()
        assert app.config_watcher is None

    def test_config_watcher_returns_watcher_when_set(self):
        """Test that config_watcher returns the watcher when set."""
        from unittest.mock import MagicMock

        app = App()
        mock_watcher = MagicMock()
        app._config_watcher = mock_watcher

        assert app.config_watcher is mock_watcher


class TestAddArgumentAfterParser:
    """Test App.add_argument when parser already exists."""

    def test_add_argument_after_parser_created(self):
        """Test that add_argument works after parser is created."""
        app = App()
        app.create_args()  # Creates the parser

        # Add argument after parser is created
        app.add_argument("--custom-arg", help="A custom argument")

        with patch.object(sys, "argv", ["test", "--custom-arg", "value"]):
            app._parsed_args = app.parser.parse_args()

        assert app._parsed_args.custom_arg == "value"

    def test_add_argument_before_parser_created(self):
        """Test that add_argument stores args when parser not yet created."""
        app = App()
        # Don't create parser yet

        # Add argument before parser is created
        app.add_argument("--custom-arg", help="A custom argument")

        # Should be stored for later
        assert len(app._custom_args) == 1

        # Now create parser - args should be applied
        app.create_args()

        with patch.object(sys, "argv", ["test", "--custom-arg", "value"]):
            app._parsed_args = app.parser.parse_args()

        assert app._parsed_args.custom_arg == "value"


# =============================================================================
# Test Deep Merge Functionality
# =============================================================================


class TestDeepMerge:
    """Test yaml.deep_merge() utility function (consolidated from App and yaml modules)."""

    def test_deep_merge_simple_dicts(self):
        """Test deep merge with simple non-nested dicts."""
        base = {"a": 1, "b": 2}
        override = {"b": 3, "c": 4}

        result = deep_merge(base, override)

        assert result == {"a": 1, "b": 3, "c": 4}

    def test_deep_merge_nested_dicts(self):
        """Test deep merge with nested dictionaries."""
        base = {"a": 1, "b": {"x": 1, "y": 2}}
        override = {"b": {"y": 3, "z": 4}, "c": 5}

        result = deep_merge(base, override)

        assert result == {"a": 1, "b": {"x": 1, "y": 3, "z": 4}, "c": 5}

    def test_deep_merge_preserves_base_fields(self):
        """Test that fields only in base are preserved."""
        base = {"logging": {"location_color": "grey-12"}}
        override = {"logging": {"level": "info", "micros": False}}

        result = deep_merge(base, override)

        assert "location_color" in result["logging"]
        assert result["logging"]["location_color"] == "grey-12"
        assert result["logging"]["level"] == "info"
        assert result["logging"]["micros"] is False

    def test_deep_merge_override_takes_precedence(self):
        """Test that override values take precedence."""
        base = {"a": 1, "b": {"x": 1}}
        override = {"a": 2, "b": {"x": 2}}

        result = deep_merge(base, override)

        assert result["a"] == 2
        assert result["b"]["x"] == 2

    def test_deep_merge_with_non_dict_values(self):
        """Test deep merge when values are not dicts."""
        base = {"a": [1, 2, 3], "b": "string"}
        override = {"a": [4, 5], "c": True}

        result = deep_merge(base, override)

        # Lists are replaced, not merged
        assert result["a"] == [4, 5]
        assert result["b"] == "string"
        assert result["c"] is True

    def test_deep_merge_type_mismatch(self):
        """Test deep merge when types don't match (dict vs non-dict)."""
        base = {"a": {"x": 1}}
        override = {"a": "string"}

        result = deep_merge(base, override)

        # Override replaces when types mismatch
        assert result["a"] == "string"

    def test_deep_merge_empty_dicts(self):
        """Test deep merge with empty dictionaries."""
        assert deep_merge({}, {}) == {}
        assert deep_merge({"a": 1}, {}) == {"a": 1}
        assert deep_merge({}, {"a": 1}) == {"a": 1}

    def test_deep_merge_realistic_config_scenario(self):
        """Test deep merge with realistic config scenario from auto-loading."""
        # Simulates loaded YAML config
        yaml_config = {
            "logging": {
                "level": "info",
                "location": False,
                "location_color": "grey-12",
            },
            "pgserver": {"port": 25432, "user": "postgres"},
        }

        # Simulates default hardcoded config
        default_config = {"logging": {"level": "info", "location": 0, "micros": False}}

        result = deep_merge(yaml_config, default_config)

        # YAML fields should be preserved
        assert result["logging"]["location_color"] == "grey-12"

        # Default fields should be added
        assert result["logging"]["micros"] is False

        # YAML values should win when both present
        assert result["logging"]["location"] == 0  # From default (override)

        # Top-level YAML sections should be preserved
        assert "pgserver" in result
        assert result["pgserver"]["port"] == 25432


# =============================================================================
# Test App Helper Methods (subprocess_context, create_config_watcher)
# =============================================================================


class TestSubprocessContextMethod:
    """Test App.subprocess_context() helper method."""

    def test_subprocess_context_yields_entered_context(self):
        """The block gets an entered SubprocessContext."""
        from appinfra.subprocess import SubprocessContext

        app = App()
        app.config = DotDict(logging=DotDict(level="info", location=0))

        with app.subprocess_context(handle_signals=False) as ctx:
            assert isinstance(ctx, SubprocessContext)
            assert ctx.running is True

    def test_subprocess_context_creates_fresh_logger(self):
        """The context logs through a root logger of its own, not the app's."""
        app = App()
        app.config = DotDict(logging=DotDict(level="debug", location=1))
        app.lifecycle._logger = Mock()

        with app.subprocess_context(handle_signals=False) as ctx:
            assert ctx.lg is not app.lifecycle._logger
            assert ctx.lg.name == "/"

    def test_subprocess_context_passes_config_files(self):
        """Test that subprocess_context() passes the resolved config file."""
        from appinfra.config import ConfigFile

        app = App()
        app.config = DotDict(logging=DotDict(level="info", location=0))
        app._config_source = ConfigFile(
            Path("/etc/myapp/config.yaml"), Path("/etc/myapp"), rule=6
        )

        with (
            patch("appinfra.subprocess.SubprocessContext._start_config_watcher"),
            app.subprocess_context(handle_signals=False) as ctx,
        ):
            assert ctx._config_files == ["/etc/myapp/config.yaml"]

    @pytest.mark.integration
    def test_subprocess_context_forwards_origin(self, tmp_path):
        """Test that subprocess_context() forwards the resolved include root."""
        from appinfra.config import ConfigFile

        etc = tmp_path / "etc"
        app = App()
        app.config = DotDict(logging=DotDict(level="info", location=0))
        app._config_source = ConfigFile(etc / "config.yaml", etc, rule=6)
        app._origin = etc

        with (
            patch("appinfra.subprocess.SubprocessContext._start_config_watcher"),
            app.subprocess_context(handle_signals=False) as ctx,
        ):
            assert ctx._origin == etc.resolve()

    def test_subprocess_context_handles_missing_config(self):
        """Test subprocess_context() works without a resolved config file."""
        app = App()
        app.config = DotDict(logging=DotDict(level="info", location=0))

        with app.subprocess_context(handle_signals=False) as ctx:
            assert ctx._config_files == []

    def test_subprocess_context_handle_signals_parameter(self):
        """handle_signals is passed through to the context."""
        app = App()
        app.config = DotDict(logging=DotDict(level="info", location=0))

        with app.subprocess_context(handle_signals=False) as ctx:
            assert ctx._handle_signals is False

    def test_subprocess_context_destroys_its_root_logger_on_exit(self):
        """The root logger lives exactly as long as the block."""
        app = App()
        app.config = DotDict(logging=DotDict(level="info", location=0))

        with app.subprocess_context(handle_signals=False) as ctx:
            assert logging.root.manager.loggerDict["/"] is ctx.lg

        assert "/" not in logging.root.manager.loggerDict
        assert ctx.lg.handlers == []

    def test_subprocess_context_can_be_entered_once_per_task(self):
        """A worker that runs several tasks enters it again without a name conflict."""
        app = App()
        app.config = DotDict(logging=DotDict(level="info", location=0))

        for _ in range(2):
            with app.subprocess_context(handle_signals=False) as ctx:
                ctx.lg.info("task")

        assert "/" not in logging.root.manager.loggerDict

    def test_subprocess_context_destroys_root_when_block_raises(self):
        """The block's exception propagates and the root logger is still destroyed."""
        app = App()
        app.config = DotDict(logging=DotDict(level="info", location=0))

        with (
            pytest.raises(RuntimeError, match="task failed"),
            app.subprocess_context(handle_signals=False),
        ):
            raise RuntimeError("task failed")

        assert "/" not in logging.root.manager.loggerDict


# Set before the pool forks; the worker inherits it
_POOL_APP: App | None = None


def _pool_task(i: int) -> int:
    """One task in a reused pool worker: enter the app's subprocess context."""
    assert _POOL_APP is not None
    with _POOL_APP.subprocess_context(handle_signals=False) as ctx:
        ctx.lg.info("task", extra={"i": i})
    return i


@pytest.mark.integration
@pytest.mark.skipif(
    "fork" not in __import__("multiprocessing").get_all_start_methods(),
    reason="needs the fork start method",
)
@forks_in_xdist_worker
def test_subprocess_context_in_a_reused_pool_worker():
    """One pool worker runs two tasks, each with its own root logger."""
    import multiprocessing

    from appinfra.log import LogConfig, LoggerFactory

    global _POOL_APP
    _POOL_APP = App()
    _POOL_APP.config = DotDict(logging=DotDict(level="info", location=0))
    parent_root = LoggerFactory.create_root(LogConfig.from_params("info"))
    try:
        with multiprocessing.get_context("fork").Pool(1) as pool:
            results = pool.map_async(_pool_task, [1, 2]).get(timeout=30)
    finally:
        _POOL_APP = None

    assert results == [1, 2]
    # the workers' roots were their own; the parent's is untouched
    assert logging.root.manager.loggerDict["/"] is parent_root


class TestCreateConfigWatcherMethod:
    """Test App.create_config_watcher() helper method."""

    def _resolved(self, app: App, tmp_path: Path) -> Path:
        """Point the app at a resolved config file under tmp_path."""
        from appinfra.config import ConfigFile

        path = tmp_path / "etc" / "config.yaml"
        path.parent.mkdir()
        path.write_text("logging:\n  level: info\n")
        app._config_source = ConfigFile(path, path.parent, rule=6)
        app._origin = path.parent
        return path

    @pytest.mark.integration
    def test_create_config_watcher_returns_watcher_when_configured(self, tmp_path):
        """Test that create_config_watcher() watches the resolved file."""
        from appinfra.config import ConfigWatcher

        app = App()
        app.lifecycle._logger = Mock()
        path = self._resolved(app, tmp_path)

        watcher = app.create_config_watcher()

        assert isinstance(watcher, ConfigWatcher)
        assert watcher._etc_dir == path.parent.resolve()
        assert watcher._config_paths == [path.resolve()]

    def test_create_config_watcher_returns_none_without_resolved_file(self):
        """Test that create_config_watcher() returns None before resolution."""
        app = App()
        app.lifecycle._logger = Mock()

        watcher = app.create_config_watcher()

        assert watcher is None

    @pytest.mark.integration
    def test_create_config_watcher_uses_app_logger(self, tmp_path):
        """Test that create_config_watcher() uses the app's logger."""
        app = App()
        mock_logger = Mock()
        app.lifecycle._logger = mock_logger
        self._resolved(app, tmp_path)

        watcher = app.create_config_watcher()

        assert watcher._lg is mock_logger


class TestAppEtcDirProperty:
    """Test App.etc_dir property exposes the resolved etc directory."""

    def test_returns_cached_value_set_by_config_load(self):
        """If config loading already populated _etc_dir, the property reuses it."""
        app = App()
        app._etc_dir = "/cached/etc"  # type: ignore[attr-defined]

        assert app.etc_dir == "/cached/etc"

    def test_returns_none_when_unset(self):
        """Before any config is resolved, the property returns None."""
        app = App()
        assert app._parsed_args is None
        assert app.etc_dir is None

    def test_returns_none_even_when_parsed_args_present(self):
        """Property does not auto-resolve from _parsed_args; framework must set _etc_dir."""
        app = App()
        app._parsed_args = argparse.Namespace(etc_dir="/some/path")
        # No config loaded yet -> framework hasn't set _etc_dir
        assert app.etc_dir is None

    def test_reflects_framework_set_value(self):
        """Property returns whatever the framework wrote to _etc_dir."""
        app = App()
        app._etc_dir = "/cached/etc"  # type: ignore[attr-defined]

        # Mutating _parsed_args after the framework sets _etc_dir must not affect the value.
        app._parsed_args = argparse.Namespace(etc_dir="/totally/different")

        assert app.etc_dir == "/cached/etc"


class TestEtcDirResolutionOnOptIn:
    """Verify _resolve_etc_dir_if_opted_in populates _etc_dir from an explicit
    --etc-dir when the standard arg is enabled on an app without a spec."""

    @pytest.mark.integration
    def test_explicit_etc_dir_resolves_and_sets(self, tmp_path):
        custom = tmp_path / "myetc"
        custom.mkdir()

        app = App()
        app._standard_args = {"etc_dir": True}
        app._parsed_args = argparse.Namespace(etc_dir=str(custom))

        app._resolve_etc_dir_if_opted_in()

        assert app.etc_dir == str(custom.resolve())

    def test_explicit_bad_etc_dir_raises(self):
        app = App()
        app._standard_args = {"etc_dir": True}
        app._parsed_args = argparse.Namespace(etc_dir="/definitely/not/there")

        with pytest.raises(FileNotFoundError):
            app._resolve_etc_dir_if_opted_in()

    @pytest.mark.integration
    def test_explicit_etc_dir_file_raises(self, tmp_path):
        """A path that exists but is not a directory is rejected too."""
        not_a_dir = tmp_path / "file.yaml"
        not_a_dir.write_text("")

        app = App()
        app._standard_args = {"etc_dir": True}
        app._parsed_args = argparse.Namespace(etc_dir=str(not_a_dir))

        with pytest.raises(FileNotFoundError):
            app._resolve_etc_dir_if_opted_in()

    @pytest.mark.integration
    def test_flag_omitted_leaves_none(self, monkeypatch, tmp_path):
        """Without --etc-dir there is no default: _etc_dir stays unset even
        when a ./etc directory exists beside the cwd."""
        (tmp_path / "etc").mkdir()
        monkeypatch.chdir(tmp_path)

        app = App()
        app._standard_args = {"etc_dir": True}
        app._parsed_args = argparse.Namespace(etc_dir=None)

        app._resolve_etc_dir_if_opted_in()

        assert app.etc_dir is None

    @pytest.mark.integration
    def test_not_opted_in_is_noop(self, tmp_path):
        app = App()
        app._standard_args = {"etc_dir": False}
        app._parsed_args = argparse.Namespace(etc_dir=str(tmp_path))

        app._resolve_etc_dir_if_opted_in()

        assert app.etc_dir is None

    def test_already_set_is_not_overwritten(self):
        """If config loading already set _etc_dir, don't clobber it."""
        app = App()
        app._standard_args = {"etc_dir": True}
        app._etc_dir = "/loaded/by/config/file"  # type: ignore[attr-defined]
        app._parsed_args = argparse.Namespace(etc_dir="/from/cli")

        app._resolve_etc_dir_if_opted_in()

        assert app.etc_dir == "/loaded/by/config/file"


class TestConfigSpecLoading:
    """`_load_config_spec` runs the v1 protocol precedence chain in App.setup."""

    @pytest.fixture(autouse=True)
    def clear_infra_env_overrides(self, monkeypatch):
        """Clear INFRA_* env vars that CI sets, so minimal test configs don't fail."""
        for var in list(os.environ):
            if var.startswith("INFRA_"):
                monkeypatch.delenv(var, raising=False)

    def _make_bundled_base(self, tmp_path: Path) -> Path:
        base = tmp_path / "pkg" / "etc" / "myapp.yaml"
        base.parent.mkdir(parents=True)
        base.write_text("origin: bundled\napi:\n  port: 8000\n")
        return base

    def _make_spec(self, tmp_path: Path):
        from appinfra.config import ConfigSpec

        return ConfigSpec("myorg", "myapp", path=self._make_bundled_base(tmp_path))

    @pytest.mark.integration
    def test_custom_etc_dir_loads_from_user_path(self, monkeypatch, tmp_path):
        custom = tmp_path / "user_etc"
        custom.mkdir()
        (custom / "myapp.yaml").write_text("origin: user\napi:\n  port: 12345\n")
        spec = self._make_spec(tmp_path)

        app = App()
        app._config_spec = spec
        app._parsed_args = argparse.Namespace(etc_dir=str(custom))

        result = app._load_config_spec()

        assert app.config.origin == "user"
        assert app.config.api.port == 12345
        assert app._etc_dir == str(custom.resolve())
        assert app._config_file == "myapp.yaml"
        assert app._origin == custom.resolve()
        assert result["etc_dir"] == str(custom.resolve())
        assert app.config_spec is spec
        assert app.config_path == custom.resolve() / "myapp.yaml"
        assert app._config_source is not None
        assert app._config_source.rule == 3

    def test_config_path_is_none_before_setup(self):
        app = App()
        assert app.config_spec is None
        assert app.config_path is None

    @pytest.mark.integration
    def test_xdg_overlay_loads_when_no_custom(self, monkeypatch, tmp_path):
        xdg_home = tmp_path / "xdg"
        (xdg_home / "myorg").mkdir(parents=True)
        overlay = xdg_home / "myorg" / "myapp.yaml"
        overlay.write_text("origin: overlay\napi:\n  port: 9000\n")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg_home))
        monkeypatch.delenv("XDG_CONFIG_DIRS", raising=False)
        spec = self._make_spec(tmp_path)

        app = App()
        app._config_spec = spec
        app._parsed_args = argparse.Namespace(etc_dir=None)

        app._load_config_spec()

        assert app.config.origin == "overlay"
        assert app._config_file == "myapp.yaml"
        assert app._origin == spec.base_config.parent.resolve()

    @pytest.mark.integration
    def test_bundled_base_when_no_custom_and_no_overlay(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "nonexistent"))
        monkeypatch.setenv("XDG_CONFIG_DIRS", str(tmp_path / "nonexistent-sys"))
        spec = self._make_spec(tmp_path)

        app = App()
        app._config_spec = spec
        app._parsed_args = argparse.Namespace(etc_dir=None)

        app._load_config_spec()

        assert app.config.origin == "bundled"
        assert app._origin == spec.base_config.parent.resolve()

    @pytest.mark.integration
    def test_custom_wins_over_xdg_overlay(self, monkeypatch, tmp_path):
        """Explicit --etc-dir must not be shadowed by an existing overlay."""
        xdg_home = tmp_path / "xdg"
        (xdg_home / "myorg").mkdir(parents=True)
        (xdg_home / "myorg" / "myapp.yaml").write_text("origin: overlay\n")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg_home))
        monkeypatch.delenv("XDG_CONFIG_DIRS", raising=False)
        custom = tmp_path / "user_etc"
        custom.mkdir()
        (custom / "myapp.yaml").write_text("origin: user\n")
        spec = self._make_spec(tmp_path)

        app = App()
        app._config_spec = spec
        app._parsed_args = argparse.Namespace(etc_dir=str(custom))

        app._load_config_spec()

        assert app.config.origin == "user"

    @pytest.mark.integration
    def test_custom_config_absolute_path_wins_over_spec(self, monkeypatch, tmp_path):
        """--config /abs.yaml loads directly, bypasses spec (XDG + base)."""
        xdg_home = tmp_path / "xdg"
        (xdg_home / "myorg").mkdir(parents=True)
        (xdg_home / "myorg" / "myapp.yaml").write_text("origin: overlay\n")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg_home))
        monkeypatch.delenv("XDG_CONFIG_DIRS", raising=False)
        target = tmp_path / "elsewhere" / "custom.yaml"
        target.parent.mkdir()
        target.write_text("origin: cli-config\napi:\n  port: 55555\n")
        spec = self._make_spec(tmp_path)

        app = App()
        app._config_spec = spec
        app._parsed_args = argparse.Namespace(etc_dir=None, config=str(target))

        app._load_config_spec()

        assert app.config.origin == "cli-config"
        assert app.config.api.port == 55555
        assert app._origin == target.parent.resolve()

    @pytest.mark.integration
    def test_custom_config_bare_filename_composes_with_etc_dir(
        self, monkeypatch, tmp_path
    ):
        """--etc-dir /foo --config alt.yaml → /foo/alt.yaml."""
        etc = tmp_path / "user_etc"
        etc.mkdir()
        (etc / "alt.yaml").write_text("origin: user-alt\napi:\n  port: 33333\n")
        # An etc/myapp.yaml also exists but must not be picked (--config wins).
        (etc / "myapp.yaml").write_text("origin: user-default\n")
        spec = self._make_spec(tmp_path)

        app = App()
        app._config_spec = spec
        app._parsed_args = argparse.Namespace(etc_dir=str(etc), config="alt.yaml")

        app._load_config_spec()

        assert app.config.origin == "user-alt"
        assert app.config.api.port == 33333

    @pytest.mark.integration
    def test_custom_config_absolute_ignores_etc_dir(self, monkeypatch, tmp_path):
        """--config /abs.yaml with --etc-dir also set → --etc-dir ignored."""
        etc = tmp_path / "user_etc"
        etc.mkdir()
        (etc / "myapp.yaml").write_text("origin: user-default\n")
        target = tmp_path / "elsewhere.yaml"
        target.write_text("origin: cli-absolute\n")
        spec = self._make_spec(tmp_path)

        app = App()
        app._config_spec = spec
        app._parsed_args = argparse.Namespace(etc_dir=str(etc), config=str(target))

        app._load_config_spec()

        assert app.config.origin == "cli-absolute"
        assert app._origin == target.parent.resolve()

    @pytest.mark.integration
    def test_load_and_merge_config_uses_spec(self, monkeypatch, tmp_path):
        """With a spec set, _load_and_merge_config loads the resolved file
        and layers CLI args over it."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "nonexistent"))
        monkeypatch.setenv("XDG_CONFIG_DIRS", str(tmp_path / "nonexistent-sys"))
        spec = self._make_spec(tmp_path)

        app = App()
        app._config_spec = spec
        app._parsed_args = argparse.Namespace(
            config=None, etc_dir=None, log_level="debug"
        )

        result = app._load_and_merge_config()

        assert result is not None
        assert app.config.origin == "bundled"
        assert app.config.logging.level == "debug"
        assert app.config_path == spec.base_config

    @pytest.mark.integration
    def test_load_and_merge_config_without_spec_loads_nothing(self, tmp_path):
        """An app without a spec ignores --config and --etc-dir for loading."""
        etc = tmp_path / "etc"
        etc.mkdir()
        (etc / "myapp.yaml").write_text("origin: should-not-load\n")

        app = App()
        app._parsed_args = argparse.Namespace(config="myapp.yaml", etc_dir=str(etc))

        result = app._load_and_merge_config()

        assert result is None
        assert not hasattr(app.config, "origin")
        assert app.config_path is None
