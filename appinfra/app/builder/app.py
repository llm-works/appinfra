# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Main AppBuilder class for constructing CLI applications.

The builder is faceted: one block per axis, each closed with ``done()``,
or called with keywords, which returns the AppBuilder directly::

    AppBuilder("myapp")
        .config.with_spec("myorg", "myapp").done()
        .cli.with_flags(etc_dir=True, log=True).done()
        .logging.with_level("info").done()
        .tools.with_tool(MigrateTool()).with_main("migrate").done()
        .lifecycle.with_hook("startup", init_db).done()
        .version.with_semver("1.0.0").done()
        .build()

``.logging`` is the standalone ``LoggingBuilder`` bound to the AppBuilder,
so every method of that builder is available on the block without
re-declaration.

One block is open at a time: ``build()``, opening another block, or a
plugin returning from ``configure()`` with a block open raises, naming
the block and the line that opened it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Self

from ...config import Config, ConfigSpec
from ...dot_dict import DotDict
from ...version import BuildInfo, PackageVersionTracker
from ...yaml import deep_merge
from ..core.app import DEFAULT_STANDARD_ARGS, App
from ..tools.base import Tool, ToolConfig
from ..tracing.traceable import Traceable
from .configurer.block import Block, OpenBlock, caller_location
from .configurer.cli import CliConfigurer
from .configurer.config import ConfigConfigurer
from .configurer.lifecycle import LifecycleConfigurer
from .configurer.logging import LoggingScope
from .configurer.tool import ToolConfigurer
from .configurer.version import VersionConfigurer, _register_startup_hook
from .hook import HookManager
from .plugin import PluginManager

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


def _register_tools_and_commands(
    app: App, tools: list[Tool], commands: list[Command]
) -> None:
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


def _configure_arguments(
    app: App, custom_args: list[tuple[tuple[Any, ...], dict[str, Any]]]
) -> None:
    """Add custom arguments declared on the cli block."""
    for args, kwargs in custom_args:
        app.add_argument(*args, **kwargs)


def _configure_hooks(app: App, hooks: Any) -> None:
    """
    Configure application hooks.

    Args:
        app: App instance
        hooks: HookManager instance
    """
    if hasattr(app, "set_hook_manager"):
        app.set_hook_manager(hooks)


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
    # Config spec; resolved at App.setup() time.
    app._config_spec = builder._config_spec
    app._standard_args = builder._standard_args.copy()
    # _standard_arg_overrides is dict[str, dict[str, Any]] — copy one level deeper
    # than _standard_args (dict[str, bool]) so per-arg overrides don't alias the
    # builder's dicts if the builder is mutated after build().
    app._standard_arg_overrides = {
        name: dict(overrides)
        for name, overrides in builder._standard_arg_overrides.items()
    }
    _set_app_metadata(app, builder._name, builder._description, builder._version)


def _register_components(app: App, builder: AppBuilder) -> None:
    """Register tools, lifecycle managers and arguments on the built App.

    Plugins have already configured the builder by now, so the tool list,
    hooks and custom arguments include their contributions.
    """
    _register_tools_and_commands(app, builder._tools, builder._commands)
    if builder._main_tool:
        app.set_main_tool(builder._main_tool)
    _register_lifecycle_managers(app, builder._hooks, builder._plugins)
    _configure_arguments(app, builder._custom_args)


@dataclass
class Command:
    """Represents a command with a run function."""

    name: str
    run_func: Callable[..., Any]
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


