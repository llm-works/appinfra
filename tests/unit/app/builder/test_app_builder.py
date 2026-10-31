# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for app/builder/app.py.

Tests key functionality including:
- Helper functions for build process
- Command and CommandTool classes
- AppBuilder initialization, blocks, and build
- Fluent builder API
"""

from unittest.mock import Mock, patch

import pytest

from appinfra.app.builder.app import (
    AppBuilder,
    Command,
    CommandTool,
    _configure_arguments,
    _configure_hooks,
    _create_base_app,
    _register_tools_and_commands,
    _set_app_metadata,
)
from appinfra.app.builder.configurer.cli import CliConfigurer
from appinfra.app.builder.configurer.config import ConfigConfigurer
from appinfra.app.builder.configurer.lifecycle import LifecycleConfigurer
from appinfra.app.builder.configurer.logging import LoggingScope
from appinfra.app.builder.configurer.tool import ToolConfigurer
from appinfra.app.builder.configurer.version import VersionConfigurer
from appinfra.app.builder.plugin import Plugin
from appinfra.app.builder.tool import ToolBuilder
from appinfra.app.core.app import DEFAULT_STANDARD_ARGS
from appinfra.app.tools.base import Tool, ToolConfig
from appinfra.dot_dict import DotDict
from appinfra.log.builder.builder import LoggingBuilder
from appinfra.yaml import deep_merge

# =============================================================================
# Test Helper Functions
# =============================================================================


class TestCreateBaseApp:
    """Test _create_base_app helper function."""

    def test_creates_app_without_main_cls(self):
        """Test creates App instance when no main_cls provided."""
        with patch("appinfra.app.builder.app.App") as MockApp:
            mock_app = Mock()
            MockApp.return_value = mock_app
            config = Mock()

            result = _create_base_app(None, config)

            MockApp.assert_called_once_with(config)
            assert result is mock_app

    def test_creates_custom_app_with_main_cls(self):
        """Test creates custom App subclass when main_cls provided."""
        custom_class = Mock()
        custom_instance = Mock()
        custom_class.return_value = custom_instance
        config = Mock()

        result = _create_base_app(custom_class, config)

        custom_class.assert_called_once_with(config)
        assert result is custom_instance


class TestSetAppMetadata:
    """Test _set_app_metadata helper function."""

    def test_sets_all_metadata(self):
        """Test sets name, description, and version."""
        app = Mock()

        _set_app_metadata(app, "myapp", "My description", "1.0.0")

        assert app.name == "myapp"
        assert app.description == "My description"
        assert app.version == "1.0.0"

    def test_skips_none_values(self):
        """Test skips setting attributes when values are None."""
        app = Mock(spec=["name", "description", "version"])

        _set_app_metadata(app, None, None, None)

        # None values shouldn't have been set
        # (Mock would have recorded the attribute assignment)


class TestRegisterToolsAndCommands:
    """Test _register_tools_and_commands helper function."""

    def test_registers_tools(self):
        """Test registers all tools with app."""
        app = Mock()
        tool1 = Mock()
        tool2 = Mock()

        _register_tools_and_commands(app, [tool1, tool2], [])

        assert app.add_tool.call_count == 2
        app.add_tool.assert_any_call(tool1)
        app.add_tool.assert_any_call(tool2)

    def test_registers_commands_as_command_tools(self):
        """Test converts commands to CommandTool and registers."""
        app = Mock()
        command = Command(name="test", run_func=lambda: 0)

        with patch("appinfra.app.builder.app.CommandTool") as MockCommandTool:
            mock_tool = Mock()
            MockCommandTool.return_value = mock_tool

            _register_tools_and_commands(app, [], [command])

            MockCommandTool.assert_called_once_with(command)
            app.add_tool.assert_called_once_with(mock_tool)


class TestConfigureArguments:
    """Test _configure_arguments helper function."""

    def test_adds_custom_arguments(self):
        """Test adds custom arguments to app, unpacking args and kwargs."""
        app = Mock()
        custom_args = [
            (("--verbose",), {"action": "store_true"}),
            (("--file",), {"required": True}),
        ]

        _configure_arguments(app, custom_args)

        assert app.add_argument.call_count == 2
        app.add_argument.assert_any_call("--verbose", action="store_true")
        app.add_argument.assert_any_call("--file", required=True)

    def test_no_arguments_is_a_no_op(self):
        """Test an empty list adds nothing."""
        app = Mock()

        _configure_arguments(app, [])

        app.add_argument.assert_not_called()


class TestConfigureHooks:
    """Test _configure_hooks helper function."""

    def test_sets_hook_manager(self):
        """Test sets hook manager on app."""
        app = Mock()
        hooks = Mock()

        _configure_hooks(app, hooks)

        app.set_hook_manager.assert_called_once_with(hooks)

    def test_handles_app_without_set_hook_manager(self):
        """Test handles app without set_hook_manager method."""
        app = Mock(spec=[])
        hooks = Mock()

        # Should not raise
        _configure_hooks(app, hooks)


# =============================================================================
# Test Command Dataclass
# =============================================================================


class TestCommand:
    """Test Command dataclass."""

    def test_basic_creation(self):
        """Test creating command with required fields."""
        run_func = lambda: 0
        cmd = Command(name="test", run_func=run_func)

        assert cmd.name == "test"
        assert cmd.run_func is run_func
        assert cmd.aliases == []
        assert cmd.help_text == ""

    def test_full_creation(self):
        """Test creating command with all fields."""
        run_func = lambda: 0
        cmd = Command(
            name="analyze",
            run_func=run_func,
            aliases=["a", "an"],
            help_text="Analyze data",
        )

        assert cmd.name == "analyze"
        assert cmd.aliases == ["a", "an"]
        assert cmd.help_text == "Analyze data"

    def test_post_init_initializes_none_aliases(self):
        """Test __post_init__ converts None aliases to empty list."""
        cmd = Command(name="test", run_func=lambda: 0, aliases=None)

        assert cmd.aliases == []


# =============================================================================
# Test CommandTool
# =============================================================================


class TestCommandTool:
    """Test CommandTool class."""

    def test_init_creates_config_from_command(self):
        """Test creates ToolConfig from Command."""
        cmd = Command(name="test", run_func=lambda: 0, aliases=["t"], help_text="Test")
        tool = CommandTool(cmd)

        assert tool.name == "test"
        assert tool.config.aliases == ["t"]
        assert tool.config.help_text == "Test"

    def test_run_executes_command_function(self):
        """Test run() executes command's run_func."""
        executed = []

        def run_func():
            executed.append(True)
            return 0

        cmd = Command(name="test", run_func=run_func)
        tool = CommandTool(cmd)

        result = tool.run()

        assert executed == [True]
        assert result == 0

    def test_run_returns_int_result(self):
        """Test run() returns int result from run_func."""
        cmd = Command(name="test", run_func=lambda: 42)
        tool = CommandTool(cmd)

        result = tool.run()

        assert result == 42

    def test_run_returns_zero_for_non_int(self):
        """Test run() returns 0 when run_func returns non-int."""
        cmd = Command(name="test", run_func=lambda: "success")
        tool = CommandTool(cmd)

        result = tool.run()

        assert result == 0

    def test_run_handles_exception(self):
        """Test run() handles exceptions and returns 1."""

        def failing_func():
            raise ValueError("Test error")

        cmd = Command(name="test", run_func=failing_func)
        tool = CommandTool(cmd)
        tool._logger = Mock()

        result = tool.run()

        assert result == 1
        tool._logger.error.assert_called()

    def test_run_passes_kwargs(self):
        """Test run() passes kwargs to run_func."""
        received_kwargs = {}

        def run_func(**kwargs):
            received_kwargs.update(kwargs)
            return 0

        cmd = Command(name="test", run_func=run_func)
        tool = CommandTool(cmd)

        tool.run(key="value", another="arg")

        assert received_kwargs == {"key": "value", "another": "arg"}


