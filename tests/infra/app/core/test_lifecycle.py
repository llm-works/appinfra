# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for app/core/lifecycle.py.

Tests key functionality including:
- LifecycleManager initialization
- Tool setup and execution
- Finalization
"""

import os
import time as std_time
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
# Test LifecycleManager Initialization
# =============================================================================


@pytest.mark.unit
class TestLifecycleManagerInit:
    """Test LifecycleManager initialization."""

    def test_basic_initialization(self):
        """Test basic initialization."""
        app = Mock()
        manager = LifecycleManager(app)

        assert manager.application is app
        assert manager._logger is None
        assert manager._start_time is None

    def test_logger_property(self):
        """Test logger property returns _logger."""
        app = Mock()
        manager = LifecycleManager(app)
        mock_logger = Mock()
        manager._logger = mock_logger

        assert manager.logger is mock_logger


# =============================================================================
# Test Initialize
# =============================================================================


@pytest.mark.unit
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

    def test_initialize_uses_test_logging_level(self):
        """Test initialize uses INFRA_TEST_LOGGING_LEVEL env var (line 31)."""
        app = Mock()
        manager = LifecycleManager(app)
        config = DotDict(logging=DotDict(level="debug", location=0, micros=False))

        with patch.dict(os.environ, {"INFRA_TEST_LOGGING_LEVEL": "warning"}):
            manager.initialize(config)

        # Logger should be created (actual level is checked internally)
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
# Test Setup Tool
# =============================================================================


@pytest.mark.unit
class TestSetupTool:
    """Test setup_tool method (lines 61-84)."""

    def test_setup_tool_not_initialized(self):
        """Test setup_tool raises when not initialized (line 63-64)."""
        app = Mock()
        manager = LifecycleManager(app)
        tool = create_test_tool("test_tool")

        with pytest.raises(LifecycleError, match="not initialized"):
            manager.setup_tool(tool)

    def test_setup_tool_calls_tool_setup(self):
        """Test setup_tool calls tool.setup (lines 66-74)."""
        app = Mock()
        manager = LifecycleManager(app)
        config = DotDict(logging=DotDict(level="info", location=0, micros=False))
        manager.initialize(config)

        tool = create_test_tool("test_tool")
        tool.setup = Mock()

        manager.setup_tool(tool, start=std_time.monotonic())

        tool.setup.assert_called_once()

    def test_setup_tool_passes_kwargs(self):
        """Test setup_tool passes kwargs to tool.setup."""
        app = Mock()
        manager = LifecycleManager(app)
        config = DotDict(logging=DotDict(level="info", location=0, micros=False))
        manager.initialize(config)

        tool = create_test_tool("test_tool")
        tool.setup = Mock()

        manager.setup_tool(tool, start=123.45, extra="value")

        tool.setup.assert_called_once_with(start=123.45, extra="value")

    def test_setup_tool_handles_exception(self):
        """Test setup_tool handles exception (lines 75-84)."""
        app = Mock()
        manager = LifecycleManager(app)
        config = DotDict(logging=DotDict(level="info", location=0, micros=False))
        manager.initialize(config)

        tool = create_test_tool("test_tool")
        tool.setup = Mock(side_effect=ValueError("setup failed"))

        with pytest.raises(LifecycleError, match="Failed to setup tool"):
            manager.setup_tool(tool)


# =============================================================================
# Test Execute Tool
# =============================================================================


@pytest.mark.unit
class TestExecuteTool:
    """Test execute_tool method (lines 86-106)."""

    def test_execute_tool_not_initialized(self):
        """Test execute_tool raises when not initialized (lines 88-89)."""
        app = Mock()
        manager = LifecycleManager(app)
        tool = create_test_tool("test_tool")

        with pytest.raises(LifecycleError, match="not initialized"):
            manager.execute_tool(tool)

    def test_execute_tool_calls_tool_run(self):
        """Test execute_tool calls tool.run (lines 91-100)."""
        app = Mock()
        manager = LifecycleManager(app)
        config = DotDict(logging=DotDict(level="info", location=0, micros=False))
        manager.initialize(config)

        tool = create_test_tool("test_tool")
        tool.run = Mock(return_value=42)

        result = manager.execute_tool(tool)

        tool.run.assert_called_once()
        assert result == 42

    def test_execute_tool_passes_args(self):
        """Test execute_tool passes args to tool (lines 98-99)."""
        import argparse

        app = Mock()
        manager = LifecycleManager(app)
        config = DotDict(logging=DotDict(level="info", location=0, micros=False))
        manager.initialize(config)

        tool = create_test_tool("test_tool")
        tool.run = Mock(return_value=0)
        mock_args = argparse.Namespace(verbose=True)

        manager.execute_tool(tool, args=mock_args)

        assert tool._parsed_args is mock_args

    def test_execute_tool_handles_exception(self):
        """Test execute_tool handles exception (lines 101-106)."""
        app = Mock()
        manager = LifecycleManager(app)
        config = DotDict(logging=DotDict(level="info", location=0, micros=False))
        manager.initialize(config)

        tool = create_test_tool("test_tool")
        tool.run = Mock(side_effect=RuntimeError("execution failed"))

        with pytest.raises(LifecycleError, match="execution failed"):
            manager.execute_tool(tool)


# =============================================================================
# Test Finalize
# =============================================================================


@pytest.mark.unit
class TestFinalize:
    """Test finalize method (lines 108-115)."""

    def test_finalize_without_logger(self):
        """Test finalize returns early when no logger (lines 110-111)."""
        app = Mock()
        manager = LifecycleManager(app)

        # Should not raise
        manager.finalize(0)

    def test_finalize_logs_completion(self):
        """Test finalize completes without error.

        Note: The 'done' message logging was moved to ShutdownManager
        to ensure it's always the absolute last log message.
        """
        app = Mock()
        manager = LifecycleManager(app)
        config = DotDict(logging=DotDict(level="info", location=0, micros=False))
        manager.initialize(config)

        # Should complete without error (finalize is now empty)
        manager.finalize(0)

    def test_finalize_with_error_code(self):
        """Test finalize with non-zero return code.

        Note: finalize() no longer logs. The return code is now logged
        by ShutdownManager as part of the final 'done' message.
        """
        app = Mock()
        manager = LifecycleManager(app)
        config = DotDict(logging=DotDict(level="info", location=0, micros=False))
        manager.initialize(config)

        # Should complete without error regardless of return code
        manager.finalize(1)


# =============================================================================
# Integration Tests
# =============================================================================


@pytest.mark.integration
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
# Test Component Registration
# =============================================================================


@pytest.mark.unit
class TestComponentRegistration:
    """Test component registration methods."""

    def test_register_hook_manager(self):
        """Test register_hook_manager stores hook manager."""
        app = Mock()
        manager = LifecycleManager(app)
        hook_manager = Mock()

        manager.register_hook_manager(hook_manager)

        assert manager._hook_manager is hook_manager

    def test_register_plugin_manager(self):
        """Test register_plugin_manager stores plugin manager."""
        app = Mock()
        manager = LifecycleManager(app)
        plugin_manager = Mock()

        manager.register_plugin_manager(plugin_manager)

        assert manager._plugin_manager is plugin_manager

    def test_register_db_manager(self):
        """Test register_db_manager stores database manager."""
        app = Mock()
        manager = LifecycleManager(app)
        db_manager = Mock()

        manager.register_db_manager(db_manager)

        assert manager._db_manager is db_manager

    def test_register_db_handler(self):
        """Test register_db_handler adds handler to list."""
        app = Mock()
        manager = LifecycleManager(app)
        handler1 = Mock()
        handler2 = Mock()

        manager.register_db_handler(handler1)
        manager.register_db_handler(handler2)

        assert handler1 in manager._db_handlers
        assert handler2 in manager._db_handlers

    def test_register_db_handler_no_duplicates(self):
        """Test register_db_handler doesn't add duplicates."""
        app = Mock()
        manager = LifecycleManager(app)
        handler = Mock()

        manager.register_db_handler(handler)
        manager.register_db_handler(handler)  # Try to add again

        assert manager._db_handlers.count(handler) == 1


