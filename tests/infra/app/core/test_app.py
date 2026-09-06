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
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from appinfra.app.core.app import App
from appinfra.app.core.config import ConfigLoader
from appinfra.app.tools.base import Tool, ToolConfig
from appinfra.dot_dict import DotDict
from appinfra.yaml import deep_merge


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


@pytest.mark.unit
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


@pytest.mark.unit
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


@pytest.mark.unit
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


@pytest.mark.unit
class TestCreateTools:
    """Test create_tools method (line 85)."""

    def test_create_tools_does_nothing_by_default(self):
        """Test create_tools is a no-op by default."""
        app = App()

        # Should not raise
        app.create_tools()

        # No tools registered
        assert len(app.registry.list_tools()) == 0


@pytest.mark.unit
class TestCreateArgs:
    """Test create_args method (lines 93-94)."""

    def test_create_args_creates_parser(self):
        """Test create_args creates the argument parser."""
        app = App()

        app.create_args()

        # Parser should now have internal parser created
        assert app.parser.parser is not None


@pytest.mark.unit
class TestAddArgs:
    """Test add_args method (line 98)."""

    def test_add_args_calls_add_default_args(self):
        """Test add_args calls add_default_args."""
        app = App()
        app.parser.create_parser()

        with patch.object(app, "add_default_args") as mock_add_default:
            app.add_args()
            mock_add_default.assert_called_once()


@pytest.mark.unit
class TestAddDefaultArgs:
    """Test add_default_args method (line 102)."""

    def test_add_default_args_calls_log_args(self):
        """Test add_default_args calls add_log_default_args."""
        app = App()
        app.parser.create_parser()

        with patch.object(app, "add_log_default_args") as mock_log_args:
            app.add_default_args()
            mock_log_args.assert_called_once()


@pytest.mark.unit
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
# Test Setup Config
# =============================================================================


@pytest.mark.unit
class TestSetupConfig:
    """Test setup_config method (lines 154-156)."""

    def test_setup_config_with_file_path(self, clean_env):
        """Test setup_config loads from file path."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("key: value\n")
            f.flush()
            temp_path = f.name

        try:
            app = App()
            app._parsed_args = argparse.Namespace()  # Set args to avoid AttributeError
            config = app.setup_config(file_path=temp_path)
            assert config.key == "value"
        finally:
            Path(temp_path).unlink()

    def test_setup_config_with_load_all(self, clean_env):
        """Test setup_config with load_all."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "config.yaml").write_text("loaded: true\n")

            app = App()
            app._parsed_args = argparse.Namespace()
            config = app.setup_config(dir_name=tmpdir, load_all=True)

            assert config.loaded is True


# =============================================================================
# Test Setup Logging From Config
# =============================================================================


@pytest.mark.unit
class TestSetupLoggingFromConfig:
    """Test setup_logging_from_config method (lines 181-188)."""

    def test_setup_logging_from_config(self):
        """Test setup_logging_from_config creates logger."""
        app = App()
        app._parsed_args = argparse.Namespace(
            log_level="debug", log_location=0, log_micros=False
        )

        config = DotDict(
            logging=DotDict(
                level="info",
                location=0,
                micros=False,
                handlers=DotDict(
                    console=DotDict(type="console", enabled=True, stream="stdout")
                ),
            )
        )

        logger, registry = app.setup_logging_from_config(config)

        assert logger is not None
        assert isinstance(logger, logging.Logger)

    def test_setup_logging_from_config_with_args(self):
        """Test setup_logging_from_config with args attribute."""
        app = App()
        app._parsed_args = argparse.Namespace(
            log_level="warning", log_location=1, log_micros=True
        )

        config = DotDict(
            logging=DotDict(
                level="info",
                location=0,
                micros=False,
                handlers=DotDict(
                    console=DotDict(type="console", enabled=True, stream="stdout")
                ),
            )
        )

        logger, registry = app.setup_logging_from_config(config)
        assert logger is not None


# =============================================================================
# Test Configure
# =============================================================================


