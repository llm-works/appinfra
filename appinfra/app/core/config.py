# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Application configuration management.

This module provides configuration classes and loaders for the application framework.
"""

import argparse
from typing import Any

from ...config import Config
from ...dot_dict import DotDict

# Logging level constant for quiet mode (suppresses all logging)
LOG_LEVEL_QUIET = 1000


class ConfigLoader:
    """Loads configuration from various sources."""

    @staticmethod
    def _ensure_nested_section(config: DotDict, *path: str) -> DotDict:
        """
        Ensure a nested section exists in config, creating it if needed.

        Args:
            config: Root config object
            *path: Path components (e.g., 'logging', 'handlers', 'console')

        Returns:
            The innermost section

        Example:
            section = _ensure_nested_section(config, 'logging', 'handlers')
            # Now config.logging.handlers exists
        """
        current = config
        for key in path:
            if not hasattr(current, key):
                setattr(current, key, DotDict())
            current = getattr(current, key)
        return current

    @staticmethod
    def _get_arg(args: argparse.Namespace, name: str, default: Any = None) -> Any:
        """
        Safely get argument value with default.

        Args:
            args: Parsed arguments
            name: Argument name
            default: Default value if not present

        Returns:
            Argument value or default
        """
        return getattr(args, name, default) if hasattr(args, name) else default

    @staticmethod
    def _set_if_present(
        config: DotDict, args: argparse.Namespace, arg_name: str, config_path: str
    ) -> None:
        """
        Set config value from arg if arg is present.

        Args:
            config: Config object to update
            args: Parsed arguments
            arg_name: Name of argument to check
            config_path: Dot-separated path in config (e.g., 'logging.level')
        """
        if not hasattr(args, arg_name):
            return

        value = getattr(args, arg_name)
        if value is None:
            return

        # Parse config path and set value
        parts = config_path.split(".")
        target = config
        for part in parts[:-1]:
            if not hasattr(target, part):
                setattr(target, part, DotDict())
            target = getattr(target, part)
        setattr(target, parts[-1], value)

    @staticmethod
    def from_args(
        args: argparse.Namespace,
        existing_config: Config | DotDict | None = None,
    ) -> Config | DotDict:
        """
        Apply command-line arguments to config, respecting YAML structure.

        Args:
            args: Parsed command-line arguments
            existing_config: Existing config to update (optional)

        Returns:
            Updated config object
        """
        # Start with existing config or create default
        config = existing_config if existing_config else DotDict()

        # Ensure logging section exists with defaults
        ConfigLoader._ensure_nested_section(config, "logging")

        # Set defaults if not already present
        if not hasattr(config.logging, "level"):  # type: ignore[attr-defined]
            config.logging.level = "info"  # type: ignore[attr-defined]
        if not hasattr(config.logging, "location"):  # type: ignore[attr-defined]
            config.logging.location = 0  # type: ignore[attr-defined]
        if not hasattr(config.logging, "micros"):  # type: ignore[attr-defined]
            config.logging.micros = False  # type: ignore[attr-defined]

        # Handle quiet mode (special case - disables logging)
        if ConfigLoader._get_arg(args, "quiet", False):
            config.logging.level = LOG_LEVEL_QUIET  # type: ignore[attr-defined]
        else:
            # Apply standard logging arguments (override defaults)
            ConfigLoader._set_if_present(config, args, "log_level", "logging.level")

        ConfigLoader._set_if_present(config, args, "log_location", "logging.location")
        ConfigLoader._set_if_present(config, args, "log_micros", "logging.micros")
        ConfigLoader._set_if_present(config, args, "default_tool", "default_tool")

        # Store etc_dir if provided (used for config loading override)
        ConfigLoader._set_if_present(config, args, "etc_dir", "etc_dir")

        return config

    @staticmethod
    def default() -> DotDict:
        """Create default configuration with logging section."""
        return DotDict(logging=DotDict(level="info", location=0, micros=False))
