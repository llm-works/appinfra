# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for app/core/lifecycle.py.

Tests key functionality including:
- LifecycleManager initialization
- Tool setup and execution
- Finalization
"""

import logging
import signal
import time as std_time
from unittest.mock import Mock

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


class _FailingCloseHandler(logging.Handler):
    """A handler whose close() fails, as a file handler's final flush can."""

    def emit(self, record: logging.LogRecord) -> None:
        pass

    def close(self) -> None:
        super().close()
        raise OSError("disk full")


# =============================================================================
# Test LifecycleManager Initialization
# =============================================================================


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
# Test Setup Tool
# =============================================================================


class TestSetupTool:
    """Test setup_tool method (lines 61-84)."""

    def test_setup_tool_not_initialized(self):
        """Test setup_tool raises when not initialized (line 63-64)."""
        app = Mock()
        manager = LifecycleManager(app)
        tool = create_test_tool("test_tool")

        with pytest.raises(LifecycleError, match="not initialized"):
            manager.setup_tool(tool)

    @pytest.mark.integration
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

    @pytest.mark.integration
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

    @pytest.mark.integration
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


class TestExecuteTool:
    """Test execute_tool method (lines 86-106)."""

    def test_execute_tool_not_initialized(self):
        """Test execute_tool raises when not initialized (lines 88-89)."""
        app = Mock()
        manager = LifecycleManager(app)
        tool = create_test_tool("test_tool")

        with pytest.raises(LifecycleError, match="not initialized"):
            manager.execute_tool(tool)

    @pytest.mark.integration
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

    @pytest.mark.integration
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

    @pytest.mark.integration
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


class TestFinalize:
    """Test finalize method (lines 108-115)."""

    def test_finalize_without_logger(self):
        """Test finalize returns early when no logger (lines 110-111)."""
        app = Mock()
        manager = LifecycleManager(app)

        # Should not raise
        manager.finalize(0)

    @pytest.mark.integration
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

    @pytest.mark.integration
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
# Test Component Registration
# =============================================================================


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


class TestShutdown:
    """Test shutdown method."""

    def test_shutdown_without_logger(self):
        """Test shutdown returns early when no logger."""
        app = Mock()
        manager = LifecycleManager(app)

        # Should not raise
        result = manager.shutdown(0)
        assert result == 0

    @pytest.mark.integration
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

    @pytest.mark.integration
    def test_shutdown_calls_finalize(self):
        """Test shutdown calls finalize at the end."""
        app = Mock()
        manager = LifecycleManager(app)
        config = DotDict(logging=DotDict(level="info", location=0, micros=False))
        manager.initialize(config)
        manager.finalize = Mock()

        manager.shutdown(42)

        manager.finalize.assert_called_once_with(42)

    @pytest.mark.integration
    def test_shutdown_returns_return_code(self):
        """Test shutdown returns the provided return code."""
        app = Mock()
        manager = LifecycleManager(app)
        config = DotDict(logging=DotDict(level="info", location=0, micros=False))
        manager.initialize(config)

        result = manager.shutdown(42)

        assert result == 42

    @pytest.mark.integration
    def test_shutdown_releases_the_root_logger(self):
        """After shutdown the root name is free, and a second shutdown does nothing."""
        config = DotDict(logging=DotDict(level="info", location=0, micros=False))
        manager = LifecycleManager(Mock())
        manager.initialize(config)

        manager.shutdown(0)
        assert "/" not in logging.root.manager.loggerDict
        assert manager.shutdown(3) == 3  # no second teardown

        next_manager = LifecycleManager(Mock())
        next_manager.initialize(config)  # creates "/" again without a conflict
        next_manager.shutdown(0)

    @pytest.mark.integration
    def test_shutdown_restores_the_signal_handlers(self):
        """The handlers initialize() installed do not outlive the lifecycle."""
        before = signal.getsignal(signal.SIGTERM)
        config = DotDict(logging=DotDict(level="info", location=0, micros=False))
        manager = LifecycleManager(Mock())
        try:
            manager.initialize(config)
            assert signal.getsignal(signal.SIGTERM) != before

            manager.shutdown(0)

            assert signal.getsignal(signal.SIGTERM) == before
        finally:
            signal.signal(signal.SIGTERM, before)

    @pytest.mark.integration
    def test_shutdown_raises_a_handler_close_error_once(self):
        """The root logger is still released, and a second shutdown does nothing."""
        config = DotDict(logging=DotDict(level="info", location=0, micros=False))
        manager = LifecycleManager(Mock())
        manager.initialize(config)
        manager._logger.addHandler(_FailingCloseHandler())

        with pytest.raises(OSError, match="disk full"):
            manager.shutdown(0)

        assert "/" not in logging.root.manager.loggerDict
        assert manager.shutdown(3) == 3
