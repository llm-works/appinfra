# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Thread-safe configuration holder for hot-reload support.

This module provides a wrapper around LogConfig that allows atomic updates
while maintaining thread-safety. Used by formatters to access configuration
indirectly, enabling hot-reload without replacing formatter instances.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import LogConfig


class LogConfigHolder:
    """
    Thread-safe holder for LogConfig that supports atomic updates.

    Uses lock-free reads with atomic reference swap for minimal overhead
    on the hot path (reading config during log formatting).

    Used by formatters to access configuration indirectly, allowing
    hot-reload without replacing formatter instances.

    Example:
        >>> from appinfra.log.config import LogConfig
        >>> config = LogConfig.from_params("info")
        >>> holder = LogConfigHolder(config)
        >>> holder.level  # Access via property (lock-free)
        20
        >>> new_config = LogConfig.from_params("debug")
        >>> holder.update(new_config)  # Atomic update
        >>> holder.level
        10
    """

    def __init__(self, config: LogConfig) -> None:
        """
        Initialize the holder with a LogConfig.

        Args:
            config: Initial LogConfig instance
        """
        # Config reference - reads are lock-free (Python GIL ensures atomic
        # reference reads/writes). Updates swap the entire immutable config.
        self._config = config
        # Lock only needed for callback list mutations, not config access
        self._lock = threading.RLock()
        self._callbacks: list[Callable[[LogConfig], None]] = []

    @property
    def config(self) -> LogConfig:
        """Get current config (lock-free read).

        Thread-safe due to Python's GIL guaranteeing atomic reference reads.
        The config object itself is treated as immutable after creation.
        """
        return self._config

    # Delegate properties for convenient access (all lock-free)

    @property
    def level(self) -> int | bool:
        """Get current log level."""
        return self._config.level

    @property
    def location(self) -> int:
        """Get current location display depth."""
        return self._config.location

    @property
    def micros(self) -> bool:
        """Get whether microsecond precision is enabled."""
        return self._config.micros

    @property
    def colors(self) -> bool:
        """Get whether colored output is enabled."""
        return self._config.colors

    @property
    def location_color(self) -> str | None:
        """Get current location color."""
        return self._config.location_color

    def update(self, new_config: LogConfig) -> None:
        """
        Update config atomically (thread-safe write).

        Args:
            new_config: New LogConfig to replace current config

        Note:
            Reference swap is atomic under GIL. Callbacks are invoked
            outside the lock to prevent deadlocks.
        """
        # Atomic reference swap (GIL ensures atomicity)
        self._config = new_config

        # Get callback list snapshot under lock
        with self._lock:
            callbacks = list(self._callbacks)

        # Notify listeners outside lock to avoid deadlock
        for callback in callbacks:
            try:
                callback(new_config)
            except Exception:
                pass  # Don't let callback errors break update

    def add_update_callback(self, callback: Callable[[LogConfig], None]) -> None:
        """
        Register callback for config updates.

        Args:
            callback: Function to call when config is updated.
                     Receives the new LogConfig as argument.
        """
        with self._lock:
            self._callbacks.append(callback)

    def remove_update_callback(self, callback: Callable[[LogConfig], None]) -> None:
        """
        Remove a previously registered callback.

        Args:
            callback: Callback function to remove
        """
        with self._lock:
            try:
                self._callbacks.remove(callback)
            except ValueError:
                pass  # Callback not found, ignore
