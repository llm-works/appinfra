# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for logging configuration serialization for multiprocessing."""

import logging
import pickle
import sys

import pytest

from appinfra.log import LogConfig, LoggingBuilder
from appinfra.log.builder.console import ConsoleHandlerConfig
from appinfra.log.builder.file import (
    FileHandlerConfig,
    RotatingFileHandlerConfig,
    TimedRotatingFileHandlerConfig,
)


@pytest.mark.unit
class TestLogConfigSerialization:
    """Test LogConfig.to_dict() and from_dict()."""

    def test_to_dict_basic(self):
        """Test basic serialization."""
        config = LogConfig(
            level=logging.DEBUG,
            location=2,
            micros=True,
            colors=False,
            location_color="\x1b[36m",
        )

        d = config.to_dict()

        assert d["level"] == logging.DEBUG
        assert d["location"] == 2
        assert d["micros"] is True
        assert d["colors"] is False
        assert d["location_color"] == "\x1b[36m"

    def test_from_dict_basic(self):
        """Test basic deserialization."""
        d = {
            "level": logging.WARNING,
            "location": 1,
            "micros": True,
            "colors": True,
            "location_color": None,
        }

        config = LogConfig.from_dict(d)

        assert config.level == logging.WARNING
        assert config.location == 1
        assert config.micros is True
        assert config.colors is True
        assert config.location_color is None

    def test_roundtrip(self):
        """Test to_dict -> from_dict preserves all values."""
        original = LogConfig(
            level=logging.INFO,
            location=3,
            micros=False,
            colors=True,
            location_color="\x1b[32m",
        )

        d = original.to_dict()
        restored = LogConfig.from_dict(d)

        assert restored.level == original.level
        assert restored.location == original.location
        assert restored.micros == original.micros
        assert restored.colors == original.colors
        assert restored.location_color == original.location_color

    def test_to_dict_is_picklable(self):
        """Test serialized config can be pickled."""
        config = LogConfig.from_params("debug", location=1, micros=True)
        d = config.to_dict()

        # Should not raise
        pickled = pickle.dumps(d)
        unpickled = pickle.loads(pickled)

        assert unpickled == d

    def test_from_dict_with_defaults(self):
        """Test from_dict uses defaults for missing keys."""
        d = {"level": logging.DEBUG}  # Minimal config

        config = LogConfig.from_dict(d)

        assert config.level == logging.DEBUG
        assert config.location == 0  # default
        assert config.micros is False  # default
        assert config.colors is True  # default


@pytest.mark.unit
class TestConsoleHandlerConfigSerialization:
    """Test ConsoleHandlerConfig.to_dict()."""

    def test_to_dict_stdout(self):
        """Test serialization with stdout."""
        config = ConsoleHandlerConfig(stream=sys.stdout, level="info", format="text")

        d = config.to_dict()

        assert d["type"] == "console"
        assert d["stream"] == "stdout"
        assert d["level"] == "info"
        assert d["format"] == "text"

    def test_to_dict_stderr(self):
        """Test serialization with stderr."""
        config = ConsoleHandlerConfig(stream=sys.stderr)

        d = config.to_dict()

        assert d["stream"] == "stderr"

    def test_to_dict_json_format(self):
        """Test serialization with JSON format options."""
        config = ConsoleHandlerConfig(
            format="json",
            format_timestamp_format="iso",
            format_pretty_print=True,
        )

        d = config.to_dict()

        assert d["format"] == "json"
        assert d["format_timestamp_format"] == "iso"
        assert d["format_pretty_print"] is True

    def test_to_dict_is_picklable(self):
        """Test serialized config can be pickled."""
        config = ConsoleHandlerConfig(stream=sys.stdout, level="debug")
        d = config.to_dict()

        pickled = pickle.dumps(d)
        unpickled = pickle.loads(pickled)

        assert unpickled == d


@pytest.mark.unit
class TestFileHandlerConfigSerialization:
    """Test FileHandlerConfig.to_dict()."""

    def test_to_dict_basic(self):
        """Test basic file handler serialization."""
        config = FileHandlerConfig(
            filename="/var/log/app.log",
            mode="a",
            level="info",
        )

        d = config.to_dict()

        assert d["type"] == "file"
        assert d["filename"] == "/var/log/app.log"
        assert d["mode"] == "a"
        assert d["level"] == "info"

    def test_to_dict_with_encoding(self):
        """Test serialization with encoding."""
        config = FileHandlerConfig(
            filename="app.log",
            encoding="utf-8",
        )

        d = config.to_dict()

        assert d["encoding"] == "utf-8"


