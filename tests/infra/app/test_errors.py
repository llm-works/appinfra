"""
Tests for appinfra.app error classes.

Tests all custom exception types and their messages.
"""

from unittest.mock import Mock

import pytest

from appinfra.app.errors import (
    AppError,
    AttrNotFoundError,
    CommandError,
    ConfigError,
    DupToolError,
    InfraAppError,
    LifecycleError,
    MissingLoggerError,
    MissingParentError,
    MissingRunFuncError,
    NoSubToolsError,
    ToolRegistrationError,
    UndefGroupError,
    UndefNameError,
)

# =============================================================================
# Test Base Exception
# =============================================================================


@pytest.mark.unit
class TestInfraAppError:
    """Test base InfraAppError class."""

    def test_basic_exception(self):
        """Test InfraAppError can be raised."""
        with pytest.raises(InfraAppError):
            raise InfraAppError("Test error")

    def test_inheritance(self):
        """Test InfraAppError inherits from Exception."""
        assert issubclass(InfraAppError, Exception)


# =============================================================================
# Test UndefNameError
# =============================================================================


@pytest.mark.unit
class TestUndefNameError:
    """Test UndefNameError class."""

    def test_with_class(self):
        """Test UndefNameError with class argument (lines 19-22)."""

        class MyToolClass:
            pass

        error = UndefNameError(cls=MyToolClass)
        assert "MyToolClass" in str(error)
        assert "must define a name property" in str(error)
        assert error.cls == MyToolClass

    def test_with_tool(self):
        """Test UndefNameError with tool argument (lines 23-24)."""
        error = UndefNameError(tool="my_tool")
        assert "my_tool" in str(error)
        assert "must have a name" in str(error)
        assert error.tool == "my_tool"

    def test_without_arguments(self):
        """Test UndefNameError without arguments (lines 25-26)."""
        error = UndefNameError()
        assert "Tool name is not defined" in str(error)


# =============================================================================
# Test UndefGroupError
# =============================================================================


@pytest.mark.unit
class TestUndefGroupError:
    """Test UndefGroupError class."""

    def test_with_tool(self):
        """Test UndefGroupError (lines 33-34)."""
        tool = Mock()
        tool.name = "my_tool"

        error = UndefGroupError(tool)

        assert "my_tool" in str(error)
        assert "requires a group" in str(error)
        assert error.tool == tool


# =============================================================================
# Test NoSubToolsError
# =============================================================================


@pytest.mark.unit
class TestNoSubToolsError:
    """Test NoSubToolsError class."""

    def test_message(self):
        """Test NoSubToolsError (line 41)."""
        error = NoSubToolsError()
        assert "No sub-tools are available" in str(error)


# =============================================================================
# Test DupToolError
# =============================================================================


@pytest.mark.unit
class TestDupToolError:
    """Test DupToolError class."""

    def test_with_tool(self):
        """Test DupToolError (lines 48-49)."""
        tool = Mock()
        tool.name = "duplicate_tool"

        error = DupToolError(tool)

        assert "duplicate_tool" in str(error)
        assert "already registered" in str(error)
        assert error.tool == tool


# =============================================================================
# Test MissingRunFuncError
# =============================================================================


@pytest.mark.unit
class TestMissingRunFuncError:
    """Test MissingRunFuncError class."""

    def test_with_cmd(self):
        """Test MissingRunFuncError (lines 56-57)."""
        error = MissingRunFuncError("my_command")

        assert "my_command" in str(error)
        assert "requires a run_func parameter" in str(error)
        assert error.cmd == "my_command"


# =============================================================================
# Test AttrNotFoundError
# =============================================================================


@pytest.mark.unit
class TestAttrNotFoundError:
    """Test AttrNotFoundError class."""

    def test_with_name(self):
        """Test AttrNotFoundError (lines 64-65)."""
        error = AttrNotFoundError("missing_attr")

        assert "missing_attr" in str(error)
        assert "not found in hierarchy" in str(error)
        assert error.name == "missing_attr"


# =============================================================================
# Test ToolRegistrationError
# =============================================================================


@pytest.mark.unit
class TestToolRegistrationError:
    """Test ToolRegistrationError class."""

    def test_with_tool_and_reason(self):
        """Test ToolRegistrationError (lines 72-74)."""
        error = ToolRegistrationError("my_tool", "invalid config")

        assert "my_tool" in str(error)
        assert "invalid config" in str(error)
        assert "Failed to register tool" in str(error)
        assert error.tool_name == "my_tool"
        assert error.reason == "invalid config"


# =============================================================================
# Test ConfigError
# =============================================================================


@pytest.mark.unit
class TestConfigError:
    """Test ConfigError class."""

    def test_with_message(self):
        """Test ConfigError (line 81)."""
        error = ConfigError("invalid setting")

        assert "Configuration error" in str(error)
        assert "invalid setting" in str(error)


# =============================================================================
# Test LifecycleError
# =============================================================================


@pytest.mark.unit
class TestLifecycleError:
    """Test LifecycleError class."""

    def test_with_message(self):
        """Test LifecycleError (line 88)."""
        error = LifecycleError("startup failed")

        assert "Lifecycle error" in str(error)
        assert "startup failed" in str(error)


# =============================================================================
# Test AppError
# =============================================================================


@pytest.mark.unit
class TestAppError:
    """Test AppError class."""

    def test_with_message(self):
        """Test AppError (line 95)."""
        error = AppError("app crashed")

        assert "Application error" in str(error)
        assert "app crashed" in str(error)


# =============================================================================
# Test CommandError
# =============================================================================


@pytest.mark.unit
class TestCommandError:
    """Test CommandError class."""

    def test_with_message(self):
        """Test CommandError (line 102)."""
        error = CommandError("invalid command")

        assert "Command error" in str(error)
        assert "invalid command" in str(error)


# =============================================================================
# Test MissingLoggerError
# =============================================================================


@pytest.mark.unit
class TestMissingLoggerError:
    """Test MissingLoggerError class."""

    def test_with_message(self):
        """Test MissingLoggerError (line 109)."""
        error = MissingLoggerError("logger not set")

        assert "Missing logger error" in str(error)
        assert "logger not set" in str(error)


# =============================================================================
# Test MissingParentError
# =============================================================================


@pytest.mark.unit
class TestMissingParentError:
    """Test MissingParentError class."""

    def test_with_tool_and_property(self):
        """Test MissingParentError (lines 116-118)."""
        error = MissingParentError("my_tool", "config")

        assert "my_tool" in str(error)
        assert "config" in str(error)
        assert "cannot access" in str(error)
        assert "without a parent" in str(error)
        assert error.tool_name == "my_tool"
        assert error.property_name == "config"
