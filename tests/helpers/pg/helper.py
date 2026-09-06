# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
PostgreSQL Test Helper - Base Test Class.

This module provides a base test class for PostgreSQL testing with automatic debug table management.
It handles common setup tasks like configuration loading, database connection, and debug table management.
"""

import unittest
from pathlib import Path
from typing import Any

from appinfra.config import Config
from appinfra.db.pg import PG
from appinfra.log import LogConfig, Logger, LoggerFactory

from .helper_core import PGTestHelperCore


def _create_debug_table_for_test(test_helper, table_name_prefix, custom_schema):
    """Create debug table with optional custom schema."""
    if custom_schema:
        return test_helper.create_debug_table_with_schema(
            table_name_prefix, custom_schema
        )
    else:
        return test_helper.create_debug_table(table_name_prefix)


def _log_test_failure(self, table_name):
    """Log test failure with debugging information."""
    if hasattr(self, "lg") and self.lg:
        self.lg.warning(
            "Test failed - table kept for debugging",
            extra={
                "table": table_name,
                "inspect_sql": f"SELECT * FROM {table_name};",
            },
        )


def _run_test_with_debug_table(self, test_method, table_name_prefix, custom_schema):
    """Run test with debug table, handling cleanup on success/failure."""
    session = None
    table_name = None
    cleanup_needed = False

    try:
        session, table_name, cleanup_needed = _create_debug_table_for_test(
            self.test_helper, table_name_prefix, custom_schema
        )
        self.session = session
        self.table_name = table_name

        test_method(self)
        cleanup_needed = True
    except Exception:
        cleanup_needed = False
        if table_name:
            _log_test_failure(self, table_name)
        raise
    finally:
        if session is not None and table_name is not None:
            self.test_helper.cleanup_debug_table(session, table_name, cleanup_needed)


class PGTestCaseHelper(unittest.TestCase):
    """
    Base test class for PostgreSQL testing with automatic debug table management.

    This class handles:
    - Configuration loading from etc/infra.yaml (or custom config path)
    - Database connection setup
    - Mock logger creation
    - Debug table management via PGTestHelperCore

    Inherit from this class to get all the common setup automatically.

    Usage:
        # Use default config (etc/infra.yaml)
        class MyTest(PGTestCaseHelper):
            pass

        # Use custom config file
        class MyTest(PGTestCaseHelper):
            @classmethod
            def setUpClass(cls):
                cls.set_config_path("path/to/custom/config.yaml")
                super().setUpClass()
    """

    # Type annotations for class attributes
    _config_path: str | None = None  # Class variable to store custom config path
    _db_available: bool
    _skip_reason: str
    config: Config
    test_config: Any
    lg: Logger
    pg: PG

    @classmethod
    def set_config_path(cls, config_path):
        """
        Set a custom configuration file path.

        Args:
            config_path (str): Path to the configuration file
        """
        cls._config_path = config_path

    @classmethod
    def setUpClass(cls):
        """Set up the test class with database connection."""
        # Load configuration
        config_path = cls._resolve_config_path()
        if config_path is None:
            return  # _db_available and _skip_reason already set

        # Load and validate config
        if not cls._load_and_validate_config(config_path):
            return  # _db_available and _skip_reason already set

        # Set up logger
        cls.lg = cls._setup_logger()

        # Test database connection
        cls._test_database_connection()

    @classmethod
    def _resolve_config_path(cls) -> Path | None:
        """
        Resolve configuration file path (custom or default).

        Returns:
            Path to config file, or None if not found
        """
        if cls._config_path:
            config_path = Path(cls._config_path)
            if not config_path.exists():
                cls._db_available = False
                cls._skip_reason = (
                    f"Custom configuration file '{cls._config_path}' not found"
                )
                return None
            return config_path

        # Find project root by looking for etc/infra.yaml
        current_path = Path(__file__)
        for parent in current_path.parents:
            if (parent / "etc" / "infra.yaml").exists():
                config_path = parent / "etc" / "infra.yaml"
                return config_path

        cls._db_available = False
        cls._skip_reason = "Could not find project root with etc/infra.yaml"
        return None

    @classmethod
    def _load_and_validate_config(cls, config_path: Path) -> bool:
        """
        Load configuration and validate database config exists.

        Returns:
            True if config loaded successfully, False otherwise
        """
        try:
            cls.config = Config(str(config_path))
            cls.test_config = cls.config.get("dbs.unittest")
            if not cls.test_config:
                cls._db_available = False
                cls._skip_reason = (
                    "Database configuration 'unittest' not found in configuration file"
                )
                return False
            return True
        except Exception as e:
            cls._db_available = False
            cls._skip_reason = f"Failed to load configuration: {e}"
            return False

    @classmethod
    def _setup_logger(cls) -> Logger:
        """Create a framework logger at the configured test level.

        `test.logging.level` is false by default (quiet tests); anything that is
        not a level name falls back to warning.
        """
        level = cls.config.get("test.logging.level")
        if not isinstance(level, str):
            level = "warning"
        return LoggerFactory.create_root(LogConfig.from_params(level=level))

    @classmethod
    def _test_database_connection(cls) -> None:
        """Test database connection and set availability flag."""
        try:
            cls.pg = PG(cls.lg, cls.test_config)
            conn = cls.pg.connect()
            conn.close()
            cls._db_available = True
        except Exception as e:
            cls._db_available = False
            cls._skip_reason = f"Cannot connect to test database: {e}"

    def setUp(self):
        """Set up each test."""
        if not self._db_available:
            self.skipTest(self._skip_reason)

        # Initialize the test helper (only once per class)
        if not hasattr(self.__class__, "_test_helper_initialized"):
            self.test_helper = PGTestHelperCore(self.pg)
            self.__class__._test_helper = self.test_helper
            self.__class__._test_helper_initialized = True
        else:
            # Reuse the existing helper instance
            self.test_helper = self.__class__._test_helper

    @staticmethod
    def debug_table(table_name_prefix="debug_test_table", custom_schema=None):
        """
        Decorator that automatically manages debug table cleanup based on test success/failure.

        This decorator eliminates the need to manually manage the cleanup_needed variable.
        It automatically:
        - Creates a debug table before the test runs
        - Cleans up the table if the test succeeds
        - Keeps the table for debugging if the test fails

        The decorator injects 'session' and 'table_name' as attributes of the test instance,
        so they can be accessed as self.session and self.table_name in the test method.

        Args:
            table_name_prefix (str): Prefix for the debug table name
            custom_schema (str, optional): Custom SQL schema for the table

        Usage:
            @PGTestCaseHelper.debug_table("my_test")
            def test_something(self):
                # Access session and table_name as self.session and self.table_name
                self.session.execute(sqlalchemy.text(f"INSERT INTO {self.table_name} ..."))
                self.session.commit()

            @PGTestCaseHelper.debug_table("custom_test", custom_schema="CREATE TABLE {table_name} (id SERIAL, data TEXT)")
            def test_with_custom_schema(self):
                # Test with custom schema
                pass
        """

        def decorator(test_method):
            def wrapper(self):
                _run_test_with_debug_table(
                    self, test_method, table_name_prefix, custom_schema
                )

            return wrapper

        return decorator
