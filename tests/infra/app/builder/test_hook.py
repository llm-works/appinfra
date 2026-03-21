"""
Tests for app/builder/hook.py.

Tests key functionality including:
- HookManager registration and triggering
- HookBuilder fluent API
- HookContext data management
- BuiltinHooks implementations
- Factory functions
"""

import logging
from unittest.mock import Mock, patch

import pytest

from appinfra.app.builder.hook import (
    BuiltinHooks,
    HookBuilder,
    HookContext,
    HookManager,
    create_hook_builder,
    create_logging_hooks,
    create_validation_hooks,
)

# =============================================================================
# Test HookManager Initialization
# =============================================================================


@pytest.mark.unit
class TestHookManagerInit:
    """Test HookManager initialization (lines 17-19)."""

    def test_basic_initialization(self):
        """Test basic initialization (lines 18-19)."""
        manager = HookManager()

        assert manager._hooks == {}
        assert manager._hook_metadata == {}


# =============================================================================
# Test HookManager register_hook
# =============================================================================


@pytest.mark.unit
class TestHookManagerRegisterHook:
    """Test HookManager register_hook method (lines 21-53)."""

    def test_registers_basic_hook(self):
        """Test registers hook (line 39)."""
        manager = HookManager()
        callback = Mock()

        manager.register_hook("startup", callback)

        assert callback in manager._hooks["startup"]

    def test_registers_hook_with_metadata(self):
        """Test registers hook with metadata (lines 40-46)."""
        manager = HookManager()
        callback = Mock()
        condition = Mock()

        manager.register_hook(
            "startup", callback, priority=10, once=True, condition=condition
        )

        metadata = manager._hook_metadata["startup"][0]
        assert metadata["priority"] == 10
        assert metadata["once"] is True
        assert metadata["condition"] is condition

    def test_sorts_by_priority(self):
        """Test sorts hooks by priority (lines 48-53)."""
        manager = HookManager()
        low_priority = Mock(name="low")
        high_priority = Mock(name="high")
        medium_priority = Mock(name="medium")

        manager.register_hook("startup", low_priority, priority=1)
        manager.register_hook("startup", high_priority, priority=10)
        manager.register_hook("startup", medium_priority, priority=5)

        # Highest priority should be first
        hooks = manager._hooks["startup"]
        assert hooks[0] is high_priority
        assert hooks[1] is medium_priority
        assert hooks[2] is low_priority


# =============================================================================
# Test HookManager trigger_hook
# =============================================================================


@pytest.mark.unit
class TestHookManagerTriggerHook:
    """Test HookManager trigger_hook method (lines 55-96)."""

    def test_triggers_all_hooks(self):
        """Test triggers all hooks for event (lines 70-80)."""
        manager = HookManager()
        hook1 = Mock(return_value="result1")
        hook2 = Mock(return_value="result2")
        manager.register_hook("startup", hook1)
        manager.register_hook("startup", hook2)

        results = manager.trigger_hook("startup", "arg1", kwarg1="value")

        hook1.assert_called_once_with("arg1", kwarg1="value")
        hook2.assert_called_once_with("arg1", kwarg1="value")
        assert results == ["result1", "result2"]

    def test_skips_when_condition_false(self):
        """Test skips hook when condition returns False (lines 74-76)."""
        manager = HookManager()
        hook = Mock()
        condition = Mock(return_value=False)
        manager.register_hook("startup", hook, condition=condition)

        manager.trigger_hook("startup")

        hook.assert_not_called()

    def test_runs_when_condition_true(self):
        """Test runs hook when condition returns True (line 75)."""
        manager = HookManager()
        hook = Mock(return_value="result")
        condition = Mock(return_value=True)
        manager.register_hook("startup", hook, condition=condition)

        results = manager.trigger_hook("startup")

        hook.assert_called_once()
        assert results == ["result"]

    def test_removes_once_hooks(self):
        """Test removes hooks marked as once (lines 82-84, 91-94)."""
        manager = HookManager()
        once_hook = Mock(return_value="once")
        normal_hook = Mock(return_value="normal")
        manager.register_hook("startup", once_hook, once=True)
        manager.register_hook("startup", normal_hook)

        # First trigger
        results = manager.trigger_hook("startup")
        assert len(results) == 2

        # Second trigger - once_hook should be removed
        results = manager.trigger_hook("startup")
        assert len(results) == 1
        assert results == ["normal"]

    def test_handles_hook_errors(self):
        """Test handles errors and continues (lines 86-89)."""
        manager = HookManager()
        error_hook = Mock(side_effect=ValueError("test error"))
        good_hook = Mock(return_value="good")
        manager.register_hook("startup", error_hook)
        manager.register_hook("startup", good_hook)

        with patch("appinfra.app.builder.hook.logging") as mock_logging:
            results = manager.trigger_hook("startup")

        # Should continue and return None for failed hook
        assert None in results
        assert "good" in results

    def test_returns_empty_for_no_hooks(self):
        """Test returns empty list for event with no hooks."""
        manager = HookManager()

        results = manager.trigger_hook("nonexistent")

        assert results == []