# =============================================================================
# Test logging block folds into the programmatic config layer
# =============================================================================


class TestLoggingBlockFold:
    """The logging block writes explicit options under ``logging`` in the config."""

    def test_untouched_block_leaves_config_alone(self):
        """Closing the block without setting anything changes nothing."""
        builder = AppBuilder("test").config.with_overrides({"app_name": "test"}).done()

        result = builder.logging.done()

        assert result is builder
        assert builder._config.to_dict() == {"app_name": "test"}

    def test_untouched_block_creates_no_config(self):
        """Closing an untouched block on a builder without config leaves it None."""
        builder = AppBuilder("test")

        builder.logging.done()

        assert builder._config is None

    def test_creates_config_when_none(self):
        """An explicit option creates the config with a logging section."""
        builder = AppBuilder("test")

        builder.logging.with_level("debug").done()

        assert builder._config is not None
        assert builder._config.logging.level == "debug"

    def test_adds_logging_section_to_existing_config(self):
        """Config without a logging section gains one; other keys survive."""
        builder = AppBuilder("test").config.with_overrides({"app_name": "test"}).done()

        builder.logging.with_level("debug").done()

        assert builder._config.app_name == "test"
        assert builder._config.logging.level == "debug"

    def test_merges_into_existing_logging_section(self):
        """Explicit options merge with an existing logging section."""
        builder = (
            AppBuilder("test")
            .config.with_overrides({"logging": {"location": 1}})
            .done()
        )

        builder.logging.with_level("debug").done()

        assert builder._config.logging.level == "debug"
        assert builder._config.logging.location == 1

    def test_keyword_form_returns_builder(self):
        """``.logging(...)`` folds and returns the AppBuilder."""
        builder = AppBuilder("test")

        result = builder.logging(level="debug", micros=True)

        assert result is builder
        assert builder._config.logging.level == "debug"
        assert builder._config.logging.micros is True

    def test_build_rejects_unclosed_block(self):
        """build() refuses a block that was never closed with done()."""
        builder = AppBuilder("test")
        builder.logging.with_level("debug")

        with (
            patch("appinfra.app.builder.app.App"),
            pytest.raises(ValueError, match="logging block opened at .* is still open"),
        ):
            builder.build()

        assert builder._config is None


