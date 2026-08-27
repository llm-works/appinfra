# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Advanced configuration builder for AppBuilder.

This module provides focused builder for advanced features like hooks,
validation, and custom arguments.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Self

from ..hook import HookBuilder
from ..validation import ValidationBuilder, ValidationRule

if TYPE_CHECKING:
    from ..app import AppBuilder


class AdvancedConfigurer:
    """
    Focused builder for advanced configuration (hooks, validation, arguments).

    This class extracts advanced features from AppBuilder,
    following the Single Responsibility Principle.
    """

    def __init__(self, app_builder: AppBuilder):
        """
        Initialize the advanced configurer.

        Args:
            app_builder: Parent AppBuilder instance
        """
        self._app_builder = app_builder

    def with_hook(self, event: str, callback: Callable) -> Self:
        """
        Add a lifecycle hook.

        Args:
            event: Event name to hook into
            callback: Callback function

        Returns:
            Self for method chaining
        """
        self._app_builder._hooks.register_hook(event, callback)
        return self

    def with_hook_builder(self, builder: HookBuilder) -> Self:
        """
        Add hooks using a hook builder.

        Args:
            builder: HookBuilder instance

        Returns:
            Self for method chaining
        """
        hook_manager = builder.build()
        # Merge hooks from the builder
        for event, callbacks in hook_manager._hooks.items():
            for callback in callbacks:
                self._app_builder._hooks.register_hook(event, callback)
        return self

    def with_validation_rule(self, rule: ValidationRule) -> Self:
        """
        Add a validation rule.

        Args:
            rule: ValidationRule instance

        Returns:
            Self for method chaining
        """
        self._app_builder._validation_rules.append(rule)
        return self

    def with_validation_builder(self, builder: ValidationBuilder) -> Self:
        """
        Add validation rules using a validation builder.

        Args:
            builder: ValidationBuilder instance

        Returns:
            Self for method chaining
        """
        self._app_builder._validation_rules.extend(builder.build())
        return self

    def with_argument(self, *args: Any, **kwargs: Any) -> Self:
        """
        Add a custom command-line argument.

        Args:
            *args: Positional arguments for argparse.add_argument()
            **kwargs: Keyword arguments for argparse.add_argument()

        Returns:
            Self for method chaining
        """
        self._app_builder._custom_args.append((args, kwargs))
        return self

    def done(self) -> AppBuilder:
        """
        Finish advanced configuration and return to main builder.

        Returns:
            Parent AppBuilder instance for continued chaining
        """
        return self._app_builder
