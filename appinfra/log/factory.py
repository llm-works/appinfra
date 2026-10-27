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
        """Return a stdout handler formatting through ``holder`` (hot-reload support)."""
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(holder.config.level)
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
        # Handlers carry the logger's level, as LogConfigReloader sets them on reload
        for handler in lg.handlers:
            handler.setLevel(effective.level)
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

        A library's logger already under ``name`` (a plain stdlib one) is taken over in
        place: the library keeps logging through the same object, now with this config
        and appinfra's format, and its own handlers and filters are dropped.

        Raises:
            LoggerExistsError: An appinfra logger this process created already holds
                ``name``, whatever its config. Use :meth:`reconfigure` to change it, or
                :meth:`destroy` it before creating the name again. A library's own
                Logger subclass under the name raises too: it is not taken over.

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
        existing = LoggerFactory._registered(name)
        if existing is None:
            lg = logger_class(name, config, CallbackRegistry(), extra)
        elif _is_library_logger(existing):
            lg = LoggerFactory._take_over(existing, config, logger_class, extra)
        else:
            raise LoggerExistsError(name)
        return LoggerFactory._finish_logger(lg, config)

    @staticmethod
    def _owned(name: str) -> Logger | None:
        """
        Return the logger the factory made in this process as ``name``, or ``None``.

        A library's logger is not one, even with appinfra's class: :meth:`reconfigure`,
        :meth:`destroy` and :meth:`create_or_replace` leave it alone, and :meth:`create`
        takes it over instead.
        """
        existing = LoggerFactory._registered(name)
        if existing is not None and _is_factory_logger(existing):
            return cast(Logger, existing)
        return None

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

        The logger is changed in place: everyone holding it sees the new settings. Its
        handlers get the new level too, as on a hot-reload of the config.

        Raises:
            LoggerNotFoundError: No appinfra logger named ``name`` exists.
            LogConfigError: ``name`` is a view made by :meth:`derive` or
                :meth:`create_child`. A view shares its root's settings, so applying a
                config to it would change the root and every view of it.
        """
        existing = LoggerFactory._owned(name)
        if existing is None:
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
            LoggerNotFoundError: No appinfra logger named ``name`` exists in this
                process. A library's logger under the name is not one.
            Exception: The first error a handler's ``close()`` raised, once every
                handler is closed and every logger removed.
        """
        target = LoggerFactory._owned(name)
        if target is None:
            raise LoggerNotFoundError(name)
        registry = logging.root.manager.loggerDict
        error: Exception | None = None
        for lg in LoggerFactory._doomed(target):
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
    def _doomed(target: Logger) -> list[logging.Logger]:
        """
        Return ``target`` and the factory's loggers below it, which :meth:`destroy` removes.

        Below a taken-over library logger, the library's own child loggers are not
        appinfra's: they stay registered, and those whose parent is ``target`` get the
        stdlib root back as their parent, as before the takeover.
        """
        registry = logging.root.manager.loggerDict
        doomed = [
            lg
            for lg in list(registry.values())
            if isinstance(lg, logging.Logger)
            and (lg is target or _is_factory_logger(lg))
            and _descends_from(lg, target)
        ]
        for lg in list(registry.values()):
            if (
                isinstance(lg, logging.Logger)
                and lg.parent is target
                and lg not in doomed
            ):
                lg.parent = logging.root
                # Clears the level caches, which hold results from the old parent
                lg.setLevel(lg.level)
        return doomed

    @staticmethod
    def destroy_if_exists(name: str) -> bool:
        """:meth:`destroy` ``name`` if this process holds an appinfra logger under it; return whether."""
        if LoggerFactory._owned(name) is None:
            return False
        LoggerFactory.destroy(name)
        return True

    @staticmethod
    def names() -> set[str]:
        """
        Return the names of the loggers the factory made in this process.

        These are the names :meth:`create` refuses and :meth:`destroy` accepts: created
        loggers and the views derived from them. Library loggers, and appinfra loggers a
        parent process created before a fork, are not included.
        """
        return {
            name
            for name in list(logging.root.manager.loggerDict)
            if LoggerFactory._owned(name) is not None
        }

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
    def _take_over(
        lg: logging.Logger,
        config: LogConfig,
        logger_class: type[Logger],
        extra: dict[str, Any] | collections.OrderedDict | None,
    ) -> Logger:
        """
        Turn a library's logger into an appinfra logger, in place.

        The library keeps its reference to this object, so its records, and those of
        its child loggers, go through appinfra's handler and format from now on. Its
        own handlers and filters are dropped, not closed: other loggers may share them.
        """
        name = lg.name
        # A fresh object under the same identity: __init__ must not run over the
        # state of an earlier one (it would wrap its own makeRecord)
        lg.__dict__.clear()
        lg.__class__ = logger_class
        taken = cast(Logger, lg)
        logger_class.__init__(taken, name, config, CallbackRegistry(), extra)
        return taken

    @staticmethod
    def _finish_logger(lg: Logger, config: LogConfig) -> Logger:
        """Give a new or taken-over logger its config and console handler; register it."""
        holder = LoggerFactory._apply_config(lg, config)
        lg.addHandler(LoggerFactory._console_handler(holder))
        lg.propagate = False

        # Set parent to root for proper propagation when propagate=True
        lg.parent = logging.root

        # Register in loggerDict so hot-reload can find it
        logging.root.manager.loggerDict[lg.name] = lg

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
        root = parent._root_logger or parent
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

        Raises:
            LoggerExistsError: A library's logger, not an appinfra one, holds the name.

        See Also:
            derive: Create logger with one or more hierarchical tag components
        """
        full_name = f"{parent.name}/{name}" if parent.name != "/" else f"/{name}"

        existing = LoggerFactory._lookup_view(full_name)
        if existing is not None:
            return existing

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

        Raises:
            LoggerExistsError: A library's logger, not an appinfra one, holds the name.

        See Also:
            create_child: Simpler API for creating single-name child loggers
        """
        if isinstance(tags, str):
            tags = [tags]

        prefix = parent.name if parent.name == "/" else parent.name + "/"
        name = prefix + "/".join(tags)

        existing = LoggerFactory._lookup_view(name)
        if existing is not None:
            return existing

        return LoggerFactory._create_view_logger(name, parent, "derived logger")

    @staticmethod
    def _lookup_view(name: str) -> Logger | None:
        """
        Return the appinfra logger already at ``name``, or ``None`` when the name is free.

        Raises:
            LoggerExistsError: A logger the factory did not make (a library's) holds
                ``name``. :meth:`derive` and :meth:`create_child` return appinfra loggers
                only; taking over a library's logger is :meth:`create`'s job.
        """
        owned = LoggerFactory._owned(name)
        if owned is None and LoggerFactory._registered(name) is not None:
            raise LoggerExistsError(name)
        return owned


