"""
Logging utilities for application setup.

This module provides helper functions for setting up logging from configuration files,
particularly useful for examples and CLI applications.
"""

import logging
from typing import Any, cast

from ...log import LogConfig, LoggerFactory
from ...log.handler_factory import HandlerRegistry


def _convert_args_to_dict(args: Any) -> dict[str, Any] | None:
    """Convert various args formats to a dictionary."""
    if args is None:
        return None
    if isinstance(args, dict):
        return args
    if hasattr(args, "__dict__"):
        return cast(dict[str, Any], vars(args))
    if hasattr(args, "get"):
        return dict(args)
    return {}


def _extract_args_from_caller_frame() -> dict[str, Any] | None:
    """Attempt to extract args from caller's frame by inspecting for self.args."""
    import inspect

    frame = inspect.currentframe()
    try:
        # Two levels up: this function -> _resolve_args_dict -> setup_logging_from_config -> caller
        if frame is None or frame.f_back is None:
            return None
        caller_frame = frame.f_back.f_back
        if caller_frame:
            caller_locals = caller_frame.f_locals
            if "self" in caller_locals and hasattr(caller_locals["self"], "args"):
                return cast(dict[str, Any], vars(caller_locals["self"].args))
    finally:
        del frame

    return None


def _resolve_args_dict(args: Any) -> dict[str, Any] | None:
    """Resolve args to dict, trying conversion first, then frame inspection."""
    args_dict = _convert_args_to_dict(args)
    if args_dict is None:
        args_dict = _extract_args_from_caller_frame()
    return args_dict


def _extract_config_value(
    arg_key: str,
    config_key: str,
    args_dict: dict[str, Any] | None,
    infra_config: Any,
    default: Any,
) -> Any:
    """
    Extract config value with precedence: args_dict > config > default.

    Args:
        arg_key: Key to look up in args_dict
        config_key: Attribute name in infra_config.logging
        args_dict: Optional arguments dictionary
        infra_config: Configuration object
        default: Default value if not found

    Returns:
        Config value following precedence rules
    """
    # Only use args_dict value if explicitly provided (not None)
    if args_dict and args_dict.get(arg_key) is not None:
        return args_dict[arg_key]
    if hasattr(infra_config, "logging"):
        return getattr(infra_config.logging, config_key, default)
    return default


def _add_optional_overrides(
    overrides: dict[str, Any], args_dict: dict[str, Any] | None, infra_config: Any
) -> None:
    """
    Add optional config overrides for colors, location_color, and log_json.

    These are only added if explicitly set (not None).
    """
    optional_mappings = [("log_colors", "colors"), ("location_color", "location_color")]
    for arg_key, config_key in optional_mappings:
        value = _extract_config_value(
            arg_key, config_key, args_dict, infra_config, None
        )
        if value is not None:
            overrides[config_key] = value

    log_json = _extract_config_value("log_json", "json", args_dict, infra_config, None)
    if log_json is not None:
        overrides["log_json"] = log_json


def _build_config_overrides(
    args_dict: dict[str, Any] | None, infra_config: Any, **kwargs: Any
) -> dict[str, Any]:
    """
    Build configuration overrides from args_dict, config, and kwargs.

    Merges command-line arguments, config file values, and explicit kwargs.
    Precedence: kwargs > args_dict > config
    """
    config_overrides = {
        "level": _extract_config_value(
            "log_level", "level", args_dict, infra_config, "info"
        ),
        "location": _extract_config_value(
            "log_location", "location", args_dict, infra_config, 0
        ),
        "micros": _extract_config_value(
            "log_micros", "micros", args_dict, infra_config, False
        ),
    }

    _add_optional_overrides(config_overrides, args_dict, infra_config)

    # Apply kwargs overrides (highest precedence)
    valid_keys = {"level", "location", "micros", "colors", "location_color"}
    for key, value in kwargs.items():
        if key in valid_keys:
            config_overrides[key] = value

    return config_overrides


