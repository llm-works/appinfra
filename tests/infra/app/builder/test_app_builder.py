"""
Tests for app/builder/app.py.

Tests key functionality including:
- Helper functions for build process
- Command and CommandTool classes
- ServerConfig and LoggingConfig dataclasses
- AppBuilder class initialization and methods
- Fluent builder API
"""

from unittest.mock import Mock, patch

import pytest

from appinfra.app.builder.app import (
    AppBuilder,
    Command,
    CommandTool,
    LoggingConfig,
    ServerConfig,
    _configure_arguments_and_validation,
    _configure_hooks,
    _configure_middleware,
    _configure_server_and_logging,
    _create_base_app,
    _register_tools_and_commands,
    _set_app_metadata,
)
from appinfra.yaml import deep_merge

# =============================================================================
# Test Helper Functions
# =============================================================================


@pytest.mark.unit
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


@pytest.mark.unit
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


@pytest.mark.unit
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


@pytest.mark.unit
class TestConfigureMiddleware:
    """Test _configure_middleware helper function."""

    def test_adds_middleware_when_server_configured(self):
        """Test adds middleware when server config present."""
        app = Mock()
        mw1 = Mock()
        mw2 = Mock()
        server_config = Mock()

        _configure_middleware(app, [mw1, mw2], server_config)

        assert app.add_middleware.call_count == 2

    def test_skips_when_no_server_config(self):
        """Test does nothing when no server config."""
        app = Mock()
        mw = Mock()

        _configure_middleware(app, [mw], None)

        app.add_middleware.assert_not_called()

    def test_handles_app_without_add_middleware(self):
        """Test handles app without add_middleware method."""
        app = Mock(spec=[])  # No add_middleware
        mw = Mock()
        server_config = Mock()

        # Should not raise
        _configure_middleware(app, [mw], server_config)


@pytest.mark.unit
class TestConfigureArgumentsAndValidation:
    """Test _configure_arguments_and_validation helper function."""

    def test_adds_custom_arguments(self):
        """Test adds custom arguments to app."""
        app = Mock()
        custom_args = [
            (("--verbose",), {"action": "store_true"}),
            (("--file",), {"required": True}),
        ]

        _configure_arguments_and_validation(app, custom_args, [])

        assert app.add_argument.call_count == 2

    def test_adds_validation_rules(self):
        """Test adds validation rules to app."""
        app = Mock()
        rules = [Mock(), Mock()]

        _configure_arguments_and_validation(app, [], rules)

        assert app.add_validation_rule.call_count == 2

    def test_handles_app_without_methods(self):
        """Test handles app without add_argument/add_validation_rule."""
        app = Mock(spec=[])  # No methods

        # Should not raise
        _configure_arguments_and_validation(app, [(("--test",), {})], [Mock()])


@pytest.mark.unit
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


@pytest.mark.unit
class TestConfigureServerAndLogging:
    """Test _configure_server_and_logging helper function."""

    def test_configures_server(self):
        """Test configures server when config provided."""
        app = Mock()
        server_config = Mock()

        _configure_server_and_logging(app, server_config, None)

        app.configure_server.assert_called_once_with(server_config)

    def test_configures_logging(self):
        """Test configures logging when config provided."""
        app = Mock()
        logging_config = Mock()

        _configure_server_and_logging(app, None, logging_config)

        app.configure_logging.assert_called_once_with(logging_config)

    def test_handles_app_without_methods(self):
        """Test handles app without configure_* methods."""
        app = Mock(spec=[])

        # Should not raise
        _configure_server_and_logging(app, Mock(), Mock())


# =============================================================================
# Test Command Dataclass
# =============================================================================


@pytest.mark.unit
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


@pytest.mark.unit
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
# Test ServerConfig
# =============================================================================


@pytest.mark.unit
class TestServerConfig:
    """Test ServerConfig dataclass."""

    def test_default_values(self):
        """Test default values."""
        config = ServerConfig()

        assert config.port == 8080
        assert config.host == "localhost"
        assert config.ssl_enabled is False
        assert config.cors_origins == []
        assert config.timeout == 30

    def test_custom_values(self):
        """Test custom values."""
        config = ServerConfig(
            port=9000,
            host="0.0.0.0",
            ssl_enabled=True,
            cors_origins=["http://localhost"],
            timeout=60,
        )

        assert config.port == 9000
        assert config.host == "0.0.0.0"
        assert config.ssl_enabled is True
        assert config.cors_origins == ["http://localhost"]
        assert config.timeout == 60

    def test_post_init_initializes_none_cors_origins(self):
        """Test __post_init__ converts None cors_origins to empty list."""
        config = ServerConfig(cors_origins=None)

        assert config.cors_origins == []


# =============================================================================
# Test LoggingConfig
# =============================================================================