# =============================================================================
# Test Shutdown Orchestration
# =============================================================================


@pytest.mark.unit
class TestShutdown:
    """Test shutdown method."""

    def test_shutdown_without_logger(self):
        """Test shutdown returns early when no logger."""
        app = Mock()
        manager = LifecycleManager(app)

        # Should not raise
        result = manager.shutdown(0)
        assert result == 0

    def test_shutdown_logs_initiation(self):
        """Test shutdown logs initiation message."""
        app = Mock()
        manager = LifecycleManager(app)
        config = DotDict(logging=DotDict(level="info", location=0, micros=False))
        manager.initialize(config)
        manager._lifecycle_logger = Mock()

        manager.shutdown(0)

        # Check that info was called with shutdown message
        info_calls = [
            call[0][0] for call in manager._lifecycle_logger.debug.call_args_list
        ]
        assert any("shutting down" in str(call) for call in info_calls)

    def test_shutdown_calls_finalize(self):
        """Test shutdown calls finalize at the end."""
        app = Mock()
        manager = LifecycleManager(app)
        config = DotDict(logging=DotDict(level="info", location=0, micros=False))
        manager.initialize(config)
        manager.finalize = Mock()

        manager.shutdown(42)

        manager.finalize.assert_called_once_with(42)

    def test_shutdown_returns_return_code(self):
        """Test shutdown returns the provided return code."""
        app = Mock()
        manager = LifecycleManager(app)
        config = DotDict(logging=DotDict(level="info", location=0, micros=False))
        manager.initialize(config)

        result = manager.shutdown(42)

        assert result == 42


@pytest.mark.unit
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


@pytest.mark.unit
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

    @patch("signal.signal")
    @patch("signal.alarm")
    def test_execute_phase_sets_timeout(self, mock_alarm, mock_signal):
        """Test _execute_phase sets and clears alarm timeout."""
        app = Mock()
        manager = LifecycleManager(app)
        config = DotDict(logging=DotDict(level="info", location=0, micros=False))
        manager.initialize(config)

        phase_func = Mock()

        manager._execute_phase("test", phase_func)

        # Should set alarm before and clear after
        assert mock_alarm.call_count >= 2
        calls = [call[0][0] for call in mock_alarm.call_args_list]
        assert any(c > 0 for c in calls)  # Set to timeout value
        assert 0 in calls  # Cleared

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


@pytest.mark.integration
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
