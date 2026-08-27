# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for app/builder/plugin.py.

Tests key functionality including:
- Plugin base class
- Plugin enable/disable
- Plugin dependencies and conflicts
- PluginManager registration
- Dependency resolution
"""

from unittest.mock import Mock, patch

import pytest

from appinfra.app.builder.plugin import Plugin, PluginManager

# =============================================================================
# Test Plugin Base Class
# =============================================================================


class ConcretePlugin(Plugin):
    """Concrete implementation for testing abstract Plugin class."""

    def configure(self, builder):
        """Configure implementation for tests."""
        pass


@pytest.mark.unit
class TestPluginInit:
    """Test Plugin initialization."""

    def test_default_name_uses_class_name(self):
        """Test plugin name defaults to class name."""
        plugin = ConcretePlugin()

        assert plugin.name == "ConcretePlugin"

    def test_custom_name(self):
        """Test plugin with custom name."""
        plugin = ConcretePlugin(name="MyPlugin")

        assert plugin.name == "MyPlugin"

    def test_enabled_by_default(self):
        """Test plugin is enabled by default."""
        plugin = ConcretePlugin()

        assert plugin.enabled is True
        assert plugin._enabled is True

    def test_empty_dependencies_and_conflicts(self):
        """Test dependencies and conflicts are empty by default."""
        plugin = ConcretePlugin()

        assert plugin._dependencies == []
        assert plugin._conflicts == []


@pytest.mark.unit
class TestPluginEnabledProperty:
    """Test Plugin.enabled property."""

    def test_returns_enabled_state(self):
        """Test enabled property returns _enabled value."""
        plugin = ConcretePlugin()

        assert plugin.enabled is True

        plugin._enabled = False
        assert plugin.enabled is False


@pytest.mark.unit
class TestPluginEnable:
    """Test Plugin.enable method."""

    def test_enables_plugin(self):
        """Test enable sets _enabled to True."""
        plugin = ConcretePlugin()
        plugin._enabled = False

        plugin.enable()

        assert plugin._enabled is True


@pytest.mark.unit
class TestPluginDisable:
    """Test Plugin.disable method."""

    def test_disables_plugin(self):
        """Test disable sets _enabled to False."""
        plugin = ConcretePlugin()

        plugin.disable()

        assert plugin._enabled is False


@pytest.mark.unit
class TestPluginAddDependency:
    """Test Plugin.add_dependency method."""

    def test_adds_dependency(self):
        """Test adds plugin name to dependencies."""
        plugin = ConcretePlugin()

        plugin.add_dependency("OtherPlugin")

        assert "OtherPlugin" in plugin._dependencies

    def test_no_duplicate_dependencies(self):
        """Test doesn't add duplicate dependencies."""
        plugin = ConcretePlugin()

        plugin.add_dependency("OtherPlugin")
        plugin.add_dependency("OtherPlugin")

        assert plugin._dependencies.count("OtherPlugin") == 1

    def test_multiple_dependencies(self):
        """Test can add multiple dependencies."""
        plugin = ConcretePlugin()

        plugin.add_dependency("Plugin1")
        plugin.add_dependency("Plugin2")
        plugin.add_dependency("Plugin3")

        assert len(plugin._dependencies) == 3


@pytest.mark.unit
class TestPluginAddConflict:
    """Test Plugin.add_conflict method."""

    def test_adds_conflict(self):
        """Test adds plugin name to conflicts."""
        plugin = ConcretePlugin()

        plugin.add_conflict("IncompatiblePlugin")

        assert "IncompatiblePlugin" in plugin._conflicts

    def test_no_duplicate_conflicts(self):
        """Test doesn't add duplicate conflicts."""
        plugin = ConcretePlugin()

        plugin.add_conflict("IncompatiblePlugin")
        plugin.add_conflict("IncompatiblePlugin")

        assert plugin._conflicts.count("IncompatiblePlugin") == 1


