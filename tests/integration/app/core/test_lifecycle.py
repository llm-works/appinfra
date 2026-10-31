# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for app/core/lifecycle.py that initialize real loggers and run shutdown phases.

Initialization installs the shutdown signal handlers and shutdown phases run under a
SIGALRM timeout, so these tests change process-wide signal state.
"""

from contextlib import nullcontext
from unittest.mock import Mock, patch

import pytest

from appinfra.app.core.lifecycle import LifecycleManager
from appinfra.app.errors import LifecycleError
from appinfra.app.tools.base import Tool, ToolConfig
from appinfra.dot_dict import DotDict


def create_test_tool(name: str):
    """Helper to create a properly configured test tool."""

    class TestTool(Tool):
        def run(self, **kwargs):
            return 0

    config = ToolConfig(name=name)
    return TestTool(config=config)


# =============================================================================
# Test Initialize
# =============================================================================


class TestInitialize:
    """Test initialize method (lines 24-59)."""

    def test_initialize_sets_start_time(self):
        """Test initialize sets start time."""
        app = Mock()
        manager = LifecycleManager(app)
        config = DotDict(logging=DotDict(level="info", location=0, micros=False))

        manager.initialize(config)

        assert manager._start_time is not None

    def test_start_t_property_exposes_anchor(self):
        """Test start_t property is None pre-initialize and matches _start_time after."""
        app = Mock()
        manager = LifecycleManager(app)
        config = DotDict(logging=DotDict(level="info", location=0, micros=False))

        assert manager.start_t is None

        manager.initialize(config)

        assert manager.start_t is not None
        assert manager.start_t == manager._start_time
        assert isinstance(manager.start_t, float)

    def test_initialize_creates_logger(self):
        """Test initialize creates logger."""
        app = Mock()
        manager = LifecycleManager(app)
        config = DotDict(logging=DotDict(level="info", location=0, micros=False))

        manager.initialize(config)

        assert manager._logger is not None

    def test_initialize_without_logging_section(self):
        """Test initialize with config without logging section."""
        app = Mock()
        manager = LifecycleManager(app)
        config = DotDict()  # No logging section

        manager.initialize(config)

        assert manager._logger is not None

    def test_initialize_with_custom_settings(self):
        """Test initialize with custom logging settings."""
        app = Mock()
        manager = LifecycleManager(app)
        config = DotDict(logging=DotDict(level="trace", location=2, micros=True))

        manager.initialize(config)

        assert manager._logger is not None

    def test_initialize_respects_handler_stream_config(self):
        """Test that stream config from handlers is respected."""
        import sys

        app = Mock()
        manager = LifecycleManager(app)
        config = DotDict(
            logging=DotDict(
                level="info",
                handlers=DotDict(console=DotDict(type="console", stream="stdout")),
            )
        )

        manager.initialize(config)

        # Verify handler uses stdout, not stderr
        assert manager._logger is not None
        assert len(manager._logger.handlers) >= 1
        handler = manager._logger.handlers[0]
        assert handler.stream is sys.stdout

    def test_initialize_creates_handler_registry(self):
        """Test that handler registry is created during initialization."""
        app = Mock()
        manager = LifecycleManager(app)
        config = DotDict(
            logging=DotDict(
                level="info",
                handlers=DotDict(console=DotDict(type="console", stream="stdout")),
            )
        )

        manager.initialize(config)

        assert manager._handler_registry is not None


# =============================================================================
# Integration Tests
# =============================================================================


class TestLifecycleIntegration:
    """Test full lifecycle scenarios."""

    def test_full_lifecycle(self):
        """Test complete lifecycle flow."""
        app = Mock()
        manager = LifecycleManager(app)
        config = DotDict(logging=DotDict(level="info", location=0, micros=False))

        # Initialize
        manager.initialize(config)
        assert manager._logger is not None
        assert manager._start_time is not None

        # Setup tool
        tool = create_test_tool("lifecycle_tool")
        tool.setup = Mock()
        manager.setup_tool(tool, start=manager._start_time)

        # Execute tool
        tool.run = Mock(return_value=0)
        result = manager.execute_tool(tool)
        assert result == 0

        # Finalize
        manager.finalize(result)

    def test_lifecycle_with_tool_failure(self):
        """Test lifecycle when tool fails."""
        app = Mock()
        manager = LifecycleManager(app)
        config = DotDict(logging=DotDict(level="info", location=0, micros=False))

        manager.initialize(config)

        # Create tool that fails
        tool = create_test_tool("failing_tool")
        tool.setup = Mock()
        tool.run = Mock(side_effect=ValueError("Tool crashed"))

        manager.setup_tool(tool)

        with pytest.raises(LifecycleError):
            manager.execute_tool(tool)

        # Should still be able to finalize
        manager.finalize(1)


# =============================================================================
# Shutdown
# =============================================================================


class TestShutdownPhases:
    """Test individual shutdown phases."""

    def test_shutdown_hooks_called(self):
        """Test shutdown triggers hooks."""
        app = Mock()
        manager = LifecycleManager(app)
        config = DotDict(logging=DotDict(level="info", location=0, micros=False))
        manager.initialize(config)

        hook_manager = Mock()
        hook_manager.has_hooks = Mock(return_value=True)
        hook_manager.trigger_hook = Mock()
        manager.register_hook_manager(hook_manager)

        manager._shutdown_hooks()

        hook_manager.has_hooks.assert_called_with("shutdown")
        hook_manager.trigger_hook.assert_called_once()

    def test_shutdown_hooks_skipped_when_no_manager(self):
        """Test shutdown hooks skipped when no hook manager registered."""
        app = Mock()
        manager = LifecycleManager(app)
        config = DotDict(logging=DotDict(level="info", location=0, micros=False))
        manager.initialize(config)

        # Should not raise
        manager._shutdown_hooks()

    def test_shutdown_hooks_handles_exception(self):
        """Test shutdown hooks handles exception."""
        app = Mock()
        manager = LifecycleManager(app)
        config = DotDict(logging=DotDict(level="info", location=0, micros=False))
        manager.initialize(config)

        hook_manager = Mock()
        hook_manager.has_hooks = Mock(return_value=True)
        hook_manager.trigger_hook = Mock(side_effect=RuntimeError("Hook failed"))
        manager.register_hook_manager(hook_manager)
        manager._lifecycle_logger = Mock()

        # Should not raise
        manager._shutdown_hooks()

        # Should log error
        manager._lifecycle_logger.error.assert_called_once()

    def test_failed_hooks_are_reported_by_the_lifecycle(self):
        """trigger_hook returns each failure in place; the lifecycle logs them."""
        app = Mock()
        manager = LifecycleManager(app)
        config = DotDict(logging=DotDict(level="info", location=0, micros=False))
        manager.initialize(config)

        failure = RuntimeError("hook failed")
        hook_manager = Mock()
        hook_manager.has_hooks = Mock(return_value=True)
        hook_manager.trigger_hook = Mock(return_value=["ok", failure, None])
        manager.register_hook_manager(hook_manager)
        manager._lifecycle_logger = Mock()

        manager._shutdown_hooks()

        manager._lifecycle_logger.error.assert_called_once()
        extra = manager._lifecycle_logger.error.call_args[1]["extra"]
        assert extra == {"event": "shutdown", "exception": failure}

    def test_shutdown_plugins_called(self):
        """Test shutdown calls plugin cleanup."""
        app = Mock()
        manager = LifecycleManager(app)
        config = DotDict(logging=DotDict(level="info", location=0, micros=False))
        manager.initialize(config)

        plugin_manager = Mock()
        plugin_manager.cleanup_all = Mock()
        manager.register_plugin_manager(plugin_manager)

        manager._shutdown_plugins()

        plugin_manager.cleanup_all.assert_called_once_with(app)

    def test_shutdown_plugins_skipped_when_no_manager(self):
        """Test shutdown plugins skipped when no plugin manager registered."""
        app = Mock()
        manager = LifecycleManager(app)
        config = DotDict(logging=DotDict(level="info", location=0, micros=False))
        manager.initialize(config)

        # Should not raise
        manager._shutdown_plugins()

    def test_shutdown_databases_called(self):
        """Test shutdown closes database connections."""
        app = Mock()
        manager = LifecycleManager(app)
        config = DotDict(logging=DotDict(level="info", location=0, micros=False))
        manager.initialize(config)

        db_manager = Mock()
        db_manager.close_all = Mock()
        manager.register_db_manager(db_manager)

        manager._shutdown_databases()

        db_manager.close_all.assert_called_once()

    def test_shutdown_databases_skipped_when_no_manager(self):
        """Test shutdown databases skipped when no db manager registered."""
        app = Mock()
        manager = LifecycleManager(app)
        config = DotDict(logging=DotDict(level="info", location=0, micros=False))
        manager.initialize(config)

        # Should not raise
        manager._shutdown_databases()

    def test_shutdown_log_handlers_flushes_all(self):
        """Test shutdown flushes all registered log handlers."""
        app = Mock()
        manager = LifecycleManager(app)
        config = DotDict(logging=DotDict(level="info", location=0, micros=False))
        manager.initialize(config)

        handler1 = Mock()
        handler1._flush_batch = Mock()
        handler2 = Mock()
        handler2._flush_batch = Mock()

        manager.register_db_handler(handler1)
        manager.register_db_handler(handler2)

        manager._shutdown_log_handlers()

        handler1._flush_batch.assert_called_once()
        handler2._flush_batch.assert_called_once()

    def test_shutdown_log_handlers_continues_on_error(self):
        """Test shutdown log handlers continues if one fails."""
        app = Mock()
        manager = LifecycleManager(app)
        config = DotDict(logging=DotDict(level="info", location=0, micros=False))
        manager.initialize(config)

        handler1 = Mock()
        handler1._flush_batch = Mock(side_effect=RuntimeError("Flush failed"))
        handler2 = Mock()
        handler2._flush_batch = Mock()

        manager.register_db_handler(handler1)
        manager.register_db_handler(handler2)
        manager._lifecycle_logger = Mock()

        # Should not raise
        manager._shutdown_log_handlers()

        # Both handlers should be attempted
        handler1._flush_batch.assert_called_once()
        handler2._flush_batch.assert_called_once()

        # Error should be logged
        manager._lifecycle_logger.error.assert_called()


class TestExecutePhase:
    """Test _execute_phase with timeout protection."""

    def test_execute_phase_calls_function(self):
        """Test _execute_phase calls the phase function."""
        app = Mock()
        manager = LifecycleManager(app)
        config = DotDict(logging=DotDict(level="info", location=0, micros=False))
        manager.initialize(config)

        phase_func = Mock()

        manager._execute_phase("test", phase_func)

        phase_func.assert_called_once()

    def test_execute_phase_handles_exception(self):
        """Test _execute_phase handles exception."""
        app = Mock()
        manager = LifecycleManager(app)
        config = DotDict(logging=DotDict(level="info", location=0, micros=False))
        manager.initialize(config)
        manager._lifecycle_logger = Mock()

        phase_func = Mock(side_effect=RuntimeError("Phase failed"))

        # Should not raise
        manager._execute_phase("test", phase_func)

        # Error should be logged
        manager._lifecycle_logger.error.assert_called()

    def test_execute_phase_runs_under_its_timeout(self):
        """The phase runs inside alarm_timeout with the phase's timeout."""
        manager = LifecycleManager(Mock())
        config = DotDict(
            logging=DotDict(level="info", location=0, micros=False),
            shutdown_timeouts={"test": 0.5},
        )
        manager.initialize(config)
        phase_func = Mock()

        with patch(
            "appinfra.app.core.lifecycle.alarm_timeout", return_value=nullcontext()
        ) as timeout:
            manager._execute_phase("test", phase_func)

        assert timeout.call_args.args[0] == 0.5
        phase_func.assert_called_once()

    def test_execute_phase_uses_configured_timeout(self):
        """Test _execute_phase uses configured timeout from config."""
        app = Mock()
        manager = LifecycleManager(app)
        config = DotDict(
            logging=DotDict(level="info", location=0, micros=False),
            shutdown_timeouts={"test_phase": 15.0},
        )
        manager.initialize(config)

        # Timeout should be updated
        assert manager._shutdown_timeouts["test_phase"] == 15.0


