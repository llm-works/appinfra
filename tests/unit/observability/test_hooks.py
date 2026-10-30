# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for observability hooks.

Tests key functionality including:
- HookEvent enum values
- HookContext dataclass
- ObservabilityHooks class (register, trigger, enable/disable, etc.)
"""

import sys
import time
from io import StringIO
from unittest.mock import Mock, patch

import pytest

from appinfra.observability.hooks import (
    HookContext,
    HookEvent,
    ObservabilityHooks,
)

# =============================================================================
# Test HookEvent Enum
# =============================================================================


@pytest.mark.unit
class TestHookEvent:
    """Test HookEvent enumeration."""

    def test_database_events_exist(self):
        """Test database-related events."""
        assert HookEvent.QUERY_START.value == "query_start"
        assert HookEvent.QUERY_END.value == "query_end"
        assert HookEvent.CONNECTION_START.value == "connection_start"
        assert HookEvent.CONNECTION_END.value == "connection_end"

    def test_http_events_exist(self):
        """Test HTTP/server events."""
        assert HookEvent.REQUEST_START.value == "request_start"
        assert HookEvent.REQUEST_END.value == "request_end"

    def test_application_events_exist(self):
        """Test application/tool events."""
        assert HookEvent.TOOL_START.value == "tool_start"
        assert HookEvent.TOOL_END.value == "tool_end"
        assert HookEvent.APP_START.value == "app_start"
        assert HookEvent.APP_END.value == "app_end"

    def test_lifecycle_events_exist(self):
        """Test lifecycle events."""
        assert HookEvent.STARTUP.value == "startup"
        assert HookEvent.SHUTDOWN.value == "shutdown"


# =============================================================================
# Test HookContext Dataclass
# =============================================================================


@pytest.mark.unit
class TestHookContext:
    """Test HookContext dataclass."""

    def test_basic_creation(self):
        """Test basic context creation."""
        context = HookContext(event=HookEvent.QUERY_START)

        assert context.event == HookEvent.QUERY_START
        assert context.timestamp > 0
        assert context.data == {}

    def test_with_data(self):
        """Test context with custom data."""
        context = HookContext(
            event=HookEvent.QUERY_END, data={"query_id": 123, "result_count": 10}
        )

        assert context.data["query_id"] == 123
        assert context.data["result_count"] == 10

    def test_optional_fields(self):
        """Test optional event-specific fields."""
        context = HookContext(
            event=HookEvent.QUERY_START,
            query="SELECT * FROM users",
            duration=1.5,
            error=ValueError("test error"),
            tool_name="test_tool",
            request_path="/api/v1/users",
            response_code=200,
        )

        assert context.query == "SELECT * FROM users"
        assert context.duration == 1.5
        assert isinstance(context.error, ValueError)
        assert context.tool_name == "test_tool"
        assert context.request_path == "/api/v1/users"
        assert context.response_code == 200

    def test_post_init_sets_start_time(self):
        """Test __post_init__ sets monotonic start_time."""
        context = HookContext(event=HookEvent.TOOL_START)

        assert hasattr(context, "start_time")
        assert context.start_time > 0

    def test_set_duration(self):
        """Test set_duration calculates from start_time."""
        context = HookContext(event=HookEvent.TOOL_START)

        # Small delay
        time.sleep(0.01)

        context.set_duration()

        assert context.duration is not None
        assert context.duration >= 0.01


# =============================================================================
# Test ObservabilityHooks Class
# =============================================================================


@pytest.mark.unit
class TestObservabilityHooksInit:
    """Test ObservabilityHooks initialization."""

    def test_init(self):
        """Test basic initialization."""
        hooks = ObservabilityHooks()

        assert hooks._hooks == {}
        assert hooks._global_hooks == []
        assert hooks._enabled is True


@pytest.mark.unit
class TestObservabilityHooksRegister:
    """Test register and on methods."""

    def test_register_callback(self):
        """Test registering a callback."""
        hooks = ObservabilityHooks()
        callback = Mock()

        hooks.register(HookEvent.QUERY_START, callback)

        assert HookEvent.QUERY_START in hooks._hooks
        assert callback in hooks._hooks[HookEvent.QUERY_START]

    def test_register_multiple_callbacks(self):
        """Test registering multiple callbacks for same event."""
        hooks = ObservabilityHooks()
        callback1 = Mock()
        callback2 = Mock()

        hooks.register(HookEvent.QUERY_START, callback1)
        hooks.register(HookEvent.QUERY_START, callback2)

        assert len(hooks._hooks[HookEvent.QUERY_START]) == 2

    def test_on_decorator(self):
        """Test @on decorator for registering callbacks."""
        hooks = ObservabilityHooks()

        @hooks.on(HookEvent.REQUEST_START)
        def my_callback(context):
            pass

        assert HookEvent.REQUEST_START in hooks._hooks
        assert my_callback in hooks._hooks[HookEvent.REQUEST_START]

    def test_on_decorator_returns_original_function(self):
        """Test that @on decorator returns the original function."""
        hooks = ObservabilityHooks()

        @hooks.on(HookEvent.TOOL_START)
        def my_function(context):
            return "test"

        # Function should still be callable and work normally
        assert callable(my_function)

    def test_register_global(self):
        """Test registering global callback."""
        hooks = ObservabilityHooks()
        callback = Mock()

        hooks.register_global(callback)

        assert callback in hooks._global_hooks


@pytest.mark.unit
class TestObservabilityHooksUnregister:
    """Test unregister method."""

    def test_unregister_existing_callback(self):
        """Test unregistering an existing callback."""
        hooks = ObservabilityHooks()
        callback = Mock()
        hooks.register(HookEvent.QUERY_START, callback)

        result = hooks.unregister(HookEvent.QUERY_START, callback)

        assert result is True
        assert callback not in hooks._hooks[HookEvent.QUERY_START]

    def test_unregister_nonexistent_callback(self):
        """Test unregistering a callback that wasn't registered."""
        hooks = ObservabilityHooks()
        callback = Mock()

        result = hooks.unregister(HookEvent.QUERY_START, callback)

        assert result is False

    def test_unregister_wrong_event(self):
        """Test unregistering callback from wrong event."""
        hooks = ObservabilityHooks()
        callback = Mock()
        hooks.register(HookEvent.QUERY_START, callback)

        result = hooks.unregister(HookEvent.QUERY_END, callback)

        assert result is False