# =============================================================================
# Test create_app_builder Factory Function
# =============================================================================


class TestCreateAppBuilder:
    """Test create_app_builder factory function."""

    def test_create_app_builder_returns_builder(self):
        """Test that create_app_builder returns an AppBuilder instance."""
        from appinfra.app.builder import create_app_builder

        builder = create_app_builder("myapp")

        assert isinstance(builder, AppBuilder)
        assert builder._name == "myapp"

    def test_create_app_builder_supports_chaining(self):
        """Test that create_app_builder result can be chained."""
        from appinfra.app.builder import create_app_builder

        app = create_app_builder("myapp").with_description("My application").build()

        assert app is not None


# =============================================================================
# Test AppBuilder Initialization
# =============================================================================


class TestAppBuilderInit:
    """Test AppBuilder initialization."""

    def test_init_with_name(self):
        """Test initialization with name."""
        builder = AppBuilder("myapp")

        assert builder._name == "myapp"

    def test_init_without_name(self):
        """Test initialization without name."""
        builder = AppBuilder()

        assert builder._name is None

    def test_init_creates_empty_collections(self):
        """Test initialization creates empty collections."""
        builder = AppBuilder()

        assert builder._tools == []
        assert builder._commands == []
        assert builder._custom_args == []
        assert builder._standard_arg_overrides == {}
        assert builder._main_tool is None
        assert builder._config is None
        assert builder._config_spec is None

    def test_init_standard_args_are_the_defaults(self):
        """Flags start as a copy of DEFAULT_STANDARD_ARGS, version included."""
        builder = AppBuilder()

        assert builder._standard_args == DEFAULT_STANDARD_ARGS
        assert builder._standard_args is not DEFAULT_STANDARD_ARGS
        assert builder._standard_args["version"] is False


# =============================================================================
# Test AppBuilder Fluent Methods
# =============================================================================


