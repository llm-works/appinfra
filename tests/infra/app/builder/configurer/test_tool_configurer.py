# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for app/builder/configurer/tool.py.

Tests key functionality including:
- ToolConfigurer initialization
- Tool registration (single and multiple)
- Tool builder integration
- Command registration
- Plugin registration
- Method chaining (fluent API)
"""

from unittest.mock import Mock, patch

import pytest

from appinfra.app.builder.configurer.tool import ToolConfigurer

# =============================================================================
# Test ToolConfigurer Initialization
# =============================================================================


@pytest.mark.unit
class TestToolConfigurerInit:
    """Test ToolConfigurer initialization."""

    def test_stores_app_builder_reference(self):
        """Test stores reference to parent AppBuilder."""
        app_builder = Mock()

        configurer = ToolConfigurer(app_builder)

        assert configurer._app_builder is app_builder


# =============================================================================
# Test with_tool
# =============================================================================


@pytest.mark.unit
class TestWithTool:
    """Test ToolConfigurer.with_tool method."""

    def test_adds_tool_to_list(self):
        """Test adds single tool to AppBuilder's tools list."""
        app_builder = Mock()
        app_builder._tools = []
        configurer = ToolConfigurer(app_builder)
        tool = Mock(name="TestTool")

        result = configurer.with_tool(tool)

        assert tool in app_builder._tools
        assert result is configurer  # Returns self for chaining

    def test_returns_self_for_chaining(self):
        """Test returns self for method chaining."""
        app_builder = Mock()
        app_builder._tools = []
        configurer = ToolConfigurer(app_builder)

        result = configurer.with_tool(Mock())

        assert result is configurer


# =============================================================================
# Test with_tools
# =============================================================================


@pytest.mark.unit
class TestWithTools:
    """Test ToolConfigurer.with_tools method."""

    def test_adds_multiple_tools(self):
        """Test adds multiple tools to AppBuilder's tools list."""
        app_builder = Mock()
        app_builder._tools = []
        configurer = ToolConfigurer(app_builder)
        tool1 = Mock(name="Tool1")
        tool2 = Mock(name="Tool2")
        tool3 = Mock(name="Tool3")

        result = configurer.with_tools(tool1, tool2, tool3)

        assert tool1 in app_builder._tools
        assert tool2 in app_builder._tools
        assert tool3 in app_builder._tools
        assert len(app_builder._tools) == 3
        assert result is configurer

    def test_extends_existing_tools(self):
        """Test extends existing tools list."""
        app_builder = Mock()
        existing_tool = Mock(name="ExistingTool")
        app_builder._tools = [existing_tool]
        configurer = ToolConfigurer(app_builder)
        new_tool = Mock(name="NewTool")

        configurer.with_tools(new_tool)

        assert existing_tool in app_builder._tools
        assert new_tool in app_builder._tools


# =============================================================================
# Test with_tool_builder
# =============================================================================


@pytest.mark.unit
class TestWithToolBuilder:
    """Test ToolConfigurer.with_tool_builder method."""

    def test_builds_and_adds_tool(self):
        """Test builds tool from builder and adds it."""
        app_builder = Mock()
        app_builder._tools = []
        configurer = ToolConfigurer(app_builder)

        builder = Mock()
        built_tool = Mock(name="BuiltTool")
        builder.build.return_value = built_tool

        result = configurer.with_tool_builder(builder)

        builder.build.assert_called_once()
        assert built_tool in app_builder._tools
        assert result is configurer


# =============================================================================
# Test with_cmd
# =============================================================================


@pytest.mark.unit
class TestWithCmd:
    """Test ToolConfigurer.with_cmd method."""

    def test_creates_and_adds_command(self):
        """Test creates Command and adds to commands list."""
        app_builder = Mock()
        app_builder._commands = []
        configurer = ToolConfigurer(app_builder)

        def my_run_func():
            return 0

        with patch("appinfra.app.builder.app.Command") as MockCommand:
            mock_command = Mock()
            MockCommand.return_value = mock_command

            result = configurer.with_cmd(
                "mycommand",
                run_func=my_run_func,
                aliases=["mc"],
                help_text="My command",
            )

            MockCommand.assert_called_once_with(
                name="mycommand",
                run_func=my_run_func,
                aliases=["mc"],
                help_text="My command",
            )
            assert mock_command in app_builder._commands
            assert result is configurer

    def test_default_empty_aliases(self):
        """Test uses empty list for aliases when not specified."""
        app_builder = Mock()
        app_builder._commands = []
        configurer = ToolConfigurer(app_builder)

        def my_run_func():
            return 0

        with patch("appinfra.app.builder.app.Command") as MockCommand:
            configurer.with_cmd("mycommand", run_func=my_run_func)

            # Check aliases defaults to empty list
            call_kwargs = MockCommand.call_args[1]
            assert call_kwargs["aliases"] == []

    def test_default_empty_help_text(self):
        """Test uses empty string for help_text when not specified."""
        app_builder = Mock()
        app_builder._commands = []
        configurer = ToolConfigurer(app_builder)

        def my_run_func():
            return 0

        with patch("appinfra.app.builder.app.Command") as MockCommand:
            configurer.with_cmd("mycommand", run_func=my_run_func)

            call_kwargs = MockCommand.call_args[1]
            assert call_kwargs["help_text"] == ""


