"""
Configuration management module for loading and resolving YAML configuration files.

This module provides a Config class that extends DotDict to handle YAML configuration
files with variable substitution capabilities, environment variable overrides, and
file inclusion support via !include tags.
"""

import os
import re
from pathlib import Path
from typing import Any, Self

import yaml  # type: ignore[import-untyped]

from ..dot_dict import DotDict
from .constants import MAX_CONFIG_SIZE_BYTES

# Helper functions for Config._load()


def _preserve_config_attributes(config_instance: Any) -> dict[str, Any]:
    """Preserve configuration attributes before clearing."""
    return {
        "enable_env_overrides": getattr(config_instance, "_enable_env_overrides", True),
        "env_prefix": getattr(config_instance, "_env_prefix", "INFRA_"),
        "merge_strategy": getattr(config_instance, "_merge_strategy", "replace"),
    }


def _restore_config_attributes(
    config_instance: Any, preserved_attrs: dict[str, Any]
) -> None:
    """Restore configuration attributes after clearing."""
    config_instance._enable_env_overrides = preserved_attrs["enable_env_overrides"]
    config_instance._env_prefix = preserved_attrs["env_prefix"]
    config_instance._merge_strategy = preserved_attrs["merge_strategy"]


def _check_file_size(fname_path: Any) -> None:
    """Check file size limit to prevent DoS attacks."""
    file_size = os.path.getsize(fname_path)
    if file_size > MAX_CONFIG_SIZE_BYTES:
        raise ValueError(
            f"Configuration file '{fname_path}' is {file_size} bytes, "
            f"exceeding maximum size of {MAX_CONFIG_SIZE_BYTES} bytes "
            f"({MAX_CONFIG_SIZE_BYTES // (1024 * 1024)} MB)"
        )


def _get_project_root_from_config(config_path: Path) -> Path | None:
    """
    Determine project root from config file location.

    Searches upward from the config file's directory for a directory
    containing an 'etc' folder. This allows appinfra to work correctly
    when used as a submodule, where the consuming project's config
    defines the security boundary.

    Args:
        config_path: Resolved path to the config file being loaded

    Returns:
        Path to project root, or None if not determinable
    """
    # Search upward from the config file's directory
    for parent in config_path.parents:
        if (parent / "etc").is_dir():
            return parent

    # Fallback: use config file's parent directory
    return config_path.parent


def _load_yaml_with_includes(
    fname_path: Any, merge_strategy: str, project_root: Path | None = None
) -> tuple[Any, dict[str, Path | None]]:
    """
    Load YAML file with include support.

    Args:
        fname_path: Path to the YAML file to load
        merge_strategy: Strategy for merging includes
        project_root: Optional project root to restrict includes (security feature)
    """
    from ..yaml import load as yaml_load

    with open(fname_path) as f:
        try:
            return yaml_load(
                f,
                current_file=fname_path,
                merge_strategy=merge_strategy,
                track_sources=True,
                project_root=project_root,
            )
        except yaml.YAMLError as e:
            raise e