class AppBuilder:
    """
    Fluent, faceted builder for CLI applications.

    Top level carries identity only: the name (constructor), a description
    and an optional ``App`` subclass. Everything else lives on a block:
    ``.config``, ``.cli``, ``.logging``, ``.tools``, ``.lifecycle``,
    ``.version``.
    """

    def __init__(self, name: str | None = None):
        """Initialize the application builder."""
        self._name: str | None = name
        self._description: str | None = None
        self._version: str | None = None
        self._main_cls: type | None = None
        # .config
        self._config: Config | DotDict | None = None
        self._config_spec: ConfigSpec | None = None
        # .cli
        self._standard_args: dict[str, bool] = DEFAULT_STANDARD_ARGS.copy()
        self._standard_arg_overrides: dict[str, dict[str, Any]] = {}
        self._custom_args: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        # .tools
        self._tools: list[Tool] = []
        self._commands: list[Command] = []
        self._main_tool: str | None = None
        self._plugins: PluginManager = PluginManager()
        # .lifecycle
        self._hooks: HookManager = HookManager()
        # .version
        self._version_packages: list[str] = []
        self._version_tracker: PackageVersionTracker | None = None
        self._build_info: BuildInfo | None = None
        self._version_startup_log = True
        self._init_block_state()

    def _init_block_state(self) -> None:
        """State about the blocks themselves rather than what they hold."""
        # The logging scope subclasses the standalone builder and holds its
        # own state, so one instance per builder.
        self._logging_scope: LoggingScope | None = None
        self._open_block: OpenBlock | None = None
        self._built = False

    def with_description(self, description: str) -> Self:
        """Set the application description."""
        self._description = description
        return self

    def with_main_cls(self, cls: type) -> Self:
        """Set the main application class."""
        self._main_cls = cls
        return self

    def _merge_overrides(self, values: Mapping[str, Any]) -> None:
        """Deep-merge a mapping into the programmatic config layer."""
        if self._config is None:
            self._config = values if isinstance(values, DotDict) else DotDict(**values)
        else:
            self._config = self._merge_configs(self._config, DotDict(**values))

    def _merge_configs(
        self, base: Config | DotDict, override: Config | DotDict
    ) -> DotDict:
        """Merge two configs, override takes precedence."""
        base_dict = base.to_dict() if hasattr(base, "to_dict") else dict(base)
        override_dict = (
            override.to_dict() if hasattr(override, "to_dict") else dict(override)
        )
        merged = deep_merge(base_dict, override_dict)
        return DotDict(**merged)

    def build(self) -> App:
        """Build the application with all configured components.

        Builds once: the hook and plugin managers are handed to the App, and
        plugins configure the builder in place, so a second App from the
        same builder would share their state. A build that fails after the
        pre-checks below consumes the builder too. The pre-checks themselves
        change nothing, so a builder they reject stays usable: close the
        block they name and build again.

        Plugins run first, so what they set on any block is realized like
        the app's own declarations: the version tracker and flag, the App's
        config snapshot and its standard flags all come after ``configure()``.
        """
        if self._built:
            raise ValueError(
                "build() was already called on this AppBuilder; it builds "
                "once, so create a new one"
            )
        self._check_blocks_closed()
        self._built = True
        self._plugins.configure_all(self)
        self._check_blocks_closed()
        self._register_version()
        self._add_version_flag()
        app = _create_base_app(self._main_cls, self._config)
        _initialize_foundation(app, self)
        _register_components(app, self)
        _configure_hooks(app, self._hooks)
        return app

    def _check_blocks_closed(self) -> None:
        """Refuse to build over an open block or an unfolded logging scope."""
        if self._open_block is not None:
            raise ValueError(
                f"the {self._open_block.name} block opened at "
                f"{self._open_block.where} is still open; close it with done()"
            )
        if self._logging_scope is not None and self._logging_scope._pending():
            raise ValueError(
                "the logging block has changes made after done(); "
                "close it again so they reach the config"
            )

    def _register_version(self) -> None:
        """Create the package tracker and the startup hook from the version block.

        The tracker covers every package added across the block's openings;
        ``_add_version_flag`` reads it.
        """
        if self._version_packages:
            self._version_tracker = PackageVersionTracker()
            self._version_tracker.track(*self._version_packages)
        if self._version_startup_log and (self._build_info or self._version_tracker):
            _register_startup_hook(self._hooks, self._version_tracker, self._build_info)

    def _add_version_flag(self) -> None:
        """Expose ``-v/--version`` from the version block when the cli flag is on."""
        if not self._standard_args.get("version", False):
            return
        if self._version is None:
            raise ValueError("cli flag 'version' requires .version.with_semver(...)")
        from ...version.actions import VersionWithTrackerAction

        kwargs: dict[str, Any] = {
            "action": VersionWithTrackerAction,
            "app_name": self._name or "app",
            "app_version": self._version,
            "tracker": self._version_tracker,
            "build_info": self._build_info,
            **self._standard_arg_overrides.get("version", {}),
        }
        self._custom_args.append((("-v", "--version"), kwargs))

    # ========================================================================
    # Blocks
    # ========================================================================

    def _open(self, block: Block) -> None:
        """Record ``block`` as the open block; one block is open at a time.

        Every block is closed with ``done()``. Opening another block, or
        building, while one is open is an error: a block left open would
        otherwise lose what was set on it or fold it late. The error names
        the block and where it was opened.
        """
        if self._open_block is not None:
            raise ValueError(
                f"the {self._open_block.name} block opened at "
                f"{self._open_block.where} is still open; close it with done() "
                f"before opening {block.block_name}"
            )
        self._open_block = OpenBlock(block, caller_location())

    def _close(self, block: Block) -> None:
        """Close ``block`` if it is the open one; ``done()`` calls this."""
        if self._open_block is not None and self._open_block.block is block:
            self._open_block = None

    @property
    def config(self) -> ConfigConfigurer:
        """
        Config-source block: spec, programmatic overrides, hot reload.

        Example:
            AppBuilder("myapp").config.with_spec("myorg", "myapp").done()
            AppBuilder("myapp").config(namespace="myorg", name="myapp")
        """
        block = ConfigConfigurer(self)
        self._open(block)
        return block

    @property
    def cli(self) -> CliConfigurer:
        """
        CLI-surface block: standard flags, presentation, custom arguments.

        Example:
            AppBuilder("myapp").cli.with_flags(etc_dir=True, log=True).done()
            AppBuilder("myapp").cli(etc_dir=True, log=True)
        """
        block = CliConfigurer(self)
        self._open(block)
        return block

    @property
    def logging(self) -> LoggingScope:
        """
        Logging block: the standalone ``LoggingBuilder`` bound to this app.

        Example:
            AppBuilder("myapp").logging.with_level("debug").with_micros().done()
            AppBuilder("myapp").logging(level="debug", micros=True)
        """
        if self._logging_scope is None:
            self._logging_scope = LoggingScope(self)
        self._open(self._logging_scope)
        return self._logging_scope

    @property
    def tools(self) -> ToolConfigurer:
        """
        Tools block: tools, commands, plugins, the main tool.

        Example:
            AppBuilder("myapp").tools.with_tool(MyTool()).with_main("run").done()
            AppBuilder("myapp").tools(MyTool(), main="run")
        """
        block = ToolConfigurer(self)
        self._open(block)
        return block

    @property
    def lifecycle(self) -> LifecycleConfigurer:
        """
        Lifecycle block: hooks by event.

        Example:
            AppBuilder("myapp").lifecycle.with_hook("startup", init_db).done()
            AppBuilder("myapp").lifecycle(startup=init_db)
        """
        block = LifecycleConfigurer(self)
        self._open(block)
        return block

    @property
    def version(self) -> VersionConfigurer:
        """
        Version block: semver, build info, tracked packages.

        Example:
            AppBuilder("myapp").version.with_semver("1.0.0").with_build_info().done()
            AppBuilder("myapp").version(semver="1.0.0", build_info=True)
        """
        block = VersionConfigurer(self)
        self._open(block)
        return block


def create_app_builder(name: str) -> AppBuilder:
    """
    Create a new application builder.

    Args:
        name: Name of the application

    Returns:
        AppBuilder instance

    Example:
        app = create_app_builder("myapp").with_description("My app").build()
    """
    return AppBuilder(name)