# =============================================================================
# Test with_plugin
# =============================================================================


@pytest.mark.unit
class TestWithPlugin:
    """Test ToolConfigurer.with_plugin method."""

    def test_registers_plugin(self):
        """Test registers plugin with plugin manager."""
        app_builder = Mock()
        app_builder._plugins = Mock()
        configurer = ToolConfigurer(app_builder)
        plugin = Mock(name="TestPlugin")

        result = configurer.with_plugin(plugin)

        app_builder._plugins.register_plugin.assert_called_once_with(plugin)
        assert result is configurer


# =============================================================================
# Test with_plugins
# =============================================================================


@pytest.mark.unit
class TestWithPlugins:
    """Test ToolConfigurer.with_plugins method."""

    def test_registers_multiple_plugins(self):
        """Test registers multiple plugins."""
        app_builder = Mock()
        app_builder._plugins = Mock()
        configurer = ToolConfigurer(app_builder)
        plugin1 = Mock(name="Plugin1")
        plugin2 = Mock(name="Plugin2")
        plugin3 = Mock(name="Plugin3")

        result = configurer.with_plugins(plugin1, plugin2, plugin3)

        assert app_builder._plugins.register_plugin.call_count == 3
        app_builder._plugins.register_plugin.assert_any_call(plugin1)
        app_builder._plugins.register_plugin.assert_any_call(plugin2)
        app_builder._plugins.register_plugin.assert_any_call(plugin3)
        assert result is configurer


# =============================================================================
# Test done
# =============================================================================


@pytest.mark.unit
class TestDone:
    """Test ToolConfigurer.done method."""

    def test_returns_app_builder(self):
        """Test returns parent AppBuilder for continued chaining."""
        app_builder = Mock()
        configurer = ToolConfigurer(app_builder)

        result = configurer.done()

        assert result is app_builder


# =============================================================================
# Integration Tests
# =============================================================================


@pytest.mark.integration
class TestToolConfigurerIntegration:
    """Integration tests for ToolConfigurer."""

    def test_full_configuration_chain(self):
        """Test complete fluent configuration chain."""
        app_builder = Mock()
        app_builder._tools = []
        app_builder._commands = []
        app_builder._plugins = Mock()

        configurer = ToolConfigurer(app_builder)
        tool1 = Mock(name="Tool1")
        tool2 = Mock(name="Tool2")
        plugin = Mock(name="Plugin")

        with patch("appinfra.app.builder.app.Command") as MockCommand:
            MockCommand.return_value = Mock()

            result = (
                configurer.with_tool(tool1)
                .with_tools(tool2)
                .with_cmd("test", run_func=lambda: 0)
                .with_plugin(plugin)
                .done()
            )

        assert result is app_builder
        assert tool1 in app_builder._tools
        assert tool2 in app_builder._tools
        assert len(app_builder._commands) == 1
        app_builder._plugins.register_plugin.assert_called_once_with(plugin)

    def test_builder_pattern_for_tools(self):
        """Test using ToolBuilder with configurer."""
        app_builder = Mock()
        app_builder._tools = []
        configurer = ToolConfigurer(app_builder)

        builder = Mock()
        built_tool = Mock(name="BuiltTool")
        builder.build.return_value = built_tool

        result = configurer.with_tool_builder(builder).done()

        assert result is app_builder
        assert built_tool in app_builder._tools

    def test_chaining_with_multiple_tools_and_commands(self):
        """Test chaining multiple tool and command additions."""
        app_builder = Mock()
        app_builder._tools = []
        app_builder._commands = []
        app_builder._plugins = Mock()

        configurer = ToolConfigurer(app_builder)

        with patch("appinfra.app.builder.app.Command") as MockCommand:
            MockCommand.side_effect = lambda **kwargs: Mock(**kwargs)

            tool1 = Mock()
            tool2 = Mock()
            tool3 = Mock()

            (
                configurer.with_tool(tool1)
                .with_cmd("cmd1", run_func=lambda: 0, aliases=["c1"])
                .with_tool(tool2)
                .with_cmd("cmd2", run_func=lambda: 1, help_text="Second command")
                .with_tools(tool3)
            )

        assert len(app_builder._tools) == 3
        assert len(app_builder._commands) == 2