@pytest.mark.unit
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


@pytest.mark.unit
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
            with patch.object(app.parser, "print_help"):
                with patch("sys.exit"):
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


@pytest.mark.unit
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


@pytest.mark.unit
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
        ):
            with pytest.raises(ValueError, match="test error"):
                app.main()

    def test_main_handles_exception_without_logger(self):
        """Test main handles exception without initialized logger."""
        app = App()
        app.lifecycle._logger = None

        with (
            patch.object(app, "setup", side_effect=ValueError("test error")),
            patch("logging.error") as mock_log_error,
        ):
            with pytest.raises(ValueError):
                app.main()

        mock_log_error.assert_called()

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


@pytest.mark.unit
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


@pytest.mark.unit
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


@pytest.mark.unit
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


@pytest.mark.unit
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


@pytest.mark.unit
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


@pytest.mark.unit
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


@pytest.mark.integration
class TestAppIntegration:
    """Test App integration scenarios."""

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


@pytest.mark.unit
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


# =============================================================================
# Test Deferred Config Loading
# =============================================================================


@pytest.mark.unit
class TestDeferredConfigLoading:
    """Test _load_deferred_config method for config file loading from etc-dir."""

    def test_load_deferred_config_returns_none_when_no_config_path(self):
        """Test that _load_deferred_config returns None when no _config_path is set."""
        app = App()
        app.create_args()

        with patch.object(sys, "argv", ["test"]):
            app._parsed_args = app.parser.parse_args()

        # No _config_path set, should return None
        result = app._load_deferred_configs()
        assert result is None

    def test_load_deferred_config_raises_for_missing_required_file(self):
        """Test that _load_deferred_config raises FileNotFoundError for missing required file."""
        from appinfra.app.builder.app import ConfigFileSpec

        with tempfile.TemporaryDirectory() as tmpdir:
            etc_dir = Path(tmpdir) / "etc"
            etc_dir.mkdir()
            # Don't create the config file

            app = App()
            app._standard_args["etc_dir"] = True
            app._config_files = [  # type: ignore[attr-defined]
                ConfigFileSpec(
                    path="nonexistent.yaml", from_etc_dir=True, optional=False
                )
            ]
            app.create_args()

            with patch.object(sys, "argv", ["test", "--etc-dir", str(etc_dir)]):
                app._parsed_args = app.parser.parse_args()
                with pytest.raises(FileNotFoundError, match="nonexistent.yaml"):
                    app._load_deferred_configs()

    def test_load_deferred_config_returns_none_for_missing_optional_file(self):
        """Test that _load_deferred_config returns None for missing optional file."""
        from appinfra.app.builder.app import ConfigFileSpec

        with tempfile.TemporaryDirectory() as tmpdir:
            etc_dir = Path(tmpdir) / "etc"
            etc_dir.mkdir()
            # Don't create the config file

            app = App()
            app._standard_args["etc_dir"] = True
            app._config_files = [  # type: ignore[attr-defined]
                ConfigFileSpec(
                    path="nonexistent.yaml", from_etc_dir=True, optional=True
                )
            ]
            app.create_args()

            with patch.object(sys, "argv", ["test", "--etc-dir", str(etc_dir)]):
                app._parsed_args = app.parser.parse_args()
                result = app._load_deferred_configs()

            # Should return None, not raise
            assert result is None
            # Warning should be stored for later logging
            assert hasattr(app, "_config_load_warnings")
            assert len(app._config_load_warnings) == 1

    def test_load_deferred_config_raises_for_required_yaml_error(self):
        """Test that _load_deferred_config raises for required configs with YAML errors."""
        import yaml

        from appinfra.app.builder.app import ConfigFileSpec

        with tempfile.TemporaryDirectory() as tmpdir:
            etc_dir = Path(tmpdir) / "etc"
            etc_dir.mkdir()
            # Create an invalid YAML file
            (etc_dir / "invalid.yaml").write_text("invalid: yaml: content: [")

            app = App()
            app._standard_args["etc_dir"] = True
            app._config_files = [  # type: ignore[attr-defined]
                ConfigFileSpec(path="invalid.yaml", from_etc_dir=True, optional=False)
            ]
            app.create_args()

            with patch.object(sys, "argv", ["test", "--etc-dir", str(etc_dir)]):
                app._parsed_args = app.parser.parse_args()
                # Required configs should raise on YAML errors
                with pytest.raises(yaml.YAMLError):
                    app._load_deferred_configs()

    def test_load_deferred_config_stores_error_for_optional_yaml_error(self):
        """Test that _load_deferred_config stores errors for optional configs."""
        from appinfra.app.builder.app import ConfigFileSpec

        with tempfile.TemporaryDirectory() as tmpdir:
            etc_dir = Path(tmpdir) / "etc"
            etc_dir.mkdir()
            # Create an invalid YAML file
            (etc_dir / "invalid.yaml").write_text("invalid: yaml: content: [")

            app = App()
            app._standard_args["etc_dir"] = True
            app._config_files = [  # type: ignore[attr-defined]
                ConfigFileSpec(path="invalid.yaml", from_etc_dir=True, optional=True)
            ]
            app.create_args()

            with patch.object(sys, "argv", ["test", "--etc-dir", str(etc_dir)]):
                app._parsed_args = app.parser.parse_args()
                result = app._load_deferred_configs()

            # Should return None, not raise (optional)
            assert result is None

            # Error should be stored for later logging
            assert hasattr(app, "_config_load_errors")
            assert len(app._config_load_errors) == 1
            filename, error = app._config_load_errors[0]
            assert filename == "invalid.yaml"
            assert isinstance(error, Exception)

    def test_load_deferred_config_loads_and_merges_config(self, clean_env):
        """Test that _load_deferred_config loads and returns config info."""
        from appinfra.app.builder.app import ConfigFileSpec

        with tempfile.TemporaryDirectory() as tmpdir:
            etc_dir = Path(tmpdir) / "etc"
            etc_dir.mkdir()
            (etc_dir / "app.yaml").write_text("test_key: test_value\n")

            app = App()
            app._standard_args["etc_dir"] = True
            app._config_files = [  # type: ignore[attr-defined]
                ConfigFileSpec(path="app.yaml", from_etc_dir=True, optional=False)
            ]
            app.create_args()

            with patch.object(sys, "argv", ["test", "--etc-dir", str(etc_dir)]):
                app._parsed_args = app.parser.parse_args()
                result = app._load_deferred_configs()

            # Should return config info
            assert result is not None
            assert result["files"] == ["app.yaml"]
            # Use realpath for comparison (macOS /var is symlink to /private/var)
            assert os.path.realpath(result["etc_dir"]) == os.path.realpath(str(etc_dir))
            # Config should be loaded
            assert hasattr(app.config, "test_key")
            assert app.config.test_key == "test_value"

    def test_is_direct_path_absolute(self):
        """Test _is_direct_path returns True for absolute paths."""
        app = App()
        assert app._is_direct_path("/etc/app/config.yaml") is True
        assert app._is_direct_path("/config.yaml") is True

    def test_is_direct_path_explicit_relative(self):
        """Test _is_direct_path returns True for ./ and ../ paths."""
        app = App()
        assert app._is_direct_path("./config.yaml") is True
        assert app._is_direct_path("../config.yaml") is True
        assert app._is_direct_path("./subdir/config.yaml") is True

    def test_is_direct_path_plain_filename(self):
        """Test _is_direct_path returns False for plain filenames."""
        app = App()
        assert app._is_direct_path("config.yaml") is False
        assert app._is_direct_path("subdir/config.yaml") is False

    def test_is_direct_path_tilde(self):
        """Test _is_direct_path returns True for tilde-prefixed paths."""
        app = App()
        assert app._is_direct_path("~/config.yaml") is True
        assert app._is_direct_path("~/.config/app.yaml") is True
        assert app._is_direct_path("~/subdir/config.yaml") is True

    def test_is_direct_path_tilde_in_middle_is_absolute(self):
        """Tilde in middle of absolute path is not a home-dir reference."""
        app = App()
        # /a/b/~/c is absolute (starts with /), tilde is literal dirname
        assert app._is_direct_path("/a/b/~/c") is True  # absolute path
        # ../~/config.yaml starts with ../, tilde is literal
        assert app._is_direct_path("../~/config.yaml") is True  # explicit relative

    def test_is_direct_path_tilde_no_slash_is_bare_filename(self):
        """~config.yaml is NOT a valid home-dir reference, it's a bare filename.

        expanduser() raises RuntimeError for ~username when the user doesn't exist,
        so we must not recognize ~config.yaml as a direct path — only ~/... or ~.
        """
        app = App()
        # ~config.yaml looks like it starts with ~ but is NOT a valid home expansion
        assert app._is_direct_path("~config.yaml") is False
        assert app._is_direct_path("~foo") is False
        # But bare ~ alone is valid (expands to home directory)
        assert app._is_direct_path("~") is True

    def test_load_direct_config_absolute_path(self, clean_env):
        """Test _load_direct_config loads from absolute path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"
            config_path.write_text("direct_key: direct_value\n")

            app = App()
            result = app._load_direct_config(str(config_path))

            assert result is not None
            assert result["files"] == ["config.yaml"]
            assert hasattr(app.config, "direct_key")
            assert app.config.direct_key == "direct_value"

    def test_load_direct_config_relative_path(self, clean_env):
        """Test _load_direct_config loads from relative path (resolved to cwd)."""
        import os

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"
            config_path.write_text("relative_key: relative_value\n")

            # Change to tmpdir so relative path works
            old_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)
                app = App()
                result = app._load_direct_config("./config.yaml")

                assert result is not None
                assert hasattr(app.config, "relative_key")
                assert app.config.relative_key == "relative_value"
            finally:
                os.chdir(old_cwd)

    def test_load_direct_config_tilde_path(self, clean_env, monkeypatch, tmp_path):
        """Test _load_direct_config expands tilde and loads from home directory."""
        monkeypatch.setenv("HOME", str(tmp_path))
        config_path = tmp_path / "config.yaml"
        config_path.write_text("tilde_key: tilde_value\n")

        app = App()
        result = app._load_direct_config("~/config.yaml")

        assert result is not None
        assert hasattr(app.config, "tilde_key")
        assert app.config.tilde_key == "tilde_value"

    def test_load_direct_config_dot_tilde_normalized(
        self, clean_env, monkeypatch, tmp_path
    ):
        """./~/config.yaml normalizes to ~/config.yaml, then expands."""
        monkeypatch.setenv("HOME", str(tmp_path))
        config_path = tmp_path / "config.yaml"
        config_path.write_text("dot_tilde_key: dot_tilde_value\n")

        app = App()
        # Path('./~/config.yaml') normalizes to '~/config.yaml'
        result = app._load_direct_config("./~/config.yaml")

        assert result is not None
        assert hasattr(app.config, "dot_tilde_key")
        assert app.config.dot_tilde_key == "dot_tilde_value"

    def test_load_direct_config_tilde_in_middle_is_literal(self, clean_env, tmp_path):
        """Tilde in middle of path is a literal directory name, not expanded."""
        # Create /tmp.../a/~/config.yaml (literal ~ directory)
        tilde_dir = tmp_path / "a" / "~"
        tilde_dir.mkdir(parents=True)
        config_path = tilde_dir / "config.yaml"
        config_path.write_text("literal_tilde_key: literal_value\n")

        app = App()
        result = app._load_direct_config(str(config_path))

        assert result is not None
        assert hasattr(app.config, "literal_tilde_key")
        assert app.config.literal_tilde_key == "literal_value"

    def test_load_direct_config_dot_tilde_filename(
        self, clean_env, monkeypatch, tmp_path
    ):
        """./~config.yaml is literal, not expanded as ~username.

        expanduser() raises RuntimeError for ~username when user doesn't exist.
        The ./ prefix makes it a direct path, but we must not call expanduser()
        on paths that don't start with ~.
        """
        monkeypatch.chdir(tmp_path)
        config_path = tmp_path / "~config.yaml"
        config_path.write_text("dot_tilde_key: dot_tilde_value\n")

        app = App()
        result = app._load_direct_config("./~config.yaml")

        assert result is not None
        assert hasattr(app.config, "dot_tilde_key")
        assert app.config.dot_tilde_key == "dot_tilde_value"

    def test_load_direct_config_missing_file_raises(self):
        """Test _load_direct_config raises for missing file."""
        app = App()
        with pytest.raises(FileNotFoundError, match="Config file not found"):
            app._load_direct_config("/nonexistent/config.yaml")

    def test_log_config_loading_logs_stored_errors(self):
        """Test that _log_config_loading logs errors stored during deferred loading."""
        from unittest.mock import MagicMock

        app = App()
        # Simulate stored errors from failed config loading
        app._config_load_errors = [
            ("config.yaml", ValueError("test error")),
            ("other.yaml", RuntimeError("another error")),
        ]

        # Mock the logger
        mock_logger = MagicMock()
        app.lifecycle._logger = mock_logger

        # Call _log_config_loading
        app._log_config_loading(None)

        # Verify warnings were logged for each error
        assert mock_logger.warning.call_count == 2
        calls = mock_logger.warning.call_args_list

        # First error
        assert calls[0][0][0] == "failed to load config file"
        assert calls[0][1]["extra"]["file"] == "config.yaml"
        assert isinstance(calls[0][1]["extra"]["exception"], ValueError)

        # Second error
        assert calls[1][0][0] == "failed to load config file"
        assert calls[1][1]["extra"]["file"] == "other.yaml"
        assert isinstance(calls[1][1]["extra"]["exception"], RuntimeError)

        # Errors should be cleared after logging
        assert app._config_load_errors == []


@pytest.mark.unit
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


@pytest.mark.unit
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


@pytest.mark.unit
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


@pytest.mark.unit
class TestSubprocessContextMethod:
    """Test App.subprocess_context() helper method."""

    def test_subprocess_context_returns_context_manager(self):
        """Test that subprocess_context() returns a SubprocessContext."""
        from appinfra.subprocess import SubprocessContext

        app = App()
        app.config = DotDict(logging=DotDict(level="info", location=0))

        ctx = app.subprocess_context()

        assert isinstance(ctx, SubprocessContext)
        # Clean up
        ctx._lg.handlers.clear()

    def test_subprocess_context_creates_fresh_logger(self):
        """Test that subprocess_context() creates a new logger instance."""
        app = App()
        app.config = DotDict(logging=DotDict(level="debug", location=1))
        app.lifecycle._logger = Mock()

        ctx = app.subprocess_context()

        # The context should have its own logger, not the app's
        assert ctx._lg is not app.lifecycle._logger
        # Clean up
        ctx._lg.handlers.clear()

    def test_subprocess_context_passes_config_files(self):
        """Test that subprocess_context() passes config_files."""
        app = App()
        app.config = DotDict(logging=DotDict(level="info", location=0))
        # Simulate loaded config paths
        app._loaded_config_paths = [  # type: ignore[attr-defined]
            ("/etc/myapp", "config.yaml", "/etc/myapp/config.yaml")
        ]

        ctx = app.subprocess_context()

        assert ctx._config_files == ["/etc/myapp/config.yaml"]
        # Clean up
        ctx._lg.handlers.clear()

    def test_subprocess_context_handles_missing_config(self):
        """Test subprocess_context() works without loaded config paths."""
        app = App()
        app.config = DotDict(logging=DotDict(level="info", location=0))
        # No _loaded_config_paths set

        ctx = app.subprocess_context()

        assert ctx._config_files == []
        # Clean up
        ctx._lg.handlers.clear()

    def test_subprocess_context_handle_signals_parameter(self):
        """Test that handle_signals parameter is passed correctly."""
        app = App()
        app.config = DotDict(logging=DotDict(level="info", location=0))

        ctx = app.subprocess_context(handle_signals=False)

        # Can't easily verify signal handling is disabled, but no exception means success
        assert ctx is not None
        # Clean up
        ctx._lg.handlers.clear()

    def test_subprocess_context_can_be_used_as_context_manager(self):
        """Test that subprocess_context() works with 'with' statement."""
        app = App()
        app.config = DotDict(logging=DotDict(level="info", location=0))

        with app.subprocess_context(handle_signals=False) as ctx:
            assert ctx.running is True

        # After exiting, running should be True (only signal sets it to False)
        # Actually verify it doesn't raise


@pytest.mark.unit
class TestCreateConfigWatcherMethod:
    """Test App.create_config_watcher() helper method."""

    def test_create_config_watcher_returns_watcher_when_configured(self):
        """Test that create_config_watcher() returns a ConfigWatcher."""
        from appinfra.config import ConfigWatcher

        app = App()
        app.lifecycle._logger = Mock()
        # Simulate loaded config paths
        app._loaded_config_paths = [  # type: ignore[attr-defined]
            ("/etc/myapp", "config.yaml", "/etc/myapp/config.yaml")
        ]

        watcher = app.create_config_watcher()

        assert isinstance(watcher, ConfigWatcher)

    def test_create_config_watcher_returns_none_when_no_loaded_paths(self):
        """Test that create_config_watcher() returns None without loaded paths."""
        app = App()
        app.lifecycle._logger = Mock()
        # No _loaded_config_paths

        watcher = app.create_config_watcher()

        assert watcher is None

    def test_create_config_watcher_returns_none_when_empty_loaded_paths(self):
        """Test that create_config_watcher() returns None with empty loaded paths."""
        app = App()
        app.lifecycle._logger = Mock()
        app._loaded_config_paths = []  # type: ignore[attr-defined]

        watcher = app.create_config_watcher()

        assert watcher is None

    def test_create_config_watcher_returns_none_when_no_paths(self):
        """Test that create_config_watcher() returns None when paths are missing."""
        app = App()
        app.lifecycle._logger = Mock()
        # No _loaded_config_paths

        watcher = app.create_config_watcher()

        assert watcher is None

    def test_create_config_watcher_uses_app_logger(self):
        """Test that create_config_watcher() uses the app's logger."""
        app = App()
        mock_logger = Mock()
        app.lifecycle._logger = mock_logger
        app._loaded_config_paths = [  # type: ignore[attr-defined]
            ("/etc/myapp", "config.yaml", "/etc/myapp/config.yaml")
        ]

        watcher = app.create_config_watcher()

        assert watcher._lg is mock_logger


