#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Critical Flush Demo Application

This example demonstrates the critical flush functionality in the database logging system.
It shows how critical errors (those with exceptions or specific trigger fields) are
immediately flushed to the database, while normal logs are batched for efficiency.

Key Features Demonstrated:
- Normal logging (batched)
- Critical error logging (immediate flush)
- Exception handling with immediate database persistence
- Custom trigger fields for critical flush
- Fallback to console when database fails

Usage:
    python examples/critical_flush_demo.py

Requirements:
    - PostgreSQL database running
    - Database table created (see setup_database function)
"""

# ci-timeout: 20

import logging
import sys
import time
from datetime import datetime
from pathlib import Path

import sqlalchemy

# Allow running from a source checkout without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from appinfra.config import Config
from appinfra.log.builder.database import DatabaseLoggingBuilder

try:
    from tests.helpers.pg.helper import PGTestCaseHelper
except ImportError:
    print("This example requires test infrastructure (tests.helpers.pg.helper).")
    print("Please run from within the development environment with tests installed,")
    print("or run: pip install -e .[dev]")
    sys.exit(0)


class CriticalFlushDemo:
    """Demonstration of critical flush functionality."""

    def __init__(self):
        """Initialize the demo application."""
        self.config = Config("etc/infra.yaml")
        self.db_interface = None
        self.logger = None
        self.setup_database()
        self.setup_logging()

    def setup_database(self):
        """Set up the database connection and create required tables."""
        print("🔧 Setting up database...")

        # Use the test helper's connection; setUpClass() probes the database
        # and setUp() raises SkipTest when it is unavailable.
        PGTestCaseHelper.setUpClass()
        self.pg_helper = PGTestCaseHelper()
        self.pg_helper.setUp()
        self.db_interface = self.pg_helper.pg

        # Recreate the error_logs table so a leftover from an aborted run
        # cannot carry an old schema into this one.
        self.drop_error_logs_table()
        self.create_error_logs_table()
        print("✅ Database setup complete")

    def create_error_logs_table(self):
        """Create the error_logs table for demonstration."""
        create_table_sql = """
        CREATE TABLE IF NOT EXISTS error_logs (
            id SERIAL PRIMARY KEY,
            timestamp TIMESTAMP NOT NULL,
            level VARCHAR(20) NOT NULL,
            logger_name VARCHAR(100),
            message TEXT NOT NULL,
            module VARCHAR(100),
            function VARCHAR(100),
            line_number INTEGER,
            process_id INTEGER,
            thread_id BIGINT,
            extra_data JSONB,
            exception_info TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """

        with self.db_interface.session() as session:
            session.execute(sqlalchemy.text(create_table_sql))
            session.commit()

    def drop_error_logs_table(self):
        """Drop the demonstration table so repeated runs start clean."""
        with self.db_interface.session() as session:
            session.execute(sqlalchemy.text("DROP TABLE IF EXISTS error_logs"))
            session.commit()

    def _add_console_handler(self):
        """Add console handler to logger for immediate feedback."""
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        console_handler.setFormatter(console_formatter)
        self.logger.addHandler(console_handler)

    def setup_logging(self):
        """Set up logging with database handler and critical flush."""
        print("🔧 Setting up logging with critical flush...")

        builder = DatabaseLoggingBuilder("critical_flush_demo")
        builder.with_database_table(
            table_name="error_logs",
            db_interface=self.db_interface,
            level=logging.DEBUG,
            batch_size=5,
            flush_interval=10.0,
        ).with_critical_error_flush(
            enabled=True,
            trigger_fields=["exception", "critical", "fatal"],
            timeout=5.0,
            fallback_to_console=True,
        )

        self.logger = builder.build()
        self._add_console_handler()

        print("✅ Logging setup complete")

    def demonstrate_normal_logging(self):
        """Demonstrate normal logging (batched)."""
        print("\n📝 Demonstrating normal logging (batched)...")

        for i in range(8):
            self.logger.info(f"Normal log message {i + 1} - this will be batched")
            time.sleep(0.5)  # Small delay to show batching

        print("✅ Normal logging complete - check database for batched entries")

    def demonstrate_critical_error_with_exception(self):
        """Demonstrate critical error logging with exception (immediate flush)."""
        print("\n🚨 Demonstrating critical error with exception (immediate flush)...")

        try:
            # Simulate an error that will trigger immediate flush
            raise ValueError(
                "This is a critical error that should be flushed immediately!"
            )
        except Exception:
            # Log with exception info - this should trigger immediate flush
            self.logger.error(
                "Critical application error occurred",
                exc_info=True,
                extra={
                    "user_id": 12345,
                    "action": "critical_operation",
                    "timestamp": datetime.now().isoformat(),
                },
            )

        print("✅ Critical error logged - should be immediately flushed to database")

    def demonstrate_critical_error_with_trigger_field(self):
        """Demonstrate critical error logging with trigger field (immediate flush)."""
        print(
            "\n🚨 Demonstrating critical error with trigger field (immediate flush)..."
        )

        # Log with a trigger field in extra - this should trigger immediate flush
        self.logger.warning(
            "System resource exhaustion detected",
            extra={
                "critical": "memory_usage_95_percent",  # This field triggers immediate flush
                "memory_usage": "95%",
                "available_memory": "512MB",
                "recommended_action": "restart_service",
            },
        )

        print("✅ Critical warning logged - should be immediately flushed to database")

    def demonstrate_fatal_error(self):
        """Demonstrate fatal error logging (immediate flush)."""
        print("\n💀 Demonstrating fatal error (immediate flush)...")

        # Log with fatal trigger field
        self.logger.error(
            "Database connection pool exhausted",
            extra={
                "fatal": "database_pool_exhausted",  # This field triggers immediate flush
                "active_connections": 100,
                "max_connections": 100,
                "pending_requests": 50,
            },
        )

        print("✅ Fatal error logged - should be immediately flushed to database")

    def demonstrate_database_failure_fallback(self):
        """Demonstrate fallback to console when database fails."""
        print("\n🔄 Demonstrating database failure fallback...")

        # Temporarily break the database connection
        original_session = self.db_interface.session
        self.db_interface.session = lambda: (_ for _ in ()).throw(
            Exception("Database connection failed")
        )

        try:
            # Try to log a critical error - should fallback to console
            self.logger.error(
                "Critical error during database failure",
                exc_info=True,
                extra={"critical": "database_connection_lost", "retry_count": 3},
            )
        except Exception as e:
            print(f"Expected exception during database failure: {e}")
        finally:
            # Restore the database connection
            self.db_interface.session = original_session

        print("✅ Database failure fallback demonstrated")

    def _display_log_row(self, row):
        """Display a single log row."""
        print(f"ID: {row.id}")
        print(f"Timestamp: {row.timestamp}")
        print(f"Level: {row.level}")
        print(f"Logger: {row.logger_name}")
        print(f"Message: {row.message}")
        if row.extra_data:
            print(f"Extra Data: {row.extra_data}")
        if row.exception_info:
            print(f"Exception: {row.exception_info[:100]}...")
        print(f"Created At: {row.created_at}")
        print("-" * 80)

    def query_database_logs(self):
        """Query and display logs from the database."""
        print("\n📊 Querying database logs...")

        query_sql = """
        SELECT id, timestamp, level, logger_name, message, extra_data,
               exception_info, created_at
        FROM error_logs
        ORDER BY created_at DESC
        LIMIT 20;
        """

        with self.db_interface.session() as session:
            result = session.execute(sqlalchemy.text(query_sql))
            rows = result.fetchall()

            if not rows:
                print("❌ No logs found in database")
                return

            print(f"📋 Found {len(rows)} log entries:")
            print("-" * 80)

            for row in rows:
                self._display_log_row(row)

    def _run_all_demonstrations(self):
        """Execute all demonstration scenarios."""
        # Demonstrate different types of logging
        self.demonstrate_normal_logging()
        time.sleep(2)  # Wait for any pending flushes

        self.demonstrate_critical_error_with_exception()
        time.sleep(1)

        self.demonstrate_critical_error_with_trigger_field()
        time.sleep(1)

        self.demonstrate_fatal_error()
        time.sleep(1)

        self.demonstrate_database_failure_fallback()
        time.sleep(2)

        # Query the database to show results
        self.query_database_logs()

    def _print_demo_summary(self):
        """Print demo completion summary and key takeaways."""
        print("\n🎉 Critical Flush Demo Complete!")
        print("\nKey Takeaways:")
        print("- Normal logs are batched for efficiency")
        print(
            "- Critical errors (exceptions or trigger fields) are flushed immediately"
        )
        print("- Fallback to console occurs when database is unavailable")
        print("- Critical flush ensures important errors are not lost during crashes")

    def run_demo(self):
        """Run the complete demonstration."""
        print("🚀 Starting Critical Flush Demo")
        print("=" * 50)

        try:
            self._run_all_demonstrations()
            self._print_demo_summary()

        except Exception as e:
            print(f"❌ Demo failed: {e}")
            raise
        finally:
            # Flush pending batches before the table goes away, then clean up.
            if hasattr(self, "pg_helper"):
                for handler in list(self.logger.handlers):
                    handler.close()
                self.drop_error_logs_table()
                self.pg_helper.tearDown()


def main():
    """Main entry point for the demo."""
    print("Critical Flush Functionality Demo")
    print("This demo shows how critical errors are immediately flushed to the database")
    print("while normal logs are batched for efficiency.\n")

    try:
        demo = CriticalFlushDemo()
        demo.run_demo()
    except KeyboardInterrupt:
        print("\n👋 Demo interrupted by user")
    except Exception as e:
        print(f"❌ Demo failed: {e}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