# =============================================================================
# Test HookManager Other Methods
# =============================================================================


@pytest.mark.unit
class TestHookManagerOtherMethods:
    """Test HookManager utility methods (lines 98-113)."""

    def test_has_hooks_true(self):
        """Test has_hooks returns True when hooks exist (line 100)."""
        manager = HookManager()
        manager.register_hook("startup", Mock())

        assert manager.has_hooks("startup") is True

    def test_has_hooks_false(self):
        """Test has_hooks returns False when no hooks (line 100)."""
        manager = HookManager()

        assert manager.has_hooks("startup") is False

    def test_get_hooks_returns_copy(self):
        """Test get_hooks returns a copy (line 104)."""
        manager = HookManager()
        hook = Mock()
        manager.register_hook("startup", hook)

        hooks = manager.get_hooks("startup")

        assert hook in hooks
        # Should be a copy, not the same list
        hooks.clear()
        assert manager.has_hooks("startup")

    def test_clear_hooks_specific_event(self):
        """Test clear_hooks clears specific event (lines 108-110)."""
        manager = HookManager()
        manager.register_hook("startup", Mock())
        manager.register_hook("shutdown", Mock())

        manager.clear_hooks("startup")

        assert not manager.has_hooks("startup")
        assert manager.has_hooks("shutdown")

    def test_clear_hooks_all(self):
        """Test clear_hooks clears all events (lines 111-113)."""
        manager = HookManager()
        manager.register_hook("startup", Mock())
        manager.register_hook("shutdown", Mock())

        manager.clear_hooks()

        assert not manager.has_hooks("startup")
        assert not manager.has_hooks("shutdown")


# =============================================================================
# Test HookBuilder
# =============================================================================


@pytest.mark.unit
class TestHookBuilder:
    """Test HookBuilder class (lines 116-207)."""

    def test_initialization(self):
        """Test initialization (lines 119-120)."""
        builder = HookBuilder()

        assert builder._hooks == {}

    def test_on_startup(self):
        """Test on_startup method (lines 122-127)."""
        builder = HookBuilder()
        func = Mock()

        result = builder.on_startup(func, priority=5)

        assert "startup" in builder._hooks
        assert result is builder

    def test_on_shutdown(self):
        """Test on_shutdown method (lines 129-134)."""
        builder = HookBuilder()
        func = Mock()

        result = builder.on_shutdown(func)

        assert "shutdown" in builder._hooks
        assert result is builder

    def test_on_tool_start(self):
        """Test on_tool_start method (lines 136-141)."""
        builder = HookBuilder()
        func = Mock()

        result = builder.on_tool_start(func)

        assert "tool_start" in builder._hooks
        assert result is builder

    def test_on_tool_end(self):
        """Test on_tool_end method (lines 143-148)."""
        builder = HookBuilder()
        func = Mock()

        result = builder.on_tool_end(func)

        assert "tool_end" in builder._hooks
        assert result is builder

    def test_on_error(self):
        """Test on_error method (lines 150-155)."""
        builder = HookBuilder()
        func = Mock()

        result = builder.on_error(func)

        assert "error" in builder._hooks
        assert result is builder

    def test_on_before_parse(self):
        """Test on_before_parse method (lines 157-162)."""
        builder = HookBuilder()
        func = Mock()

        result = builder.on_before_parse(func)

        assert "before_parse" in builder._hooks
        assert result is builder

    def test_on_after_parse(self):
        """Test on_after_parse method (lines 164-169)."""
        builder = HookBuilder()
        func = Mock()

        result = builder.on_after_parse(func)

        assert "after_parse" in builder._hooks
        assert result is builder

    def test_on_before_setup(self):
        """Test on_before_setup method (lines 171-176)."""
        builder = HookBuilder()
        func = Mock()

        result = builder.on_before_setup(func)

        assert "before_setup" in builder._hooks
        assert result is builder

    def test_on_after_setup(self):
        """Test on_after_setup method (lines 178-183)."""
        builder = HookBuilder()
        func = Mock()

        result = builder.on_after_setup(func)

        assert "after_setup" in builder._hooks
        assert result is builder

    def test_on_custom(self):
        """Test on_custom method (lines 185-190)."""
        builder = HookBuilder()
        func = Mock()

        result = builder.on_custom("my_event", func, priority=10)

        assert "my_event" in builder._hooks
        assert result is builder

    def test_once(self):
        """Test once method (lines 192-197)."""
        builder = HookBuilder()
        func = Mock()

        result = builder.once("startup", func)

        # Hook should be marked as once=True (index 2 in tuple)
        hook_tuple = builder._hooks["startup"][0]
        assert hook_tuple[2] is True  # once flag
        assert result is builder

    def test_build(self):
        """Test build method (lines 199-207)."""
        builder = HookBuilder()
        func1 = Mock()
        func2 = Mock()
        builder.on_startup(func1, priority=10)
        builder.on_shutdown(func2)

        manager = builder.build()

        assert isinstance(manager, HookManager)
        assert manager.has_hooks("startup")
        assert manager.has_hooks("shutdown")