@pytest.mark.unit
class TestObservabilityHooksClear:
    """Test clear method."""

    def test_clear_all(self):
        """Test clearing all callbacks."""
        hooks = ObservabilityHooks()
        hooks.register(HookEvent.QUERY_START, Mock())
        hooks.register(HookEvent.QUERY_END, Mock())
        hooks.register_global(Mock())

        hooks.clear()

        assert hooks._hooks == {}
        assert hooks._global_hooks == []

    def test_clear_specific_event(self):
        """Test clearing specific event callbacks."""
        hooks = ObservabilityHooks()
        hooks.register(HookEvent.QUERY_START, Mock())
        hooks.register(HookEvent.QUERY_END, Mock())

        hooks.clear(HookEvent.QUERY_START)

        assert hooks._hooks.get(HookEvent.QUERY_START, []) == []
        assert len(hooks._hooks[HookEvent.QUERY_END]) == 1

    def test_clear_nonexistent_event(self):
        """Test clearing event with no callbacks."""
        hooks = ObservabilityHooks()

        # Should not raise
        hooks.clear(HookEvent.QUERY_START)


@pytest.mark.unit
class TestObservabilityHooksTrigger:
    """Test trigger method."""

    def test_trigger_calls_callback(self):
        """Test trigger calls registered callback."""
        hooks = ObservabilityHooks()
        callback = Mock()
        hooks.register(HookEvent.QUERY_START, callback)

        hooks.trigger(HookEvent.QUERY_START)

        callback.assert_called_once()
        context = callback.call_args[0][0]
        assert context.event == HookEvent.QUERY_START

    def test_trigger_passes_kwargs(self):
        """Test trigger passes kwargs to HookContext."""
        hooks = ObservabilityHooks()
        callback = Mock()
        hooks.register(HookEvent.QUERY_START, callback)

        # Only pass fields that HookContext accepts
        hooks.trigger(HookEvent.QUERY_START, query="SELECT 1", tool_name="test_tool")

        context = callback.call_args[0][0]
        assert context.query == "SELECT 1"
        assert context.tool_name == "test_tool"
        # Data dict should contain all kwargs
        assert context.data["query"] == "SELECT 1"

    def test_trigger_calls_all_callbacks(self):
        """Test trigger calls all registered callbacks."""
        hooks = ObservabilityHooks()
        callback1 = Mock()
        callback2 = Mock()
        hooks.register(HookEvent.QUERY_START, callback1)
        hooks.register(HookEvent.QUERY_START, callback2)

        hooks.trigger(HookEvent.QUERY_START)

        callback1.assert_called_once()
        callback2.assert_called_once()

    def test_trigger_calls_global_hooks(self):
        """Test trigger calls global callbacks."""
        hooks = ObservabilityHooks()
        event_callback = Mock()
        global_callback = Mock()
        hooks.register(HookEvent.QUERY_START, event_callback)
        hooks.register_global(global_callback)

        hooks.trigger(HookEvent.QUERY_START)

        event_callback.assert_called_once()
        global_callback.assert_called_once()

    def test_trigger_when_disabled_does_nothing(self):
        """Test trigger does nothing when hooks disabled."""
        hooks = ObservabilityHooks()
        callback = Mock()
        hooks.register(HookEvent.QUERY_START, callback)
        hooks.disable()

        hooks.trigger(HookEvent.QUERY_START)

        callback.assert_not_called()

    def test_trigger_handles_callback_exception(self):
        """Test trigger handles exceptions in callbacks gracefully."""
        hooks = ObservabilityHooks()

        def bad_callback(context):
            raise RuntimeError("Callback error")

        good_callback = Mock()
        hooks.register(HookEvent.QUERY_START, bad_callback)
        hooks.register(HookEvent.QUERY_START, good_callback)

        # Should not raise, but should write to stderr
        captured_stderr = StringIO()
        with patch.object(sys, "stderr", captured_stderr):
            hooks.trigger(HookEvent.QUERY_START)

        # Good callback should still be called despite bad callback exception
        good_callback.assert_called_once()
        # Error should be written to stderr
        assert "Error in observability hook" in captured_stderr.getvalue()

    def test_trigger_handles_global_callback_exception(self):
        """Test trigger handles exceptions in global callbacks."""
        hooks = ObservabilityHooks()

        def bad_global(context):
            raise ValueError("Global callback error")

        hooks.register_global(bad_global)

        captured_stderr = StringIO()
        with patch.object(sys, "stderr", captured_stderr):
            hooks.trigger(HookEvent.STARTUP)

        assert "Error in global observability hook" in captured_stderr.getvalue()

    def test_trigger_nonexistent_event(self):
        """Test trigger with no registered callbacks."""
        hooks = ObservabilityHooks()

        # Should not raise
        hooks.trigger(HookEvent.QUERY_START)