class TestAppBuilderFluentMethods:
    """Test AppBuilder fluent builder methods."""

    def test_with_description(self):
        """Test with_description sets description and returns self."""
        builder = AppBuilder()

        result = builder.with_description("My app description")

        assert builder._description == "My app description"
        assert result is builder

    def test_version_block_sets_version(self):
        """The version block's with_semver sets the version; done() returns self."""
        builder = AppBuilder()

        result = builder.version.with_semver("1.0.0").done()

        assert builder._version == "1.0.0"
        assert result is builder

    def test_version_keyword_form(self):
        """``.version(semver=...)`` sets the version and returns self."""
        builder = AppBuilder()

        result = builder.version(semver="1.0.0")

        assert builder._version == "1.0.0"
        assert result is builder

    def test_config_block_with_overrides(self):
        """The config block's overrides layer lands on the builder."""
        builder = AppBuilder()

        result = builder.config.with_overrides({"a": 1}).done()

        assert builder._config.a == 1
        assert result is builder

    def test_cli_keyword_form(self):
        """``.cli(...)`` sets flags on the builder and returns self."""
        builder = AppBuilder()

        result = builder.cli(etc_dir=True, log=True)

        assert result is builder
        assert builder._standard_args["etc_dir"] is True
        assert builder._standard_args["log_level"] is True
        assert builder._standard_args["help"] is True

    def test_deep_merge_dict_recursive(self):
        """Test that yaml.deep_merge merges nested dicts recursively."""
        base = {"a": 1, "nested": {"x": 1, "y": 2}}
        override = {"b": 2, "nested": {"y": 3, "z": 4}}

        result = deep_merge(base, override)

        assert result == {"a": 1, "b": 2, "nested": {"x": 1, "y": 3, "z": 4}}

    def test_merge_configs_returns_dot_dict(self):
        """_merge_configs deep-merges two layers into a DotDict."""
        builder = AppBuilder()

        merged = builder._merge_configs(
            DotDict(a=1, nested=DotDict(x=1)), DotDict(nested=DotDict(y=2))
        )

        assert isinstance(merged, DotDict)
        assert merged.to_dict() == {"a": 1, "nested": {"x": 1, "y": 2}}

    def test_with_main_cls(self):
        """Test with_main_cls sets main class."""
        builder = AppBuilder()

        class CustomApp:
            pass

        result = builder.with_main_cls(CustomApp)

        assert builder._main_cls is CustomApp
        assert result is builder

    def test_main_tool_by_name(self):
        """A name only names the main tool; it registers nothing."""
        builder = AppBuilder()

        result = builder.tools.with_main("run").done()

        assert builder._main_tool == "run"
        assert builder._tools == []
        assert result is builder

    def test_main_tool_by_object_registers_it(self):
        """A Tool instance is registered as well as named."""
        builder = AppBuilder()
        tool = Tool(config=ToolConfig(name="process"))

        result = builder.tools.with_main(tool).done()

        assert builder._main_tool == "process"
        assert builder._tools == [tool]
        assert result is builder

    def test_main_tool_by_object_not_registered_twice(self):
        """An instance already added via with_tool is not added again."""
        builder = AppBuilder()
        tool = Tool(config=ToolConfig(name="process"))

        builder.tools.with_tool(tool).with_main(tool).done()

        assert builder._tools == [tool]


# =============================================================================
# Test AppBuilder Decorator API
# =============================================================================


class TestAppBuilderNoDecoratorAPI:
    """Test that AppBuilder does not expose decorator methods."""

    def test_no_tool_method(self):
        """Builder should not have tool() — use @app.tool() post-build."""
        builder = AppBuilder()
        assert not hasattr(builder, "tool")

    def test_no_argument_property(self):
        """Builder should not have argument — use @app.argument post-build."""
        builder = AppBuilder()
        assert not hasattr(builder, "argument")


# =============================================================================
# Test AppBuilder Blocks
# =============================================================================


