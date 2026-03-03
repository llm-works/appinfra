"""
Tests for infra exception hierarchy.

Tests key exception features including:
- Base InfraError with context
- All specific exception classes
- Exception inheritance
- String representations
"""

import pytest

from appinfra.errors import (
    ConfigError,
    DatabaseError,
    DependencyError,
    InfraError,
    LoggingError,
    ObservabilityError,
    ServerError,
    ToolError,
    ValidationError,
)

# =============================================================================
# Test InfraError Base Class
# =============================================================================


@pytest.mark.unit
class TestInfraError:
    """Test InfraError base class."""

    def test_infra_error_with_message(self):
        """Test InfraError with simple message."""
        error = InfraError("Test error")
        assert str(error) == "Test error"
        assert error.message == "Test error"

    def test_infra_error_with_context(self):
        """Test InfraError with context."""
        error = InfraError("Test error", key1="value1", key2="value2")
        assert error.message == "Test error"
        assert error.context == {"key1": "value1", "key2": "value2"}

    def test_infra_error_str_with_context(self):
        """Test InfraError string representation includes context."""
        error = InfraError("Test error", user="john", code=123)
        error_str = str(error)
        assert "Test error" in error_str
        assert "user=john" in error_str
        assert "code=123" in error_str

    def test_infra_error_str_without_context(self):
        """Test InfraError string representation without context."""
        error = InfraError("Test error")
        assert str(error) == "Test error"

    def test_infra_error_can_be_raised(self):
        """Test InfraError can be raised and caught."""
        with pytest.raises(InfraError) as exc_info:
            raise InfraError("Test error")
        assert str(exc_info.value) == "Test error"

    def test_infra_error_with_empty_context(self):
        """Test InfraError with empty context dict."""
        error = InfraError("Test error")
        assert error.context == {}


# =============================================================================
# Test ConfigError
# =============================================================================


@pytest.mark.unit
class TestConfigError:
    """Test ConfigError class."""

    def test_config_error_inherits_from_infra_error(self):
        """Test ConfigError inherits from InfraError."""
        error = ConfigError("Config error")
        assert isinstance(error, InfraError)
        assert isinstance(error, ConfigError)

    def test_config_error_with_message(self):
        """Test ConfigError with message."""
        error = ConfigError("Invalid configuration")
        assert str(error) == "Invalid configuration"

    def test_config_error_with_context(self):
        """Test ConfigError with context."""
        error = ConfigError("Missing value", key="database.host")
        assert "Missing value" in str(error)
        assert "key=database.host" in str(error)

    def test_config_error_can_be_raised(self):
        """Test ConfigError can be raised and caught."""
        with pytest.raises(ConfigError):
            raise ConfigError("Config error")

    def test_config_error_can_be_caught_as_infra_error(self):
        """Test ConfigError can be caught as InfraError."""
        with pytest.raises(InfraError):
            raise ConfigError("Config error")


# =============================================================================
# Test DatabaseError
# =============================================================================


@pytest.mark.unit
class TestDatabaseError:
    """Test DatabaseError class."""

    def test_database_error_inherits_from_infra_error(self):
        """Test DatabaseError inherits from InfraError."""
        error = DatabaseError("DB error")
        assert isinstance(error, InfraError)
        assert isinstance(error, DatabaseError)

    def test_database_error_with_message(self):
        """Test DatabaseError with message."""
        error = DatabaseError("Connection failed")
        assert str(error) == "Connection failed"

    def test_database_error_with_context(self):
        """Test DatabaseError with context."""
        error = DatabaseError("Query failed", table="users", query="SELECT *")
        assert "Query failed" in str(error)
        assert "table=users" in str(error)


# =============================================================================
# Test LoggingError
# =============================================================================


@pytest.mark.unit
class TestLoggingError:
    """Test LoggingError class."""

    def test_logging_error_inherits_from_infra_error(self):
        """Test LoggingError inherits from InfraError."""
        error = LoggingError("Log error")
        assert isinstance(error, InfraError)
        assert isinstance(error, LoggingError)

    def test_logging_error_with_message(self):
        """Test LoggingError with message."""
        error = LoggingError("Invalid log level")
        assert str(error) == "Invalid log level"

    def test_logging_error_with_context(self):
        """Test LoggingError with context."""
        error = LoggingError("Handler error", handler="file", path="/var/log")
        assert "Handler error" in str(error)
        assert "handler=file" in str(error)


# =============================================================================
# Test ValidationError
# =============================================================================


