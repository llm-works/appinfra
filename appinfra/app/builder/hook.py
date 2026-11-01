# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Hook system for the AppBuilder framework.

This module provides a fluent API for managing application lifecycle hooks
and event handling.
"""

from collections import defaultdict
from collections.abc import Callable, Iterator
from typing import Any, Self


class HookManager:
    """Manages application lifecycle hooks."""

    def __init__(self) -> None:
        self._hooks: dict[str, list[Callable[..., Any]]] = defaultdict(list)
        self._hook_metadata: dict[str, list[dict[str, Any]]] = defaultdict(list)

    def register_hook(
        self,
        event: str,
        callback: Callable[..., Any],
        priority: int = 0,
        once: bool = False,
        condition: Callable[..., Any] | None = None,
    ) -> None:
        """
        Register a hook for an event.

        Args:
            event: Event name
            callback: Function to call when event occurs
            priority: Hook priority (higher numbers run first)
            once: Whether to run only once
            condition: Optional condition function that must return True
        """
        self._hooks[event].append(callback)
        self._hook_metadata[event].append(
            {
                "priority": priority,
                "once": once,
                "condition": condition,
            }
        )

        # Sort hooks by priority (highest first)
        # Zip hooks with metadata, sort by priority, then unzip
        paired = list(zip(self._hooks[event], self._hook_metadata[event]))
        paired.sort(key=lambda pair: pair[1].get("priority", 0), reverse=True)
        self._hooks[event] = [hook for hook, _ in paired]
        self._hook_metadata[event] = [metadata for _, metadata in paired]

    def trigger_hook(self, event: str, *args: Any, **kwargs: Any) -> list[Any]:
        """
        Trigger all hooks for an event.

        Every hook runs even if an earlier one fails. A failing hook's slot
        in the results holds the exception it raised; the caller, which has
        the logger, reports it.

        Args:
            event: Event name
            *args: Positional arguments to pass to hooks
            **kwargs: Keyword arguments to pass to hooks

        Returns:
            One entry per hook that ran: its return value, or the exception
            it raised
        """
        results = []
        hooks_to_remove = []

        for i, hook in enumerate(self._hooks[event]):
            metadata = self._hook_metadata[event][i]

            try:
                # Check condition if provided
                condition = metadata.get("condition")
                if condition and not condition(*args, **kwargs):
                    continue

                result = hook(*args, **kwargs)
                results.append(result)

                # Remove hook if it's marked as once
                if metadata.get("once", False):
                    hooks_to_remove.append(i)

            except Exception as e:
                results.append(e)

        # Remove hooks marked as once (both hook and metadata)
        for i in reversed(hooks_to_remove):
            del self._hooks[event][i]
            del self._hook_metadata[event][i]

        return results

    def has_hooks(self, event: str) -> bool:
        """Check if there are any hooks for an event."""
        return len(self._hooks[event]) > 0

    def get_hooks(self, event: str) -> list[Callable[..., Any]]:
        """Get all hooks for an event."""
        return self._hooks[event].copy()

    def iter_hooks(self) -> Iterator[tuple[str, Callable[..., Any], dict[str, Any]]]:
        """Every hook with its event and metadata, in trigger order.

        The metadata keys are ``register_hook``'s keyword arguments, so a
        hook can be re-registered on another manager unchanged.
        """
        for event, callbacks in self._hooks.items():
            yield from (
                (event, callback, dict(meta))
                for callback, meta in zip(
                    callbacks, self._hook_metadata[event], strict=True
                )
            )

    def clear_hooks(self, event: str | None = None) -> None:
        """Clear hooks for an event or all events."""
        if event:
            self._hooks[event].clear()
            self._hook_metadata[event].clear()
        else:
            self._hooks.clear()
            self._hook_metadata.clear()


# The events the framework fires; ``HookBuilder`` has one ``on_*`` per name.
# Custom events are registered by name through ``HookManager.register_hook``.
STANDARD_EVENTS = frozenset(
    {
        "startup",
        "shutdown",
        "tool_start",
        "tool_end",
        "error",
        "before_parse",
        "after_parse",
        "before_setup",
        "after_setup",
    }
)


class HookBuilder:
    """Builder for registering hooks."""

    def __init__(self) -> None:
        # (func, priority, once, condition)
        self._hooks: dict[str, list[tuple[Any, ...]]] = defaultdict(list)

    def on_startup(
        self,
        func: Callable[..., Any],
        priority: int = 0,
        condition: Callable[..., Any] | None = None,
    ) -> Self:
        """Register a startup hook."""
        self._hooks["startup"].append((func, priority, False, condition))
        return self

    def on_shutdown(
        self,
        func: Callable[..., Any],
        priority: int = 0,
        condition: Callable[..., Any] | None = None,
    ) -> Self:
        """Register a shutdown hook."""
        self._hooks["shutdown"].append((func, priority, False, condition))
        return self

    def on_tool_start(
        self,
        func: Callable[..., Any],
        priority: int = 0,
        condition: Callable[..., Any] | None = None,
    ) -> Self:
        """Register a tool start hook."""
        self._hooks["tool_start"].append((func, priority, False, condition))
        return self

    def on_tool_end(
        self,
        func: Callable[..., Any],
        priority: int = 0,
        condition: Callable[..., Any] | None = None,
    ) -> Self:
        """Register a tool end hook."""
        self._hooks["tool_end"].append((func, priority, False, condition))
        return self

    def on_error(
        self,
        func: Callable[..., Any],
        priority: int = 0,
        condition: Callable[..., Any] | None = None,
    ) -> Self:
        """Register an error hook."""
        self._hooks["error"].append((func, priority, False, condition))
        return self

    def on_before_parse(
        self,
        func: Callable[..., Any],
        priority: int = 0,
        condition: Callable[..., Any] | None = None,
    ) -> Self:
        """Register a before argument parsing hook."""
        self._hooks["before_parse"].append((func, priority, False, condition))
        return self

    def on_after_parse(
        self,
        func: Callable[..., Any],
        priority: int = 0,
        condition: Callable[..., Any] | None = None,
    ) -> Self:
        """Register an after argument parsing hook."""
        self._hooks["after_parse"].append((func, priority, False, condition))
        return self

    def on_before_setup(
        self,
        func: Callable[..., Any],
        priority: int = 0,
        condition: Callable[..., Any] | None = None,
    ) -> Self:
        """Register a before setup hook."""
        self._hooks["before_setup"].append((func, priority, False, condition))
        return self

    def on_after_setup(
        self,
        func: Callable[..., Any],
        priority: int = 0,
        condition: Callable[..., Any] | None = None,
    ) -> Self:
        """Register an after setup hook."""
        self._hooks["after_setup"].append((func, priority, False, condition))
        return self

    def on_custom(
        self,
        event: str,
        func: Callable[..., Any],
        priority: int = 0,
        condition: Callable[..., Any] | None = None,
    ) -> Self:
        """Register a custom event hook."""
        self._hooks[event].append((func, priority, False, condition))
        return self

    def once(
        self,
        event: str,
        func: Callable[..., Any],
        priority: int = 0,
        condition: Callable[..., Any] | None = None,
    ) -> Self:
        """Register a hook that runs only once."""
        self._hooks[event].append((func, priority, True, condition))
        return self

    def build(self) -> HookManager:
        """Build the hook manager with all registered hooks."""
        manager = HookManager()

        for event, hooks in self._hooks.items():
            for func, priority, once, condition in hooks:
                manager.register_hook(event, func, priority, once, condition)

        return manager


class HookContext:
    """Context object passed to hooks."""

    def __init__(
        self,
        application: Any = None,
        tool: Any = None,
        error: Exception | None = None,
        **kwargs: Any,
    ) -> None:
        """
        Initialize hook context.

        Args:
            application: App instance
            tool: Tool instance (if applicable)
            error: Error instance (if applicable)
            **kwargs: Additional context data
        """
        self.application = application
        self.tool = tool
        self.error = error
        self.data = kwargs

    def get(self, key: str, default: Any = None) -> Any:
        """Get a context value."""
        return self.data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set a context value."""
        self.data[key] = value