# =============================================================================
# Test HookContext
# =============================================================================


@pytest.mark.unit
class TestHookContext:
    """Test HookContext class (lines 210-234)."""

    def test_initialization(self):
        """Test initialization (lines 213-226)."""
        app = Mock()
        tool = Mock()
        error = Mock()

        context = HookContext(
            application=app,
            tool=tool,
            error=error,
            custom_key="custom_value",
        )

        assert context.application is app
        assert context.tool is tool
        assert context.error is error
        assert context.data["custom_key"] == "custom_value"

    def test_get_existing_key(self):
        """Test get method for existing key (line 230)."""
        context = HookContext(key1="value1")

        assert context.get("key1") == "value1"

    def test_get_missing_key_with_default(self):
        """Test get method for missing key with default (line 230)."""
        context = HookContext()

        assert context.get("missing", "default") == "default"

    def test_set(self):
        """Test set method (lines 232-234)."""
        context = HookContext()

        context.set("new_key", "new_value")

        assert context.data["new_key"] == "new_value"


# =============================================================================
# Test BuiltinHooks
# =============================================================================


@pytest.mark.unit
class TestBuiltinHooks:
    """Test BuiltinHooks class (lines 237-288)."""

    def test_log_startup(self):
        """Test log_startup hook (lines 240-244)."""
        app = Mock()
        app.lg = Mock()
        context = HookContext(application=app)

        BuiltinHooks.log_startup(context)

        app.lg.debug.assert_called_once()
        assert "starting" in app.lg.debug.call_args[0][0]

    def test_log_startup_no_logger(self):
        """Test log_startup with no logger."""
        context = HookContext()

        # Should not raise
        BuiltinHooks.log_startup(context)

    def test_log_shutdown(self):
        """Test log_shutdown hook (lines 246-250)."""
        app = Mock()
        app.lg = Mock()
        context = HookContext(application=app)

        BuiltinHooks.log_shutdown(context)

        app.lg.debug.assert_called_once()
        assert "shutting down" in app.lg.debug.call_args[0][0]

    def test_log_tool_start(self):
        """Test log_tool_start hook (lines 252-256)."""
        tool = Mock()
        tool.lg = Mock()
        tool.name = "mytool"
        context = HookContext(tool=tool)

        BuiltinHooks.log_tool_start(context)

        tool.lg.debug.assert_called_once()
        assert "tool" in tool.lg.debug.call_args[1]["extra"]

    def test_log_tool_end(self):
        """Test log_tool_end hook (lines 258-262)."""
        tool = Mock()
        tool.lg = Mock()
        tool.name = "mytool"
        context = HookContext(tool=tool)

        BuiltinHooks.log_tool_end(context)

        tool.lg.debug.assert_called_once()
        assert "tool" in tool.lg.debug.call_args[1]["extra"]

    def test_log_error_with_app_logger(self):
        """Test log_error with app logger (lines 264-269)."""
        app = Mock()
        app.lg = Mock()
        error = ValueError("test error")
        context = HookContext(application=app, error=error)

        BuiltinHooks.log_error(context)

        app.lg.error.assert_called_once()

    def test_log_error_fallback_to_logging(self, caplog):
        """Test log_error falls back to logging module (lines 270-274)."""
        error = ValueError("test error")
        context = HookContext(error=error)

        with caplog.at_level(logging.ERROR):
            BuiltinHooks.log_error(context)

        # Should have logged to root logger
        assert len(caplog.records) == 1
        assert "error occurred" in caplog.text

    def test_validate_config_passes(self):
        """Test validate_config passes with config (lines 276-282)."""
        app = Mock()
        app.config = {"key": "value"}
        context = HookContext(application=app)

        # Should not raise
        BuiltinHooks.validate_config(context)

    def test_validate_config_raises_when_missing(self):
        """Test validate_config raises when no config (line 282)."""
        app = Mock()
        app.config = None
        context = HookContext(application=app)

        with pytest.raises(ValueError):
            BuiltinHooks.validate_config(context)

    def test_cleanup_resources(self):
        """Test cleanup_resources (lines 284-288)."""
        context = HookContext()

        # Should not raise (currently a no-op)
        BuiltinHooks.cleanup_resources(context)