@pytest.mark.unit
class TestLoggingConfig:
    """Test LoggingConfig dataclass."""

    def test_default_values(self):
        """Test default values are None (to allow config file values to take precedence)."""
        config = LoggingConfig()

        assert config.level is None
        assert config.location is None
        assert config.micros is None
        assert config.format_string is None
        assert config.location_color is None

    def test_custom_values(self):
        """Test custom values."""
        config = LoggingConfig(
            level="debug",
            location=1,
            micros=True,
            format_string="%(message)s",
        )

        assert config.level == "debug"
        assert config.location == 1
        assert config.micros is True
        assert config.format_string == "%(message)s"


# =============================================================================
# Test LoggingConfig Merge
# =============================================================================


@pytest.mark.unit
class TestLoggingConfigMerge:
    """Test AppBuilder._merge_logging_into_config method."""

    def test_merge_returns_config_when_no_logging_settings(self):
        """Test that merge returns original config when no logging settings are set."""
        from appinfra.dot_dict import DotDict

        # Create a config, but no logging settings in builder
        builder = AppBuilder("test")
        builder._config = DotDict(app_name="test")
        # _logging_config has all None values by default

        result = builder._merge_logging_into_config()

        # Should return original config unchanged
        assert result is builder._config
        assert result.app_name == "test"

    def test_merge_creates_config_with_logging_when_no_config(self):
        """Test that merge creates new config with logging when no config exists."""
        builder = AppBuilder("test")
        builder._config = None
        builder._logging_config = LoggingConfig(level="debug")

        result = builder._merge_logging_into_config()

        # Should create new config with logging
        assert result is not None
        assert hasattr(result, "logging")
        assert result.logging.level == "debug"

    def test_merge_adds_logging_to_config_without_logging_section(self):
        """Test that logging config is added when config has no logging section."""
        from appinfra.dot_dict import DotDict

        # Create a config without logging section
        builder = AppBuilder("test")
        builder._config = DotDict(app_name="test")
        builder._logging_config = LoggingConfig(level="debug")

        result = builder._merge_logging_into_config()

        assert hasattr(result, "logging")
        assert result.logging.level == "debug"

    def test_merge_updates_existing_logging_section(self):
        """Test that logging config updates existing logging section."""
        from appinfra.dot_dict import DotDict

        # Create a config with existing logging section
        builder = AppBuilder("test")
        builder._config = DotDict(logging=DotDict(location=1))
        builder._logging_config = LoggingConfig(level="debug")

        result = builder._merge_logging_into_config()

        # Should have both values
        assert result.logging.level == "debug"
        assert result.logging.location == 1


# =============================================================================
# Test create_app_builder Factory Function
# =============================================================================


@pytest.mark.unit
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


@pytest.mark.unit
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
        assert builder._middleware == []
        assert builder._validation_rules == []
        assert builder._custom_args == []


# =============================================================================
# Test AppBuilder Fluent Methods
# =============================================================================


@pytest.mark.unit
class TestAppBuilderFluentMethods:
    """Test AppBuilder fluent builder methods."""

    def test_with_name(self):
        """Test with_name sets name and returns self."""
        builder = AppBuilder()

        result = builder.with_name("myapp")

        assert builder._name == "myapp"
        assert result is builder

    def test_with_description(self):
        """Test with_description sets description and returns self."""
        builder = AppBuilder()

        result = builder.with_description("My app description")

        assert builder._description == "My app description"
        assert result is builder

    def test_with_version(self):
        """Test with_version sets version and returns self."""
        builder = AppBuilder()

        result = builder.with_version("1.0.0")

        assert builder._version == "1.0.0"
        assert result is builder

    def test_with_config(self):
        """Test with_config sets config and returns self."""
        builder = AppBuilder()
        config = Mock()

        result = builder.with_config(config)

        assert builder._config is config
        assert result is builder

    def test_with_config_file_uses_default_when_none(self):
        """Test that with_config_file() uses default config filename when path is None."""
        builder = AppBuilder("test")

        result = builder.with_config_file()

        assert builder._config_path == "infra.yaml"
        assert builder._config_from_etc_dir is True
        assert result is builder

    def test_with_config_file_with_explicit_path(self):
        """Test that with_config_file() uses explicit path when provided."""
        builder = AppBuilder("test")

        result = builder.with_config_file("custom.yaml")

        assert builder._config_path == "custom.yaml"
        assert builder._config_from_etc_dir is True
        assert result is builder

    def test_with_config_file_multiple_immediate_merges(self):
        """Test that multiple immediate config files are merged correctly."""
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create base config
            base_path = Path(tmpdir) / "base.yaml"
            base_path.write_text("key1: base\nnested:\n  a: 1\n  b: 2\n")

            # Create overlay config
            overlay_path = Path(tmpdir) / "overlay.yaml"
            overlay_path.write_text("key2: overlay\nnested:\n  b: 3\n  c: 4\n")

            builder = AppBuilder("test")
            builder.with_config_file(str(base_path))  # Absolute path = immediate
            builder.with_config_file(str(overlay_path))  # Absolute path = immediate

            # Both should be merged (overlay wins)
            assert builder._config.key1 == "base"  # From base
            assert builder._config.key2 == "overlay"  # From overlay
            assert builder._config.nested.a == 1  # From base only
            assert builder._config.nested.b == 3  # Overridden by overlay
            assert builder._config.nested.c == 4  # From overlay only

    def test_with_config_file_optional_missing_returns_false(self):
        """Test that optional config file returns False when missing."""
        builder = AppBuilder("test")

        result = builder._load_config_immediately(
            "/nonexistent/path.yaml", optional=True
        )

        assert result is False
        assert builder._config is None

    def test_with_config_file_required_missing_raises(self):
        """Test that required config file raises FileNotFoundError."""
        builder = AppBuilder("test")

        with pytest.raises(FileNotFoundError, match="Config file not found"):
            builder._load_config_immediately("/nonexistent/path.yaml", optional=False)

    def test_deep_merge_dict_recursive(self):
        """Test that yaml.deep_merge merges nested dicts recursively."""
        base = {"a": 1, "nested": {"x": 1, "y": 2}}
        override = {"b": 2, "nested": {"y": 3, "z": 4}}

        result = deep_merge(base, override)

        assert result == {"a": 1, "b": 2, "nested": {"x": 1, "y": 3, "z": 4}}

    def test_with_main_cls(self):
        """Test with_main_cls sets main class."""
        builder = AppBuilder()

        class CustomApp:
            pass

        result = builder.with_main_cls(CustomApp)

        assert builder._main_cls is CustomApp
        assert result is builder

    def test_with_main_tool_by_name(self):
        """Test with_main_tool sets main tool by name."""
        builder = AppBuilder()

        result = builder.with_main_tool("run")

        assert builder._main_tool == "run"
        assert result is builder

    def test_with_main_tool_by_object(self):
        """Test with_main_tool sets main tool by Tool object."""
        from appinfra.app.tools.base import Tool, ToolConfig

        builder = AppBuilder()
        tool = Tool(config=ToolConfig(name="process"))

        result = builder.with_main_tool(tool)

        assert builder._main_tool == "process"
        assert result is builder