class Config(DotDict):
    """
    Configuration class that loads YAML files and resolves variable substitutions.

    Extends DotDict to provide a dictionary-like interface for configuration data.
    Supports variable substitution using ${variable_name} syntax in YAML values.
    Supports environment variable overrides using INFRA_* prefix.
    Supports file inclusion via !include tags with circular dependency detection.

    Environment Variable Override Format:
        INFRA_<SECTION>_<SUBSECTION>_<KEY>=value

    Hyphenated Keys:
        YAML keys with hyphens are automatically matched to environment variables
        with underscores. Hyphens and underscores are treated as equivalent during
        lookup.

        Example:
            YAML: services.web-server.port
            Env:  INFRA_SERVICES_WEB_SERVER_PORT=8080

    Examples:
        INFRA_LOGGING_LEVEL=debug
        INFRA_PGSERVER_PORT=5432
        INFRA_SERVICES_WEB_SERVER_PORT=8080  # Matches 'web-server' key

    Include Example:
        # In config.yaml:
        database: !include "./database_config.yaml"

        # Supports relative paths (resolved from config file's directory)
        # Supports absolute paths
        # Detects circular includes

    Example:
        config = Config('config.yaml')
        # Access configuration values like dictionary keys
        value = config.get('database.host')
    """

    def __init__(
        self,
        fname: str,
        enable_env_overrides: bool = True,
        env_prefix: str = "INFRA_",
        merge_strategy: str = "replace",
    ):
        """
        Initialize configuration from a YAML file with optional environment variable overrides.

        Args:
            fname: Path to the YAML configuration file
            enable_env_overrides: Whether to apply environment variable overrides
            env_prefix: Prefix for environment variables (default: 'INFRA_')
            merge_strategy: Strategy for handling includes - "replace" or "merge" (default: "replace")
                           Note: Currently only "replace" is fully supported

        Note:
            Path resolution is handled explicitly via the !path YAML tag. Use !path for paths
            that should be resolved relative to the config file or for tilde (~) expansion.
        """
        super().__init__()  # Initialize DotDict first
        self._enable_env_overrides = enable_env_overrides
        self._env_prefix = env_prefix
        self._merge_strategy = merge_strategy
        self._load(fname)

    def __setattr__(self, key: str, value: Any) -> None:
        """
        Set attribute, routing underscore-prefixed names to object attributes.

        Config uses underscore-prefixed attributes for internal state (e.g.,
        _enable_env_overrides, _config_path). These are stored as true object
        attributes, not dict entries, keeping them separate from config data.

        Args:
            key: Attribute name to set
            value: Value to set
        """
        if key.startswith("_"):
            object.__setattr__(self, key, value)
        else:
            self._set_item(key, value)

    def _load(self, fname: str) -> None:
        """
        Load configuration from YAML file and resolve variable substitutions.

        Supports !include tags for including other YAML files.

        Args:
            fname: Path to the YAML configuration file

        Raises:
            yaml.YAMLError: If the YAML file is malformed or includes are circular
        """
        preserved_attrs = _preserve_config_attributes(self)
        self.clear()
        _restore_config_attributes(self, preserved_attrs)

        fname_path = Path(fname).resolve()
        _check_file_size(fname_path)
        self._config_path = fname_path  # Store for get_source_files()

        # Determine project root from config file location for security checks.
        # This allows appinfra to work correctly when used as a submodule,
        # where the consuming project's config should define the boundary.
        proj_root = _get_project_root_from_config(fname_path)

        config_data, source_map = _load_yaml_with_includes(
            fname_path, self._merge_strategy, project_root=proj_root
        )
        self._source_map = source_map  # Store for get_source_files()

        if self._enable_env_overrides:
            config_data = self._apply_env_overrides(config_data)

        self.set(**config_data)
        self.set(**self._resolve(self.dict()))

    def reload(self) -> Self:
        """Reload configuration from disk.

        Re-reads all source files, re-applies variable substitution
        and environment overrides.

        Note:
            Not thread-safe. Callers must coordinate access if config is
            shared across threads during reload.

        Returns:
            Self for chaining.

        Raises:
            RuntimeError: If Config was not loaded from a file.
        """
        if not hasattr(self, "_config_path") or self._config_path is None:
            raise RuntimeError("Config was not loaded from a file")
        self._load(str(self._config_path))
        return self

    def _resolve(self, content: Any) -> Any:
        """
        Recursively resolve variable substitutions in configuration content.

        Variables are specified using ${variable_name} syntax and are replaced
        with values from the configuration itself, enabling hierarchical references.

        Args:
            content: Configuration content (dict, list, str, or other)

        Returns:
            Resolved content with variable substitutions applied
        """
        if isinstance(content, dict):
            # Recursively resolve all dictionary values
            keys = [k for k in content.keys()]
            for k in keys:
                content[k] = self._resolve(content[k])
        elif isinstance(content, str):
            # Replace ${variable_name} patterns with actual values
            # Restrict to valid config keys (alphanumeric + dot + underscore) to prevent ReDoS
            return re.sub(r"\$\{([a-zA-Z0-9_.]+)\}", self._substitute_var, content)
        return content

    def _substitute_var(self, match: re.Match) -> str:
        """
        Substitute a variable reference with its value.

        Args:
            match: Regex match object containing the variable name

        Returns:
            String value of the variable

        Raises:
            DotDictPathNotFoundError: If the variable is not defined
        """
        from ..dot_dict import DotDictPathNotFoundError

        var_name = match.group(1)
        if not self.has(var_name):
            raise DotDictPathNotFoundError(self, var_name)
        return str(self.get(var_name))

    def _apply_env_overrides(self, config_data: dict[str, Any]) -> dict[str, Any]:
        """
        Apply environment variable overrides to configuration data.

        Args:
            config_data: Configuration data dictionary

        Returns:
            Configuration data with environment variable overrides applied
        """
        env_overrides = self._collect_env_vars()

        for env_key, env_value in env_overrides.items():
            # Convert INFRA_LOGGING_LEVEL -> ['logging', 'level']
            config_path = self._env_key_to_path(env_key)

            # Apply the override
            self._set_nested_value(config_data, config_path, env_value)

        return config_data

    def _collect_env_vars(self) -> dict[str, str]:
        """
        Collect all environment variables with the configured prefix.

        Returns:
            Dictionary of environment variable names and values
        """
        env_vars = {}
        for key, value in os.environ.items():
            if key.startswith(self._env_prefix):
                env_vars[key] = value
        return env_vars

    def _env_key_to_path(self, env_key: str) -> list[str]:
        """
        Convert environment variable key to configuration path.

        Args:
            env_key: Environment variable key (e.g., 'INFRA_LOGGING_LEVEL')

        Returns:
            List of path components (e.g., ['logging', 'level'])
        """
        # Remove prefix and split by underscore
        path_parts = env_key[len(self._env_prefix) :].lower().split("_")
        return path_parts

    def _set_nested_value(self, data: dict, path: list[str], value: Any) -> None:
        """
        Set a nested value in the configuration dictionary.

        Uses context-aware matching for hyphenated keys:
        - Traverses the YAML structure intelligently
        - Tries to match existing keys by combining path components with hyphens
        - Treats hyphens and underscores as equivalent during comparison

        Args:
            data: Configuration dictionary to modify
            path: List of keys representing the path to the value
            value: Value to set
        """
        if not path:
            return

        converted_value = self._convert_env_value(value)
        current = data
        i = 0

        while i < len(path):
            if current is None:
                return

            # Cannot traverse into non-dict values (scalars, lists, etc.)
            if not isinstance(current, dict):
                return

            remaining_components = len(path) - i
            matched_key, consumed = self._match_key_greedy(current, path, i)
            is_final = consumed > 0 and consumed == remaining_components
            is_final = is_final or (consumed == 0 and remaining_components == 1)

            if is_final:
                self._set_final_value(current, path[i], matched_key, converted_value)
                return

            i = self._traverse_to_next_level(current, path, i, matched_key, consumed)
            if i < 0:
                # Cannot traverse further (e.g., hit a list)
                return
            current = current[matched_key] if matched_key else current[path[i - 1]]

    def _set_final_value(
        self, target: dict, part: str, matched_key: str | None, value: Any
    ) -> None:
        """Set the final value in the target dictionary."""
        target[matched_key if matched_key else part] = value

    def _traverse_to_next_level(
        self,
        current: dict,
        path: list[str],
        idx: int,
        matched_key: str | None,
        consumed: int,
    ) -> int:
        """Traverse to next level or create new section, return new index."""
        if matched_key:
            matched_val = current.get(matched_key)
            if isinstance(matched_val, dict):
                return idx + consumed
            # Matched key exists but is not a dict
            # Only replace scalars/None with dicts to allow nesting
            # Lists are not replaced (cannot traverse into lists)
            if matched_val is None or isinstance(matched_val, (str, int, float, bool)):
                current[matched_key] = {}
                return idx + consumed
            # For lists or other types, stop traversal (no modification)
            return -1

        part = path[idx]
        if part not in current:
            current[part] = {}
        return idx + 1

    def _match_key_greedy(
        self, data: dict, path: list[str], start_idx: int
    ) -> tuple[str | None, int]:
        """
        Try to match a key in the dictionary by greedily combining path components.

        This enables matching hyphenated YAML keys like 'web-server' with
        environment variable components like ['web', 'server'].

        Matching priority (for each combination length, longest first):
        1. Exact single-component match
        2. For multi-component: exact underscore → exact hyphen → normalized

        Args:
            data: Dictionary to search in
            path: Full path components list
            start_idx: Current position in path

        Returns:
            Tuple of (matched_key, num_components_consumed)
            Returns (None, 0) if no match found
        """
        if not isinstance(data, dict):
            return (None, 0)

        # Try combining components (greedy: longer combinations first)
        for end_idx in range(len(path), start_idx, -1):
            components = path[start_idx:end_idx]
            num_components = end_idx - start_idx

            if num_components == 1:
                if components[0] in data:
                    return (components[0], 1)
                continue

            # Try multi-component matching strategies
            matched = self._try_multicomponent_match(data, components, num_components)
            if matched:
                return matched

        return (None, 0)

    def _try_multicomponent_match(
        self, data: dict, components: list[str], num_components: int
    ) -> tuple[str, int] | None:
        """Try matching multi-component key with various strategies."""
        candidate_underscored = "_".join(components)
        candidate_hyphenated = "-".join(components)

        # Priority 1: Exact underscore match (e.g., web_server)
        if candidate_underscored in data:
            return (candidate_underscored, num_components)

        # Priority 2: Exact hyphenated match (e.g., web-server)
        if candidate_hyphenated in data:
            return (candidate_hyphenated, num_components)

        # Priority 3: Normalized match (handles mixed hyphens/underscores)
        for key in data.keys():
            if key.replace("-", "_") == candidate_underscored:
                return (key, num_components)

        return None

    def _convert_env_value(
        self, value: str
    ) -> bool | int | float | str | list[str] | None:
        """
        Convert environment variable string to appropriate type.

        Args:
            value: Environment variable value as string

        Returns:
            Converted value with appropriate type
        """
        # Handle null/none values
        if value.lower() in ("null", "none", ""):
            return None

        # Handle boolean values
        if value.lower() in ("true", "false"):
            return value.lower() == "true"

        # Handle list values (comma-separated)
        if "," in value:
            return [self._convert_env_value(v.strip()) for v in value.split(",")]  # type: ignore[misc]

        # Handle numeric values
        try:
            if "." in value:
                return float(value)
            else:
                return int(value)
        except ValueError:
            pass

        # Return as string
        return value

    def get_env_overrides(self) -> dict[str, Any]:
        """
        Get all environment variable overrides that would be applied.

        Returns:
            Dictionary of environment variable overrides
        """
        if not self._enable_env_overrides:
            return {}

        env_vars = self._collect_env_vars()
        overrides = {}

        for env_key, env_value in env_vars.items():
            config_path = self._env_key_to_path(env_key)
            path_str = ".".join(config_path)
            overrides[path_str] = self._convert_env_value(env_value)

        return overrides

    def validate(self, raise_on_error: bool = True) -> bool | Any:
        """
        Validate configuration against schema (if pydantic is installed).

        This method provides optional schema validation using Pydantic models.
        If pydantic is not installed, this method returns True (no validation).

        Args:
            raise_on_error: If True, raise ValidationError on invalid config.
                           If False, return False on invalid config.

        Returns:
            If pydantic installed: validated config object or raises/returns False
            If pydantic not installed: True (no validation performed)

        Raises:
            ValidationError: If config is invalid and raise_on_error=True

        Example:
            # Install validation support: pip install infra[validation]
            import logging

            lg = logging.getLogger(__name__)
            config = Config('etc/infra.yaml')
            try:
                validated = config.validate()
                lg.info("Configuration is valid!")
            except ValidationError as e:
                lg.error(f"Invalid configuration: {e}")
        """
        try:
            from . import PYDANTIC_AVAILABLE, validate_config

            if not PYDANTIC_AVAILABLE:
                # Pydantic not installed - skip validation
                return True

            # Convert config to dict for validation
            config_dict = dict(self)

            # Validate using pydantic schema
            if raise_on_error:
                return validate_config(config_dict)
            else:
                try:
                    return validate_config(config_dict)
                except Exception:
                    return False

        except ImportError:
            # Config schemas module not available
            return True

    def get_source_files(self) -> set[Path]:
        """
        Return all files that contributed to this config (main file + includes).

        Useful for file watchers that need to monitor all config files for changes,
        including files loaded via !include directives.

        Returns:
            Set of resolved Path objects for all source files
        """
        files: set[Path] = set()
        if hasattr(self, "_config_path") and self._config_path:
            files.add(self._config_path)
        if hasattr(self, "_source_map") and self._source_map:
            files.update(p.resolve() for p in self._source_map.values() if p)
        return files