def _create_logger_without_default_handlers(
    config_overrides: dict[str, Any],
) -> tuple[logging.Logger, LogConfig]:
    """Create logger from config overrides with default handlers removed."""
    # Filter to valid LogConfig parameters
    valid_log_config_params = {
        "level",
        "location",
        "micros",
        "colors",
        "location_color",
    }
    log_config_params = {
        k: v for k, v in config_overrides.items() if k in valid_log_config_params
    }

    # Create log config
    log_config = LogConfig.from_params(**log_config_params)

    # Create logger and remove default handler
    # The factory sets up the holder on the logger for hot-reload support
    logger = LoggerFactory.create_root(log_config)
    if logger.handlers:
        logger.handlers.clear()

    return logger, log_config


def _add_handlers_to_logger(
    logger: logging.Logger, registry: HandlerRegistry, log_config: LogConfig
) -> int:
    """Add all enabled handlers from registry to logger with error handling."""
    handler_count = 0
    for handler_config in registry.iter_enabled_handlers():
        try:
            actual_handler = handler_config.create_handler(log_config, logger=logger)
            logger.addHandler(actual_handler)
            handler_count += 1
        except Exception as e:
            logger.warning(
                f"Failed to create {handler_config.__class__.__name__} handler: {e}"
            )
            import traceback

            logger.debug(
                "Handler creation error",
                extra={"exception": e, "traceback": traceback.format_exc()},
            )

    return handler_count


def _add_default_console_handler(
    logger: logging.Logger,
    registry: HandlerRegistry,
    config_overrides: dict[str, Any],
    log_config: LogConfig,
    global_level: int,
) -> None:
    """Add default console handler when no handlers are configured."""
    logger.trace("no handlers configured - creating default console handler")  # type: ignore[attr-defined]

    # Build default handler config
    default_config = {
        "type": "console",
        "enabled": True,
        "level": config_overrides.get("level", "info"),
        "format": "json" if config_overrides.get("log_json") else "text",
        "stream": "stdout",
    }

    # Apply config overrides
    for key in ["colors", "location", "micros"]:
        if key in config_overrides:
            default_config[key] = config_overrides[key]

    # Add to registry and logger
    registry.add_handler_from_config(default_config, global_level)
    default_handler_config = list(registry.iter_enabled_handlers())[-1]
    actual_handler = default_handler_config.create_handler(log_config, logger=logger)
    logger.addHandler(actual_handler)
    logger.trace("added default console handler using global config values")  # type: ignore[attr-defined]


def _extract_topics_dict(topics_attr: Any) -> dict:
    """
    Convert topics attribute to dictionary format.

    Handles various input formats: DotDict, dict-like objects, plain dicts.

    Args:
        topics_attr: Topics configuration in any supported format

    Returns:
        Dictionary of topic patterns to log levels
    """
    # Try various dict conversion methods
    if hasattr(topics_attr, "to_dict"):
        return dict(topics_attr.to_dict())
    elif hasattr(topics_attr, "dict"):
        return dict(topics_attr.dict())
    elif isinstance(topics_attr, dict):
        return dict(topics_attr)
    else:
        # Fallback: attempt conversion
        try:
            return dict(topics_attr)
        except (TypeError, ValueError):
            return {}


def _load_topic_levels(config: Any, args_dict: dict | None) -> None:
    """
    Load topic-based level rules from YAML config and CLI args.

    Args:
        config: Configuration object
        args_dict: Command-line arguments dictionary

    Loads rules with precedence:
    - YAML config (priority=1)
    - CLI args (priority=5) - handled in Phase 4
    """
    from ...log.level_manager import LogLevelManager

    manager = LogLevelManager.get_instance()

    # 1. Load from YAML config (priority=1)
    if hasattr(config, "logging") and hasattr(config.logging, "topics"):
        topics_dict = _extract_topics_dict(config.logging.topics)
        if topics_dict:
            manager.add_rules_from_dict(topics_dict, source="yaml", priority=1)

    # 2. Load from CLI args (priority=5)
    if args_dict and "log_topics" in args_dict and args_dict["log_topics"]:
        for pattern, level in args_dict["log_topics"]:
            manager.add_rule(pattern, level, source="cli", priority=5)

    # 3. Set default level from global config
    if hasattr(config, "logging") and hasattr(config.logging, "level"):
        manager.set_default_level(config.logging.level)


