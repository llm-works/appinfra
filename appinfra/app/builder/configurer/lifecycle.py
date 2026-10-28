# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Lifecycle block for AppBuilder.

Registers callbacks on lifecycle events. App-only concerns; there is no
standalone builder behind this block.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Self

from ..hook import STANDARD_EVENTS, HookBuilder
from .block import check_fields, close_on_error

if TYPE_CHECKING:
    from ..app import AppBuilder


class LifecycleConfigurer:
    """Lifecycle block: hooks by event.

    Chained::

        AppBuilder("myapp").lifecycle.with_hook("startup", init_db).done()

    Keyword, returning the AppBuilder directly::

        AppBuilder("myapp").lifecycle(startup=init_db, shutdown=close_db)

    Event names are those of ``HookManager`` (``startup``, ``shutdown``,
    ``tool_start``, ``tool_end``, ``error``, ``before_parse``,
    ``after_parse``, ``before_setup``, ``after_setup`` and custom names).
    """

    block_name = "lifecycle"

    def __init__(self, app_builder: AppBuilder):
        """Bind the block to its parent builder."""
        self._app_builder = app_builder

    def with_hook(
        self, event: str, callback: Callable[..., Any], priority: int = 0
    ) -> Self:
        """Register ``callback`` on ``event``; higher priority runs first."""
        self._app_builder._hooks.register_hook(event, callback, priority=priority)
        return self

    def with_hook_builder(self, builder: HookBuilder) -> Self:
        """Register every hook of a ``HookBuilder``, keeping priority and conditions."""
        for event, callback, meta in builder.build().iter_hooks():
            self._app_builder._hooks.register_hook(event, callback, **meta)
        return self

    def done(self) -> AppBuilder:
        """Return to the AppBuilder."""
        self._app_builder._close(self)
        return self._app_builder

    def __call__(self, **hooks: Callable[..., Any]) -> AppBuilder:
        """Keyword form of the block: one callback per standard event.

        Only the events the framework fires are accepted, so a misspelled
        name fails here instead of registering a hook nothing runs. Custom
        event names go through ``with_hook``.

        Raises:
            TypeError: for a keyword that is not a standard event.
        """
        with close_on_error(self._app_builder, self):
            check_fields("lifecycle", hooks, STANDARD_EVENTS)
            for event, callback in hooks.items():
                self.with_hook(event, callback)
        return self.done()