@pytest.mark.unit
class TestObservabilityHooksEnableDisable:
    """Test enable/disable methods."""

    def test_disable(self):
        """Test disabling hooks."""
        hooks = ObservabilityHooks()

        hooks.disable()

        assert hooks._enabled is False
        assert hooks.enabled is False

    def test_enable(self):
        """Test enabling hooks."""
        hooks = ObservabilityHooks()
        hooks.disable()

        hooks.enable()

        assert hooks._enabled is True
        assert hooks.enabled is True

    def test_enabled_property(self):
        """Test enabled property."""
        hooks = ObservabilityHooks()

        assert hooks.enabled is True

        hooks.disable()
        assert hooks.enabled is False

        hooks.enable()
        assert hooks.enabled is True


@pytest.mark.unit
class TestObservabilityHooksCallbackQuery:
    """Test get_callbacks and has_callbacks methods."""

    def test_get_callbacks_returns_copy(self):
        """Test get_callbacks returns a copy of callbacks list."""
        hooks = ObservabilityHooks()
        callback = Mock()
        hooks.register(HookEvent.QUERY_START, callback)

        result = hooks.get_callbacks(HookEvent.QUERY_START)

        assert callback in result
        # Verify it's a copy by modifying it
        result.append(Mock())
        assert len(hooks._hooks[HookEvent.QUERY_START]) == 1

    def test_get_callbacks_empty_event(self):
        """Test get_callbacks for event with no callbacks."""
        hooks = ObservabilityHooks()

        result = hooks.get_callbacks(HookEvent.QUERY_START)

        assert result == []

    def test_has_callbacks_true(self):
        """Test has_callbacks returns True when callbacks exist."""
        hooks = ObservabilityHooks()
        hooks.register(HookEvent.QUERY_START, Mock())

        assert hooks.has_callbacks(HookEvent.QUERY_START) is True

    def test_has_callbacks_false(self):
        """Test has_callbacks returns False when no callbacks."""
        hooks = ObservabilityHooks()

        assert hooks.has_callbacks(HookEvent.QUERY_START) is False

    def test_has_callbacks_after_clear(self):
        """Test has_callbacks after clearing callbacks."""
        hooks = ObservabilityHooks()
        hooks.register(HookEvent.QUERY_START, Mock())
        hooks.clear(HookEvent.QUERY_START)

        assert hooks.has_callbacks(HookEvent.QUERY_START) is False


