# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Log configuration reloader for hot-reload support.

This module provides the LogConfigReloader class that handles updating
logger configuration when config files change. It is designed to be used
as a callback for ConfigWatcher.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .config import LogConfig
    from .logger import Logger


class LogConfigReloader:
    """
    Handles logger config updates from config file changes.

    This class is designed to be used as a callback for ConfigWatcher.
    It parses the new config, updates the logger's holder, and applies
    level changes.

    Example:
        >>> from appinfra.log import LogConfigReloader
        >>> from appinfra.config import ConfigWatcher
        >>>
        >>> reloader = LogConfigReloader(root_logger, section="logging")
        >>> watcher = ConfigWatcher(lg=lifecycle_logger)
        >>> watcher.configure(config_path, on_change=reloader)
        >>> watcher.start()
    """

    def __init__(
        self,
        root_logger: Logger | logging.Logger,
        section: str = "logging",
    ) -> None:
        """
        Initialize the reloader.

        Args:
            root_logger: The root logger to update on config reload. Its holder
                        is shared with all formatters for hot-reload.
            section: Config section containing logging config (default: "logging")
        """
        self._root_logger = root_logger
        self._section = section

    def __call__(self, config_dict: dict[str, Any]) -> None:
        """
        Handle config change by updating logger configuration.

        This method is called by ConfigWatcher when the config file changes.

        Args:
            config_dict: The full config dictionary from the config file
        """
        from .config import LogConfig

        new_log_config = LogConfig.from_config(config_dict, self._section)
        self._update_holder(new_log_config)
        self._update_level_manager(config_dict)

    def _update_holder(self, new_config: LogConfig) -> None:
        """
        Update holder and logger levels with new config.

        The holder is shared with all child loggers and formatters,
        so this single update propagates to the entire logger hierarchy.
        """
        holder = getattr(self._root_logger, "_holder", None)
        if holder is None:
            return

        old_location = holder.location
        holder.update(new_config)

        # Update logger and handler levels
        self._root_logger.setLevel(new_config.level)
        for handler in self._root_logger.handlers:
            handler.setLevel(new_config.level)

        self._root_logger.debug(
            "config reloaded",
            extra={
                "location": f"{old_location} -> {new_config.location}",
                "level": logging.getLevelName(new_config.level),
            },
        )

    def _update_level_manager(self, config_dict: dict[str, Any]) -> None:
        """Update level manager with new topic rules."""
        from .level_manager import LogLevelManager

        # Navigate to logging section
        section_parts = self._section.split(".")
        current: Any = config_dict
        for part in section_parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return

        if not isinstance(current, dict):
            return

        topics = current.get("topics")
        if topics and isinstance(topics, dict):
            manager = LogLevelManager.get_instance()
            # Clear old yaml rules and add new ones
            manager.clear_rules(source="yaml")
            manager.add_rules_from_dict(topics, source="yaml", priority=1)