@pytest.mark.unit
class TestRotatingFileHandlerConfigSerialization:
    """Test RotatingFileHandlerConfig.to_dict()."""

    def test_to_dict(self):
        """Test rotating file handler serialization."""
        config = RotatingFileHandlerConfig(
            filename="/var/log/app.log",
            max_bytes=10_000_000,
            backup_count=5,
            level="warning",
        )

        d = config.to_dict()

        assert d["type"] == "rotating_file"
        assert d["filename"] == "/var/log/app.log"
        assert d["max_bytes"] == 10_000_000
        assert d["backup_count"] == 5
        assert d["level"] == "warning"


@pytest.mark.unit
class TestTimedRotatingFileHandlerConfigSerialization:
    """Test TimedRotatingFileHandlerConfig.to_dict()."""

    def test_to_dict(self):
        """Test timed rotating file handler serialization."""
        config = TimedRotatingFileHandlerConfig(
            filename="/var/log/app.log",
            when="midnight",
            interval=1,
            backup_count=7,
            utc=True,
        )

        d = config.to_dict()

        assert d["type"] == "timed_rotating_file"
        assert d["filename"] == "/var/log/app.log"
        assert d["when"] == "midnight"
        assert d["interval"] == 1
        assert d["backup_count"] == 7
        assert d["utc"] is True


@pytest.mark.unit
class TestLoggingBuilderSerialization:
    """Test LoggingBuilder.to_dict() and from_dict()."""

    def test_to_dict_basic(self):
        """Test basic builder serialization."""
        builder = (
            LoggingBuilder("app")
            .with_level("debug")
            .with_location(2)
            .with_micros(True)
            .with_colors(False)
        )

        d = builder.to_dict()

        assert d["name"] == "app"
        assert d["level"] == "debug"
        assert d["location"] == 2
        assert d["micros"] is True
        assert d["colors"] is False

    def test_to_dict_with_handlers(self):
        """Test builder serialization with handlers."""
        builder = (
            LoggingBuilder("app")
            .with_console_handler()
            .with_file_handler("/var/log/app.log")
        )

        d = builder.to_dict()

        assert len(d["handlers"]) == 2
        assert d["handlers"][0]["type"] == "console"
        assert d["handlers"][1]["type"] == "file"

    def test_to_dict_with_extra(self):
        """Test builder serialization with extra fields."""
        builder = LoggingBuilder("app").with_extra(service="api", version="1.0")

        d = builder.to_dict()

        assert d["extra"]["service"] == "api"
        assert d["extra"]["version"] == "1.0"

    def test_from_dict_basic(self):
        """Test basic builder deserialization."""
        d = {
            "name": "restored",
            "level": "warning",
            "location": 1,
            "micros": True,
            "colors": True,
            "handlers": [],
            "extra": {},
        }

        builder = LoggingBuilder.from_dict(d)

        assert builder._name == "restored"
        assert builder._level == "warning"
        assert builder._location == 1
        assert builder._micros is True

    def test_from_dict_with_name_override(self):
        """Test builder deserialization with name override."""
        d = {"name": "original", "level": "info", "handlers": [], "extra": {}}

        builder = LoggingBuilder.from_dict(d, name="subprocess-1")

        assert builder._name == "subprocess-1"

    def test_from_dict_with_console_handler(self):
        """Test deserialization of console handler."""
        d = {
            "name": "app",
            "level": "info",
            "location": 0,
            "micros": False,
            "colors": True,
            "handlers": [{"type": "console", "stream": "stderr", "format": "text"}],
            "extra": {},
        }

        builder = LoggingBuilder.from_dict(d)

        assert len(builder._handlers) == 1
        handler = builder._handlers[0]
        assert isinstance(handler, ConsoleHandlerConfig)
        assert handler.stream is sys.stderr

    def test_from_dict_with_file_handler(self):
        """Test deserialization of file handler."""
        d = {
            "name": "app",
            "level": "info",
            "handlers": [{"type": "file", "filename": "/var/log/app.log", "mode": "a"}],
            "extra": {},
        }

        builder = LoggingBuilder.from_dict(d)

        assert len(builder._handlers) == 1
        handler = builder._handlers[0]
        assert isinstance(handler, FileHandlerConfig)
        assert handler.filename == "/var/log/app.log"

    def test_roundtrip(self):
        """Test to_dict -> from_dict preserves configuration."""
        original = (
            LoggingBuilder("app")
            .with_level("debug")
            .with_location(2)
            .with_micros(True)
            .with_console_handler()
            .with_extra(env="test")
        )

        d = original.to_dict()
        restored = LoggingBuilder.from_dict(d)

        assert restored._name == original._name
        assert restored._level == original._level
        assert restored._location == original._location
        assert restored._micros == original._micros
        assert restored._extra == original._extra
        assert len(restored._handlers) == len(original._handlers)

    def test_to_dict_is_picklable(self):
        """Test complete builder config can be pickled."""
        builder = (
            LoggingBuilder("app")
            .with_level("info")
            .with_console_handler()
            .with_file_handler("/tmp/app.log")
            .with_extra(key="value")
        )

        d = builder.to_dict()

        pickled = pickle.dumps(d)
        unpickled = pickle.loads(pickled)

        assert unpickled == d

    def test_from_dict_builds_working_logger(self):
        """Test deserialized builder produces working logger."""
        d = {
            "name": "test.subprocess",
            "level": "debug",
            "location": 0,
            "micros": False,
            "colors": True,
            "handlers": [{"type": "console", "stream": "stdout", "format": "text"}],
            "extra": {"worker": "1"},
        }

        builder = LoggingBuilder.from_dict(d)
        logger = builder.build()

        assert logger.name == "test.subprocess"
        assert len(logger.handlers) == 1