# =============================================================================
# Integration Tests
# =============================================================================


@pytest.mark.integration
class TestObservabilityHooksIntegration:
    """Test real-world usage scenarios."""

    def test_query_monitoring_workflow(self):
        """Test complete query monitoring workflow."""
        hooks = ObservabilityHooks()
        query_log = []

        @hooks.on(HookEvent.QUERY_START)
        def log_query_start(context):
            query_log.append(f"START: {context.query}")

        @hooks.on(HookEvent.QUERY_END)
        def log_query_end(context):
            query_log.append(f"END: {context.query} took {context.duration}s")

        # Simulate query execution
        hooks.trigger(HookEvent.QUERY_START, query="SELECT * FROM users")
        time.sleep(0.01)
        hooks.trigger(HookEvent.QUERY_END, query="SELECT * FROM users", duration=0.01)

        assert len(query_log) == 2
        assert "START: SELECT * FROM users" in query_log[0]
        assert "END:" in query_log[1]

    def test_request_lifecycle(self):
        """Test HTTP request lifecycle monitoring."""
        hooks = ObservabilityHooks()
        events = []

        hooks.register_global(lambda ctx: events.append(ctx.event))

        hooks.trigger(HookEvent.REQUEST_START, request_path="/api/users")
        hooks.trigger(HookEvent.QUERY_START, query="SELECT * FROM users")
        hooks.trigger(HookEvent.QUERY_END, query="SELECT * FROM users")
        hooks.trigger(
            HookEvent.REQUEST_END, request_path="/api/users", response_code=200
        )

        assert HookEvent.REQUEST_START in events
        assert HookEvent.QUERY_START in events
        assert HookEvent.QUERY_END in events
        assert HookEvent.REQUEST_END in events

    def test_tool_execution_timing(self):
        """Test tool execution timing with context."""
        hooks = ObservabilityHooks()
        timings = []

        @hooks.on(HookEvent.TOOL_START)
        def start_timing(context):
            pass  # Context already has start_time

        @hooks.on(HookEvent.TOOL_END)
        def record_timing(context):
            context.set_duration()
            timings.append((context.tool_name, context.duration))

        # Simulate tool execution
        ctx = HookContext(event=HookEvent.TOOL_START, tool_name="my_tool")
        hooks.trigger(HookEvent.TOOL_START, tool_name="my_tool")

        time.sleep(0.01)

        # Create end context and set duration
        end_ctx = HookContext(event=HookEvent.TOOL_END, tool_name="my_tool")
        end_ctx.set_duration()
        hooks.trigger(
            HookEvent.TOOL_END, tool_name="my_tool", duration=end_ctx.duration
        )

    def test_multiple_hooks_with_disable(self):
        """Test multiple hooks with enable/disable."""
        hooks = ObservabilityHooks()
        callback1 = Mock()
        callback2 = Mock()

        hooks.register(HookEvent.APP_START, callback1)
        hooks.register(HookEvent.APP_START, callback2)

        # Trigger when enabled
        hooks.trigger(HookEvent.APP_START)
        assert callback1.call_count == 1
        assert callback2.call_count == 1

        # Disable and trigger
        hooks.disable()
        hooks.trigger(HookEvent.APP_START)
        assert callback1.call_count == 1  # Still 1, not called again
        assert callback2.call_count == 1

        # Re-enable and trigger
        hooks.enable()
        hooks.trigger(HookEvent.APP_START)
        assert callback1.call_count == 2
        assert callback2.call_count == 2
