#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

import json
import pathlib
import random
import sys
import time
from datetime import datetime

# Add the project root to the path
project_root = str(pathlib.Path(__file__).resolve().parents[3])
sys.path.append(project_root) if project_root not in sys.path else None

import sqlalchemy

from appinfra import get_default_config
from appinfra.app import App, AppBuilder
from appinfra.db import Manager as DBManager
from appinfra.log.builder import (
    DatabaseLoggingBuilder,
    quick_audit_logger,
    quick_custom_database_logger,
    quick_error_logger,
)


class DatabaseLoggingApp(App):
    """Example application demonstrating database logging capabilities."""

    def add_args(self):
        # Add default logging arguments
        super().add_args()

        # Add database logging specific arguments
        self._add_demo_mode_arg()
        self._add_log_count_arg()
        self._add_batch_size_arg()
        self._add_flush_interval_arg()
        self._add_mock_db_arg()

    def _add_demo_mode_arg(self):
        """Add demo mode argument."""
        self.parser.add_argument(
            "--demo-mode",
            choices=["basic", "audit", "error", "custom", "multi", "all"],
            default="basic",
            help="database logging demo mode (default: basic)",
        )

    def _add_log_count_arg(self):
        """Add log count argument."""
        self.parser.add_argument(
            "--log-count",
            type=int,
            default=10,
            help="number of log messages to generate (default: 10)",
        )

    def _add_batch_size_arg(self):
        """Add batch size argument."""
        self.parser.add_argument(
            "--batch-size",
            type=int,
            default=3,
            help="batch size for database logging (default: 3)",
        )

    def _add_flush_interval_arg(self):
        """Add flush interval argument."""
        self.parser.add_argument(
            "--flush-interval",
            type=float,
            default=2.0,
            help="flush interval in seconds (default: 2.0)",
        )

    def _add_mock_db_arg(self):
        """Add mock database argument."""
        self.parser.add_argument(
            "--mock-db",
            action="store_true",
            help="use mock database interface instead of real database (default: False)",
        )

    def setup_database(self):
        """Set up database connection and create demo tables."""
        # Check if mock database mode is explicitly requested
        use_mock_db = getattr(self.args, "mock_db", False)

        if use_mock_db:
            self.lg.info("Mock database mode explicitly enabled")
            # Create a mock database interface for demonstration purposes
            self.db = self._create_mock_db_interface()
            self.lg.info("mock database setup completed")
            return

        # Load configuration
        self.config = get_default_config()

        # Create database manager
        self.db_manager = DBManager(self.lg, self.config)

        # Set up database connections
        self.db_manager.setup()

        # Get database interface (using unittest db for demo)
        self.db = self.db_manager.db("unittest")

        # Create demo tables
        self._create_demo_tables()

        self.lg.info("database setup completed", extra={"db_url": self.db.url})

    def _create_mock_db_interface(self):
        """Create a mock database interface for demonstration when real DB is not available."""
        mock_session_cls = self._create_mock_session_class()
        mock_db_interface_cls = self._create_mock_db_interface_class(mock_session_cls)
        return mock_db_interface_cls(self.lg)

    def _create_mock_session_class(self):
        """Create MockSession class for mock database."""
        mock_result_cls = self._create_mock_result_class()

        class MockSession:
            def __init__(self, lg):
                self.lg = lg

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                pass

            def execute(self, query, params=None):
                self.lg.info(f"Mock DB: Would execute: {str(query)[:100]}...")
                if "COUNT" in str(query).upper():
                    return mock_result_cls([(0,)])
                return mock_result_cls([])

            def commit(self):
                self.lg.info("Mock DB: Would commit transaction")

        return MockSession

    def _create_mock_result_class(self):
        """Create MockResult class for mock database."""

        class MockResult:
            def __init__(self, rows):
                self.rows = rows

            def fetchone(self):
                return self.rows[0] if self.rows else (0,)

            def fetchall(self):
                return self.rows

            def keys(self):
                return ["id", "timestamp", "message"]

        return MockResult

    def _create_mock_db_interface_class(self, mock_session_cls):
        """Create MockDBInterface class for mock database."""

        class MockDBInterface:
            def __init__(self, lg):
                self.lg = lg
                self.url = "mock://localhost/demo"

            def session(self):
                return mock_session_cls(self.lg)

        return MockDBInterface

    def _create_basic_logs_table(self, session):
        """Create basic logs table."""
        session.execute(
            sqlalchemy.text(
                """
            CREATE TABLE IF NOT EXISTS demo_logs (
                id SERIAL PRIMARY KEY,
                timestamp TIMESTAMP NOT NULL,
                level VARCHAR(20) NOT NULL,
                logger_name VARCHAR(100) NOT NULL,
                message TEXT NOT NULL,
                module VARCHAR(100),
                function VARCHAR(100),
                line_number INTEGER,
                process_id INTEGER,
                thread_id BIGINT,
                extra_data JSONB,
                exception_info TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
            )
        )

    def _create_audit_logs_table(self, session):
        """Create audit logs table."""
        session.execute(
            sqlalchemy.text(
                """
            CREATE TABLE IF NOT EXISTS audit_logs (
                id SERIAL PRIMARY KEY,
                created_at TIMESTAMP NOT NULL,
                log_level VARCHAR(20) NOT NULL,
                logger_name VARCHAR(100) NOT NULL,
                action_description TEXT NOT NULL,
                module_name VARCHAR(100),
                function_name VARCHAR(100),
                line_number INTEGER,
                process_id INTEGER,
                thread_id BIGINT,
                metadata JSONB,
                error_details TEXT
            )
        """
            )
        )

    def _create_error_logs_table(self, session):
        """Create error logs table."""
        session.execute(
            sqlalchemy.text(
                """
            CREATE TABLE IF NOT EXISTS error_logs (
                id SERIAL PRIMARY KEY,
                error_time TIMESTAMP NOT NULL,
                severity VARCHAR(20) NOT NULL,
                source_logger VARCHAR(100) NOT NULL,
                error_message TEXT NOT NULL,
                module_name VARCHAR(100),
                function_name VARCHAR(100),
                line_number INTEGER,
                process_id INTEGER,
                thread_id BIGINT,
                context_data JSONB,
                stack_trace TEXT
            )
        """
            )
        )

    def _create_custom_events_table(self, session):
        """Create custom events table."""
        session.execute(
            sqlalchemy.text(
                """
            CREATE TABLE IF NOT EXISTS custom_events (
                id SERIAL PRIMARY KEY,
                event_time TIMESTAMP NOT NULL,
                event_type VARCHAR(50) NOT NULL,
                event_source VARCHAR(100) NOT NULL,
                event_data JSONB NOT NULL,
                user_id INTEGER,
                session_id VARCHAR(100),
                ip_address INET,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
            )
        )

    def _create_demo_tables(self):
        """Create demo tables for different logging scenarios."""
        with self.db.session() as session:
            self._create_basic_logs_table(session)
            self._create_audit_logs_table(session)
            self._create_error_logs_table(session)
            self._create_custom_events_table(session)
            session.commit()
            self.lg.info("demo tables created successfully")

    def run(self, **kwargs):
        """Run the database logging demonstration."""
        params = self._get_demo_parameters()
        self._log_demo_start(params)
        self.setup_database()
        self._run_demo(params)
        self.lg.info("database logging demo completed")
        return 0

    def _get_demo_parameters(self):
        """Get demo parameters from args."""
        return {
            "demo_mode": getattr(self.args, "demo_mode", "basic"),
            "log_count": getattr(self.args, "log_count", 10),
            "batch_size": getattr(self.args, "batch_size", 3),
            "flush_interval": getattr(self.args, "flush_interval", 2.0),
        }

    def _log_demo_start(self, params):
        """Log demo start with parameters."""
        self.lg.info("starting database logging demo", extra=params)

    def _run_demo(self, params):
        """Run the appropriate demo based on mode."""
        demo_mode = params["demo_mode"]
        log_count = params["log_count"]
        batch_size = params["batch_size"]
        flush_interval = params["flush_interval"]

        demo_map = {
            "basic": lambda: self._demo_basic_logging(
                log_count, batch_size, flush_interval
            ),
            "audit": lambda: self._demo_audit_logging(log_count),
            "error": lambda: self._demo_error_logging(log_count),
            "custom": lambda: self._demo_custom_logging(
                log_count, batch_size, flush_interval
            ),
            "multi": lambda: self._demo_multi_table_logging(log_count),
            "all": lambda: self._demo_all_logging_types(
                log_count, batch_size, flush_interval
            ),
        }

        if demo_mode in demo_map:
            demo_map[demo_mode]()

    def _create_basic_db_logger(self, batch_size, flush_interval):
        """Create basic database logger."""
        return (
            DatabaseLoggingBuilder("db_demo")
            .with_level("info")
            .with_database_table(
                "demo_logs",
                self.db,
                batch_size=batch_size,
                flush_interval=flush_interval,
            )
            .build()
        )

    def _get_sample_messages(self):
        """Get sample log messages."""
        return [
            "Application started successfully",
            "Processing user request",
            "Database connection established",
            "Cache updated",
            "Background task completed",
            "API endpoint called",
            "File uploaded",
            "Email sent",
            "Report generated",
            "Cleanup task finished",
        ]

    def _generate_basic_logs(self, db_logger, log_count):
        """Generate sample log messages."""
        sample_messages = self._get_sample_messages()

        for i in range(log_count):
            message = random.choice(sample_messages)
            level = random.choice(["info", "warning", "debug"])
            extra_data = {
                "request_id": f"req_{random.randint(1000, 9999)}",
                "user_id": random.randint(1, 100),
                "operation": f"op_{i + 1}",
                "duration_ms": random.randint(10, 1000),
            }

            if level == "info":
                db_logger.info(f"{message} #{i + 1}", extra=extra_data)
            elif level == "warning":
                db_logger.warning(f"{message} #{i + 1}", extra=extra_data)
            else:
                db_logger.debug(f"{message} #{i + 1}", extra=extra_data)

            time.sleep(0.1)

    def _demo_basic_logging(self, log_count, batch_size, flush_interval):
        """Demonstrate basic database logging."""
        self.lg.info("=== Basic Database Logging Demo ===")

        db_logger = self._create_basic_db_logger(batch_size, flush_interval)
        self._generate_basic_logs(db_logger, log_count)

        for handler in db_logger.handlers:
            handler.close()

        self._show_table_contents("demo_logs")

    def _get_audit_actions(self):
        """Get list of audit actions."""
        return [
            "user_login",
            "user_logout",
            "password_change",
            "profile_update",
            "file_download",
            "data_export",
            "permission_change",
            "account_creation",
            "account_deletion",
            "settings_update",
        ]

    def _generate_audit_logs(self, audit_logger, log_count):
        """Generate audit log messages."""
        audit_actions = self._get_audit_actions()

        for i in range(log_count):
            action = random.choice(audit_actions)
            user_id = random.randint(1, 50)

            audit_data = {
                "user_id": user_id,
                "action": action,
                "ip_address": f"192.168.1.{random.randint(1, 254)}",
                "user_agent": "Mozilla/5.0 (Demo Browser)",
                "session_id": f"sess_{random.randint(10000, 99999)}",
            }

            audit_logger.info(f"User {user_id} performed {action}", extra=audit_data)
            time.sleep(0.05)

    def _demo_audit_logging(self, log_count):
        """Demonstrate audit logging."""
        self.lg.info("=== Audit Logging Demo ===")

        audit_logger = quick_audit_logger("audit_demo", self.db, "info")
        self._generate_audit_logs(audit_logger, log_count)

        for handler in audit_logger.handlers:
            handler.close()

        self._show_table_contents("audit_logs")

    def _get_error_types(self):
        """Get list of error types."""
        return [
            "database_connection_failed",
            "api_timeout",
            "validation_error",
            "permission_denied",
            "file_not_found",
            "memory_limit_exceeded",
            "network_error",
            "authentication_failed",
            "rate_limit_exceeded",
            "service_unavailable",
        ]

    def _log_single_error(self, error_logger, error_type, error_context):
        """Log a single error with appropriate severity."""
        if random.random() < 0.3:
            error_logger.critical(f"Critical error: {error_type}", extra=error_context)
        else:
            error_logger.error(f"Error occurred: {error_type}", extra=error_context)

        if random.random() < 0.2:
            try:
                raise ValueError(f"Simulated {error_type} exception")
            except ValueError:
                error_logger.exception(
                    "Exception caught during processing", extra=error_context
                )

    def _generate_error_logs(self, error_logger, log_count):
        """Generate error log messages."""
        error_types = self._get_error_types()

        for i in range(log_count):
            error_type = random.choice(error_types)
            error_context = {
                "error_code": f"E{random.randint(1000, 9999)}",
                "component": random.choice(
                    ["api", "database", "cache", "auth", "file_system"]
                ),
                "retry_count": random.randint(0, 3),
                "request_id": f"req_{random.randint(10000, 99999)}",
            }

            self._log_single_error(error_logger, error_type, error_context)
            time.sleep(0.05)

    def _demo_error_logging(self, log_count):
        """Demonstrate error logging."""
        self.lg.info("=== Error Logging Demo ===")

        error_logger = quick_error_logger("error_demo", self.db, "warning")
        self._generate_error_logs(error_logger, log_count)

        for handler in error_logger.handlers:
            handler.close()

        self._show_table_contents("error_logs")

    def _create_event_mapper(self):
        """Create custom event data mapper."""

        def event_mapper(record):
            extra_data = getattr(record, "_extra", {}) or {}
            return {
                "event_time": datetime.fromtimestamp(record.created),
                "event_type": record.levelname.lower(),
                "event_source": record.name,
                "event_data": json.dumps(
                    {
                        "message": record.getMessage(),
                        "module": record.module,
                        "function": record.funcName,
                        "line": record.lineno,
                        **extra_data,
                    }
                ),
                "user_id": extra_data.get("user_id"),
                "session_id": extra_data.get("session_id"),
                "ip_address": extra_data.get("ip_address"),
            }

        return event_mapper

    def _generate_custom_events(self, custom_logger, log_count):
        """Generate custom event log messages."""
        event_types = [
            "page_view",
            "button_click",
            "form_submit",
            "search_query",
            "download_start",
            "video_play",
            "comment_post",
            "share_content",
            "bookmark_add",
            "notification_view",
        ]

        for i in range(log_count):
            event_type = random.choice(event_types)
            event_data = {
                "user_id": random.randint(1, 100),
                "session_id": f"sess_{random.randint(100000, 999999)}",
                "ip_address": f"10.0.{random.randint(1, 255)}.{random.randint(1, 255)}",
                "event_category": "user_interaction",
                "page_url": f"/page/{random.randint(1, 20)}",
                "referrer": "https://example.com" if random.random() > 0.5 else None,
            }
            custom_logger.info(f"Event: {event_type}", extra=event_data)
            time.sleep(0.05)

    def _demo_custom_logging(self, log_count, batch_size, flush_interval):
        """Demonstrate custom data mapping."""
        self.lg.info("=== Custom Database Logging Demo ===")

        event_mapper = self._create_event_mapper()
        custom_logger = quick_custom_database_logger(
            "custom_demo", "custom_events", self.db, event_mapper, "info"
        )

        self._generate_custom_events(custom_logger, log_count)

        for handler in custom_logger.handlers:
            handler.close()

        self._show_table_contents("custom_events")

    def _generate_multi_table_logs(self, multi_logger, log_count):
        """Generate mixed log messages for multi-table demo."""
        for i in range(log_count):
            if i % 3 == 0:
                error_data = {
                    "component": "multi_demo",
                    "error_id": f"ERR_{i:04d}",
                    "severity": "high" if i % 6 == 0 else "medium",
                }
                multi_logger.error(f"Multi-table error #{i + 1}", extra=error_data)
            else:
                audit_data = {
                    "action": "multi_table_operation",
                    "operation_id": f"OP_{i:04d}",
                    "user": f"user_{random.randint(1, 10)}",
                }
                multi_logger.info(f"Multi-table operation #{i + 1}", extra=audit_data)

            time.sleep(0.1)

    def _demo_multi_table_logging(self, log_count):
        """Demonstrate logging to multiple tables simultaneously."""
        self.lg.info("=== Multi-Table Logging Demo ===")

        multi_logger = (
            DatabaseLoggingBuilder("multi_demo")
            .with_level("info")
            .with_audit_table(self.db, level=20, batch_size=2)  # INFO level
            .with_error_table(self.db, level=40, batch_size=1)  # ERROR level
            .build()
        )

        self._generate_multi_table_logs(multi_logger, log_count)

        for handler in multi_logger.handlers:
            handler.close()

        self._show_table_contents("audit_logs", "Multi-table audit logs")
        self._show_table_contents("error_logs", "Multi-table error logs")

    def _demo_all_logging_types(self, log_count, batch_size, flush_interval):
        """Demonstrate all logging types in sequence."""
        self.lg.info("=== All Logging Types Demo ===")

        # Run each demo with fewer messages
        demo_count = max(1, log_count // 4)

        self._demo_basic_logging(demo_count, batch_size, flush_interval)
        time.sleep(1)
        self._demo_audit_logging(demo_count)
        time.sleep(1)
        self._demo_error_logging(demo_count)
        time.sleep(1)
        self._demo_custom_logging(demo_count, batch_size, flush_interval)
        time.sleep(1)
        self._demo_multi_table_logging(demo_count)

    def _display_table_records(self, session, table_name):
        """Display recent records from a table."""
        result = session.execute(
            sqlalchemy.text(f"SELECT * FROM {table_name} ORDER BY id DESC LIMIT 5")
        )

        rows = result.fetchall()
        column_names = result.keys()

        self.lg.info(f"Last {min(5, len(rows))} records:")
        for i, row in enumerate(rows):
            row_dict = dict(zip(column_names, row))
            self.lg.info(f"  Record {i + 1}: {row_dict}")

    def _show_table_contents(self, table_name, title=None):
        """Display the contents of a database table."""
        if title is None:
            title = f"Contents of {table_name}"

        self.lg.info(f"=== {title} ===")

        try:
            with self.db.session() as session:
                result = session.execute(
                    sqlalchemy.text(f"SELECT COUNT(*) FROM {table_name}")
                )
                count = result.fetchone()[0]

                self.lg.info(f"Total records in {table_name}: {count}")

                if count > 0:
                    self._display_table_records(session, table_name)

        except Exception as e:
            self.lg.error(f"Error querying {table_name}: {e}")


def create_application():
    """Create the application using AppBuilder."""
    app = (
        AppBuilder("main_with_dblog")
        .with_main_cls(DatabaseLoggingApp)
        .with_description(
            "Example application demonstrating database logging capabilities"
        )
        .build()
    )

    return app


def main():
    """Main function."""
    app = create_application()
    return app.main()


if __name__ == "__main__":
    sys.exit(main())