@pytest.mark.unit
class TestPluginInitialize:
    """Test Plugin.initialize method."""

    def test_initialize_default_does_nothing(self):
        """Test default initialize does nothing (can be overridden)."""
        plugin = ConcretePlugin()
        app = Mock()

        # Should not raise
        plugin.initialize(app)


@pytest.mark.unit
class TestPluginCleanup:
    """Test Plugin.cleanup method."""

    def test_cleanup_default_does_nothing(self):
        """Test default cleanup does nothing (can be overridden)."""
        plugin = ConcretePlugin()
        app = Mock()

        # Should not raise
        plugin.cleanup(app)


# =============================================================================
# Test PluginManager
# =============================================================================


@pytest.mark.unit
class TestPluginManagerInit:
    """Test PluginManager initialization."""

    def test_initializes_empty(self):
        """Test manager initializes with empty collections."""
        manager = PluginManager()

        assert manager._plugins == {}
        assert manager._enabled_plugins == []
        assert manager._plugin_order == []


@pytest.mark.unit
class TestPluginManagerRegister:
    """Test PluginManager.register_plugin method."""

    def test_registers_enabled_plugin(self):
        """Test registers plugin and adds to enabled list."""
        manager = PluginManager()
        plugin = ConcretePlugin(name="TestPlugin")

        manager.register_plugin(plugin)

        assert "TestPlugin" in manager._plugins
        assert manager._plugins["TestPlugin"] is plugin
        assert "TestPlugin" in manager._enabled_plugins

    def test_registers_disabled_plugin(self):
        """Test registers disabled plugin without adding to enabled list."""
        manager = PluginManager()
        plugin = ConcretePlugin(name="TestPlugin")
        plugin.disable()

        manager.register_plugin(plugin)

        assert "TestPlugin" in manager._plugins
        assert "TestPlugin" not in manager._enabled_plugins

    def test_raises_on_duplicate_registration(self):
        """Test raises ValueError when registering duplicate plugin."""
        manager = PluginManager()
        plugin1 = ConcretePlugin(name="TestPlugin")
        plugin2 = ConcretePlugin(name="TestPlugin")

        manager.register_plugin(plugin1)

        with pytest.raises(ValueError) as exc_info:
            manager.register_plugin(plugin2)

        assert "already registered" in str(exc_info.value)


@pytest.mark.unit
class TestPluginManagerUnregister:
    """Test PluginManager.unregister_plugin method."""

    def test_unregisters_plugin(self):
        """Test removes plugin from all collections."""
        manager = PluginManager()
        plugin = ConcretePlugin(name="TestPlugin")
        manager.register_plugin(plugin)

        manager.unregister_plugin("TestPlugin")

        assert "TestPlugin" not in manager._plugins
        assert "TestPlugin" not in manager._enabled_plugins

    def test_unregister_removes_from_plugin_order(self):
        """Test removes plugin from order list."""
        manager = PluginManager()
        plugin = ConcretePlugin(name="TestPlugin")
        manager.register_plugin(plugin)
        manager._plugin_order.append("TestPlugin")

        manager.unregister_plugin("TestPlugin")

        assert "TestPlugin" not in manager._plugin_order

    def test_unregister_nonexistent_does_nothing(self):
        """Test unregistering nonexistent plugin doesn't raise."""
        manager = PluginManager()

        # Should not raise
        manager.unregister_plugin("NonexistentPlugin")


@pytest.mark.unit
class TestPluginManagerEnablePlugin:
    """Test PluginManager.enable_plugin method."""

    def test_enables_plugin(self):
        """Test enables disabled plugin."""
        manager = PluginManager()
        plugin = ConcretePlugin(name="TestPlugin")
        plugin.disable()
        manager.register_plugin(plugin)

        manager.enable_plugin("TestPlugin")

        assert plugin.enabled is True
        assert "TestPlugin" in manager._enabled_plugins

    def test_enable_already_enabled(self):
        """Test enabling already enabled plugin doesn't duplicate."""
        manager = PluginManager()
        plugin = ConcretePlugin(name="TestPlugin")
        manager.register_plugin(plugin)

        manager.enable_plugin("TestPlugin")

        assert manager._enabled_plugins.count("TestPlugin") == 1

    def test_enable_nonexistent_does_nothing(self):
        """Test enabling nonexistent plugin doesn't raise."""
        manager = PluginManager()

        # Should not raise
        manager.enable_plugin("NonexistentPlugin")