@pytest.mark.unit
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


@pytest.mark.unit
class TestEtcDirResolutionOnOptIn:
    """Verify _resolve_etc_dir_if_opted_in populates _etc_dir from --etc-dir or
    the fallback chain when the standard arg is enabled — even without any
    registered config files."""

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

    def test_fallback_resolves_when_flag_omitted(self, monkeypatch, tmp_path):
        cwd_etc = tmp_path / "etc"
        cwd_etc.mkdir()
        monkeypatch.chdir(tmp_path)

        app = App()
        app._standard_args = {"etc_dir": True}
        app._parsed_args = argparse.Namespace(etc_dir=None)

        app._resolve_etc_dir_if_opted_in()

        assert Path(app.etc_dir).resolve() == cwd_etc.resolve()

    def test_fallback_miss_is_tolerant(self, monkeypatch, tmp_path):
        """When the user didn't pass --etc-dir and no fallback exists, leave
        _etc_dir unset (app.etc_dir returns None) — don't raise."""
        empty = tmp_path / "empty"
        empty.mkdir()
        monkeypatch.chdir(empty)

        app = App()
        app._standard_args = {"etc_dir": True}
        app._parsed_args = argparse.Namespace(etc_dir=None)

        # Force the project-root and package-etc fallbacks to also fail.
        from appinfra.config import config as _config_mod

        monkeypatch.setattr(
            _config_mod,
            "get_etc_dir",
            lambda: (_ for _ in ()).throw(FileNotFoundError("no project root")),
        )
        monkeypatch.setattr(_config_mod, "_get_package_etc_dir", lambda: None)

        app._resolve_etc_dir_if_opted_in()  # must not raise

        assert app.etc_dir is None

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


