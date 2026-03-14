"""
Modern application framework for CLI tools and applications.

This module provides a comprehensive framework for building CLI applications with:
- AppBuilder for fluent application construction
- Tool framework with classes and protocols
- Server framework with middleware support
- Configuration and lifecycle management
- Validation and hook systems
- Plugin architecture
"""

# Import core modules
from ..config import (
    DEFAULT_CONFIG_FILE,
    DEFAULT_CONFIG_FILENAME,
    ETC_DIR,
    PROJECT_ROOT,
    Config,
    get_config_file_path,
    get_default_config,
    get_etc_dir,
    get_project_root,
)
from .args import DefaultsHelpFormatter
from .builder import (
    AppBuilder,
    ConfigBuilder,
    HookBuilder,
    HookManager,
    LoggingConfigBuilder,
    MiddlewareBuilder,
    Plugin,
    PluginManager,
    ServerConfigBuilder,
    ToolBuilder,
    ValidationBuilder,
    ValidationResult,
    ValidationRule,
)
from .cli import CLIParser, CommandHandler, HelpGenerator
from .core import (
    App,
    ConfigLoader,
    LifecycleManager,
    setup_logging_from_config,
)
from .core.config import create_config
from .decorators import DecoratorAPI, ToolFunction
from .errors import *
from .server import Middleware, RequestHandler, RouteManager, Server
from .server.base import get_server_routes, lock_helper
from .testing import MockApp
from .tools import Tool, ToolConfig, ToolGroup, ToolRegistry
from .tools.protocol import ToolProtocol
from .tracing import Traceable
from .utils import disable_urllib_warnings

__all__ = [
    # Core API
    "App",
    "ToolRegistry",
    "LifecycleManager",
    "ConfigLoader",
    "setup_logging_from_config",
    "create_config",
    "CLIParser",
    "CommandHandler",
    "HelpGenerator",
    "Tool",
    "ToolConfig",
    "ToolGroup",
    "Server",
    "RouteManager",
    "RequestHandler",
    "Middleware",
    "Traceable",
    "ToolProtocol",
    "DefaultsHelpFormatter",
    # Configuration
    "Config",
    "get_project_root",
    "get_etc_dir",
    "get_config_file_path",
    "get_default_config",
    "PROJECT_ROOT",
    "ETC_DIR",
    "DEFAULT_CONFIG_FILE",
    "DEFAULT_CONFIG_FILENAME",
    # AppBuilder API
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
    # Decorator API
    "DecoratorAPI",
    "ToolFunction",
    # Utilities
    "lock_helper",
    "get_server_routes",
    "disable_urllib_warnings",
    # Testing
    "MockApp",
    # Errors
    "InfraAppError",
    "UndefNameError",
    "UndefGroupError",
    "NoSubToolsError",
    "DupToolError",
    "MissingRunFuncError",
    "MissingParentError",
    "AttrNotFoundError",
    "ToolRegistrationError",
    "ConfigError",
    "LifecycleError",
    "AppError",
    "CommandError",
]
