# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for app/builder/configurer/lifecycle.py.

The lifecycle block registers callbacks on lifecycle events.
"""

from unittest.mock import Mock

import pytest

from appinfra.app.builder.app import AppBuilder
from appinfra.app.builder.hook import HookBuilder

# =============================================================================
# with_hook
# =============================================================================


@pytest.mark.unit
class TestWithHook:
    """with_hook registers a callback on the builder's hook manager."""

    def test_registers_callback_on_event(self):
        """The callback is on the event's list."""
        builder = AppBuilder("test")
        callback = Mock()
        block = builder.lifecycle

        assert block.with_hook("startup", callback) is block
        assert builder._hooks._hooks["startup"] == [callback]

    def test_priority_orders_callbacks(self):
        """Higher priority runs first."""
        builder = AppBuilder("test")
        low, high = Mock(name="low"), Mock(name="high")

        builder.lifecycle.with_hook("startup", low, priority=1).with_hook(
            "startup", high, priority=10
        )

        assert builder._hooks._hooks["startup"] == [high, low]

    def test_done_returns_builder(self):
        """done() closes the block."""
        builder = AppBuilder("test")

        assert builder.lifecycle.done() is builder


# =============================================================================
# with_hook_builder
# =============================================================================


@pytest.mark.unit
class TestWithHookBuilder:
    """with_hook_builder merges a HookBuilder's hooks with their metadata."""

    def test_merges_hooks_with_metadata(self):
        """Priority and condition survive the merge."""
        builder = AppBuilder("test")
        callback = Mock()
        condition = Mock(return_value=True)

        builder.lifecycle.with_hook_builder(
            HookBuilder().on_startup(callback, priority=90, condition=condition)
        )

        assert builder._hooks._hooks["startup"] == [callback]
        assert builder._hooks._hook_metadata["startup"] == [
            {"priority": 90, "once": False, "condition": condition}
        ]

    def test_merges_every_event(self):
        """All events on the HookBuilder are registered."""
        builder = AppBuilder("test")
        start, stop = Mock(), Mock()

        builder.lifecycle.with_hook_builder(
            HookBuilder().on_startup(start).on_shutdown(stop)
        )

        assert builder._hooks._hooks["startup"] == [start]
        assert builder._hooks._hooks["shutdown"] == [stop]


# =============================================================================
# Keyword form
# =============================================================================


@pytest.mark.unit
class TestKeywordForm:
    """Calling the block registers one callback per event and returns the builder."""

    def test_call_registers_one_callback_per_event(self):
        """Keys are event names."""
        builder = AppBuilder("test")
        start, stop = Mock(), Mock()

        assert builder.lifecycle(startup=start, shutdown=stop) is builder
        assert builder._hooks._hooks["startup"] == [start]
        assert builder._hooks._hooks["shutdown"] == [stop]

    def test_call_rejects_unknown_event(self):
        """A misspelled standard event fails instead of registering a dead hook."""
        with pytest.raises(TypeError, match="unknown lifecycle field\\(s\\): shutdwn"):
            AppBuilder("test").lifecycle(startup=Mock(), shutdwn=Mock())

    def test_custom_event_goes_through_with_hook(self):
        """Custom event names are registered by the chained form."""
        builder = AppBuilder("test").lifecycle.with_hook("deploy", Mock()).done()

        assert builder._hooks.has_hooks("deploy")


# =============================================================================
# Integration with the App
# =============================================================================


@pytest.mark.integration
class TestHooksReachApp:
    """The builder's hook manager is the one the app's lifecycle uses."""

    def test_hook_manager_registered_on_lifecycle(self):
        """build() hands the hook manager to the app lifecycle."""
        builder = AppBuilder("test").lifecycle(startup=Mock())

        app = builder.build()

        assert app.lifecycle._hook_manager is builder._hooks
        assert app.lifecycle._hook_manager.has_hooks("startup")
