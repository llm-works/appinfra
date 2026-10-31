# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for app/core/lifecycle.py.

Tests key functionality including:
- LifecycleManager initialization
- Finalization
- Component registration
"""

from unittest.mock import Mock

import pytest

from appinfra.app.core.lifecycle import LifecycleManager
from appinfra.dot_dict import DotDict

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