# Project path utilities
def get_project_root() -> Path:
    """
    Get the project root directory by looking for the etc/infra.yaml file.

    This function searches upward from the current file's location until it finds
    a directory containing etc/infra.yaml, which indicates the project root.

    Returns:
        Path to the project root directory

    Raises:
        FileNotFoundError: If the project root cannot be found
    """
    current_path = Path(__file__).resolve()

    # Search upward from the current file's location
    for parent in current_path.parents:
        if (parent / "etc" / "infra.yaml").exists():
            return parent

    raise FileNotFoundError(
        "Could not find project root with etc/infra.yaml. "
        "Make sure you're running from within the infra project directory."
    )


def get_etc_dir() -> Path:
    """
    Get the etc directory path relative to the project root.

    Returns:
        Path to the etc directory (project_root/etc)

    Raises:
        FileNotFoundError: If the project root cannot be found
    """
    return get_project_root() / "etc"


# Default config filename - can be overridden via INFRA_DEFAULT_CONFIG_FILE env var
DEFAULT_CONFIG_FILENAME: str = os.environ.get("INFRA_DEFAULT_CONFIG_FILE", "infra.yaml")


def get_config_file_path(config_file: str | None = None) -> Path:
    """
    Get the path to a configuration file in the etc directory.

    Args:
        config_file: Name of the configuration file. If None, uses DEFAULT_CONFIG_FILENAME
                     (which can be overridden via INFRA_DEFAULT_CONFIG_FILE env var).

    Returns:
        Path to the configuration file

    Raises:
        FileNotFoundError: If the project root cannot be found

    Example:
        # Uses default (infra.yaml or INFRA_DEFAULT_CONFIG_FILE env var)
        path = get_config_file_path()

        # Explicit filename
        path = get_config_file_path("app.yaml")
    """
    filename = config_file if config_file is not None else DEFAULT_CONFIG_FILENAME
    return get_etc_dir() / filename


