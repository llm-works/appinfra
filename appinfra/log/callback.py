"""
Callback system for the logging system.

This module provides a registry system for managing log event callbacks,
allowing external code to react to logging events.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from .errors import CallbackError

if TYPE_CHECKING:
    from .logger import Logger


class CallbackRegistry:
    """
    Manages log event callbacks.

    This class provides a registry system for callbacks that can be triggered
    when specific log levels are used. Callbacks can be inherited by child loggers.

    Example:
        >>> import logging
        >>> from appinfra.log.callback import CallbackRegistry
        >>>
        >>> registry = CallbackRegistry()
        >>>
        >>> def on_error(logger, level, msg, args, **kwargs):
        ...     print(f"ERROR: {msg}")
        ...     # Could send to alerting system, etc.
        >>>
        >>> registry.register(logging.ERROR, on_error, inherit=True)
        >>> registry.has_callbacks(logging.ERROR)
        True
    """

    def __init__(self) -> None:
        """Initialize the callback registry."""
        self._callbacks: dict[int, list[tuple[Callable, bool]]] = {}

    def register(self, level: int, callback: Callable, inherit: bool = False) -> None:
        """
        Register a callback for a specific level.

        Args:
            level: Log level to register callback for
            callback: Callback function to register
            inherit: Whether this callback should be inherited by child loggers

        Raises:
            CallbackError: If callback is not callable

        Example:
            >>> import logging
            >>>
            >>> def alert_on_critical(logger, level, msg, args, **kwargs):
            ...     send_alert(f"CRITICAL: {msg}")
            >>>
            >>> registry.register(logging.CRITICAL, alert_on_critical, inherit=True)
        """
        if not callable(callback):
            raise CallbackError(f"Callback must be callable, got {type(callback)}")

        if level not in self._callbacks:
            self._callbacks[level] = []

        self._callbacks[level].append((callback, inherit))

    def trigger(
        self, level: int, logger: Logger, msg: str, args: tuple, kwargs: dict
    ) -> None:
        """
        Trigger callbacks for a specific level.

        Called automatically by the logging system when a message is logged.
        Users typically don't call this directly - it's invoked by the Logger.

        Args:
            level: Log level that triggered the callbacks
            logger: Logger instance that triggered the event
            msg: Log message
            args: Message format arguments
            kwargs: Additional keyword arguments

        Example:
            >>> # Triggered automatically when logger.error() is called:
            >>> logger.error("Connection failed", extra={"host": "db.example.com"})
            >>> # All callbacks registered for ERROR level will be invoked
        """
        if level not in self._callbacks:
            return

        for callback, _ in self._callbacks[level]:
            try:
                callback(logger, level, msg, args, **kwargs)
            except Exception as e:
                # Don't let callback errors break logging
                # Use logging instead of print for better error handling
                logging.getLogger(__name__).warning(
                    "callback error", extra={"exception": e}
                )

    def inherit_to(self, other: CallbackRegistry) -> None:
        """
        Copy inheritable callbacks to another registry.

        Args:
            other: Target callback registry
        """
        for level, callbacks in self._callbacks.items():
            for callback, inherit in callbacks:
                if inherit:
                    other.register(level, callback, inherit=True)

    def has_callbacks(self, level: int) -> bool:
        """
        Check if there are callbacks registered for a level.

        Args:
            level: Log level to check

        Returns:
            True if callbacks are registered for this level
        """
        return level in self._callbacks and len(self._callbacks[level]) > 0

    def get_callback_count(self, level: int) -> int:
        """
        Get the number of callbacks registered for a level.

        Args:
            level: Log level to check

        Returns:
            Number of callbacks registered for this level
        """
        return len(self._callbacks.get(level, []))

    def clear(self) -> None:
        """Clear all registered callbacks."""
        self._callbacks.clear()

    def remove_callback(self, level: int, callback: Callable) -> bool:
        """
        Remove a specific callback from a level.

        Args:
            level: Log level to remove callback from
            callback: Callback function to remove

        Returns:
            True if callback was removed, False if not found
        """
        if level not in self._callbacks:
            return False

        callbacks = self._callbacks[level]
        for i, (cb, inherit) in enumerate(callbacks):
            if cb == callback:
                callbacks.pop(i)
                if not callbacks:
                    del self._callbacks[level]
                return True

        return False


def listens_for(logger: Logger, level: int, inherit: bool = False) -> Callable:
    """
    Decorator for registering callbacks with a logger.

    Args:
        logger: Logger instance to register callback with
        level: Log level to listen for
        inherit: Whether callback should be inherited by child loggers

    Returns:
        Decorator function
    """

    def decorator(func: Callable) -> Callable:
        """Register the decorated function as a callback."""
        if not callable(func):
            raise CallbackError(
                f"Decorated function must be callable, got {type(func)}"
            )

        logger._callbacks.register(level, func, inherit)
        return func

    return decorator
