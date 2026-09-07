# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Configuration management package.

This module provides:
- Config class for loading YAML configuration files
- ConfigWatcher for hot-reload of configuration
- Optional schema validation using Pydantic (if installed)
"""

from typing import Any

from .config import Config
from .constants import MAX_CONFIG_SIZE_BYTES
from .spec import AUTO, Auto, ConfigFile, ConfigSpec
from .watcher import ConfigWatcher

try:
    from .schemas import (
        PYDANTIC_AVAILABLE,
        DatabaseConfig,
        InfraConfig,
        LoggingConfig,
        validate_config,
    )
except ImportError:
    # Pydantic not installed - validation not available
    PYDANTIC_AVAILABLE = False
    InfraConfig: type[Any] | None = None  # type: ignore[no-redef]
    LoggingConfig: type[Any] | None = None  # type: ignore[no-redef]
    DatabaseConfig: type[Any] | None = None  # type: ignore[no-redef]

    def validate_config(config_dict: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-redef,misc]
        """No-op validation when pydantic is not installed."""
        return config_dict


__all__ = [
    # Config class
    "Config",
    # Watcher
    "ConfigWatcher",
    # Config-protocol identity and resolution
    "ConfigSpec",
    "ConfigFile",
    "AUTO",
    "Auto",
    # Constants
    "MAX_CONFIG_SIZE_BYTES",
    # Validation (optional)
    "InfraConfig",
    "LoggingConfig",
    "DatabaseConfig",
    "validate_config",
    "PYDANTIC_AVAILABLE",
]
