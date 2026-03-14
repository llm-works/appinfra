"""Tests for capture_all_loggers and capture_logger functions."""

import logging

import pytest

from appinfra.log import capture_all_loggers, capture_logger


@pytest.fixture(autouse=True)
def reset_logging():
    """Reset logging state before and after each test."""
    # Store original state
    original_handlers = logging.root.handlers[:]
    original_level = logging.root.level
    original_disabled = logging.root.manager.disable

    yield

    # Restore original state
    logging.root.handlers = original_handlers
    logging.root.setLevel(original_level)
    logging.disable(logging.NOTSET)  # Re-enable logging

    # Clear any loggers we created during tests
    for name in list(logging.Logger.manager.loggerDict.keys()):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.setLevel(logging.NOTSET)


@pytest.mark.unit
class TestCaptureAllLoggers:
    """Tests for capture_all_loggers function."""

    def test_basic_capture(self):
        """Test basic functionality - root logger gets appinfra handler."""
        capture_all_loggers(level="info")

        root = logging.getLogger()
        assert len(root.handlers) == 1
        assert root.level == logging.INFO

    def test_child_logger_propagates(self):
        """Test that child loggers propagate to root after capture."""
        # Create a logger before capture
        child = logging.getLogger("test.child")
        child.addHandler(logging.NullHandler())
        child.propagate = False  # Initially don't propagate

        capture_all_loggers(level="debug")

        # After capture, propagate should be True and handlers cleared
        assert child.propagate is True
        assert len(child.handlers) == 0

    def test_clear_handlers_true(self):
        """Test that clear_handlers=True removes existing handlers."""
        # Create a logger with a handler
        test_logger = logging.getLogger("test.clear")
        test_handler = logging.StreamHandler()
        test_logger.addHandler(test_handler)

        capture_all_loggers(level="info", clear_handlers=True)

        assert len(test_logger.handlers) == 0

    def test_clear_handlers_false(self):
        """Test that clear_handlers=False preserves existing handlers."""
        # Create a logger with a handler
        test_logger = logging.getLogger("test.preserve")
        test_handler = logging.StreamHandler()
        test_logger.addHandler(test_handler)

        capture_all_loggers(level="info", clear_handlers=False)

        # Handler should still be there
        assert test_handler in test_logger.handlers
        # But propagate should still be True
        assert test_logger.propagate is True

    def test_level_filtering(self):
        """Test that level filtering works correctly."""
        capture_all_loggers(level="warning")

        root = logging.getLogger()
        assert root.level == logging.WARNING

    def test_level_debug(self):
        """Test capture with debug level."""
        capture_all_loggers(level="debug")

        root = logging.getLogger()
        assert root.level == logging.DEBUG

    def test_level_false_disables_logging(self):
        """Test that level=False disables all logging."""
        capture_all_loggers(level=False)

        # Logging should be disabled at CRITICAL level
        assert logging.root.manager.disable >= logging.CRITICAL

    def test_simulated_third_party_logger(self):
        """Test that simulated third-party loggers are captured."""
        # Simulate a third-party library logger (like requests, sqlalchemy)
        third_party = logging.getLogger("third_party.module.submodule")
        third_party.addHandler(logging.NullHandler())
        third_party.propagate = False

        capture_all_loggers(level="info")

        # After capture, third-party logger should propagate
        assert third_party.propagate is True
        assert len(third_party.handlers) == 0

    def test_output_uses_appinfra_format(self, capsys):
        """Test that output uses appinfra's formatting."""
        capture_all_loggers(level="info", colors=False)

        # Log a message
        test_logger = logging.getLogger("test.format")
        test_logger.info("Test message")

        # Check output contains expected format elements
        captured = capsys.readouterr()
        assert "Test message" in captured.out
        # appinfra format includes process ID in brackets
        assert "[" in captured.out

    def test_colors_parameter(self):
        """Test that colors parameter is passed to formatter."""
        capture_all_loggers(level="info", colors=True)

        root = logging.getLogger()
        handler = root.handlers[0]
        formatter = handler.formatter

        # Check formatter has colors config
        assert hasattr(formatter, "_config")
        assert formatter._config.colors is True

    def test_location_parameter(self):
        """Test that location parameter is passed to formatter."""
        capture_all_loggers(level="info", location=True)

        root = logging.getLogger()
        handler = root.handlers[0]
        formatter = handler.formatter

        # location=True is converted to 1 (int) by LogConfig.from_params
        assert formatter._config.location == 1

    def test_micros_parameter(self):
        """Test that micros parameter is passed to formatter."""
        capture_all_loggers(level="info", micros=True)

        root = logging.getLogger()
        handler = root.handlers[0]
        formatter = handler.formatter

        assert formatter._config.micros is True

    def test_multiple_calls_replace_handler(self):
        """Test that multiple calls replace the root handler."""
        capture_all_loggers(level="info")
        capture_all_loggers(level="debug")

        root = logging.getLogger()
        # Should still have exactly one handler
        assert len(root.handlers) == 1
        assert root.level == logging.DEBUG

    def test_existing_logger_hierarchy(self):
        """Test that complex logger hierarchies work correctly."""
        # Create a hierarchy of loggers
        parent = logging.getLogger("hierarchy")
        child1 = logging.getLogger("hierarchy.child1")
        child2 = logging.getLogger("hierarchy.child2")
        grandchild = logging.getLogger("hierarchy.child1.grandchild")

        # Add handlers and disable propagation
        for logger in [parent, child1, child2, grandchild]:
            logger.addHandler(logging.NullHandler())
            logger.propagate = False

        capture_all_loggers(level="info")

        # All loggers should now propagate
        for logger in [parent, child1, child2, grandchild]:
            assert logger.propagate is True
            assert len(logger.handlers) == 0