def _resolve_log_level(level: str | int) -> int:
    """Resolve log level to integer, handling both string and int inputs."""
    if isinstance(level, int):
        return level
    return getattr(logging, level.upper(), logging.INFO)


def _apply_cli_overrides_to_handler(
    cfg: dict[str, Any], force_json: bool, force_no_colors: bool
) -> None:
    """Apply CLI log overrides (--log-json, --no-log-colors) to a console handler config."""
    if cfg.get("type") != "console":
        return
    if force_json:
        cfg["format"] = "json"
    if force_no_colors and cfg.get("format") != "json":
        cfg["colors"] = False


def _load_handlers_from_config(
    config: Any, registry: HandlerRegistry, config_overrides: dict[str, Any]
) -> None:
    """Load handlers from config into registry if handlers section exists.

    CLI args (log_json, log_colors) override handler config settings.
    """
    if not hasattr(config, "logging"):
        return
    handlers = getattr(config.logging, "handlers", None)
    if not handlers:
        return
    if not hasattr(handlers, "items"):
        from ...log.handler_factory import LogConfigError

        raise LogConfigError(
            f"Handlers configuration must be a dictionary, got {type(handlers)}"
        )

    force_json = config_overrides.get("log_json", False)
    force_no_colors = "colors" in config_overrides and not config_overrides["colors"]

    for handler_name, handler_config in handlers.items():
        if hasattr(handler_config, "copy"):
            cfg = handler_config.copy()
        elif hasattr(handler_config, "to_dict"):
            cfg = handler_config.to_dict()
        else:
            cfg = dict(handler_config)

        cfg["_handler_name"] = handler_name
        _apply_cli_overrides_to_handler(cfg, force_json, force_no_colors)
        registry.add_handler_from_config(cfg, registry.global_level)


def setup_logging_from_config(
    config: Any,
    args: Any = None,
    **kwargs: Any,
) -> tuple[logging.Logger, HandlerRegistry]:
    """
    Set up logging from the provided configuration object with command-line overrides.

    This helper function handles the common pattern of:
    1. Creating handler registry with global level consideration
    2. Setting up logger with command-line level overrides
    3. Adding handlers from configuration

    Use create_config() or App.setup_config() to load configuration from files.

    Args:
        config: Configuration object (from create_config() or setup_config())
        args: Command-line arguments - can be dict (e.g., vars(args)) or object (e.g., self.args)
        **kwargs: Additional override values (for backward compatibility)

    Returns:
        Tuple of (configured_logger, handler_registry)

    Raises:
        ValueError: If configuration is invalid
    """
    # Resolve args to dictionary
    args_dict = _resolve_args_dict(args)

    # Build configuration overrides
    config_overrides = _build_config_overrides(args_dict, config, **kwargs)

    # Load topic-based level rules BEFORE creating loggers
    _load_topic_levels(config, args_dict)

    # Create handler registry and load handlers from config
    global_level = _resolve_log_level(config_overrides["level"])
    registry = HandlerRegistry(global_level)
    _load_handlers_from_config(config, registry, config_overrides)

    # Create logger without default handlers
    logger, log_config = _create_logger_without_default_handlers(config_overrides)

    # Add configured handlers
    handler_count = _add_handlers_to_logger(logger, registry, log_config)

    # Add default handler if none configured
    if handler_count == 0:
        _add_default_console_handler(
            logger, registry, config_overrides, log_config, global_level
        )

    return logger, registry