@pytest.mark.unit
class TestPluginManagerDisablePlugin:
    """Test PluginManager.disable_plugin method."""

    def test_disables_plugin(self):
        """Test disables enabled plugin."""
        manager = PluginManager()
        plugin = ConcretePlugin(name="TestPlugin")
        manager.register_plugin(plugin)

        manager.disable_plugin("TestPlugin")

        assert plugin.enabled is False
        assert "TestPlugin" not in manager._enabled_plugins

    def test_disable_nonexistent_does_nothing(self):
        """Test disabling nonexistent plugin doesn't raise."""
        manager = PluginManager()

        # Should not raise
        manager.disable_plugin("NonexistentPlugin")


@pytest.mark.unit
class TestPluginManagerGetPlugin:
    """Test PluginManager.get_plugin method."""

    def test_returns_plugin_when_exists(self):
        """Test returns plugin by name."""
        manager = PluginManager()
        plugin = ConcretePlugin(name="TestPlugin")
        manager.register_plugin(plugin)

        result = manager.get_plugin("TestPlugin")

        assert result is plugin

    def test_returns_none_when_not_found(self):
        """Test returns None for nonexistent plugin."""
        manager = PluginManager()

        result = manager.get_plugin("NonexistentPlugin")

        assert result is None


@pytest.mark.unit
class TestPluginManagerListPlugins:
    """Test PluginManager.list_plugins method."""

    def test_returns_all_plugin_names(self):
        """Test returns list of all registered plugin names."""
        manager = PluginManager()
        manager.register_plugin(ConcretePlugin(name="Plugin1"))
        manager.register_plugin(ConcretePlugin(name="Plugin2"))

        result = manager.list_plugins()

        assert "Plugin1" in result
        assert "Plugin2" in result

    def test_returns_empty_list_when_no_plugins(self):
        """Test returns empty list when no plugins registered."""
        manager = PluginManager()

        result = manager.list_plugins()

        assert result == []


@pytest.mark.unit
class TestPluginManagerListEnabledPlugins:
    """Test PluginManager.list_enabled_plugins method."""

    def test_returns_enabled_plugin_names(self):
        """Test returns only enabled plugin names."""
        manager = PluginManager()
        plugin1 = ConcretePlugin(name="EnabledPlugin")
        plugin2 = ConcretePlugin(name="DisabledPlugin")
        plugin2.disable()

        manager.register_plugin(plugin1)
        manager.register_plugin(plugin2)

        result = manager.list_enabled_plugins()

        assert "EnabledPlugin" in result
        assert "DisabledPlugin" not in result

    def test_returns_copy(self):
        """Test returns a copy, not the original list."""
        manager = PluginManager()
        manager.register_plugin(ConcretePlugin(name="TestPlugin"))

        result = manager.list_enabled_plugins()
        result.append("ModifiedPlugin")

        assert "ModifiedPlugin" not in manager._enabled_plugins


# =============================================================================
# Test Dependency Resolution
# =============================================================================


