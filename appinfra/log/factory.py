# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Factory classes for creating and configuring loggers.

This module provides factory classes for creating loggers with consistent
configuration and proper setup of handlers and formatters.
"""

import collections
import logging
import os
import sys
from typing import Any, cast

from .callback import CallbackRegistry
from .config import ChildLogConfig, LogConfig
from .config_holder import LogConfigHolder
from .errors import LogConfigError, LoggerExistsError, LoggerNotFoundError
from .formatters import LogFormatter
from .logger import Logger


class LoggerFactory:
    """Factory for creating and configuring loggers."""

    @staticmethod
    def create_root(
        config: LogConfig,
        logger_class: type[Logger] = Logger,
        extra: dict[str, Any] | collections.OrderedDict | None = None,
    ) -> Logger:
        """
        Create a root logger with the specified configuration.

        Args:
            config: Logger configuration
            logger_class: Logger class to use
            extra: Pre-populated extra fields to include in all log records

        Returns:
            Configured root logger

        Example:
            >>> from appinfra.log import LoggerFactory, LogConfig
            >>>
            >>> config = LogConfig.from_params(level="info", colors=True)
            >>> logger = LoggerFactory.create_root(config)
            >>> logger.info("Application started")
            [12:34:56,789] [I] Application started [1234] [/]
        """
        return LoggerFactory.create("/", config, logger_class, extra)

    @staticmethod
    def _get_effective_config(name: str, config: LogConfig) -> LogConfig:
        """Get effective config with topic-based level override if applicable."""
        from .level_manager import LogLevelManager

        level_manager = LogLevelManager.get_instance()
        effective_level = level_manager.get_effective_level(name)

        if effective_level is None:
            return config

        if isinstance(effective_level, str):
            resolved_level = getattr(logging, effective_level.upper(), logging.INFO)
        else:
            resolved_level = effective_level

        return LogConfig(
            level=resolved_level,
            location=config.location,
            micros=config.micros,
            colors=config.colors,
            location_color=getattr(config, "location_color", None),
        )

    @staticmethod
    def _console_handler(holder: LogConfigHolder) -> logging.Handler:
        """Return a stdout handler formatting through ``holder`` (hot-reload support).

        It has no level of its own: the logger's level, and a view's topic level,
        decide what it prints.
        """
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(LogFormatter(holder))
        return handler

    @staticmethod
    def _apply_config(lg: Logger, config: LogConfig) -> LogConfigHolder:
        """
        Give ``lg`` the settings of ``config``; return its holder of the effective config.

        Sets the config, the level (after topic overrides), the disabled flag and the
        holder its formatters read location, micros and colors from. Used both for a new
        logger and for reconfiguring an existing one, so the two cannot drift apart.
        """
        effective = LoggerFactory._get_effective_config(lg.name, config)
        lg._config = config
        lg._logging_disabled = config.level is False
        lg.setLevel(effective.level)
        if lg._holder is None:
            lg._holder = LogConfigHolder(effective)
        else:
            lg._holder.update(effective)
        return lg._holder

    @staticmethod
    def create(
        name: str,
        config: LogConfig,
        logger_class: type[Logger] = Logger,
        extra: dict[str, Any] | collections.OrderedDict | None = None,
    ) -> Logger:
        """
        Create a logger with the specified configuration.

        Args:
            name: Logger name
            config: Logger configuration
            logger_class: Logger class to use
            extra: Pre-populated extra fields to include in all log records

        Returns:
            Configured logger instance

        Raises:
            LoggerExistsError: A logger named ``name`` already exists, whatever its
                config. Use :meth:`reconfigure` to change it, or :meth:`destroy` it
                before creating the name again.

        Example:
            >>> from appinfra.log import LoggerFactory, LogConfig
            >>>
            >>> config = LogConfig.from_params(level="debug")
            >>> db_logger = LoggerFactory.create("/database", config)
            >>> db_logger.info("Connected", extra={"host": "localhost"})
            [12:34:56,789] [I] Connected [host:localhost] [1234] [/database]
            >>>
            >>> # With pre-populated extra fields
            >>> api_logger = LoggerFactory.create(
            ...     "/api", config, extra={"service": "users"}
            ... )
            >>> api_logger.info("Request received")
            [12:34:56,789] [I] Request received [service:users] [1234] [/api]
        """
        logging.setLoggerClass(logger_class)
        if LoggerFactory._registered(name) is not None:
            raise LoggerExistsError(name)
        return LoggerFactory._create_new_logger(name, config, logger_class, extra)

    @staticmethod
    def create_or_replace(
        name: str,
        config: LogConfig,
        logger_class: type[Logger] = Logger,
        extra: dict[str, Any] | collections.OrderedDict | None = None,
    ) -> Logger:
        """
        Create logger ``name``, first destroying any logger this process holds under it.

        :meth:`destroy` then :meth:`create`: the old logger's handlers are closed and the
        loggers derived from it are removed, so whoever still holds it logs nowhere. Use
        it when this code owns the name and means to start over; to change a live
        logger's settings without that, use :meth:`reconfigure`.
        """
        LoggerFactory.destroy_if_exists(name)
        return LoggerFactory.create(name, config, logger_class, extra)

    @staticmethod
    def reconfigure(name: str, config: LogConfig) -> Logger:
        """
        Apply ``config`` (level, location, micros, colors) to the existing logger ``name``.

        The logger is changed in place: everyone holding it sees the new settings.
        Handlers are left as they are.

        Raises:
            LoggerNotFoundError: No appinfra logger named ``name`` exists.
            LogConfigError: ``name`` is a view made by :meth:`derive` or
                :meth:`create_child`. A view shares its root's settings, so applying a
                config to it would change the root and every view of it.
        """
        existing = LoggerFactory._registered(name)
        if not isinstance(existing, Logger):
            raise LoggerNotFoundError(name)
        if existing._root_logger is not None:
            raise LogConfigError(
                f"{name!r} is a derived view; reconfigure its root "
                f"{existing._root_logger.name!r}"
            )
        LoggerFactory._apply_config(existing, config)
        return existing

    @staticmethod
    def destroy(name: str) -> None:
        """
        Close and remove the logger ``name``, and every logger derived from it.

        Derived loggers (:meth:`derive`, :meth:`create_child`) are views that log through
        it, so they go too: none is left pointing at a removed logger. Their names are
        free again for :meth:`create`. A reference still held to a removed logger keeps
        working but has no handlers left.

        Raises:
            LoggerNotFoundError: No logger named ``name`` exists in this process.
            Exception: The first error a handler's ``close()`` raised, once every
                handler is closed and every logger removed.
        """
        target = LoggerFactory._registered(name)
        if target is None:
            raise LoggerNotFoundError(name)
        registry = logging.root.manager.loggerDict
        doomed = [
            lg
            for lg in list(registry.values())
            if isinstance(lg, logging.Logger) and _descends_from(lg, target)
        ]
        error: Exception | None = None
        for lg in doomed:
            for handler in list(lg.handlers):
                lg.removeHandler(handler)
                try:
                    handler.close()
                except Exception as e:
                    # finish the cleanup first: a half-destroyed name could not be reused
                    error = error or e
            registry.pop(lg.name, None)
        if error is not None:
            raise error

    @staticmethod
    def destroy_if_exists(name: str) -> bool:
        """:meth:`destroy` ``name`` if this process holds a logger under it; return whether."""
        if LoggerFactory._registered(name) is None:
            return False
        LoggerFactory.destroy(name)
        return True

    @staticmethod
    def _registered(name: str) -> logging.Logger | None:
        """
        Return the logger this process registered as ``name``, or ``None``.

        A stdlib ``PlaceHolder`` is not a logger. An appinfra logger created by another
        process was inherited across a fork: it belongs to the parent, so the name is
        free in this process. The inherited object keeps working for code that holds it.
        """
        existing = logging.root.manager.loggerDict.get(name)
        if not isinstance(existing, logging.Logger):
            return None
        if isinstance(existing, Logger) and existing._owner_pid != os.getpid():
            return None
        return existing

    @staticmethod
    def _create_new_logger(
        name: str,
        config: LogConfig,
        logger_class: type[Logger],
        extra: dict[str, Any] | collections.OrderedDict | None,
    ) -> Logger:
        """Create a new logger with effective config and handler."""
        callback_registry = CallbackRegistry()
        lg = logger_class(name, config, callback_registry, extra)
        holder = LoggerFactory._apply_config(lg, config)
        lg.addHandler(LoggerFactory._console_handler(holder))
        lg.propagate = False

        # Set parent to root for proper propagation when propagate=True
        lg.parent = logging.root

        # Register in loggerDict so hot-reload can find it
        logging.root.manager.loggerDict[name] = lg

        lg.trace2(
            "created logger",
            extra={
                "level": logging.getLevelName(holder.config.level),
                "location": holder.config.location,
                "micros": holder.config.micros,
            },
        )
        return lg

    @staticmethod
    def _get_view_logger_config(name: str, parent: Logger) -> ChildLogConfig:
        """Build effective config for a view logger based on parent.

        Child loggers only store level. Global settings (location, colors, etc.)
        are read from the registry's root config for hot-reload support.
        """
        from .level_manager import LogLevelManager

        # Check if there's a topic-specific level override
        level_manager = LogLevelManager.get_instance()
        effective_level = level_manager.get_effective_level(name)

        if effective_level is not None:
            if isinstance(effective_level, str):
                resolved_level = getattr(logging, effective_level.upper(), logging.INFO)
            else:
                resolved_level = effective_level
        else:
            resolved_level = parent.get_level()

        return ChildLogConfig(level=resolved_level)

    @staticmethod
    def _set_view_logger_level(
        lg: Logger, name: str, effective_config: ChildLogConfig
    ) -> None:
        """Set level for view logger - NOTSET for inheritance or explicit if topic rule."""
        from .level_manager import LogLevelManager

        level_manager = LogLevelManager.get_instance()
        topic_level = level_manager.get_effective_level(name)
        if topic_level is not None:
            lg.setLevel(effective_config.level)
        else:
            lg.setLevel(logging.NOTSET)

    @staticmethod
    def _create_view_logger(name: str, parent: Logger, label: str) -> Logger:
        """Create a view logger that delegates to root's handlers.

        View loggers have no handlers of their own - they delegate to the root
        logger's handlers via the _root_logger reference. They share the root's
        holder for hot-reload of location settings.
        """
        root = parent._root_logger if parent._root_logger else parent
        effective_config = LoggerFactory._get_view_logger_config(name, parent)

        logging.setLoggerClass(parent.__class__)
        callback_registry = CallbackRegistry()
        lg = parent.__class__(name, effective_config, callback_registry)

        LoggerFactory._set_view_logger_level(lg, name, effective_config)

        lg._root_logger = root
        lg._holder = root._holder  # Share holder for hot-reload of location
        lg.parent = parent
        lg.propagate = False

        logging.root.manager.loggerDict[name] = lg
        parent._callbacks.inherit_to(lg._callbacks)

        lg.trace2(
            label,
            extra={
                "level": logging.getLevelName(effective_config.level),
                "root": root.name,
            },
        )
        return lg

    @staticmethod
    def create_child(parent: Logger, name: str) -> Logger:
        """
        Create a child "view" logger that delegates to root's handlers.

        This method creates a direct child logger by appending a single name
        to the parent's path. The child logger shares handlers with the root
        logger, making it a lightweight "view" rather than an independent logger.

        Examples:
            >>> parent = LoggerFactory.create_root(config)  # name: "/"
            >>> child = LoggerFactory.create_child(parent, "database")
            >>> child.name
            '/database'

            >>> parent = LoggerFactory.create("/infra", config)  # name: "/infra"
            >>> child = LoggerFactory.create_child(parent, "db")
            >>> child.name
            '/infra/db'

        Differences from derive():
            - create_child() takes a single name string
            - derive() takes a string or list of tags and joins them with "/"
            - Use create_child() for simple parent-child relationships
            - Use derive() when you need multiple hierarchical components

        Args:
            parent: Parent logger instance
            name: Single child logger name (no "/" separators)

        Returns:
            Child logger instance with inherited configuration

        See Also:
            derive: Create logger with one or more hierarchical tag components
        """
        full_name = f"{parent.name}/{name}" if parent.name != "/" else f"/{name}"

        existing = LoggerFactory._registered(full_name)
        if existing is not None:
            return cast(Logger, existing)

        return LoggerFactory._create_view_logger(full_name, parent, "child logger")

    @staticmethod
    def derive(parent: Logger, tags: str | list[str]) -> Logger:
        """
        Derive a "view" logger that delegates to root's handlers.

        Creates a derived logger that has its own name and level but shares
        handlers with the root logger. This is more efficient than creating
        independent loggers and ensures all derived loggers automatically
        benefit from handlers added to the root (e.g., FileHandler).

        Examples:
            >>> parent = LoggerFactory.create_root(config)  # name: "/"
            >>> derived = LoggerFactory.derive(parent, "request")
            >>> derived.name
            '/request'

            >>> # Multiple tags create hierarchical path
            >>> derived = LoggerFactory.derive(parent, ["api", "v1", "users"])
            >>> derived.name
            '/api/v1/users'

            >>> parent = LoggerFactory.create("/infra", config)  # name: "/infra"
            >>> derived = LoggerFactory.derive(parent, ["db", "query"])
            >>> derived.name
            '/infra/db/query'

        Differences from create_child():
            - derive() accepts a string OR list of tags
            - Multiple tags are joined with "/" automatically
            - create_child() only accepts a single name string
            - Both methods are functionally equivalent for single tags

        Use Cases:
            - Use derive() when you have dynamic tag hierarchies
            - Use derive() when tags come from a list/array
            - Use create_child() for static, single-level child creation

        Args:
            parent: Parent logger instance
            tags: Single tag string OR list of tag strings to form hierarchy

        Returns:
            Derived logger instance with inherited configuration

        See Also:
            create_child: Simpler API for creating single-name child loggers
        """
        if isinstance(tags, str):
            tags = [tags]

        prefix = parent.name if parent.name == "/" else parent.name + "/"
        name = prefix + "/".join(tags)

        existing = LoggerFactory._registered(name)
        if existing is not None:
            return cast(Logger, existing)

        return LoggerFactory._create_view_logger(name, parent, "derived logger")


def _descends_from(lg: logging.Logger, target: logging.Logger) -> bool:
    """True when ``lg`` is ``target`` or reaches it through its ``parent`` chain."""
    node: logging.Logger | None = lg
    while node is not None:
        if node is target:
            return True
        node = node.parent
    return False
