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

from .config import (
    DEFAULT_CONFIG_FILE,
    DEFAULT_CONFIG_FILENAME,
    ETC_DIR,
    PROJECT_ROOT,
    Config,
    get_config_file_path,
    get_default_config,
    get_etc_dir,
    get_project_root,
    resolve_etc_dir,
)
from .constants import MAX_CONFIG_SIZE_BYTES
from .watcher import ConfigWatcher
from .xdg import xdg_candidates

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
    # Config class and utilities
    "Config",
    "get_project_root",
    "get_etc_dir",
    "resolve_etc_dir",
    "get_config_file_path",
    "get_default_config",
    "PROJECT_ROOT",
    "ETC_DIR",
    "DEFAULT_CONFIG_FILE",
    "DEFAULT_CONFIG_FILENAME",
    # Watcher
    "ConfigWatcher",
    # XDG discovery
    "xdg_candidates",
    # Constants
    "MAX_CONFIG_SIZE_BYTES",
    # Validation (optional)
    "InfraConfig",
    "LoggingConfig",
    "DatabaseConfig",
    "validate_config",
    "PYDANTIC_AVAILABLE",
]
