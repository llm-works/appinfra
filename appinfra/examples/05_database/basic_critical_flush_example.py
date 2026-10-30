#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Basic Critical Flush Example

This is a simple example showing how critical flush works in practice.
It demonstrates the key difference between normal logging (batched) and
critical error logging (immediate flush). A mock database stands in for
PostgreSQL, so it runs anywhere.

Usage:
    python examples/05_database/basic_critical_flush_example.py
"""

import sys
from pathlib import Path
from typing import Any, Self
from unittest.mock import Mock, patch

# Allow running from a source checkout without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from appinfra.log import Logger
from appinfra.log.builder.database import DatabaseLoggingBuilder

BATCH_SIZE = 3
TRIGGER_FIELDS = ["exception", "critical"]


class SimpleDatabaseInterface:
    """Simple mock database interface for demonstration."""

    def __init__(self) -> None:
        self.operations: list[str] = []
        self.should_fail = False

    def session(self) -> "MockSession":
        """Return a mock session."""
        return MockSession(self)


class MockSession:
    """Mock database session."""

    def __init__(self, db_interface: SimpleDatabaseInterface) -> None:
        self.db_interface = db_interface

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        pass

    def execute(self, sql: Any, params: Any = None) -> Mock:
        """Mock execute method."""
        if self.db_interface.should_fail:
            raise Exception("Database connection lost")

        self.db_interface.operations.append("execute")
        print("    💾 Database: Executing SQL")
        return Mock()

    def commit(self) -> None:
        """Mock commit method."""
        if self.db_interface.should_fail:
            raise Exception("Database commit failed")

        self.db_interface.operations.append("commit")
        print("    ✅ Database: Committed transaction")


def _demo_normal_logging(lg: Logger, db_interface: SimpleDatabaseInterface) -> None:
    """Demonstrate normal batched logging."""
    print("📝 1. Normal Logging (Batched)")
    print("   Sending 5 normal log messages...")

    for i in range(5):
        lg.info(f"Normal log message {i + 1}")
        print(f"   📤 Sent normal log {i + 1}")

    print(f"   Database operations: {len(db_interface.operations)}")
    print(f"   Messages 4-5 wait until the batch of {BATCH_SIZE} fills")
    print()


def _report_flush(db_interface: SimpleDatabaseInterface, before: int) -> None:
    """Print whether the last log call wrote to the database at once."""
    after = len(db_interface.operations)
    print(f"   Database operations: {before} → {after}")
    print(f"   Immediate flush: {'Yes' if after > before else 'No'}")
    print()


def _demo_critical_exception(lg: Logger, db_interface: SimpleDatabaseInterface) -> None:
    """Demonstrate critical flush with exception."""
    print("🚨 2. Critical Error with Exception (Immediate Flush)")
    print("   Sending critical error with exception...")

    before = len(db_interface.operations)
    try:
        raise ValueError("Critical application error!")
    except ValueError:
        lg.error("Critical error occurred", exc_info=True, extra={"user_id": 12345})
    _report_flush(db_interface, before)


def _demo_critical_trigger_field(
    lg: Logger, db_interface: SimpleDatabaseInterface
) -> None:
    """Demonstrate critical flush with trigger field."""
    print("🚨 3. Critical Error with Trigger Field (Immediate Flush)")
    print("   Sending critical warning with trigger field...")

    before = len(db_interface.operations)
    lg.warning(
        "System resource exhausted",
        extra={
            "critical": "memory_usage_95_percent",  # This triggers immediate flush
            "memory_usage": "95%",
        },
    )
    _report_flush(db_interface, before)


def _demo_database_failure_fallback(
    lg: Logger, db_interface: SimpleDatabaseInterface
) -> None:
    """Demonstrate fallback to console on database failure."""
    print("🔄 4. Database Failure Fallback")
    print("   Simulating database failure...")

    db_interface.should_fail = True
    # The console handler prints the fallback line; the failed write's own traceback
    # goes to stderr, kept out of the demo output.
    with patch("sys.stderr"):
        try:
            raise ConnectionError("Database connection lost")
        except ConnectionError:
            lg.error("Critical error during database failure", exc_info=True)
    db_interface.should_fail = False
    print()


def _print_summary(db_interface: SimpleDatabaseInterface) -> None:
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


def _build_logger(db_interface: SimpleDatabaseInterface) -> Logger:
    """Build a logger writing to the database, with critical flush enabled."""
    return (
        DatabaseLoggingBuilder("critical_flush_demo")
        .with_level("debug")
        .with_database_table(
            table_name="error_logs",
            db_interface=db_interface,
            batch_size=BATCH_SIZE,
            flush_interval=5.0,
        )
        .with_critical_error_flush(
            enabled=True,
            trigger_fields=TRIGGER_FIELDS,
            timeout=2.0,
            fallback_to_console=True,
        )
        # Shows the fallback line when the database is down
        .with_console_handler(level="critical")
        .build()
    )


def _print_config() -> None:
    """Print handler configuration."""
    print("📋 Configuration:")
    print(f"   - Batch size: {BATCH_SIZE}")
    print("   - Critical flush: enabled")
    print(f"   - Trigger fields: {TRIGGER_FIELDS}")
    print()


def demonstrate_critical_flush() -> None:
    """Demonstrate critical flush functionality."""
    print("🚀 Critical Flush Demonstration")
    print("=" * 50)

    db_interface = SimpleDatabaseInterface()
    lg = _build_logger(db_interface)
    _print_config()

    try:
        _demo_normal_logging(lg, db_interface)
        _demo_critical_exception(lg, db_interface)
        _demo_critical_trigger_field(lg, db_interface)
        _demo_database_failure_fallback(lg, db_interface)
    finally:
        # Closing the handlers writes what is still batched
        for handler in list(lg.handlers):
            handler.close()
    _print_summary(db_interface)


def main() -> int:
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
