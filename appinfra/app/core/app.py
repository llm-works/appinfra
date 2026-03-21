"""
Core app class for CLI tools and applications.

This module provides the main App class that orchestrates the entire
application lifecycle including tool registration, argument parsing, and execution.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ...config import Config
from ...dot_dict import DotDict

if TYPE_CHECKING:
    from ...config import ConfigWatcher
    from ...log import Logger
    from ...subprocess import SubprocessContext

from ... import time
from ..cli.commands import CommandHandler
from ..cli.parser import CLIParser
from ..decorators import DecoratorAPI
from ..tools import ToolRegistry
from ..tools.base import Tool
from ..tracing.traceable import Traceable
from .config import ConfigLoader
from .lifecycle import LifecycleManager


class App(Traceable):
    """
    Core app class for CLI tools and applications.

    Provides a framework for building command-line applications with:
    - Tool registration and management
    - Argument parsing and validation
    - Application lifecycle management
    - Logging and configuration
    """

    def __init__(self, config: Config | DotDict | None = None):
        """
        Initialize the app.

        Args:
            config: Application configuration (optional)
        """
        super().__init__()
        # Use empty DotDict if no config provided - defaults are applied later
        # in ConfigLoader.from_args() to allow YAML config to take precedence
        self.config: Config | DotDict = config if config is not None else DotDict()
        self.registry: ToolRegistry = ToolRegistry()
        self.parser: CLIParser = CLIParser()
        self.command_handler: CommandHandler = CommandHandler(self)
        self.lifecycle: LifecycleManager = LifecycleManager(self)
        self._parsed_args: argparse.Namespace | None = None

        # Standard args configuration (set by builder, default: all enabled)
        self._standard_args: dict[str, bool] = {
            "etc_dir": True,
            "log_level": True,
            "log_location": True,
            "log_micros": True,
            "log_topic": True,
            "log_colors": True,
            "log_json": True,
            "quiet": True,
        }

        self._decorators: DecoratorAPI = DecoratorAPI(self)  # Decorator API support
        self._custom_args: list[tuple] = []  # Custom args (from builder)
        self._main_tool: str | None = None  # Main tool (runs without subcommand)
        self._config_watcher: ConfigWatcher | None = None  # Hot-reload watcher

    @property
    def config_watcher(self) -> ConfigWatcher | None:
        """Get the config watcher instance (if hot-reload is enabled)."""
        return self._config_watcher

    def set_main_tool(self, name: str) -> None:
        """
        Set the main tool that runs when no subcommand is specified.

        Args:
            name: Name of the tool to use as main

        Raises:
            ValueError: If main tool is already set or tool doesn't exist
        """
        if self._main_tool is not None:
            raise ValueError(f"Main tool already set: {self._main_tool}")
        # Validation that tool exists happens later when registry is populated
        self._main_tool = name

    def add_tool(self, tool: Tool) -> None:
        """
        Add a tool to the application.

        Automatically sets this app as the tool's parent if not already set,
        establishing the parent-child relationship for config and logger access.
        """
        # Set this app as the tool's parent if not already set
        if tool.parent is None:
            tool.set_parent(self)

        self.registry.register(tool)

    def create_tools(self) -> None:
        """
        Create and register tools for the application.

        Override this method in subclasses to register application-specific tools.
        """
        pass

    def create_args(self) -> None:
        """
        Create the argument parser with default configuration.

        Override this method in subclasses to add custom arguments.
        """
        self.parser.create_parser()
        self.add_args()

    def add_args(self) -> None:
        """Add arguments to the parser."""
        self.add_default_args()
        self._apply_custom_args()

    def _apply_custom_args(self) -> None:
        """Apply any stored custom arguments to the parser."""
        for args, kwargs in self._custom_args:
            self.parser.add_argument(*args, **kwargs)

    def add_default_args(self) -> None:
        """Add default command-line arguments."""
        if self._standard_args.get("etc_dir", True):
            self.add_etc_dir_arg()

        self.add_log_default_args()

    def add_etc_dir_arg(self) -> None:
        """Add etc directory command-line argument."""
        self.parser.add_argument(
            "--etc-dir",
            type=str,
            default=None,
            metavar="DIR",
            help="configuration directory (default: auto-detect ./etc/, project etc/, or package etc/)",
        )

    def add_argument(self, *args: Any, **kwargs: Any) -> None:
        """
        Add a custom command-line argument.

        If called before parser creation, the argument is stored and applied later.
        If called after parser creation, the argument is added immediately.

        Args:
            *args: Positional arguments for argparse.add_argument()
            **kwargs: Keyword arguments for argparse.add_argument()
        """
        if self.parser.parser is not None:
            # Parser already created, add immediately
            self.parser.add_argument(*args, **kwargs)
        else:
            # Store for later application
            self._custom_args.append((args, kwargs))

    def _add_log_argument(self, flag_key: str, *args: Any, **kwargs: Any) -> None:
        """Add a logging argument if enabled in standard args."""
        if self._standard_args.get(flag_key, True):
            self.parser.add_argument(*args, **kwargs)

    def add_log_default_args(self) -> None:
        """Add logging-related command-line arguments."""
        self._add_log_level_arg()
        self._add_log_json_arg()
        self._add_log_location_arg()
        self._add_log_micros_arg()
        self._add_log_topic_arg()
        self._add_log_colors_arg()
        self._add_quiet_arg()

    def _add_log_level_arg(self) -> None:
        """Add log level argument."""
        self._add_log_argument(
            "log_level",
            "-l",
            "--log-level",
            default=None,
            metavar="LEVEL",
            help="log level (default: from config or 'info')",
        )

    def _add_log_location_arg(self) -> None:
        """Add log location argument."""
        self._add_log_argument(
            "log_location",
            "--log-location",
            type=int,
            default=None,
            metavar="DEPTH",
            help="show file locations in logs (depth)",
        )

    def _add_log_micros_arg(self) -> None:
        """Add log micros argument."""
        self._add_log_argument(
            "log_micros",
            "--log-micros",
            action="store_true",
            default=None,
            help="show microseconds timestamps",
        )

    def _add_log_topic_arg(self) -> None:
        """Add log topic argument."""
        self._add_log_argument(
            "log_topic",
            "--log-topic",
            nargs=2,
            action="append",
            dest="log_topics",
            metavar=("PATTERN", "LEVEL"),
            help="set log level for topic pattern (e.g., --log-topic '/infra/db/**' debug)",
        )

    def _add_quiet_arg(self) -> None:
        """Add quiet argument."""
        self._add_log_argument(
            "quiet", "-q", "--quiet", action="store_true", help="disable logging"
        )

    def _add_log_colors_arg(self) -> None:
        """Add no-log-colors argument (disables colors)."""
        self._add_log_argument(
            "log_colors",
            "--no-log-colors",
            action="store_false",
            dest="log_colors",
            default=None,
            help="disable colored log output",
        )

    def _add_log_json_arg(self) -> None:
        """Add log-json argument (enables JSON format)."""
        self._add_log_argument(
            "log_json",
            "--log-json",
            action="store_true",
            default=None,
            help="output logs in JSON format",
        )

    def setup_config(
        self,
        file_path: str | None = None,
        file_name: str | None = None,
        dir_name: str | None = None,
        load_all: bool = False,
    ) -> Any:
        """
        Set up configuration from YAML files with flexible path resolution.

        This method allows loading configuration from various sources:
        - Single file by full path (file_path parameter)
        - Single file by name in a specific directory (file_name + dir_name)
        - Multiple files merged together (load_all=True)

        Args:
            file_path: Full path to a specific config file (takes precedence if provided)
            file_name: Name of config file (e.g., "infra.yaml", "app.yaml")
            dir_name: Directory to search for config files (defaults to "etc" directory)
            load_all: If True, loads and merges all YAML files from dir_name

        Returns:
            Config object with loaded configuration

        Raises:
            FileNotFoundError: If specified config file not found
            ValueError: If neither file_path nor file_name is provided when load_all=False
        """
        from .config import create_config as _create_config

        return _create_config(
            file_path=file_path,
            file_name=file_name,
            dir_name=dir_name,
            load_all=load_all,
            lg=self.lg,
        )

    def setup_logging_from_config(self, config: Any) -> tuple[logging.Logger, Any]:
        """
        Set up logging from the provided configuration object with command-line overrides.

        This method leverages the standalone setup_logging_from_config utility function
        and automatically passes the parsed command-line arguments. Use setup_config()
        to load configuration from files.

        Args:
            config: Configuration object (from setup_config() or other sources)

        Returns:
            Tuple of (configured_logger, handler_registry)

        Raises:
            ValueError: If configuration is invalid
        """
        from .logging_utils import (
            setup_logging_from_config as _setup_logging_from_config,
        )

        # Use the parsed arguments from the app
        args_dict = vars(self.args) if hasattr(self, "args") else {}

        return _setup_logging_from_config(config=config, args=args_dict)

    def configure(self) -> None:
        """
        Configure the application after argument parsing.

        Override this method in subclasses to perform custom configuration
        after command-line arguments have been parsed.
        """
        pass

    def _log_setup_complete(self, start_time: float) -> None:
        """Log application setup completion."""
        config_dict = (
            self.config.to_dict()
            if hasattr(self.config, "to_dict")
            else dict(self.config)
        )
        self.lg.trace(  # type: ignore[attr-defined]
            "app setup complete",
            extra={"after": time.since(start_time), "config": config_dict},
        )

    def setup(self) -> None:
        """Set up the application framework."""
        start_t = time.start()

        self.create_tools()
        self.create_args()
        self.command_handler.setup_subcommands()
        self._parsed_args = self.parser.parse_args()

        # Load and merge configuration
        auto_load_result = self._load_and_merge_config()

        # Initialize lifecycle with final merged config and parsed args
        self.lifecycle.initialize(self.config, args=self._parsed_args)

        # Log configuration loading results
        self._log_config_loading(auto_load_result)

        # Configure application
        self.configure()

        # Check if tool is selected
        self._check_tool_selection()

        self._log_setup_complete(start_t)

    def _load_and_merge_config(self) -> dict | None:
        """
        Load configuration from etc directory and merge with CLI args.

        Returns:
            Dict with 'etc_dir' and 'file' if config was loaded, None otherwise
        """
        # Load deferred config from etc-dir if configured
        load_result = None
        if getattr(self, "_config_from_etc_dir", False):
            load_result = self._load_deferred_config()

        # Apply command-line args to config, preserving loaded YAML sections
        # CLI args override anything loaded from etc directory
        assert self._parsed_args is not None  # Set in setup() before this method
        self.config = ConfigLoader.from_args(
            self._parsed_args, existing_config=self.config
        )

        return load_result

    def _log_config_loading(self, load_result: dict | None) -> None:
        """
        Log configuration loading results.

        Args:
            load_result: Result from loading config file
        """
        # Log any deferred config loading errors
        for filename, error in getattr(self, "_config_load_errors", []):
            self.lg.warning(
                "failed to load config file",
                extra={"file": filename, "exception": error},
            )
        if hasattr(self, "_config_load_errors"):
            self._config_load_errors.clear()

        if load_result:
            self.lg.debug(
                "loaded config from etc",
                extra={
                    "etc_dir": load_result["etc_dir"],
                    "file": load_result["file"],
                },
            )

    def _check_tool_selection(self) -> None:
        """Check if tool is selected and show help if needed."""
        if (
            self._parsed_args is not None
            and hasattr(self._parsed_args, "tool")
            and self._parsed_args.tool is None
            and self.registry.list_tools()
        ):
            self.parser.print_help(sys.stderr)
            sys.exit(0)

    @staticmethod
    def _deep_merge(base: dict, override: dict) -> dict:
        """
        Deep merge two dictionaries recursively.

        Fields in 'override' take precedence over 'base', but nested dictionaries
        are merged recursively rather than replaced entirely. This preserves all
        fields from both sources while maintaining precedence.

        Precedence example:
            base = {"a": 1, "b": {"x": 1, "y": 2}}
            override = {"b": {"y": 3, "z": 4}, "c": 5}
            result = {"a": 1, "b": {"x": 1, "y": 3, "z": 4}, "c": 5}

        Args:
            base: Base dictionary (lower precedence)
            override: Override dictionary (higher precedence)

        Returns:
            Merged dictionary with all fields from both sources
        """
        result = dict(base)  # Start with base

        for key, value in override.items():
            if (
                key in result
                and isinstance(result[key], dict)
                and isinstance(value, dict)
            ):
                # Both are dicts - merge recursively
                result[key] = App._deep_merge(result[key], value)
            else:
                # Override takes precedence (non-dict or only in override)
                result[key] = value

        return result

    def _merge_loaded_and_programmatic_config(self, loaded_config: DotDict) -> DotDict:
        """Merge loaded config with programmatic config, programmatic takes precedence."""
        if self.config and dict(self.config):
            # Deep merge: loaded as base, programmatic takes precedence
            loaded_dict = (
                loaded_config.to_dict()
                if hasattr(loaded_config, "to_dict")
                else dict(loaded_config)
            )
            config_dict = (
                self.config.to_dict()
                if hasattr(self.config, "to_dict")
                else dict(self.config)
            )
            merged = App._deep_merge(loaded_dict, config_dict)
            return DotDict(**merged)
        else:
            # No programmatic config, just use loaded
            return loaded_config

    def _add_config_error(self, filename: str, error: Exception) -> None:
        """Store a config loading error to be logged later."""
        if not hasattr(self, "_config_load_errors"):
            self._config_load_errors: list[tuple[str, Exception]] = []
        self._config_load_errors.append((filename, error))

    def _store_config_paths(self, etc_dir: str, filename: str, full_path: Path) -> None:
        """Store config paths for hot-reload watcher and backwards compat."""
        self._etc_dir = etc_dir  # type: ignore[attr-defined]
        self._config_file = filename  # type: ignore[attr-defined]
        self._config_path = str(full_path)  # type: ignore[attr-defined]

    def _load_deferred_config(self) -> dict | None:
        """Load deferred config file from etc directory (for from_etc_dir=True)."""
        from .config import create_config, resolve_etc_dir

        config_filename = getattr(self, "_config_path", None)
        if not config_filename:
            return None

        try:
            custom_etc_dir = getattr(self._parsed_args, "etc_dir", None)
            etc_dir = str(resolve_etc_dir(custom_etc_dir))
            config_path = Path(etc_dir) / config_filename

            loaded_config = create_config(file_path=str(config_path), lg=None)
            self.config = self._merge_loaded_and_programmatic_config(loaded_config)
            self._store_config_paths(etc_dir, config_filename, config_path)

            return {"etc_dir": etc_dir, "file": config_filename}
        except FileNotFoundError:
            return None  # Config file doesn't exist - expected for optional configs
        except Exception as e:
            self._add_config_error(config_filename, e)  # Store for later logging
            return None

    def run_no_tool(self) -> int:
        """
        Handle the case where no tool is selected.

        Override this method to provide custom behavior when no tool is specified.
        """
        self.lg.error("no tool selected")
        return 1

    def main(self) -> int:
        """
        Main application entry point.

        Sets up the application, resolves tool selection, executes the selected tool,
        and handles the application lifecycle with timing and logging.

        Returns:
            int: Exit code (0 for success, non-zero for error)
        """
        try:
            self.setup()
            return self.run()

        except KeyboardInterrupt:
            # Handle interrupt - signal handler raises KeyboardInterrupt to allow
            # tool code to unwind before shutdown (fixes async cleanup log ordering)
            if hasattr(self, "lifecycle") and self.lifecycle.logger:
                self.lg.info("... interrupted by user")
                # Use signal return code if available (130 for SIGINT, 143 for SIGTERM)
                return_code = 130
                if self.lifecycle._shutdown_manager:
                    return_code = (
                        self.lifecycle._shutdown_manager.get_signal_return_code()
                    )
                return self.lifecycle.shutdown(return_code)
            return 130
        except Exception as e:
            if hasattr(self, "lifecycle") and self.lifecycle.logger:
                self.lg.error("app exception", extra={"exception": e})
                # Call shutdown on exception too for cleanup
                self.lifecycle.shutdown(1)
            else:
                # Fallback to root logger if app logger not available
                logging.error("app error", extra={"exception": e})
            raise  # Always re-raise to preserve stack trace

    def run(self) -> int:
        """Run the application and finalize lifecycle."""
        return_code = self._run()
        # Normal exit path - call shutdown for proper cleanup
        self.lifecycle.shutdown(return_code)
        return return_code

    def _run(self) -> int:
        """Internal run method that executes the selected tool."""
        if self._parsed_args is None:
            self.lg.error("no parsed arguments available")
            return 1

        # Resolve tool name (handle aliases)
        tool_name = self._parsed_args.tool
        if tool_name in self.registry.list_aliases():
            tool_name = self.registry.list_aliases()[tool_name]

        if tool_name:
            # Execute the selected tool
            tool = self.registry.get_tool(tool_name)
            if not tool:
                self.lg.error("tool not found", extra={"tool": tool_name})
                return 1

            self.lifecycle.setup_tool(tool, start=self.lifecycle._start_time)
            return_code = self.lifecycle.execute_tool(tool, args=self._parsed_args)
        else:
            # Handle case where no tool is selected
            self.lg.trace("running in no-tool mode")  # type: ignore[attr-defined]
            return_code = self.run_no_tool()

        return return_code

    def tool(self, *args: Any, **kwargs: Any) -> Callable:
        """
        Decorator to register a tool from a function.

        Provides a decorator-based API for creating tools with less boilerplate.
        The decorated function receives `self` as the first parameter, which is
        the generated Tool instance with full framework access (lg, config, args).

        Example:
            @app.tool(name="analyze", help="Analyze data")
            @app.argument('--file', required=True)
            def analyze(self):
                self.lg.info(f"Analyzing {self.args.file}")
                return 0

        Args:
            *args: Positional arguments passed to DecoratorAPI.tool()
            **kwargs: Keyword arguments passed to DecoratorAPI.tool()

        Returns:
            Decorator function
        """
        return self._decorators.tool(*args, **kwargs)

    @property
    def argument(self) -> Callable:
        """
        Decorator to add command-line arguments to a tool.

        Returns the argument decorator from DecoratorAPI.

        Example:
            @app.tool()
            @app.argument('--file', required=True)
            @app.argument('--verbose', action='store_true')
            def process(self):
                self.lg.info(f"Processing {self.args.file}")

        Returns:
            Argument decorator function
        """
        return self._decorators.argument

    @property
    def args(self) -> argparse.Namespace | None:
        """Get parsed command-line arguments."""
        return self._parsed_args

    @property
    def lg(self) -> Logger:
        """Get the application logger."""
        from typing import cast

        return cast("Logger", self.lifecycle.logger)

    def subprocess_context(self, handle_signals: bool = True) -> SubprocessContext:
        """
        Create a SubprocessContext for use in child processes.

        Creates a fresh logger for the subprocess and wires up config hot-reload.
        Use this in worker processes spawned via multiprocessing.

        Usage:
            with app.subprocess_context() as ctx:
                while ctx.running:
                    # do work
                    pass

        Args:
            handle_signals: Whether to install signal handlers (default True)

        Returns:
            SubprocessContext configured with fresh logger and config watcher
        """
        from ...log import LoggerFactory
        from ...log.config import LogConfig
        from ...subprocess import SubprocessContext

        # Create fresh logger for subprocess (forked memory is isolated)
        config_dict = (
            self.config.to_dict()
            if hasattr(self.config, "to_dict")
            else dict(self.config)
        )
        log_config = LogConfig.from_config(config_dict, "logging")
        lg = LoggerFactory.create_root(log_config)

        return SubprocessContext(
            lg=lg,
            etc_dir=getattr(self, "_etc_dir", None),
            config_file=getattr(self, "_config_file", None),
            handle_signals=handle_signals,
        )

    def create_config_watcher(self) -> ConfigWatcher | None:
        """
        Create a ConfigWatcher for config hot-reload.

        Returns None if etc_dir or config_file are not configured.

        Usage:
            watcher = app.create_config_watcher()
            if watcher:
                reloader = LogConfigReloader(lg)
                watcher.configure(config_file, on_change=reloader)
                watcher.start()

        Returns:
            ConfigWatcher or None if not configured
        """
        from typing import cast as type_cast

        from ...config import ConfigWatcher
        from ...log import Logger

        etc_dir = getattr(self, "_etc_dir", None)
        config_file = getattr(self, "_config_file", None)

        if etc_dir is None or config_file is None:
            return None

        return ConfigWatcher(lg=type_cast(Logger, self.lg), etc_dir=etc_dir)
