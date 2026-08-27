# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Plugin system for the AppBuilder framework.

This module provides a plugin architecture for extending application
functionality in a modular way.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from ..core.app import App

if TYPE_CHECKING:
    from .builder import AppBuilder


class Plugin(ABC):
    """Base class for application plugins."""

    def __init__(self, name: str | None = None):
        """
        Initialize the plugin.

        Args:
            name: Plugin name (defaults to class name)
        """
        self.name = name or self.__class__.__name__
        self._enabled = True
        self._dependencies: list[str] = []
        self._conflicts: list[str] = []

    @property
    def enabled(self) -> bool:
        """Check if the plugin is enabled."""
        return self._enabled

    def enable(self) -> None:
        """Enable the plugin."""
        self._enabled = True

    def disable(self) -> None:
        """Disable the plugin."""
        self._enabled = False

    def add_dependency(self, plugin_name: str) -> None:
        """Add a plugin dependency."""
        if plugin_name not in self._dependencies:
            self._dependencies.append(plugin_name)

    def add_conflict(self, plugin_name: str) -> None:
        """Add a plugin conflict."""
        if plugin_name not in self._conflicts:
            self._conflicts.append(plugin_name)

    @abstractmethod
    def configure(self, builder: AppBuilder) -> None:
        """
        Configure the application builder with plugin features.

        Args:
            builder: Application builder to configure
        """
        pass

    def initialize(self, application: App) -> None:
        """
        Initialize the plugin with the application.

        Args:
            application: Application instance
        """
        pass

    def cleanup(self, application: App) -> None:
        """
        Clean up plugin resources.

        Args:
            application: Application instance
        """
        pass


class PluginManager:
    """Manages application plugins."""

    def __init__(self) -> None:
        self._plugins: dict[str, Plugin] = {}
        self._enabled_plugins: list[str] = []
        self._plugin_order: list[str] = []
        self._initialized_plugins: list[str] = []  # Track initialized plugins

    def register_plugin(self, plugin: Plugin) -> None:
        """
        Register a plugin.

        Args:
            plugin: Plugin instance to register
        """
        if plugin.name in self._plugins:
            raise ValueError(f"Plugin '{plugin.name}' is already registered")

        self._plugins[plugin.name] = plugin
        if plugin.enabled:
            self._enabled_plugins.append(plugin.name)

    def unregister_plugin(self, name: str) -> None:
        """
        Unregister a plugin.

        Args:
            name: Plugin name
        """
        if name in self._plugins:
            del self._plugins[name]
            if name in self._enabled_plugins:
                self._enabled_plugins.remove(name)
            if name in self._plugin_order:
                self._plugin_order.remove(name)

    def enable_plugin(self, name: str) -> None:
        """
        Enable a plugin.

        Args:
            name: Plugin name
        """
        if name in self._plugins:
            self._plugins[name].enable()
            if name not in self._enabled_plugins:
                self._enabled_plugins.append(name)

    def disable_plugin(self, name: str) -> None:
        """
        Disable a plugin.

        Args:
            name: Plugin name
        """
        if name in self._plugins:
            self._plugins[name].disable()
            if name in self._enabled_plugins:
                self._enabled_plugins.remove(name)

    def get_plugin(self, name: str) -> Plugin | None:
        """
        Get a plugin by name.

        Args:
            name: Plugin name

        Returns:
            Plugin instance or None if not found
        """
        return self._plugins.get(name)

    def list_plugins(self) -> list[str]:
        """List all registered plugin names."""
        return list(self._plugins.keys())

    def list_enabled_plugins(self) -> list[str]:
        """List enabled plugin names."""
        return self._enabled_plugins.copy()

    def configure_all(self, builder: AppBuilder) -> None:
        """
        Configure all enabled plugins with the application builder.

        Args:
            builder: AppBuilder instance
        """
        # Resolve plugin dependencies and conflicts
        self._resolve_dependencies()

        # Configure plugins in dependency order
        for plugin_name in self._plugin_order:
            if plugin_name in self._enabled_plugins:
                plugin = self._plugins[plugin_name]
                plugin.configure(builder)
                # Track as initialized for cleanup
                if plugin_name not in self._initialized_plugins:
                    self._initialized_plugins.append(plugin_name)

    def _check_plugin_dependencies(
        self, plugin_name: str, plugin: Any, visit_fn: Any
    ) -> None:
        """Check and recursively visit plugin dependencies."""
        for dep in plugin._dependencies:
            if dep not in self._plugins:
                raise ValueError(
                    f"Plugin '{plugin_name}' depends on unknown plugin '{dep}'"
                )
            visit_fn(dep)

    def _check_plugin_conflicts(self, plugin_name: str, plugin: Any) -> None:
        """Check for conflicts with enabled plugins."""
        for conflict in plugin._conflicts:
            if conflict in self._enabled_plugins:
                raise ValueError(
                    f"Plugin '{plugin_name}' conflicts with enabled plugin '{conflict}'"
                )

    def _resolve_dependencies(self) -> None:
        """Resolve plugin dependencies and determine load order."""
        self._plugin_order = []
        visited = set()
        temp_visited = set()

        def visit(plugin_name: str) -> None:
            if plugin_name in temp_visited:
                raise ValueError(
                    f"Circular dependency detected involving plugin '{plugin_name}'"
                )
            if plugin_name in visited:
                return

            temp_visited.add(plugin_name)

            if plugin_name in self._plugins:
                plugin = self._plugins[plugin_name]
                self._check_plugin_dependencies(plugin_name, plugin, visit)
                self._check_plugin_conflicts(plugin_name, plugin)

            temp_visited.remove(plugin_name)
            visited.add(plugin_name)
            self._plugin_order.append(plugin_name)

        for plugin_name in self._enabled_plugins:
            visit(plugin_name)

    def cleanup_all(self, application: Any) -> None:
        """
        Clean up all initialized plugins in reverse order.

        Cleanup happens in LIFO order (last initialized, first cleaned)
        to respect dependency relationships.

        Args:
            application: Application instance to pass to cleanup methods
        """
        import logging

        # Cleanup in reverse order
        for plugin_name in reversed(self._initialized_plugins):
            plugin = self._plugins.get(plugin_name)
            if plugin:
                try:
                    plugin.cleanup(application)
                except Exception as e:
                    # Log error but continue with other cleanups
                    logging.error(
                        "plugin cleanup failed",
                        extra={"plugin": plugin_name, "exception": e},
                    )


__all__ = [
    "Plugin",
    "PluginManager",
]
