# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
AppBuilder framework for constructing CLI applications.

This module provides a fluent, declarative API for building applications
with tools, middleware, configuration, and lifecycle management.
"""

from .app import AppBuilder, create_app_builder
from .config import (
    ConfigBuilder,
    LoggingConfigBuilder,
    ServerConfigBuilder,
    create_config_builder,
    create_logging_config_builder,
    create_server_config_builder,
)
from .hook import HookBuilder, HookManager, create_hook_builder
from .middleware import MiddlewareBuilder, create_middleware_builder
from .plugin import Plugin, PluginManager
from .tool import ToolBuilder, create_tool_builder
from .validation import (
    ValidationBuilder,
    ValidationResult,
    ValidationRule,
    create_validation_builder,
)

__all__ = [
    # Builder classes
    "AppBuilder",
    "ConfigBuilder",
    "ServerConfigBuilder",
    "LoggingConfigBuilder",
    "ToolBuilder",
    "MiddlewareBuilder",
    "ValidationBuilder",
    "ValidationRule",
    "ValidationResult",
    "HookBuilder",
    "HookManager",
    "Plugin",
    "PluginManager",
    # Factory functions
    "create_app_builder",
    "create_config_builder",
    "create_server_config_builder",
    "create_logging_config_builder",
    "create_tool_builder",
    "create_middleware_builder",
    "create_validation_builder",
    "create_hook_builder",
]