@pytest.mark.unit
class TestLoggingBuilderSerializationWithDatabaseHandler:
    """Test LoggingBuilder serialization skips database handlers."""

    def test_to_dict_skips_database_handler(self):
        """Test to_dict skips non-serializable database handlers."""
        from unittest.mock import MagicMock

        from appinfra.log.builder.database import DatabaseHandlerConfig

        builder = LoggingBuilder("app").with_console_handler()

        # Add a database handler manually
        db_handler = DatabaseHandlerConfig(
            table_name="logs",
            db_interface=MagicMock(),
        )
        builder._handlers.append(db_handler)

        # Should not raise, should skip database handler
        d = builder.to_dict()

        # Only console handler should be serialized
        assert len(d["handlers"]) == 1
        assert d["handlers"][0]["type"] == "console"


@pytest.mark.unit
class TestDeserializeHandler:
    """Test _deserialize_handler helper function."""

    def test_unknown_handler_type_returns_none(self):
        """Test deserialization of unknown handler type returns None."""
        from appinfra.log.builder.builder import _deserialize_handler

        result = _deserialize_handler({"type": "unknown_type"})
        assert result is None

    def test_missing_type_returns_none(self):
        """Test deserialization without type returns None."""
        from appinfra.log.builder.builder import _deserialize_handler

        result = _deserialize_handler({})
        assert result is None

    def test_rotating_file_handler(self):
        """Test deserialization of rotating file handler."""
        from appinfra.log.builder.builder import _deserialize_handler
        from appinfra.log.builder.file import RotatingFileHandlerConfig

        result = _deserialize_handler(
            {
                "type": "rotating_file",
                "filename": "/var/log/app.log",
                "max_bytes": 1000,
                "backup_count": 3,
            }
        )

        assert isinstance(result, RotatingFileHandlerConfig)
        assert result.filename == "/var/log/app.log"
        assert result.max_bytes == 1000

    def test_timed_rotating_file_handler(self):
        """Test deserialization of timed rotating file handler."""
        from appinfra.log.builder.builder import _deserialize_handler
        from appinfra.log.builder.file import TimedRotatingFileHandlerConfig

        result = _deserialize_handler(
            {
                "type": "timed_rotating_file",
                "filename": "/var/log/app.log",
                "when": "midnight",
                "backup_count": 7,
            }
        )

        assert isinstance(result, TimedRotatingFileHandlerConfig)
        assert result.when == "midnight"


@pytest.mark.unit
class TestDatabaseHandlerNotSerializable:
    """Test DatabaseHandlerConfig raises on serialization."""

    def test_to_dict_raises(self):
        """Test DatabaseHandlerConfig.to_dict() raises NotImplementedError."""
        from unittest.mock import MagicMock

        from appinfra.log.builder.database import DatabaseHandlerConfig

        config = DatabaseHandlerConfig(
            table_name="logs",
            db_interface=MagicMock(),
        )

        with pytest.raises(NotImplementedError) as exc_info:
            config.to_dict()

        assert "cannot be serialized" in str(exc_info.value)