# =============================================================================
# Test Factory Functions
# =============================================================================


@pytest.mark.unit
class TestFactoryFunctions:
    """Test factory functions (lines 291-309)."""

    def test_create_logging_hooks(self):
        """Test create_logging_hooks (lines 291-300)."""
        builder = create_logging_hooks()

        assert isinstance(builder, HookBuilder)
        assert "startup" in builder._hooks
        assert "shutdown" in builder._hooks
        assert "tool_start" in builder._hooks
        assert "tool_end" in builder._hooks
        assert "error" in builder._hooks

    def test_create_validation_hooks(self):
        """Test create_validation_hooks (lines 303-309)."""
        builder = create_validation_hooks()

        assert isinstance(builder, HookBuilder)
        assert "startup" in builder._hooks
        assert "shutdown" in builder._hooks

    def test_create_hook_builder(self):
        """Test create_hook_builder factory function."""
        builder = create_hook_builder()

        assert isinstance(builder, HookBuilder)
        # Should be a fresh builder with no hooks registered
        assert len(builder._hooks) == 0


# =============================================================================
# Integration Tests
# =============================================================================


@pytest.mark.integration
class TestHookIntegration:
    """Test hook system integration."""

    def test_full_hook_lifecycle(self):
        """Test complete hook lifecycle."""
        call_order = []

        def on_startup(ctx):
            call_order.append("startup")

        def on_tool_start(ctx):
            call_order.append("tool_start")

        def on_tool_end(ctx):
            call_order.append("tool_end")

        def on_shutdown(ctx):
            call_order.append("shutdown")

        manager = (
            HookBuilder()
            .on_startup(on_startup)
            .on_tool_start(on_tool_start)
            .on_tool_end(on_tool_end)
            .on_shutdown(on_shutdown)
            .build()
        )

        # Simulate application lifecycle
        context = HookContext()
        manager.trigger_hook("startup", context)
        manager.trigger_hook("tool_start", context)
        manager.trigger_hook("tool_end", context)
        manager.trigger_hook("shutdown", context)

        assert call_order == ["startup", "tool_start", "tool_end", "shutdown"]

    def test_priority_ordering(self):
        """Test hooks are called in priority order."""
        call_order = []

        def high_priority(ctx):
            call_order.append("high")

        def low_priority(ctx):
            call_order.append("low")

        def medium_priority(ctx):
            call_order.append("medium")

        manager = (
            HookBuilder()
            .on_startup(low_priority, priority=1)
            .on_startup(high_priority, priority=100)
            .on_startup(medium_priority, priority=50)
            .build()
        )

        manager.trigger_hook("startup", HookContext())

        assert call_order == ["high", "medium", "low"]

    def test_conditional_hooks(self):
        """Test hooks with conditions."""
        call_order = []

        def always_run(ctx):
            call_order.append("always")

        def only_on_error(ctx):
            call_order.append("error")

        manager = (
            HookBuilder()
            .on_startup(always_run)
            .on_startup(only_on_error, condition=lambda ctx: ctx.error is not None)
            .build()
        )

        # No error - only always_run should run
        manager.trigger_hook("startup", HookContext())
        assert call_order == ["always"]

        # With error - both should run
        call_order.clear()
        manager.trigger_hook("startup", HookContext(error=ValueError("test")))
        assert call_order == ["always", "error"]

    def test_once_hooks(self):
        """Test hooks that run only once."""
        call_count = [0]

        def once_hook(ctx):
            call_count[0] += 1

        manager = HookBuilder().once("startup", once_hook).build()

        manager.trigger_hook("startup", HookContext())
        manager.trigger_hook("startup", HookContext())
        manager.trigger_hook("startup", HookContext())

        assert call_count[0] == 1
