"""
Main AppBuilder class for constructing CLI applications.

This module provides the core AppBuilder class that orchestrates
the construction of applications using a fluent API.

The AppBuilder has been refactored to use focused configurers for better
maintainability and testability. Use .tools(), .server(), .logging(),
and .advanced() to access specialized configuration builders.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Self

from ...config import Config
from ...dot_dict import DotDict
from ..core.app import App
from ..server.handlers import Middleware
from ..tools.base import Tool, ToolConfig
from ..tracing.traceable import Traceable
from .configurer.advanced import AdvancedConfigurer
from .configurer.logging import LoggingConfigurer
from .configurer.server import ServerConfigurer
from .configurer.tool import ToolConfigurer
from .configurer.version import VersionConfigurer
from .hook import HookManager
from .plugin import PluginManager
from .validation import ValidationRule


@dataclass
class ConfigFileSpec:
    """Specification for a config file to load."""

    path: str
    from_etc_dir: bool = True
    optional: bool = False


# Helper functions for AppBuilder.build()


def _create_base_app(main_cls: type | None, config: Any) -> App:
    """
    Create base application instance.

    Args:
        main_cls: Optional custom App subclass
        config: Application configuration

    Returns:
        App instance
    """
    return main_cls(config) if main_cls is not None else App(config)


def _set_app_metadata(
    app: App, name: str | None, description: str | None, version: str | None
) -> None:
    """
    Set application metadata (name, description, version).

    Args:
        app: App instance to configure
        name: Application name
        description: Application description
        version: Application version
    """
    if name:
        app.name = name  # type: ignore[attr-defined]
    if description:
        app.description = description  # type: ignore[attr-defined]
    if version:
        app.version = version  # type: ignore[attr-defined]


def _register_tools_and_commands(app: App, tools: list, commands: list) -> None:
    """
    Register tools and commands with application.

    Args:
        app: App instance
        tools: List of Tool instances
        commands: List of Command instances
    """
    for tool in tools:
        app.add_tool(tool)

    for command in commands:
        command_tool = CommandTool(command)
        app.add_tool(command_tool)


def _configure_middleware(app: App, middleware: list, server_config: Any) -> None:
    """
    Add middleware if server is configured.

    Args:
        app: App instance
        middleware: List of middleware
        server_config: Server configuration (None if no server)
    """
    if server_config:
        for mw in middleware:
            if hasattr(app, "add_middleware"):
                app.add_middleware(mw)


def _configure_arguments_and_validation(
    app: App, custom_args: list[tuple], validation_rules: list
) -> None:
    """
    Add custom arguments and validation rules.

    Args:
        app: App instance
        custom_args: List of (args, kwargs) tuples for add_argument
        validation_rules: List of validation rules
    """
    for args, kwargs in custom_args:
        if hasattr(app, "add_argument"):
            app.add_argument(*args, **kwargs)

    if hasattr(app, "add_validation_rule"):
        for rule in validation_rules:
            app.add_validation_rule(rule)


def _configure_hooks(app: App, hooks: Any) -> None:
    """
    Configure application hooks.

    Args:
        app: App instance
        hooks: HookManager instance
    """
    if hasattr(app, "set_hook_manager"):
        app.set_hook_manager(hooks)


def _configure_server_and_logging(
    app: App, server_config: Any, logging_config: Any
) -> None:
    """
    Configure server and logging if specified.

    Args:
        app: App instance
        server_config: Server configuration (optional)
        logging_config: Logging configuration (optional)
    """
    if server_config and hasattr(app, "configure_server"):
        app.configure_server(server_config)

    if logging_config and hasattr(app, "configure_logging"):
        app.configure_logging(logging_config)


def _register_lifecycle_managers(app: App, hooks: Any, plugins: Any) -> None:
    """
    Register component managers with lifecycle for shutdown coordination.

    Args:
        app: App instance
        hooks: HookManager instance (optional)
        plugins: PluginManager instance (optional)
    """
    if not hasattr(app, "lifecycle"):
        return

    lifecycle = app.lifecycle

    # Register hook manager
    if hooks and hasattr(lifecycle, "register_hook_manager"):
        lifecycle.register_hook_manager(hooks)

    # Register plugin manager
    if plugins and hasattr(lifecycle, "register_plugin_manager"):
        lifecycle.register_plugin_manager(plugins)

    # Register database manager if app has one
    if hasattr(app, "db") and hasattr(lifecycle, "register_db_manager"):
        lifecycle.register_db_manager(app.db)


def _initialize_foundation(app: App, builder: AppBuilder) -> None:
    """Initialize app foundation: flags and metadata."""
    # Copy config file specs for deferred loading
    app._config_files = builder._config_files.copy()  # type: ignore[attr-defined]
    # Legacy scalar fields for backward compat
    app._config_path = builder._config_path  # type: ignore[attr-defined, assignment]
    app._config_from_etc_dir = builder._config_from_etc_dir  # type: ignore[attr-defined]
    app._config_optional = builder._config_optional  # type: ignore[attr-defined]
    # Copy etc_dir and config_file for hot-reload support (set for absolute paths)
    if hasattr(builder, "_etc_dir"):
        app._etc_dir = builder._etc_dir  # type: ignore[attr-defined]
    if hasattr(builder, "_config_file"):
        app._config_file = builder._config_file  # type: ignore[attr-defined]
    app._standard_args = builder._standard_args.copy()
    _set_app_metadata(app, builder._name, builder._description, builder._version)


def _register_components(app: App, builder: AppBuilder) -> None:
    """Register all app components: tools, plugins, lifecycle."""
    _register_tools_and_commands(app, builder._tools, builder._commands)
    if builder._main_tool:
        app.set_main_tool(builder._main_tool)
    builder._plugins.configure_all(builder)
    _register_lifecycle_managers(app, builder._hooks, builder._plugins)
    _configure_arguments_and_validation(
        app, builder._custom_args, builder._validation_rules
    )


def _configure_external_services(app: App, builder: AppBuilder) -> None:
    """Configure external services: server, logging, middleware, hooks."""
    _configure_middleware(app, builder._middleware, builder._server_config)
    _configure_hooks(app, builder._hooks)
    _configure_server_and_logging(app, builder._server_config, builder._logging_config)


@dataclass
class Command:
    """Represents a command with a run function."""

    name: str
    run_func: Callable
    aliases: list[str] | None = None
    help_text: str = ""

    def __post_init__(self) -> None:
        if self.aliases is None:
            self.aliases = []


class CommandTool(Tool):
    """Simple tool wrapper for commands with run functions."""

    def __init__(self, command: Command, parent: Traceable | None = None):
        config = ToolConfig(
            name=command.name,
            aliases=command.aliases or [],  # __post_init__ ensures this is never None
            help_text=command.help_text,
        )
        super().__init__(parent, config)
        self._run_func = command.run_func

    def run(self, **kwargs: Any) -> int:
        """Run the command function."""
        try:
            result = self._run_func(**kwargs)
            # If the function returns an int, use it as exit code
            if isinstance(result, int):
                return result
            # Otherwise, assume success
            return 0
        except Exception as e:
            self.lg.error(f"command '{self.name}' failed", extra={"exception": e})
            return 1


@dataclass
class ServerConfig:
    """Configuration for server components."""

    port: int = 8080
    host: str = "localhost"
    ssl_enabled: bool = False
    cors_origins: list[str] | None = None
    timeout: int = 30

    def __post_init__(self) -> None:
        if self.cors_origins is None:
            self.cors_origins = []


@dataclass
class LoggingConfig:
    """Configuration for logging.

    Fields with None defaults will not override config file values during merge.
    Only explicitly set values will take precedence over config files.
    """

    level: str | None = None
    location: int | None = None
    micros: bool | None = None
    format_string: str | None = None
    location_color: str | None = None


class AppBuilder:
    """
    Fluent builder for constructing CLI applications.

    Provides a declarative API for building applications with tools,
    middleware, configuration, and lifecycle management.
    """

    # Default standard args configuration
    _DEFAULT_STANDARD_ARGS: dict[str, bool] = {
        "etc_dir": True,
        "log_level": True,
        "log_location": True,
        "log_micros": True,
        "log_topic": True,
        "quiet": True,
        "log_colors": True,
        "log_json": True,
    }

    def __init__(self, name: str | None = None):
        """Initialize the application builder."""
        self._name: str | None = name
        self._config: Config | DotDict | None = None
        self._config_files: list[ConfigFileSpec] = []  # Track all config files
        # Legacy scalar fields (derived from _config_files for backward compat)
        self._config_path: str | Path | None = None
        self._config_from_etc_dir: bool = False
        self._config_optional: bool = False
        self._server_config: ServerConfig | None = None
        self._logging_config: LoggingConfig | None = None
        self._tools: list[Tool] = []
        self._commands: list[Command] = []
        self._middleware: list[Middleware] = []
        self._validation_rules: list[ValidationRule] = []
        self._hooks: HookManager = HookManager()
        self._plugins: PluginManager = PluginManager()
        self._custom_args: list[tuple] = []
        self._description: str | None = None
        self._version: str | None = None
        self._main_cls: type | None = None
        self._standard_args: dict[str, bool] = self._DEFAULT_STANDARD_ARGS.copy()
        self._main_tool: str | None = None
        # Version tracking
        self._version_tracker: Any | None = None
        self._build_info: Any | None = None

    def with_name(self, name: str) -> Self:
        """Set the application name."""
        self._name = name
        return self

    def with_description(self, description: str) -> Self:
        """Set the application description."""
        self._description = description
        return self

    def with_version(self, version: str) -> Self:
        """Set the application version."""
        self._version = version
        return self

    def _load_config_immediately(self, path: str, optional: bool) -> bool:
        """Load config file immediately. Returns True if loaded, False if skipped."""
        from pathlib import Path

        path_obj = Path(path).resolve()
        try:
            new_config = Config(path)
        except FileNotFoundError:
            if optional:
                return False
            raise FileNotFoundError(f"Config file not found: {path_obj}") from None

        # Merge with existing config (new overrides existing)
        if self._config is not None:
            self._config = self._merge_configs(self._config, new_config)
        else:
            self._config = new_config

        # Track path for hot-reload (last loaded file)
        self._config_path = path
        self._config_from_etc_dir = False
        self._etc_dir = str(path_obj.parent)
        self._config_file = path_obj.name
        return True

    def _merge_configs(
        self, base: Config | DotDict, override: Config | DotDict
    ) -> DotDict:
        """Merge two configs, override takes precedence."""
        base_dict = base.to_dict() if hasattr(base, "to_dict") else dict(base)
        override_dict = (
            override.to_dict() if hasattr(override, "to_dict") else dict(override)
        )
        merged = self._deep_merge_dict(base_dict, override_dict)
        return DotDict(**merged)

    @staticmethod
    def _deep_merge_dict(base: dict, override: dict) -> dict:
        """Deep merge two dicts, override takes precedence."""
        result = base.copy()
        for key, value in override.items():
            if (
                key in result
                and isinstance(result[key], dict)
                and isinstance(value, dict)
            ):
                result[key] = AppBuilder._deep_merge_dict(result[key], value)
            else:
                result[key] = value
        return result

    def with_config_file(
        self, path: str | None = None, from_etc_dir: bool = True, optional: bool = False
    ) -> Self:
        """
        Load configuration from a YAML file.

        Multiple calls are supported - configs are merged in order, with later
        files overriding earlier ones. This enables layered configuration:

            app = (AppBuilder("myapp")
                .with_config_file("base.yaml")           # Base config
                .with_config_file("env.yaml", optional=True)  # Optional overlay
                .build())

        By default, relative paths are resolved from --etc-dir at runtime.
        Absolute paths are always loaded immediately.

        Args:
            path: Path to configuration YAML file. If None, uses the default
                  config filename (infra.yaml or INFRA_DEFAULT_CONFIG_FILE env var).
            from_etc_dir: If True (default), resolve relative paths from --etc-dir.
                          If False, resolve relative paths from current working directory.
                          Absolute paths ignore this parameter.
            optional: If True, silently skip loading if the file doesn't exist.
                      If False (default), raise an error if the file is missing.
                      Note: Syntax errors in existing files still raise.

        Returns:
            Self for method chaining

        Example:
            # Load default config (infra.yaml) from --etc-dir
            app = AppBuilder("myapp").with_config_file().build()

            # Load specific file from --etc-dir
            app = (AppBuilder("myapp")
                .with_config_file("app.yaml")
                .build())

            # Load absolute path
            app = (AppBuilder("myapp")
                .with_config_file("/etc/myapp/config.yaml")
                .build())

            # Load relative to cwd
            app = (AppBuilder("myapp")
                .with_config_file("./local.yaml", from_etc_dir=False)
                .build())

            # Layered config: base + optional environment overlay
            app = (AppBuilder("myapp")
                .with_config_file("config.yaml")
                .with_config_file(".env.yaml", from_etc_dir=False, optional=True)
                .build())
        """
        import os

        from ...config import DEFAULT_CONFIG_FILENAME

        if path is None:
            path = DEFAULT_CONFIG_FILENAME

        # Track all config files for reference
        spec = ConfigFileSpec(path=path, from_etc_dir=from_etc_dir, optional=optional)
        self._config_files.append(spec)

        if os.path.isabs(path) or not from_etc_dir:
            self._load_config_immediately(path, optional)
        else:
            # Defer loading - will be resolved from --etc-dir at runtime
            # Legacy scalar fields updated for backward compat (last deferred wins)
            self._config_path = path
            self._config_from_etc_dir = True
            self._config_optional = optional

        return self

    def with_config(self, config: Config | DotDict) -> Self:
        """Set the application configuration."""
        self._config = config
        # Track path if Config has it
        if hasattr(config, "_config_path"):
            self._config_path = config._config_path
        return self

    def with_main_cls(self, cls: type) -> Self:
        """Set the main application class."""
        self._main_cls = cls
        return self

    def with_main_tool(self, tool: str | Tool) -> Self:
        """
        Set the main tool that runs when no subcommand is specified.

        Args:
            tool: Tool name (str) or Tool instance

        Returns:
            AppBuilder: Self for method chaining

        Example:
            app = builder.with_main_tool("run").build()

            @app.tool(name="run")
            def run_proxy(self):
                ...

            # Or with tool object:
            builder.with_main_tool(my_tool)
        """
        self._main_tool = tool.name if isinstance(tool, Tool) else tool
        return self

    def _validate_standard_arg_name(self, name: str) -> None:
        """Validate that argument name is a valid standard arg."""
        valid_args = {
            "etc_dir",
            "log_level",
            "log_location",
            "log_micros",
            "log_topic",
            "quiet",
            "log_colors",
            "log_json",
        }
        if name not in valid_args:
            raise ValueError(
                f"Invalid standard argument name: '{name}'. "
                f"Valid names are: {', '.join(sorted(valid_args))}"
            )

    def with_standard_args(self, **kwargs: bool) -> Self:
        """
        Control which standard CLI arguments are enabled.

        When called without arguments, enables all standard arguments.
        When called with keyword arguments, sets specific arguments to True/False.

        Args:
            **kwargs: Keyword arguments matching standard arg names (etc_dir, log_level,
                      log_location, log_micros, quiet) with boolean values.

        Returns:
            AppBuilder: Self for method chaining

        Raises:
            ValueError: If invalid argument name or non-boolean value provided

        Examples:
            # Enable all standard args (explicit)
            AppBuilder("myapp").with_standard_args().build()

            # Disable specific args
            AppBuilder("myapp").with_standard_args(log_location=False, log_micros=False).build()

            # After disabling all, enable specific args
            AppBuilder("myapp").without_standard_args().with_standard_args(etc_dir=True).build()
        """
        if not kwargs:
            # No arguments: enable all
            for key in self._standard_args:
                self._standard_args[key] = True
        else:
            # Validate and apply specific settings
            for name, enabled in kwargs.items():
                self._validate_standard_arg_name(name)
                if not isinstance(enabled, bool):
                    raise ValueError(
                        f"Value for '{name}' must be a boolean, got {type(enabled).__name__}"
                    )
                self._standard_args[name] = enabled

        return self

    def without_standard_args(self) -> Self:
        """
        Disable all standard CLI arguments.

        By default, the application framework adds standard arguments like --etc-dir,
        --log-level, --log-location, --log-micros, and -q/--quiet. Use this method
        to disable all of them if you want full manual control.

        You can selectively re-enable specific arguments using with_standard_args():
            AppBuilder("myapp")
                .without_standard_args()
                .with_standard_args(etc_dir=True, log_level=True)
                .build()

        Returns:
            AppBuilder: Self for method chaining

        Example:
            app = AppBuilder("myapp").without_standard_args().build()
        """
        for key in self._standard_args:
            self._standard_args[key] = False
        return self

    def build(self) -> App:
        """Build the application with all configured components."""
        config = self._merge_logging_into_config()
        app = _create_base_app(self._main_cls, config)
        _initialize_foundation(app, self)
        _register_components(app, self)
        _configure_external_services(app, self)
        return app

    def _merge_logging_into_config(self) -> Config | DotDict | None:
        """Merge logging config into base config, skipping None values."""
        if self._logging_config is None:
            return self._config

        from dataclasses import asdict

        from ...dot_dict import DotDict

        # Get non-None logging values
        logging_dict = {
            k: v for k, v in asdict(self._logging_config).items() if v is not None
        }

        if not logging_dict:
            return self._config

        # Merge into config
        if self._config is None:
            return DotDict(logging=DotDict(**logging_dict))

        # Ensure logging section exists
        if not hasattr(self._config, "logging"):
            self._config.logging = DotDict()  # type: ignore[attr-defined]

        # Update logging section with non-None values
        for key, value in logging_dict.items():
            setattr(self._config.logging, key, value)  # type: ignore[attr-defined]

        return self._config

    # ========================================================================
    # Focused Configurers
    # ========================================================================

    @property
    def tools(self) -> ToolConfigurer:
        """
        Access tool configuration builder.

        Returns a focused builder for configuring tools, commands, and plugins.
        Use .done() to return to the main AppBuilder.

        Example:
            app = (AppBuilder("myapp")
                .tools
                    .with_tool(MyTool())
                    .with_plugin(DatabasePlugin())
                    .done()
                .build())

        Returns:
            ToolConfigurer instance for method chaining
        """
        return ToolConfigurer(self)

    @property
    def server(self) -> ServerConfigurer:
        """
        Access server configuration builder.

        Returns a focused builder for configuring server and middleware.
        Use .done() to return to the main AppBuilder.

        Example:
            app = (AppBuilder("myapp")
                .server
                    .with_port(8080)
                    .with_middleware(AuthMiddleware())
                    .done()
                .build())

        Returns:
            ServerConfigurer instance for method chaining
        """
        return ServerConfigurer(self)

    @property
    def logging(self) -> LoggingConfigurer:
        """
        Access logging configuration builder.

        Returns a focused builder for configuring logging.
        Use .done() to return to the main AppBuilder.

        Example:
            app = (AppBuilder("myapp")
                .logging
                    .with_level("debug")
                    .with_micros(True)
                    .done()
                .build())

        Returns:
            LoggingConfigurer instance for method chaining
        """
        return LoggingConfigurer(self)

    @property
    def advanced(self) -> AdvancedConfigurer:
        """
        Access advanced configuration builder.

        Returns a focused builder for hooks, validation, and custom arguments.
        Use .done() to return to the main AppBuilder.

        Example:
            app = (AppBuilder("myapp")
                .advanced
                    .with_hook("startup", on_startup)
                    .with_validation_rule(rule)
                    .done()
                .build())

        Returns:
            AdvancedConfigurer instance for method chaining
        """
        return AdvancedConfigurer(self)

    @property
    def version(self) -> VersionConfigurer:
        """
        Access version tracking configuration builder.

        Configures app version and tracks commit hashes of packages
        that use the appinfra build protocol (_build_info.py).

        Example:
            app = (AppBuilder("myapp")
                .version
                    .with_semver("1.0.0")
                    .with_package("mylib")
                    .done()
                .build())

        Returns:
            VersionConfigurer instance for method chaining
        """
        return VersionConfigurer(self)


def create_app_builder(name: str) -> AppBuilder:
    """
    Create a new application builder.

    Args:
        name: Name of the application

    Returns:
        AppBuilder instance

    Example:
        app = create_app_builder("myapp").with_help("My app").build()
    """
    return AppBuilder(name)