class TestAppBuilderBlocks:
    """Each block property returns its configurer bound to the builder."""

    def test_config_block(self):
        builder = AppBuilder()
        block = builder.config
        assert isinstance(block, ConfigConfigurer)
        assert block.done() is builder

    def test_cli_block(self):
        builder = AppBuilder()
        block = builder.cli
        assert isinstance(block, CliConfigurer)
        assert block.done() is builder

    def test_logging_block(self):
        """The logging block is the standalone LoggingBuilder bound to the app."""
        builder = AppBuilder()
        block = builder.logging
        assert isinstance(block, LoggingScope)
        assert isinstance(block, LoggingBuilder)
        assert block.done() is builder

    def test_logging_block_is_one_instance_per_builder(self):
        """The scope holds builder state, so repeated access returns the same one."""
        builder = AppBuilder()
        block = builder.logging
        block.done()
        assert builder.logging is block

    def test_tools_block(self):
        builder = AppBuilder()
        block = builder.tools
        assert isinstance(block, ToolConfigurer)
        assert block.done() is builder

    def test_lifecycle_block(self):
        builder = AppBuilder()
        block = builder.lifecycle
        assert isinstance(block, LifecycleConfigurer)
        assert block.done() is builder

    def test_version_block(self):
        builder = AppBuilder()
        block = builder.version
        assert isinstance(block, VersionConfigurer)
        assert block.done() is builder

    def test_no_advanced_block(self):
        """The former advanced block is split across cli and lifecycle."""
        builder = AppBuilder()
        assert not hasattr(builder, "advanced")


# =============================================================================
# Test AppBuilder Build
# =============================================================================


class TestAppBuilderBuild:
    """Test AppBuilder.build method."""

    def test_build_creates_app(self):
        """Test build creates and returns App instance."""
        builder = AppBuilder("myapp")

        with patch("appinfra.app.builder.app.App") as MockApp:
            mock_app = Mock()
            MockApp.return_value = mock_app

            result = builder.build()

            MockApp.assert_called_once()
            assert result is mock_app
            assert mock_app.name == "myapp"

    def test_build_configures_plugins(self):
        """Test build calls plugin configuration."""
        builder = AppBuilder()
        builder._plugins = Mock()

        with patch("appinfra.app.builder.app.App"):
            builder.build()

            builder._plugins.configure_all.assert_called_once_with(builder)

    def test_build_copies_flags_and_overrides_without_aliasing(self):
        """The app gets its own copies of the flag set and per-flag overrides."""
        builder = (
            AppBuilder("myapp")
            .cli.with_flags(etc_dir=True)
            .with_flag("etc_dir", help="config dir")
            .done()
        )

        app = builder.build()

        assert app._standard_args["etc_dir"] is True
        assert app._standard_arg_overrides == {"etc_dir": {"help": "config dir"}}
        builder._standard_args["etc_dir"] = False
        builder._standard_arg_overrides["etc_dir"]["help"] = "changed"
        assert app._standard_args["etc_dir"] is True
        assert app._standard_arg_overrides["etc_dir"]["help"] == "config dir"

    def test_build_registers_tools_and_main_tool(self):
        """Tools from the block reach the registry and the main tool is set."""
        tool = Tool(config=ToolConfig(name="process"))

        app = AppBuilder("myapp").tools.with_main(tool).done().build()

        assert app.registry.get_tool("process") is tool
        assert app._main_tool == "process"

    def test_build_adds_custom_arguments(self):
        """Custom arguments from the cli block are handed to the app."""
        app = (
            AppBuilder("myapp")
            .cli.with_argument("--verbose", action="store_true")
            .done()
            .build()
        )

        assert (("--verbose",), {"action": "store_true"}) in app._custom_args


# =============================================================================
# Integration Tests
# =============================================================================


class TestAppBuilderIntegration:
    """Integration tests for AppBuilder."""

    def test_full_builder_workflow(self):
        """Test complete builder workflow."""
        builder = AppBuilder("myapp")

        with patch("appinfra.app.builder.app.App") as MockApp:
            mock_app = Mock()
            MockApp.return_value = mock_app

            result = (
                builder.with_description("My application")
                .version(semver="1.0.0")
                .build()
            )

            assert result is mock_app
            assert mock_app.name == "myapp"
            assert mock_app.description == "My application"
            assert mock_app.version == "1.0.0"

    def test_block_chain_workflow(self):
        """Every block closes back to the same builder."""
        builder = AppBuilder("myapp")

        assert builder.config.done() is builder
        assert builder.cli.done() is builder
        assert builder.logging.done() is builder
        assert builder.tools.done() is builder
        assert builder.lifecycle.done() is builder
        assert builder.version.done() is builder

    def test_keyword_blocks_chain_directly(self):
        """Keyword forms return the AppBuilder, so blocks chain without done()."""
        tool = Tool(config=ToolConfig(name="process"))

        builder = (
            AppBuilder("myapp")
            .cli(etc_dir=True)
            .logging(level="debug")
            .tools(tool, main="process")
            .version(semver="1.0.0")
        )

        assert builder._standard_args["etc_dir"] is True
        assert builder._config.logging.level == "debug"
        assert builder._tools == [tool]
        assert builder._main_tool == "process"
        assert builder._version == "1.0.0"