def _is_library_logger(lg: logging.Logger) -> bool:
    """
    Whether ``lg`` is a library's logger that :meth:`LoggerFactory.create` may take over.

    That is a plain stdlib logger, or an appinfra one that ``logging.getLogger()`` made
    (``setLoggerClass`` is process-wide) and the factory never configured. A library's
    own Logger subclass is not: rewriting its class would break the library's calls to
    its own methods.
    """
    if type(lg) is logging.Logger:
        return True
    return isinstance(lg, Logger) and not _is_factory_logger(lg)


def _is_factory_logger(lg: logging.Logger) -> bool:
    """
    Whether :class:`LoggerFactory` made ``lg``.

    A created logger has a config holder; a view (:meth:`LoggerFactory.derive`,
    :meth:`LoggerFactory.create_child`) has a root, and no holder when its root was
    built without the factory (``Logger(...)``, ``Logger.with_queue()``).
    """
    return isinstance(lg, Logger) and (
        lg._holder is not None or lg._root_logger is not None
    )


def _descends_from(lg: logging.Logger, target: logging.Logger) -> bool:
    """True when ``lg`` is ``target`` or reaches it through its ``parent`` chain."""
    node: logging.Logger | None = lg
    while node is not None:
        if node is target:
            return True
        node = node.parent
    return False
