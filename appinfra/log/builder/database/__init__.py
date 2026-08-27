# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Database logging package.

Provides database logging handlers, configuration, and fluent builder API
for logging to database tables.
"""

from .builder import (
    DatabaseLoggingBuilder,
    create_database_logger,
    create_database_logger_from_config,
    load_database_logging_config,
)
from .config import DatabaseHandlerConfig
from .handler import DatabaseHandler

__all__ = [
    "DatabaseHandlerConfig",
    "DatabaseHandler",
    "DatabaseLoggingBuilder",
    "create_database_logger",
    "load_database_logging_config",
    "create_database_logger_from_config",
]