class BuiltinHooks:
    """Collection of built-in hook implementations."""

    @staticmethod
    def log_startup(context: HookContext) -> None:
        """Log application startup."""
        if context.application and hasattr(context.application, "lg"):
            context.application.lg.debug("starting application")

    @staticmethod
    def log_shutdown(context: HookContext) -> None:
        """Log application shutdown."""
        if context.application and hasattr(context.application, "lg"):
            context.application.lg.debug("shutting down application...")

    @staticmethod
    def log_tool_start(context: HookContext) -> None:
        """Log tool start."""
        if context.tool and hasattr(context.tool, "lg"):
            context.tool.lg.debug("starting tool...", extra={"tool": context.tool.name})

    @staticmethod
    def log_tool_end(context: HookContext) -> None:
        """Log tool end."""
        if context.tool and hasattr(context.tool, "lg"):
            context.tool.lg.debug("finished tool", extra={"tool": context.tool.name})

    @staticmethod
    def log_error(context: HookContext) -> None:
        """Log the context's error through the application logger."""
        if context.error and context.application and hasattr(context.application, "lg"):
            context.application.lg.error(
                "error occurred", extra={"exception": context.error}
            )

    @staticmethod
    def validate_config(context: HookContext) -> None:
        """Validate application configuration."""
        if context.application and hasattr(context.application, "config"):
            config = context.application.config
            if not config:
                raise ValueError("App configuration is required")

    @staticmethod
    def cleanup_resources(context: HookContext) -> None:
        """Clean up resources on shutdown."""
        # This would be implemented based on specific application needs


def create_logging_hooks() -> HookBuilder:
    """Create a hook builder with logging hooks."""
    return (
        HookBuilder()
        .on_startup(BuiltinHooks.log_startup)
        .on_shutdown(BuiltinHooks.log_shutdown)
        .on_tool_start(BuiltinHooks.log_tool_start)
        .on_tool_end(BuiltinHooks.log_tool_end)
        .on_error(BuiltinHooks.log_error)
    )


def create_validation_hooks() -> HookBuilder:
    """Create a hook builder with validation hooks."""
    return (
        HookBuilder()
        .on_startup(BuiltinHooks.validate_config)
        .on_shutdown(BuiltinHooks.cleanup_resources)
    )


def create_hook_builder() -> HookBuilder:
    """
    Create a new hook builder.

    Returns:
        HookBuilder instance

    Example:
        hooks = create_hook_builder().on_startup(my_handler).build()
    """
    return HookBuilder()
