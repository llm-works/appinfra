# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Application configuration management.

This module provides configuration classes and loaders for the application framework.
"""

import argparse
from pathlib import Path
from typing import Any

from ...config import Config, get_etc_dir
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


def create_config(
    file_path: str | None = None,
    file_name: str | None = None,
    dir_name: str | None = None,
    load_all: bool = False,
    lg: Any | None = None,
) -> Config | DotDict:
    """
    Create configuration from YAML files with flexible path resolution.

    This function handles loading configuration from various sources:
    - Single file by full path (file_path parameter)
    - Single file by name in a specific directory (file_name + dir_name)
    - Multiple files merged together (load_all=True)

    Args:
        file_path: Full path to a specific config file (takes precedence if provided)
        file_name: Name of config file (e.g., "infra.yaml", "app.yaml")
        dir_name: Directory to search for config files (defaults to "etc" directory)
        load_all: If True, loads and merges all YAML files from dir_name
        lg: Optional logger instance. If provided, will log warnings for failed config files.
            If None, no logging will occur.

    Returns:
        Config object or DotDict with loaded configuration

    Raises:
        FileNotFoundError: If specified config file not found
        ValueError: If neither file_path nor file_name is provided when load_all=False
    """
    if dir_name is None:
        dir_name = str(get_etc_dir())

    # Mode 1: Load single file by full path
    if file_path is not None:
        return _load_config_by_path(file_path)

    # Mode 2: Load and merge all YAML files from directory
    if load_all:
        return _load_all_configs(dir_name, lg)

    # Mode 3: Load single file by name in directory
    return _load_config_by_name(file_name, dir_name)


def _load_config_by_path(file_path: str) -> Config:
    """Load config from a specific file path."""
    config_path = Path(file_path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    return Config(str(config_path))


def _load_all_configs(dir_name: str, lg: Any | None) -> DotDict:
    """Load and merge all YAML files from a directory."""
    config_dir = Path(dir_name)
    if not config_dir.exists():
        raise FileNotFoundError(f"Config directory not found: {config_dir}")

    yaml_files = list(config_dir.glob("*.yaml")) + list(config_dir.glob("*.yml"))

    if not yaml_files:
        raise FileNotFoundError(f"No YAML files found in directory: {config_dir}")

    # Merge all configurations
    final_config = {}
    for yaml_file in yaml_files:
        try:
            file_config = Config(str(yaml_file))
            config_dict = _convert_to_dict(file_config)
            # Merge configurations (later files can override earlier ones)
            final_config.update(config_dict)
        except Exception as e:
            if lg:
                lg.warning(
                    "failed to load config file",
                    extra={"file": str(yaml_file), "exception": e},
                )

    return DotDict(**final_config)


def _convert_to_dict(obj: Any) -> Any:
    """Recursively convert config objects to plain dictionaries."""
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    elif isinstance(obj, dict):
        return {k: _convert_to_dict(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_convert_to_dict(item) for item in obj]
    else:
        return obj


def _load_config_by_name(file_name: str | None, dir_name: str) -> Config:
    """Load config by file name in a directory."""
    if file_name is None:
        file_name = "infra.yaml"  # Default config file name

    config_path = Path(dir_name) / file_name
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    return Config(str(config_path))