@pytest.mark.unit
class TestValidationError:
    """Test ValidationError class."""

    def test_validation_error_inherits_from_infra_error(self):
        """Test ValidationError inherits from InfraError."""
        error = ValidationError("Validation failed")
        assert isinstance(error, InfraError)
        assert isinstance(error, ValidationError)

    def test_validation_error_with_message(self):
        """Test ValidationError with message."""
        error = ValidationError("Invalid type")
        assert str(error) == "Invalid type"

    def test_validation_error_with_context(self):
        """Test ValidationError with context."""
        error = ValidationError("Missing field", field="email", required=True)
        assert "Missing field" in str(error)
        assert "field=email" in str(error)


# =============================================================================
# Test ToolError
# =============================================================================


@pytest.mark.unit
class TestToolError:
    """Test ToolError class."""

    def test_tool_error_inherits_from_infra_error(self):
        """Test ToolError inherits from InfraError."""
        error = ToolError("Tool error")
        assert isinstance(error, InfraError)
        assert isinstance(error, ToolError)

    def test_tool_error_with_message(self):
        """Test ToolError with message."""
        error = ToolError("Tool not found")
        assert str(error) == "Tool not found"

    def test_tool_error_with_context(self):
        """Test ToolError with context."""
        error = ToolError("Execution failed", tool="mytool", code=1)
        assert "Execution failed" in str(error)
        assert "tool=mytool" in str(error)


# =============================================================================
# Test ServerError
# =============================================================================


@pytest.mark.unit
class TestServerError:
    """Test ServerError class."""

    def test_server_error_inherits_from_infra_error(self):
        """Test ServerError inherits from InfraError."""
        error = ServerError("Server error")
        assert isinstance(error, InfraError)
        assert isinstance(error, ServerError)

    def test_server_error_with_message(self):
        """Test ServerError with message."""
        error = ServerError("Port already in use")
        assert str(error) == "Port already in use"

    def test_server_error_with_context(self):
        """Test ServerError with context."""
        error = ServerError("Startup failed", port=8080, host="0.0.0.0")
        assert "Startup failed" in str(error)
        assert "port=8080" in str(error)


# =============================================================================
# Test ObservabilityError
# =============================================================================


@pytest.mark.unit
class TestObservabilityError:
    """Test ObservabilityError class."""

    def test_observability_error_inherits_from_infra_error(self):
        """Test ObservabilityError inherits from InfraError."""
        error = ObservabilityError("Hook error")
        assert isinstance(error, InfraError)
        assert isinstance(error, ObservabilityError)

    def test_observability_error_with_message(self):
        """Test ObservabilityError with message."""
        error = ObservabilityError("Hook registration failed")
        assert str(error) == "Hook registration failed"

    def test_observability_error_with_context(self):
        """Test ObservabilityError with context."""
        error = ObservabilityError("Callback error", hook="on_start", callback="my_fn")
        assert "Callback error" in str(error)
        assert "hook=on_start" in str(error)


# =============================================================================
# Test Exception Hierarchy
# =============================================================================


@pytest.mark.integration
class TestExceptionHierarchy:
    """Test exception hierarchy and catching."""

    def test_catch_specific_exception(self):
        """Test catching specific exception type."""
        with pytest.raises(ConfigError):
            raise ConfigError("Config error")

    def test_catch_all_infra_errors(self):
        """Test catching all InfraError types."""
        exception_types = [
            ConfigError,
            DatabaseError,
            LoggingError,
            ValidationError,
            ToolError,
            ServerError,
            ObservabilityError,
            DependencyError,
        ]

        for exc_type in exception_types:
            with pytest.raises(InfraError):
                if exc_type is DependencyError:
                    raise exc_type(package="pkg", extra="extra", feature="Feature")
                else:
                    raise exc_type("Test error")

    def test_exception_context_preserved_when_caught(self):
        """Test exception context is preserved when caught."""
        try:
            raise ConfigError("Test error", key="value", code=123)
        except InfraError as e:
            assert e.context == {"key": "value", "code": 123}
            assert "key=value" in str(e)
            assert "code=123" in str(e)


# =============================================================================
# Test DependencyError
# =============================================================================


@pytest.mark.unit
class TestDependencyError:
    """Test DependencyError class."""

    def test_dependency_error_inherits_from_infra_error(self):
        """Test DependencyError inherits from InfraError."""
        error = DependencyError(
            package="sqlalchemy", extra="sql", feature="Database support"
        )
        assert isinstance(error, InfraError)
        assert isinstance(error, DependencyError)

    def test_dependency_error_message_format(self):
        """Test DependencyError message format."""
        error = DependencyError(
            package="sqlalchemy", extra="sql", feature="Database support"
        )
        error_str = str(error)
        assert "Database support" in error_str
        assert "sqlalchemy" in error_str
        assert "pip install appinfra[sql]" in error_str

    def test_dependency_error_context(self):
        """Test DependencyError context contains package and extra."""
        error = DependencyError(
            package="pydantic", extra="validation", feature="Schema validation"
        )
        assert error.context["package"] == "pydantic"
        assert error.context["extra"] == "validation"