# Constants for common paths
PROJECT_ROOT: Path | None
ETC_DIR: Path | None
DEFAULT_CONFIG_FILE: Path | None

try:
    PROJECT_ROOT = get_project_root()
    ETC_DIR = get_etc_dir()
    DEFAULT_CONFIG_FILE = get_config_file_path()
except FileNotFoundError:
    # Set to None if project root cannot be found (e.g., during package installation)
    PROJECT_ROOT = None
    ETC_DIR = None
    DEFAULT_CONFIG_FILE = None


# Lazy-loaded default config (convenience function for examples/scripts).
#
# NOTE: This global is intentional and acceptable because:
# 1. It's lazy-loaded (no import-time side effects)
# 2. Only used in examples/ - core library code uses explicit Config(path)
# 3. Returns None gracefully if no config file exists
# 4. Tests create fresh Config() instances, so no test isolation issues
#
# Production code should use: Config(path) or AppBuilder().with_config(...)
_default_config: Config | None = None


def get_default_config() -> Config | None:
    """
    Get the default configuration, lazily loading it on first access.

    This is a convenience function for examples and quick scripts. Production code
    should use explicit Config(path) instantiation for better control and testability.

    This function avoids executing file I/O at module import time, which improves
    test isolation and prevents issues in environments without config files.

    Returns:
        Config instance loaded from DEFAULT_CONFIG_FILE, or None if file not found

    Example:
        config = get_default_config()
        if config:
            db_host = config.database.host
    """
    global _default_config

    # Return cached config if already loaded
    if _default_config is not None:
        return _default_config

    # Load config if file exists
    if DEFAULT_CONFIG_FILE is not None:
        try:
            _default_config = Config(str(DEFAULT_CONFIG_FILE))
        except FileNotFoundError:
            _default_config = None

    return _default_config