@pytest.mark.unit
class TestCaptureLogger:
    """Tests for capture_logger function."""

    def test_pre_capture_logger(self):
        """Test that pre-captured logger is reused by subsequent getLogger calls."""
        capture_all_loggers(level="info")

        # Pre-capture a logger before "library" uses it
        capture_logger("future_library")

        # Simulate library getting the same logger
        library_logger = logging.getLogger("future_library")

        # Should be the same logger we pre-captured
        assert library_logger.propagate is True
        assert len(library_logger.handlers) == 0

    def test_capture_logger_with_level(self):
        """Test that level override works."""
        capture_all_loggers(level="info")
        capture_logger("noisy_library", level="warning")

        logger = logging.getLogger("noisy_library")
        assert logger.level == logging.WARNING

    def test_capture_logger_without_level(self):
        """Test that level is unchanged when no level specified."""
        capture_all_loggers(level="debug")

        # Pre-set a level on the logger
        logger = logging.getLogger("inherit_library")
        logger.setLevel(logging.ERROR)

        # Capture without level - should not change the level
        capture_logger("inherit_library")

        # Level should remain unchanged
        assert logger.level == logging.ERROR

    def test_capture_logger_clears_handlers(self):
        """Test that capture_logger clears existing handlers."""
        # Create logger with handler first
        logger = logging.getLogger("has_handler")
        logger.addHandler(logging.StreamHandler())
        assert len(logger.handlers) == 1

        capture_logger("has_handler")

        assert len(logger.handlers) == 0

    def test_capture_logger_sets_propagate(self):
        """Test that capture_logger sets propagate=True."""
        logger = logging.getLogger("no_propagate")
        logger.propagate = False

        capture_logger("no_propagate")

        assert logger.propagate is True

    def test_capture_logger_output_uses_appinfra_format(self, capsys):
        """Test that pre-captured logger uses appinfra formatting."""
        capture_all_loggers(level="info", colors=False)
        capture_logger("format_test")

        logger = logging.getLogger("format_test")
        logger.info("Test message from pre-captured logger")

        captured = capsys.readouterr()
        assert "Test message from pre-captured logger" in captured.out
        # appinfra format includes brackets
        assert "[" in captured.out

    def test_capture_logger_child_propagates(self):
        """Test that child loggers of captured parent propagate correctly."""
        capture_all_loggers(level="info", colors=False)
        capture_logger("parent_lib")

        # Child logger should also propagate through parent to root
        child = logging.getLogger("parent_lib.submodule")
        child.info("Child message")

        # Child inherits propagation behavior