@pytest.mark.unit
class TestResolveDependencies:
    """Test PluginManager._resolve_dependencies method."""

    def test_resolves_simple_dependency(self):
        """Test resolves simple A depends on B."""
        manager = PluginManager()

        plugin_a = ConcretePlugin(name="PluginA")
        plugin_a.add_dependency("PluginB")

        plugin_b = ConcretePlugin(name="PluginB")

        manager.register_plugin(plugin_a)
        manager.register_plugin(plugin_b)

        manager._resolve_dependencies()

        # B should come before A
        assert manager._plugin_order.index("PluginB") < manager._plugin_order.index(
            "PluginA"
        )

    def test_resolves_chain_dependency(self):
        """Test resolves A -> B -> C dependency chain."""
        manager = PluginManager()

        plugin_a = ConcretePlugin(name="PluginA")
        plugin_a.add_dependency("PluginB")

        plugin_b = ConcretePlugin(name="PluginB")
        plugin_b.add_dependency("PluginC")

        plugin_c = ConcretePlugin(name="PluginC")

        manager.register_plugin(plugin_a)
        manager.register_plugin(plugin_b)
        manager.register_plugin(plugin_c)

        manager._resolve_dependencies()

        # Order should be C, B, A
        assert manager._plugin_order.index("PluginC") < manager._plugin_order.index(
            "PluginB"
        )
        assert manager._plugin_order.index("PluginB") < manager._plugin_order.index(
            "PluginA"
        )

    def test_detects_circular_dependency(self):
        """Test raises ValueError for circular dependencies."""
        manager = PluginManager()

        plugin_a = ConcretePlugin(name="PluginA")
        plugin_a.add_dependency("PluginB")

        plugin_b = ConcretePlugin(name="PluginB")
        plugin_b.add_dependency("PluginA")

        manager.register_plugin(plugin_a)
        manager.register_plugin(plugin_b)

        with pytest.raises(ValueError) as exc_info:
            manager._resolve_dependencies()

        assert "Circular dependency" in str(exc_info.value)

    def test_raises_for_unknown_dependency(self):
        """Test raises ValueError when depending on unknown plugin."""
        manager = PluginManager()

        plugin_a = ConcretePlugin(name="PluginA")
        plugin_a.add_dependency("NonexistentPlugin")

        manager.register_plugin(plugin_a)

        with pytest.raises(ValueError) as exc_info:
            manager._resolve_dependencies()

        assert "unknown plugin" in str(exc_info.value)

    def test_detects_conflict_with_enabled_plugin(self):
        """Test raises ValueError when conflicting plugin is enabled."""
        manager = PluginManager()

        plugin_a = ConcretePlugin(name="PluginA")
        plugin_a.add_conflict("PluginB")

        plugin_b = ConcretePlugin(name="PluginB")

        manager.register_plugin(plugin_a)
        manager.register_plugin(plugin_b)

        with pytest.raises(ValueError) as exc_info:
            manager._resolve_dependencies()

        assert "conflicts" in str(exc_info.value)


@pytest.mark.unit
class TestConfigureAll:
    """Test PluginManager.configure_all method."""

    def test_configures_enabled_plugins_in_order(self):
        """Test calls configure on enabled plugins in dependency order."""
        manager = PluginManager()

        configure_order = []

        class TrackingPlugin(Plugin):
            def configure(self, builder):
                configure_order.append(self.name)

        plugin_a = TrackingPlugin(name="PluginA")
        plugin_a.add_dependency("PluginB")

        plugin_b = TrackingPlugin(name="PluginB")

        manager.register_plugin(plugin_a)
        manager.register_plugin(plugin_b)

        builder = Mock()
        manager.configure_all(builder)

        # B should be configured before A
        assert configure_order == ["PluginB", "PluginA"]

    def test_skips_disabled_plugins(self):
        """Test doesn't configure disabled plugins."""
        manager = PluginManager()

        configured = []

        class TrackingPlugin(Plugin):
            def configure(self, builder):
                configured.append(self.name)

        plugin_enabled = TrackingPlugin(name="EnabledPlugin")
        plugin_disabled = TrackingPlugin(name="DisabledPlugin")
        plugin_disabled.disable()

        manager.register_plugin(plugin_enabled)
        manager.register_plugin(plugin_disabled)

        builder = Mock()
        manager.configure_all(builder)

        assert "EnabledPlugin" in configured
        assert "DisabledPlugin" not in configured