class TestPluginContributedTools:
    """Tools a plugin adds in configure() must reach the tool registry."""

    def test_tool_added_in_configure_is_registered(self):
        """Plugins are configured before the registry is populated."""

        class ToolPlugin(Plugin):
            def configure(self, builder):
                builder.tools.with_tool_builder(
                    ToolBuilder("from-plugin")
                    .with_help("added by a plugin")
                    .with_run_function(lambda tool, **kwargs: 0)
                ).done()

        app = AppBuilder("myapp").tools.with_plugin(ToolPlugin()).done().build()

        assert app.registry.get_tool("from-plugin") is not None

    def test_version_set_in_configure_is_realized(self):
        """Plugins run before the tracker and startup hook are created."""

        class VersionPlugin(Plugin):
            def configure(self, builder):
                builder.version.with_package("pytest").done()

        builder = AppBuilder("myapp").tools.with_plugin(VersionPlugin()).done()
        builder.build()

        assert builder._version_tracker is not None
        assert "pytest" in builder._version_tracker.get_all()
        assert len(builder._hooks.get_hooks("startup")) == 1

    def test_config_and_logging_set_in_configure_reach_the_app(self):
        """Plugins run before the App takes its config snapshot."""

        class ConfigPlugin(Plugin):
            def configure(self, builder):
                builder.config.with_value("db.host", "plugin").done()
                builder.logging(level="error")

        app = AppBuilder("myapp").tools.with_plugin(ConfigPlugin()).done().build()

        assert app.config.db.host == "plugin"
        assert app.config.logging.level == "error"

    def test_cli_flag_set_in_configure_reaches_the_app(self):
        """Plugins run before the standard flags are copied to the App."""

        class FlagPlugin(Plugin):
            def configure(self, builder):
                builder.cli(etc_dir=True)

        app = AppBuilder("myapp").tools.with_plugin(FlagPlugin()).done().build()

        assert app._standard_args["etc_dir"] is True

    def test_failed_build_consumes_the_builder(self):
        """A build that fails inside a plugin cannot be retried on the same builder."""

        class BrokenPlugin(Plugin):
            def configure(self, builder):
                raise RuntimeError("plugin failed")

        builder = AppBuilder("myapp").tools.with_plugin(BrokenPlugin()).done()
        with pytest.raises(RuntimeError, match="plugin failed"):
            builder.build()

        with pytest.raises(ValueError, match="already called"):
            builder.build()

    def test_rejected_precheck_leaves_the_builder_usable(self):
        """An open block fails before anything is realized, so closing it and building works."""
        builder = AppBuilder("myapp")
        block = builder.tools
        with pytest.raises(ValueError, match="still open"):
            builder.build()

        block.done()

        assert builder.build() is not None

    def test_plugin_leaving_a_block_open_is_named(self):
        """The error carries the plugin's name and the line that opened the block."""

        class SloppyPlugin(Plugin):
            def __init__(self):
                super().__init__("sloppy")

            def configure(self, builder):
                builder.tools.with_tool_builder(
                    ToolBuilder("dangling").with_run_function(lambda tool, **kw: 0)
                )  # no done()

        builder = AppBuilder("myapp").tools.with_plugin(SloppyPlugin()).done()

        with pytest.raises(
            ValueError,
            match=r"plugin 'sloppy' left the tools block opened at .*test_app_builder.py:\d+",
        ):
            builder.build()
