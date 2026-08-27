# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for logging builder interfaces.

Tests key interface features including:
- HandlerConfig abstract base class
- LoggingBuilderInterface abstract methods
- Interface contract enforcement
"""

import logging
from pathlib import Path
from typing import Any

import pytest

from appinfra.log.builder.interface import (
    HandlerConfig,
    LoggingBuilderInterface,
)
from appinfra.log.config import LogConfig
from appinfra.log.logger import Logger

# =============================================================================
# Test Fixtures and Helpers
# =============================================================================


class ConcreteHandlerConfigFixture(HandlerConfig):
    """Concrete HandlerConfig implementation for testing."""

    def create_handler(self, config: LogConfig) -> logging.Handler:
        return logging.StreamHandler()

    def to_dict(self) -> dict:
        return {"type": "test", "level": self.level}


class ConcreteBuilderFixture(LoggingBuilderInterface):
    """Complete concrete implementation of LoggingBuilderInterface for testing."""

    def __init__(self, name: str):
        self.name = name
        self._config = {}
        self.handlers = []

    def with_level(self, level: str | int) -> "ConcreteBuilderFixture":
        self._config["level"] = level
        return self

    def with_location(self, location: bool | int) -> "ConcreteBuilderFixture":
        self._config["location"] = location
        return self

    def with_micros(self, micros: bool = True) -> "ConcreteBuilderFixture":
        self._config["micros"] = micros
        return self

    def with_colors(self, enabled: bool = True) -> "ConcreteBuilderFixture":
        self._config["colors"] = enabled
        return self

    def with_config(self, config: dict[str, Any]) -> "ConcreteBuilderFixture":
        self._config.update(config)
        return self

    def with_separator(self) -> "ConcreteBuilderFixture":
        self._config["separator"] = True
        return self

    def with_extra(self, **kwargs) -> "ConcreteBuilderFixture":
        self._config["extra"] = kwargs
        return self

    def with_handler(self, handler_config: HandlerConfig) -> "ConcreteBuilderFixture":
        self.handlers.append(handler_config)
        return self

    def with_console_handler(
        self, stream=None, level: str | int | None = None
    ) -> "ConcreteBuilderFixture":
        self.handlers.append(("console", stream, level))
        return self

    def with_file_handler(
        self,
        file_path: str | Path,
        level: str | int | None = None,
        **kwargs,
    ) -> "ConcreteBuilderFixture":
        self.handlers.append(("file", file_path, level, kwargs))
        return self

    def with_rotating_file_handler(
        self,
        file_path: str | Path,
        max_bytes: int = 0,
        backup_count: int = 0,
        level: str | int | None = None,
        **kwargs,
    ) -> "ConcreteBuilderFixture":
        self.handlers.append(
            ("rotating", file_path, max_bytes, backup_count, level, kwargs)
        )
        return self

    def with_timed_rotating_file_handler(
        self,
        file_path: str | Path,
        when: str = "h",
        interval: int = 1,
        backup_count: int = 0,
        level: str | int | None = None,
        **kwargs,
    ) -> "ConcreteBuilderFixture":
        self.handlers.append(
            ("timed_rotating", file_path, when, interval, backup_count, level, kwargs)
        )
        return self

    def build(self) -> Logger:
        from unittest.mock import Mock

        mock_logger = Mock(spec=Logger)
        mock_logger.name = self.name
        return mock_logger


# =============================================================================
# Test HandlerConfig Abstract Base Class
# =============================================================================


@pytest.mark.unit
class TestHandlerConfig:
    """Test HandlerConfig abstract base class."""

    def test_cannot_instantiate_abstract_class(self):
        """Test HandlerConfig cannot be instantiated directly."""
        with pytest.raises(TypeError):
            HandlerConfig()

    def test_concrete_implementation_with_level(self):
        """Test concrete HandlerConfig implementation with level."""
        config = ConcreteHandlerConfigFixture(level="info")
        assert config.level == "info"

    def test_concrete_implementation_without_level(self):
        """Test concrete HandlerConfig implementation without level."""
        config = ConcreteHandlerConfigFixture()
        assert config.level is None

    def test_concrete_implementation_numeric_level(self):
        """Test concrete HandlerConfig with numeric level."""
        config = ConcreteHandlerConfigFixture(level=logging.INFO)
        assert config.level == logging.INFO

    def test_create_handler_must_be_implemented(self):
        """Test create_handler must be implemented in subclass."""

        class IncompleteHandlerConfig(HandlerConfig):
            pass

        with pytest.raises(TypeError):
            IncompleteHandlerConfig()


# =============================================================================
# Test LoggingBuilderInterface Abstract Base Class
# =============================================================================


@pytest.mark.unit
class TestLoggingBuilderInterface:
    """Test LoggingBuilderInterface abstract base class."""

    def test_cannot_instantiate_abstract_class(self):
        """Test LoggingBuilderInterface cannot be instantiated directly."""
        with pytest.raises(TypeError):
            LoggingBuilderInterface()

    def test_must_implement_all_abstract_methods(self):
        """Test all abstract methods must be implemented."""

        class IncompleteBuilder(LoggingBuilderInterface):
            """Incomplete implementation missing abstract methods."""

            pass

        with pytest.raises(TypeError):
            IncompleteBuilder()

    def test_concrete_implementation(self):
        """Test complete concrete implementation of interface."""
        # Use the module-level ConcreteBuilderFixture
        builder = ConcreteBuilderFixture("test")
        assert builder.name == "test"
        assert isinstance(builder, LoggingBuilderInterface)


# =============================================================================
# Test Method Chaining
# =============================================================================


@pytest.mark.unit
class TestMethodChaining:
    """Test method chaining behavior of interface."""

    def test_method_chaining(self):
        """Test method chaining works with complete implementation."""
        # Test chaining using the shared ConcreteBuilderFixture
        builder = (
            ConcreteBuilderFixture("test")
            .with_level("info")
            .with_location(True)
            .with_micros(True)
        )

        assert builder._config["level"] == "info"
        assert builder._config["location"] is True
        assert builder._config["micros"] is True


# =============================================================================
# Test Interface Contracts
# =============================================================================


@pytest.mark.unit
class TestInterfaceContracts:
    """Test interface contract enforcement."""

    def test_with_level_return_type(self):
        """Test with_level returns builder for chaining."""
        builder = ConcreteBuilderFixture("test")
        result = builder.with_level("info")
        assert result is builder

    def test_build_returns_logger(self):
        """Test build returns Logger instance."""
        builder = ConcreteBuilderFixture("test")
        logger = builder.build()
        # Logger is mocked but should have the spec
        assert hasattr(logger, "info")


# =============================================================================
# Test Abstract Method Coverage
# =============================================================================


@pytest.mark.unit
class TestAbstractMethodCoverage:
    """Test individual abstract methods for full coverage."""

    def test_abstract_create_handler_not_implemented(self):
        """Test HandlerConfig.create_handler is abstract."""

        class PartialHandlerConfig(HandlerConfig):
            pass

        with pytest.raises(TypeError, match="abstract"):
            PartialHandlerConfig()

    def test_abstract_with_level_not_implemented(self):
        """Test with_level is abstract."""

        class PartialBuilder(LoggingBuilderInterface):
            def with_location(self, location):
                return self

            def with_micros(self, micros=True):
                return self

            def with_colors(self, enabled=True):
                return self

            def with_config(self, config):
                return self

            def with_separator(self):
                return self

            def with_extra(self, **kwargs):
                return self

            def with_handler(self, handler_config):
                return self

            def with_console_handler(self, stream=None, level=None):
                return self

            def with_file_handler(self, file_path, level=None, **kwargs):
                return self

            def with_rotating_file_handler(
                self, file_path, max_bytes=0, backup_count=0, level=None, **kwargs
            ):
                return self

            def with_timed_rotating_file_handler(
                self,
                file_path,
                when="h",
                interval=1,
                backup_count=0,
                level=None,
                **kwargs,
            ):
                return self

            def build(self):
                return None

        with pytest.raises(TypeError, match="abstract"):
            PartialBuilder()

    def test_abstract_with_location_not_implemented(self):
        """Test with_location is abstract."""

        class PartialBuilder(LoggingBuilderInterface):
            def with_level(self, level):
                return self

            def with_micros(self, micros=True):
                return self

            def with_colors(self, enabled=True):
                return self

            def with_config(self, config):
                return self

            def with_separator(self):
                return self

            def with_extra(self, **kwargs):
                return self

            def with_handler(self, handler_config):
                return self

            def with_console_handler(self, stream=None, level=None):
                return self

            def with_file_handler(self, file_path, level=None, **kwargs):
                return self

            def with_rotating_file_handler(
                self, file_path, max_bytes=0, backup_count=0, level=None, **kwargs
            ):
                return self

            def with_timed_rotating_file_handler(
                self,
                file_path,
                when="h",
                interval=1,
                backup_count=0,
                level=None,
                **kwargs,
            ):
                return self

            def build(self):
                return None

        with pytest.raises(TypeError, match="abstract"):
            PartialBuilder()


# =============================================================================
# Test Integration with Real Builder
# =============================================================================


@pytest.mark.integration
class TestInterfaceIntegration:
    """Test interface integration with real builder implementations."""

    def test_logging_builder_implements_interface(self):
        """Test LoggingBuilder implements LoggingBuilderInterface."""
        from appinfra.log.builder.builder import LoggingBuilder

        # LoggingBuilder should be an instance of LoggingBuilderInterface
        builder = LoggingBuilder("test")
        assert isinstance(builder, LoggingBuilderInterface)

    def test_console_builder_implements_interface(self):
        """Test ConsoleLoggingBuilder implements LoggingBuilderInterface."""
        from appinfra.log.builder.console import ConsoleLoggingBuilder

        builder = ConsoleLoggingBuilder("test")
        assert isinstance(builder, LoggingBuilderInterface)

    def test_file_builder_implements_interface(self):
        """Test FileLoggingBuilder implements LoggingBuilderInterface."""
        from appinfra.log.builder.file import FileLoggingBuilder

        builder = FileLoggingBuilder("test", "/tmp/test.log")
        assert isinstance(builder, LoggingBuilderInterface)