# =============================================================================
# Integration Tests
# =============================================================================


@pytest.mark.integration
class TestPluginSystemIntegration:
    """Integration tests for the plugin system."""

    def test_full_plugin_lifecycle(self):
        """Test complete plugin registration, configuration, and cleanup."""
        manager = PluginManager()

        initialized = []
        cleaned_up = []

        class LifecyclePlugin(Plugin):
            def configure(self, builder):
                pass

            def initialize(self, app):
                initialized.append(self.name)

            def cleanup(self, app):
                cleaned_up.append(self.name)

        plugin = LifecyclePlugin(name="TestPlugin")
        manager.register_plugin(plugin)

        # Configure
        builder = Mock()
        manager.configure_all(builder)

        # Initialize
        app = Mock()
        plugin.initialize(app)

        # Cleanup
        plugin.cleanup(app)

        assert "TestPlugin" in initialized
        assert "TestPlugin" in cleaned_up

    def test_complex_dependency_graph(self):
        """Test complex dependency resolution."""
        manager = PluginManager()

        configure_order = []

        class OrderPlugin(Plugin):
            def configure(self, builder):
                configure_order.append(self.name)

        # Create dependency graph:
        # D depends on C
        # C depends on B
        # B depends on A
        # E depends on A and C

        plugin_a = OrderPlugin(name="A")
        plugin_b = OrderPlugin(name="B")
        plugin_b.add_dependency("A")
        plugin_c = OrderPlugin(name="C")
        plugin_c.add_dependency("B")
        plugin_d = OrderPlugin(name="D")
        plugin_d.add_dependency("C")
        plugin_e = OrderPlugin(name="E")
        plugin_e.add_dependency("A")
        plugin_e.add_dependency("C")

        # Register in random order
        manager.register_plugin(plugin_d)
        manager.register_plugin(plugin_b)
        manager.register_plugin(plugin_e)
        manager.register_plugin(plugin_a)
        manager.register_plugin(plugin_c)

        builder = Mock()
        manager.configure_all(builder)

        # Verify dependencies are satisfied
        assert configure_order.index("A") < configure_order.index("B")
        assert configure_order.index("B") < configure_order.index("C")
        assert configure_order.index("C") < configure_order.index("D")
        assert configure_order.index("A") < configure_order.index("E")
        assert configure_order.index("C") < configure_order.index("E")

    def test_enable_disable_workflow(self):
        """Test enabling and disabling plugins."""
        manager = PluginManager()

        plugin = ConcretePlugin(name="TogglePlugin")
        manager.register_plugin(plugin)

        assert "TogglePlugin" in manager.list_enabled_plugins()

        manager.disable_plugin("TogglePlugin")
        assert "TogglePlugin" not in manager.list_enabled_plugins()

        manager.enable_plugin("TogglePlugin")
        assert "TogglePlugin" in manager.list_enabled_plugins()

    def test_conflict_resolution(self):
        """Test that conflicts are detected during configuration."""
        manager = PluginManager()

        # Plugin A conflicts with Plugin B
        plugin_a = ConcretePlugin(name="MutuallyExclusiveA")
        plugin_a.add_conflict("MutuallyExclusiveB")

        plugin_b = ConcretePlugin(name="MutuallyExclusiveB")

        manager.register_plugin(plugin_a)
        manager.register_plugin(plugin_b)

        builder = Mock()

        with pytest.raises(ValueError) as exc_info:
            manager.configure_all(builder)

        assert "conflicts" in str(exc_info.value)

    def test_conflict_avoided_when_conflicting_disabled(self):
        """Test no conflict when conflicting plugin is disabled."""
        manager = PluginManager()

        plugin_a = ConcretePlugin(name="PluginA")
        plugin_a.add_conflict("PluginB")

        plugin_b = ConcretePlugin(name="PluginB")
        plugin_b.disable()

        manager.register_plugin(plugin_a)
        manager.register_plugin(plugin_b)

        builder = Mock()
        # Should not raise since PluginB is disabled
        manager.configure_all(builder)