class TestShutdownIntegration:
    """Test full shutdown flow integration."""

    def test_full_shutdown_flow(self):
        """Test complete shutdown orchestration."""
        app = Mock()
        manager = LifecycleManager(app)
        config = DotDict(logging=DotDict(level="info", location=0, micros=False))
        manager.initialize(config)

        # Register all components
        hook_manager = Mock()
        hook_manager.has_hooks = Mock(return_value=True)
        hook_manager.trigger_hook = Mock()
        manager.register_hook_manager(hook_manager)

        plugin_manager = Mock()
        plugin_manager.cleanup_all = Mock()
        manager.register_plugin_manager(plugin_manager)

        db_manager = Mock()
        db_manager.close_all = Mock()
        manager.register_db_manager(db_manager)

        handler = Mock()
        handler._flush_batch = Mock()
        manager.register_db_handler(handler)

        # Execute shutdown
        result = manager.shutdown(0)

        # Verify all phases executed
        hook_manager.trigger_hook.assert_called_once()
        plugin_manager.cleanup_all.assert_called_once_with(app)
        db_manager.close_all.assert_called_once()
        handler._flush_batch.assert_called_once()

        assert result == 0

    def test_shutdown_continues_on_component_failure(self):
        """Test shutdown continues even if components fail."""
        app = Mock()
        manager = LifecycleManager(app)
        config = DotDict(logging=DotDict(level="info", location=0, micros=False))
        manager.initialize(config)

        # Register components that will fail
        hook_manager = Mock()
        hook_manager.has_hooks = Mock(return_value=True)
        hook_manager.trigger_hook = Mock(side_effect=RuntimeError("Hook failed"))
        manager.register_hook_manager(hook_manager)

        plugin_manager = Mock()
        plugin_manager.cleanup_all = Mock(side_effect=RuntimeError("Plugin failed"))
        manager.register_plugin_manager(plugin_manager)

        db_manager = Mock()
        db_manager.close_all = Mock(side_effect=RuntimeError("DB failed"))
        manager.register_db_manager(db_manager)

        handler = Mock()
        handler._flush_batch = Mock(side_effect=RuntimeError("Handler failed"))
        manager.register_db_handler(handler)

        # Should not raise, continues with all phases
        result = manager.shutdown(0)

        # All components should have been attempted
        hook_manager.trigger_hook.assert_called_once()
        plugin_manager.cleanup_all.assert_called_once()
        db_manager.close_all.assert_called_once()
        handler._flush_batch.assert_called_once()

        assert result == 0
