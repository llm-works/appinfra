# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Observability hooks for monitoring framework operations.

This module provides a simple callback-based system for monitoring and
instrumenting framework operations without external dependencies.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class HookEvent(Enum):
    """Event types for observability hooks."""

    # Database events
    QUERY_START = "query_start"
    QUERY_END = "query_end"
    CONNECTION_START = "connection_start"
    CONNECTION_END = "connection_end"

    # HTTP/Server events
    REQUEST_START = "request_start"
    REQUEST_END = "request_end"

    # Application/Tool events
    TOOL_START = "tool_start"
    TOOL_END = "tool_end"
    APP_START = "app_start"
    APP_END = "app_end"

    # Lifecycle events
    STARTUP = "startup"
    SHUTDOWN = "shutdown"


@dataclass
class HookContext:
    """
    Context information passed to observability hooks.

    Provides relevant data about the event being monitored.
    """

    event: HookEvent
    timestamp: float = field(default_factory=time.time)
    data: dict[str, Any] = field(default_factory=dict)

    # Event-specific fields (optional)
    query: str | None = None
    duration: float | None = None
    error: Exception | None = None
    tool_name: str | None = None
    request_path: str | None = None
    response_code: int | None = None

    def __post_init__(self) -> None:
        """Set monotonic time for accurate duration measurement."""
        self.start_time = time.monotonic()

    def set_duration(self) -> None:
        """Calculate and set duration from start_time."""
        self.duration = time.monotonic() - self.start_time


class ObservabilityHooks:
    """
    Simple callback-based observability system.

    Allows registering callbacks for various framework events without
    requiring external observability frameworks.

    Example:
        import logging

        lg = logging.getLogger(__name__)
        hooks = ObservabilityHooks()

        # Register a callback for query events
        @hooks.on(HookEvent.QUERY_START)
        def log_query_start(context: HookContext):
            lg.info(f"Query started: {context.query}")

        # Or register directly
        hooks.register(HookEvent.QUERY_END, lambda ctx: lg.info(f"Query took {ctx.duration}s"))

        # Trigger hooks from framework code
        hooks.trigger(HookEvent.QUERY_START, query="SELECT * FROM users")
    """

    def __init__(self) -> None:
        """Initialize the hooks registry."""
        self._hooks: dict[HookEvent, list[Callable[[HookContext], None]]] = {}
        self._global_hooks: list[Callable[[HookContext], None]] = []
        self._enabled: bool = True

    def register(
        self, event: HookEvent, callback: Callable[[HookContext], None]
    ) -> None:
        """
        Register a callback for a specific event.

        Args:
            event: Event type to listen for
            callback: Callback function that receives HookContext
        """
        if event not in self._hooks:
            self._hooks[event] = []
        self._hooks[event].append(callback)

    def on(self, event: HookEvent) -> Callable:
        """
        Decorator for registering event callbacks.

        Args:
            event: Event type to listen for

        Returns:
            Decorator function

        Example:
            import logging

            lg = logging.getLogger(__name__)

            @hooks.on(HookEvent.QUERY_START)
            def my_callback(context: HookContext):
                lg.info(f"Query: {context.query}")
        """

        def decorator(callback: Callable[[HookContext], None]) -> Callable:
            self.register(event, callback)
            return callback

        return decorator

    def register_global(self, callback: Callable[[HookContext], None]) -> None:
        """
        Register a global callback that receives all events.

        Args:
            callback: Callback function that receives HookContext

        Example:
            import logging

            lg = logging.getLogger(__name__)
            hooks.register_global(lambda ctx: lg.info(f"Event: {ctx.event}"))
        """
        self._global_hooks.append(callback)

    def unregister(
        self, event: HookEvent, callback: Callable[[HookContext], None]
    ) -> bool:
        """
        Unregister a callback for a specific event.

        Args:
            event: Event type
            callback: Callback function to remove

        Returns:
            bool: True if callback was found and removed
        """
        if event in self._hooks and callback in self._hooks[event]:
            self._hooks[event].remove(callback)
            return True
        return False

    def clear(self, event: HookEvent | None = None) -> None:
        """
        Clear registered callbacks.

        Args:
            event: Specific event to clear, or None to clear all events
        """
        if event is None:
            self._hooks.clear()
            self._global_hooks.clear()
        elif event in self._hooks:
            self._hooks[event].clear()

    def trigger(self, event: HookEvent, **kwargs: Any) -> None:
        """
        Trigger all callbacks registered for an event.

        Args:
            event: Event type to trigger
            **kwargs: Event-specific data to include in HookContext

        Example:
            hooks.trigger(
                HookEvent.QUERY_START,
                query="SELECT * FROM users",
                query_id=12345
            )
        """
        if not self._enabled:
            return

        # Create context
        context = HookContext(event=event, data=kwargs, **kwargs)

        # Call event-specific hooks
        if event in self._hooks:
            for callback in self._hooks[event]:
                try:
                    callback(context)
                except Exception as e:
                    # Log error but don't break execution
                    import sys

                    sys.stderr.write(f"Error in observability hook for {event}: {e}\n")

        # Call global hooks
        for callback in self._global_hooks:
            try:
                callback(context)
            except Exception as e:
                import sys

                sys.stderr.write(f"Error in global observability hook: {e}\n")

    def enable(self) -> None:
        """Enable hook execution."""
        self._enabled = True

    def disable(self) -> None:
        """Disable hook execution (for performance)."""
        self._enabled = False

    @property
    def enabled(self) -> bool:
        """Check if hooks are enabled."""
        return self._enabled

    def get_callbacks(self, event: HookEvent) -> list[Callable]:
        """
        Get all callbacks registered for an event.

        Args:
            event: Event type

        Returns:
            List of callback functions
        """
        return self._hooks.get(event, []).copy()

    def has_callbacks(self, event: HookEvent) -> bool:
        """
        Check if any callbacks are registered for an event.

        Args:
            event: Event type

        Returns:
            bool: True if callbacks exist
        """
        return event in self._hooks and len(self._hooks[event]) > 0
