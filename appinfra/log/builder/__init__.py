# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Logging builder module for creating and configuring loggers with a fluent API.

This module provides various builder classes and factory functions for creating
loggers with different configurations and output formats.

Note: Database logging requires the [sql] extra: pip install appinfra[sql]
"""

from typing import TYPE_CHECKING

from .builder import (
    LoggingBuilder,
    create_logger,
)
from .console import (
    ConsoleHandlerConfig,
    ConsoleLoggingBuilder,
    create_console_logger,
)

# Lazy imports for database module (requires sqlalchemy - optional [sql] extra)
if TYPE_CHECKING:
    from .database import (
        DatabaseHandler,
        DatabaseHandlerConfig,
        DatabaseLoggingBuilder,
        create_database_logger,
    )

from .file import (
    FileHandlerConfig,
    FileLoggingBuilder,
    RotatingFileHandlerConfig,
    TimedRotatingFileHandlerConfig,
    create_file_logger,
)
from .interface import HandlerConfig, LoggingBuilderInterface
from .json import (
    JSONFormatter,
    JSONLoggingBuilder,
    create_json_logger,
)
from .quick import (
    quick_audit_logger,
    quick_both_logger,
    quick_both_outputs,
    quick_console_and_file,
    quick_console_logger,
    quick_console_with_colors,
    quick_custom_database_logger,
    quick_daily_file_logger,
    quick_error_logger,
    quick_file_logger,
    quick_file_with_rotation,
    quick_json_console,
    quick_json_file,
)

__all__ = [
    # Main builder classes
    "LoggingBuilder",
    "LoggingBuilderInterface",
    "JSONLoggingBuilder",
    "ConsoleLoggingBuilder",
    "FileLoggingBuilder",
    "MultiOutputLoggingBuilder",
    "DatabaseLoggingBuilder",
    "JSONFormatter",
    # Handler configuration classes
    "HandlerConfig",
    "ConsoleHandlerConfig",
    "FileHandlerConfig",
    "RotatingFileHandlerConfig",
    "TimedRotatingFileHandlerConfig",
    "DatabaseHandlerConfig",
    "DatabaseHandler",
    # Factory functions
    "create_logger",
    "create_json_logger",
    "create_console_logger",
    "create_file_logger",
    "create_multi_output_logger",
    "create_database_logger",
    # Quick setup functions
    "quick_console_logger",
    "quick_file_logger",
    "quick_both_logger",
    "quick_console_with_colors",
    "quick_file_with_rotation",
    "quick_daily_file_logger",
    "quick_console_and_file",
    "quick_json_console",
    "quick_json_file",
    "quick_both_outputs",
    "quick_audit_logger",
    "quick_error_logger",
    "quick_custom_database_logger",
]

# Lazy loading for database module (requires sqlalchemy)
_DATABASE_EXPORTS = {
    "DatabaseHandler",
    "DatabaseHandlerConfig",
    "DatabaseLoggingBuilder",
    "create_database_logger",
}


def __getattr__(name: str) -> object:
    """Lazy import for database module (requires sqlalchemy - optional [sql] extra)."""
    if name in _DATABASE_EXPORTS:
        from . import database

        return getattr(database, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