# =============================================================================
# Test AppBuilder Decorator API
# =============================================================================


@pytest.mark.unit
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
# Test AppBuilder Configurer Properties
# =============================================================================


@pytest.mark.unit
class TestAppBuilderConfigurerProperties:
    """Test AppBuilder configurer properties."""

    def test_tools_property(self):
        """Test tools property returns ToolConfigurer."""
        builder = AppBuilder()

        result = builder.tools

        from appinfra.app.builder.configurer.tool import ToolConfigurer

        assert isinstance(result, ToolConfigurer)

    def test_server_property(self):
        """Test server property returns ServerConfigurer."""
        builder = AppBuilder()

        result = builder.server

        from appinfra.app.builder.configurer.server import ServerConfigurer

        assert isinstance(result, ServerConfigurer)

    def test_logging_property(self):
        """Test logging property returns LoggingConfigurer."""
        builder = AppBuilder()

        result = builder.logging

        from appinfra.app.builder.configurer.logging import LoggingConfigurer

        assert isinstance(result, LoggingConfigurer)

    def test_advanced_property(self):
        """Test advanced property returns AdvancedConfigurer."""
        builder = AppBuilder()

        result = builder.advanced

        from appinfra.app.builder.configurer.advanced import AdvancedConfigurer

        assert isinstance(result, AdvancedConfigurer)


# =============================================================================
# Test AppBuilder Build
# =============================================================================


@pytest.mark.unit
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
            assert mock_app.name == "myapp"

    def test_build_configures_plugins(self):
        """Test build calls plugin configuration."""
        builder = AppBuilder()
        builder._plugins = Mock()

        with patch("appinfra.app.builder.app.App"):
            builder.build()

            builder._plugins.configure_all.assert_called_once_with(builder)


# =============================================================================
# Integration Tests
# =============================================================================


@pytest.mark.integration
class TestAppBuilderIntegration:
    """Integration tests for AppBuilder."""

    def test_full_builder_workflow(self):
        """Test complete builder workflow."""
        builder = AppBuilder("myapp")

        with patch("appinfra.app.builder.app.App") as MockApp:
            mock_app = Mock()
            MockApp.return_value = mock_app

            result = (
                builder.with_description("My application").with_version("1.0.0").build()
            )

            assert result is mock_app
            assert mock_app.name == "myapp"
            assert mock_app.description == "My application"
            assert mock_app.version == "1.0.0"

    def test_configurer_chain_workflow(self):
        """Test using configurer chain."""
        builder = AppBuilder("myapp")

        # Test that configurers can be chained
        tool_configurer = builder.tools
        assert tool_configurer.done() is builder

        server_configurer = builder.server
        assert server_configurer.done() is builder

        logging_configurer = builder.logging
        assert logging_configurer.done() is builder

        advanced_configurer = builder.advanced
        assert advanced_configurer.done() is builder
