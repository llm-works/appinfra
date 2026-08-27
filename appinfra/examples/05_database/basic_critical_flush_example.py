#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Basic Critical Flush Example

This is a simple example showing how critical flush works in practice.
It demonstrates the key difference between normal logging (batched) and
critical error logging (immediate flush).

Usage:
    python examples/basic_critical_flush_example.py
"""

import logging
import pathlib
import sys
import time
from unittest.mock import Mock, patch

# Add the project root to the path
project_root = str(pathlib.Path(__file__).resolve().parents[3])
sys.path.insert(0, project_root)

from appinfra.log.builder.database import DatabaseHandler, DatabaseHandlerConfig
from appinfra.log.config import LogConfig


class SimpleDatabaseInterface:
    """Simple mock database interface for demonstration."""

    def __init__(self):
        self.operations = []
        self.should_fail = False

    def session(self):
        """Return a mock session."""
        return MockSession(self)


class MockSession:
    """Mock database session."""

    def __init__(self, db_interface):
        self.db_interface = db_interface

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def execute(self, sql, params=None):
        """Mock execute method."""
        if self.db_interface.should_fail:
            raise Exception("Database connection lost")

        self.db_interface.operations.append("execute")
        print("    💾 Database: Executing SQL (immediate flush)")
        return Mock()

    def commit(self):
        """Mock commit method."""
        if self.db_interface.should_fail:
            raise Exception("Database commit failed")

        self.db_interface.operations.append("commit")
        print("    ✅ Database: Committed transaction")


def create_log_record(level, message, exc_info=None, extra=None):
    """Create a proper log record."""
    logger = logging.getLogger("demo_logger")
    logger.setLevel(logging.DEBUG)

    record = logger.makeRecord(
        name="demo_logger",
        level=level,
        fn="demo_function",
        lno=42,
        msg=message,
        args=(),
        exc_info=exc_info,
    )

    if extra:
        record.extra = extra
    else:
        record.extra = {}

    return record


def _demo_normal_logging(handler, db_interface):
    """Demonstrate normal batched logging."""
    print("📝 1. Normal Logging (Batched)")
    print("   Sending 5 normal log messages...")

    for i in range(5):
        record = create_log_record(logging.INFO, f"Normal log message {i + 1}")
        handler.emit(record)
        print(f"   📤 Sent normal log {i + 1}")
        time.sleep(0.2)

    print(f"   Database operations: {len(db_interface.operations)}")
    print()


def _demo_critical_exception(handler, db_interface):
    """Demonstrate critical flush with exception."""
    print("🚨 2. Critical Error with Exception (Immediate Flush)")
    print("   Sending critical error with exception...")

    try:
        raise ValueError("Critical application error!")
    except Exception as e:
        record = create_log_record(
            logging.ERROR,
            "Critical error occurred",
            exc_info=(type(e), e, None),
            extra={"user_id": 12345},
        )

    operations_before = len(db_interface.operations)
    handler.emit(record)
    operations_after = len(db_interface.operations)

    print(f"   Database operations: {operations_before} → {operations_after}")
    print(
        f"   Immediate flush: {'Yes' if operations_after > operations_before else 'No'}"
    )
    print()


def _demo_critical_trigger_field(handler, db_interface):
    """Demonstrate critical flush with trigger field."""
    print("🚨 3. Critical Error with Trigger Field (Immediate Flush)")
    print("   Sending critical warning with trigger field...")

    record = create_log_record(
        logging.WARNING,
        "System resource exhausted",
        extra={
            "critical": "memory_usage_95_percent",  # This triggers immediate flush
            "memory_usage": "95%",
        },
    )

    operations_before = len(db_interface.operations)
    handler.emit(record)
    operations_after = len(db_interface.operations)

    print(f"   Database operations: {operations_before} → {operations_after}")
    print(
        f"   Immediate flush: {'Yes' if operations_after > operations_before else 'No'}"
    )
    print()


def _demo_database_failure_fallback(handler, db_interface):
    """Demonstrate fallback to console on database failure."""
    print("🔄 4. Database Failure Fallback")
    print("   Simulating database failure...")

    db_interface.should_fail = True

    record = create_log_record(
        logging.ERROR,
        "Critical error during database failure",
        exc_info=(Exception, Exception("Database connection lost"), None),
    )

    with patch("sys.stderr") as mock_stderr:
        handler.emit(record)

        if mock_stderr.write.called:
            print("   ✅ Fallback to console occurred")
        else:
            print("   ❌ Fallback to console did not occur")

    print()


def _print_summary(db_interface):
    """Print demonstration summary."""
    print("📊 Summary")
    print("=" * 50)
    print(f"Total database operations: {len(db_interface.operations)}")
    print(f"Operations: {db_interface.operations}")
    print()
    print("🎯 Key Points:")
    print("✅ Normal logs are batched for efficiency")
    print("✅ Critical errors trigger immediate flush")
    print("✅ Exceptions automatically trigger critical flush")
    print("✅ Custom trigger fields provide flexibility")
    print("✅ Fallback to console prevents silent failures")
    print("✅ Critical flush ensures important errors survive crashes")


def _setup_handler():
    """Setup database handler and configuration."""
    db_interface = SimpleDatabaseInterface()
    handler_config = DatabaseHandlerConfig(
        table_name="error_logs",
        db_interface=db_interface,
        batch_size=3,
        flush_interval=5.0,
        critical_flush_enabled=True,
        critical_trigger_fields=["exception", "critical"],
        critical_flush_timeout=2.0,
        fallback_to_console=True,
    )

    error_logger = logging.getLogger("database_handler_errors")
    error_logger.setLevel(logging.ERROR)
    error_logger.addHandler(logging.StreamHandler(sys.stderr))

    handler = DatabaseHandler(
        error_logger, handler_config, LogConfig.from_params("debug")
    )

    return db_interface, handler, handler_config


def _print_config(handler_config):
    """Print handler configuration."""
    print("📋 Configuration:")
    print(f"   - Batch size: {handler_config.batch_size}")
    print(
        f"   - Critical flush: {'enabled' if handler_config.critical_flush_enabled else 'disabled'}"
    )
    print(f"   - Trigger fields: {handler_config.critical_trigger_fields}")
    print()


def demonstrate_critical_flush():
    """Demonstrate critical flush functionality."""
    print("🚀 Critical Flush Demonstration")
    print("=" * 50)

    db_interface, handler, handler_config = _setup_handler()
    _print_config(handler_config)

    _demo_normal_logging(handler, db_interface)
    _demo_critical_exception(handler, db_interface)
    _demo_critical_trigger_field(handler, db_interface)
    _demo_database_failure_fallback(handler, db_interface)
    _print_summary(db_interface)


def main():
    """Main entry point."""
    try:
        demonstrate_critical_flush()
    except KeyboardInterrupt:
        print("\n👋 Demo interrupted by user")
    except Exception as e:
        print(f"❌ Demo failed: {e}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