# =============================================================================
# Test Plugin Cleanup
# =============================================================================


@pytest.mark.unit
class TestPluginManagerCleanup:
    """Test plugin cleanup_all method."""

    def test_cleanup_all_calls_plugin_cleanup(self):
        """Test cleanup_all calls cleanup on all initialized plugins."""
        manager = PluginManager()
        app = Mock()

        plugin_a = ConcretePlugin(name="PluginA")
        plugin_a.cleanup = Mock()
        plugin_b = ConcretePlugin(name="PluginB")
        plugin_b.cleanup = Mock()

        manager.register_plugin(plugin_a)
        manager.register_plugin(plugin_b)

        # Configure to mark as initialized
        builder = Mock()
        manager.configure_all(builder)

        # Cleanup
        manager.cleanup_all(app)

        plugin_a.cleanup.assert_called_once_with(app)
        plugin_b.cleanup.assert_called_once_with(app)

    def test_cleanup_all_lifo_order(self):
        """Test cleanup_all cleans up in LIFO order."""
        manager = PluginManager()
        app = Mock()
        cleanup_order = []

        plugin_a = ConcretePlugin(name="PluginA")
        plugin_a.cleanup = Mock(side_effect=lambda _: cleanup_order.append("A"))

        plugin_b = ConcretePlugin(name="PluginB")
        plugin_b.cleanup = Mock(side_effect=lambda _: cleanup_order.append("B"))

        plugin_c = ConcretePlugin(name="PluginC")
        plugin_c.cleanup = Mock(side_effect=lambda _: cleanup_order.append("C"))

        manager.register_plugin(plugin_a)
        manager.register_plugin(plugin_b)
        manager.register_plugin(plugin_c)

        # Configure in order A, B, C
        builder = Mock()
        manager.configure_all(builder)

        # Cleanup should be in reverse: C, B, A
        manager.cleanup_all(app)

        assert cleanup_order == ["C", "B", "A"]

    def test_cleanup_all_handles_exception(self):
        """Test cleanup_all continues on exception."""
        manager = PluginManager()
        app = Mock()

        plugin_a = ConcretePlugin(name="PluginA")
        plugin_a.cleanup = Mock(side_effect=RuntimeError("Cleanup failed"))

        plugin_b = ConcretePlugin(name="PluginB")
        plugin_b.cleanup = Mock()

        manager.register_plugin(plugin_a)
        manager.register_plugin(plugin_b)

        builder = Mock()
        manager.configure_all(builder)

        # Should not raise
        with patch("logging.error") as mock_log:
            manager.cleanup_all(app)

            # Both plugins should be attempted
            plugin_a.cleanup.assert_called_once()
            plugin_b.cleanup.assert_called_once()

            # Error should be logged
            mock_log.assert_called_once()

    def test_cleanup_all_only_cleans_initialized(self):
        """Test cleanup_all only cleans up initialized plugins."""
        manager = PluginManager()
        app = Mock()

        plugin_a = ConcretePlugin(name="PluginA")
        plugin_a.cleanup = Mock()

        plugin_b = ConcretePlugin(name="PluginB")
        plugin_b.cleanup = Mock()

        manager.register_plugin(plugin_a)
        manager.register_plugin(plugin_b)

        # Only configure plugin_a
        builder = Mock()
        manager._plugin_order = ["PluginA"]
        manager._enabled_plugins = ["PluginA"]
        manager._initialized_plugins = ["PluginA"]

        manager.cleanup_all(app)

        # Only plugin_a should be cleaned
        plugin_a.cleanup.assert_called_once()
        plugin_b.cleanup.assert_not_called()

    def test_cleanup_all_empty_manager(self):
        """Test cleanup_all handles empty plugin manager."""
        manager = PluginManager()
        app = Mock()

        # Should not raise
        manager.cleanup_all(app)