@pytest.mark.unit
class TestResolveEtcDirReExport:
    """Verify resolve_etc_dir is reachable from the public import paths."""

    def test_appinfra_root_namespace(self):
        from appinfra import resolve_etc_dir as r1
        from appinfra.config import resolve_etc_dir as r2

        assert r1 is r2

    def test_appinfra_app_namespace(self):
        from appinfra.app import resolve_etc_dir as r1
        from appinfra.config import resolve_etc_dir as r2

        assert r1 is r2


@pytest.mark.unit
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
        from appinfra.app.builder.app import ConfigSpecV1

        return ConfigSpecV1(
            namespace="myorg",
            package="myapp",
            base_config=self._make_bundled_base(tmp_path),
        )

    def test_custom_etc_dir_loads_from_user_path(self, monkeypatch, tmp_path):
        # Clear CI env vars that trigger UndeclaredConfigPathError on minimal test configs
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
        assert app._project_root == custom.resolve()
        assert result["etc_dir"] == str(custom.resolve())

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
        assert app._project_root == spec.base_config.parent.resolve()

    def test_bundled_base_when_no_custom_and_no_overlay(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "nonexistent"))
        monkeypatch.setenv("XDG_CONFIG_DIRS", str(tmp_path / "nonexistent-sys"))
        spec = self._make_spec(tmp_path)

        app = App()
        app._config_spec = spec
        app._parsed_args = argparse.Namespace(etc_dir=None)

        app._load_config_spec()

        assert app.config.origin == "bundled"
        assert app._project_root == spec.base_config.parent.resolve()

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
        assert app._project_root == target.parent.resolve()

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
        assert app._project_root == target.parent.resolve()

    def test_load_and_merge_config_dispatches_to_spec_branch(
        self, monkeypatch, tmp_path
    ):
        """When a spec is set, _load_and_merge_config takes the v1 branch and
        never touches the deferred/direct file-loading path."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "nonexistent"))
        monkeypatch.setenv("XDG_CONFIG_DIRS", str(tmp_path / "nonexistent-sys"))
        spec = self._make_spec(tmp_path)

        app = App()
        app._config_spec = spec
        app._parsed_args = argparse.Namespace(config=None, etc_dir=None)

        # Deferred/direct paths would raise if invoked with these args.
        called = {"deferred": False, "direct": False}
        monkeypatch.setattr(
            app,
            "_load_deferred_configs",
            lambda: called.__setitem__("deferred", True),
        )
        monkeypatch.setattr(
            app,
            "_load_direct_config",
            lambda *a, **kw: called.__setitem__("direct", True),
        )

        app._load_and_merge_config()

        assert called == {"deferred": False, "direct": False}
        assert app.config.origin == "bundled"

    def test_populates_loaded_config_paths(self, monkeypatch, tmp_path):
        """_load_config_spec populates _loaded_config_paths for API parity."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "nonexistent"))
        monkeypatch.setenv("XDG_CONFIG_DIRS", str(tmp_path / "nonexistent-sys"))
        spec = self._make_spec(tmp_path)

        app = App()
        app._config_spec = spec
        app._parsed_args = argparse.Namespace(etc_dir=None)

        app._load_config_spec()

        assert hasattr(app, "_loaded_config_paths")
        assert len(app._loaded_config_paths) == 1
        etc_dir, config_file, full_path = app._loaded_config_paths[0]
        assert etc_dir == str(spec.base_config.parent.resolve())
        assert config_file == "myapp.yaml"
        assert full_path == str(spec.base_config.resolve())
        # Public API should also work
        assert app.loaded_config_paths == app._loaded_config_paths
