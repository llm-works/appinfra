# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Configuration management package.

This module provides:
- Config class for loading YAML configuration files
- ConfigWatcher for hot-reload of configuration
- Optional schema validation using Pydantic (if installed)
"""

from .config import Config
from .constants import MAX_CONFIG_SIZE_BYTES
from .spec import AUTO, Auto, ConfigFile, ConfigSpec
from .watcher import ConfigWatcher

# The schema models need pydantic (the validation extra); without it they are not exported
try:
    from .schemas import DatabaseConfig, InfraConfig, LoggingConfig, validate_config
except ImportError:
    PYDANTIC_AVAILABLE = False
else:
    PYDANTIC_AVAILABLE = True


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
    "PYDANTIC_AVAILABLE",
]
if PYDANTIC_AVAILABLE:
    __all__ += ["InfraConfig", "LoggingConfig", "DatabaseConfig", "validate_config"]
