#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
PGTestCaseHelper Custom Config Example

This example demonstrates how to use PGTestCaseHelper with custom configuration files
instead of the default etc/infra.yaml.

What This Example Shows:
1. Custom Config Path: How to set a custom configuration file path
2. Default Config: How the default behavior works when no custom path is set
3. Flexible Configuration: Support for different database configurations per test class

Running the Example:
    # From the project root
    # From the infra project root
    ~/.venv/bin/python examples/pg_test_helper_custom_config.py

Example Tests:

1. TestPGHelperCustomConfig.test_with_custom_config
   - Sets a custom config path using cls.set_config_path("etc/infra.yaml")
   - Demonstrates how to override the default configuration
   - Shows the custom config path in the output

2. TestPGHelperDefaultConfig.test_with_default_config
   - Uses the default configuration (no custom path set)
   - Shows how the default behavior works
   - Demonstrates that _config_path is None when using defaults

Key Features Demonstrated:
1. Custom Config Support: set_config_path() method for flexible configuration
2. Backward Compatibility: Existing tests continue to work without changes
3. Clear Error Messages: Helpful error messages when config files are missing
4. Path Validation: Automatic validation of config file existence

Usage Patterns:

Pattern 1: Custom Config File
    class MyTest(PGTestCaseHelper):
        @classmethod
        def setUpClass(cls):
            cls.set_config_path("path/to/my/config.yaml")
            super().setUpClass()

        def test_something(self):
            # Your test logic here
            pass

Pattern 2: Default Config (No Changes Needed)
    class MyTest(PGTestCaseHelper):
        # No setUpClass needed - uses default etc/infra.yaml

        def test_something(self):
            # Your test logic here
            pass

Pattern 3: Environment-Specific Configs
    class MyTest(PGTestCaseHelper):
        @classmethod
        def setUpClass(cls):
            import os
            env = os.getenv('TEST_ENV', 'dev')
            cls.set_config_path(f"configs/{env}_config.yaml")
            super().setUpClass()

Configuration File Requirements:
    Your custom configuration file should follow the same structure as etc/infra.yaml:

    dbs:
      test:
        host: "127.0.0.1"
        port: 7432
        user: "postgres"
        password: "postgres"
        database: "unittest"

Benefits:
- [TOOL] Flexible Testing: Use different database configurations for different test scenarios
- [GLOBE] Environment Support: Easy support for dev/staging/prod test environments
- [FOLDER] Organization: Keep test-specific configurations separate from main config
- [REFRESH] Backward Compatible: Existing tests continue to work without modification
- [OK] Validation: Automatic validation of config file existence and structure

This makes PGTestCaseHelper much more flexible for different testing scenarios while
maintaining simplicity for basic usage!
"""

import sys
import unittest
from pathlib import Path

# Add the project root to the Python path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

import sqlalchemy

try:
    from tests.helpers.pg.helper import PGTestCaseHelper
except ImportError:
    print("This example requires test infrastructure (tests.helpers.pg.helper).")
    print("Please run from within the development environment with tests installed,")
    print("or run: pip install -e .[dev]")
    sys.exit(0)


class TestPGHelperCustomConfig(PGTestCaseHelper):
    """Example tests using PGTestCaseHelper with custom config."""

    @classmethod
    def setUpClass(cls):
        """Set up with custom config file."""
        # Set custom config path (in this case, we'll use the default for demo)
        # In real usage, you would point to your custom config file
        # Use the default config file constant
        from appinfra import DEFAULT_CONFIG_FILE

        cls.set_config_path(str(DEFAULT_CONFIG_FILE))  # Using default for demo
        super().setUpClass()

    def _create_config_test_table(self, session, table_name):
        """Create config test table."""
        session.execute(
            sqlalchemy.text(
                f"""
            CREATE TABLE {table_name} (
                id SERIAL PRIMARY KEY,
                config_source VARCHAR(100) NOT NULL,
                test_data VARCHAR(200)
            )
        """
            )
        )

    def _insert_config_data(self, session, table_name, config_source, test_data):
        """Insert config test data."""
        session.execute(
            sqlalchemy.text(
                f"""
            INSERT INTO {table_name} (config_source, test_data)
            VALUES ('{config_source}', '{test_data}')
        """
            )
        )
        session.commit()

    def _verify_config_data(self, session, table_name, expected_config_source):
        """Verify config test data."""
        result = session.execute(sqlalchemy.text(f"SELECT COUNT(*) FROM {table_name}"))
        self.assertEqual(result.fetchone()[0], 1)

        result = session.execute(
            sqlalchemy.text(f"SELECT config_source FROM {table_name}")
        )
        self.assertEqual(result.fetchone()[0], expected_config_source)

    def test_with_custom_config(self):
        """Test using custom configuration."""
        print("\n=== Running test with custom config ===")

        session, table_name, cleanup_needed = self.test_helper.create_debug_table(
            "custom_config_test"
        )

        try:
            self._create_config_test_table(session, table_name)
            self._insert_config_data(
                session,
                table_name,
                "custom_config",
                "This test used a custom config file",
            )
            self._verify_config_data(session, table_name, "custom_config")

            print(f"[OK] Test passed! Used config: {self._config_path or 'default'}")
            cleanup_needed = True

        except Exception:
            print(f"[DEBUG] Test failed! Table '{table_name}' kept for debugging.")
            cleanup_needed = False
            raise

        finally:
            self.test_helper.cleanup_debug_table(session, table_name, cleanup_needed)


class TestPGHelperDefaultConfig(PGTestCaseHelper):
    """Example tests using PGTestCaseHelper with default config (no custom path)."""

    def _create_config_test_table(self, session, table_name):
        """Create config test table."""
        session.execute(
            sqlalchemy.text(
                f"""
            CREATE TABLE {table_name} (
                id SERIAL PRIMARY KEY,
                config_source VARCHAR(100) NOT NULL,
                test_data VARCHAR(200)
            )
        """
            )
        )

    def _insert_config_data(self, session, table_name, config_source, test_data):
        """Insert config test data."""
        session.execute(
            sqlalchemy.text(
                f"""
            INSERT INTO {table_name} (config_source, test_data)
            VALUES ('{config_source}', '{test_data}')
        """
            )
        )
        session.commit()

    def _verify_config_data(self, session, table_name, expected_config_source):
        """Verify config test data."""
        result = session.execute(sqlalchemy.text(f"SELECT COUNT(*) FROM {table_name}"))
        self.assertEqual(result.fetchone()[0], 1)

        result = session.execute(
            sqlalchemy.text(f"SELECT config_source FROM {table_name}")
        )
        self.assertEqual(result.fetchone()[0], expected_config_source)

    def test_with_default_config(self):
        """Test using default configuration (no custom config path set)."""
        print("\n=== Running test with default config ===")

        session, table_name, cleanup_needed = self.test_helper.create_debug_table(
            "default_config_test"
        )

        try:
            self._create_config_test_table(session, table_name)
            self._insert_config_data(
                session,
                table_name,
                "default_config",
                "This test used the default config file",
            )
            self._verify_config_data(session, table_name, "default_config")

            print(f"[OK] Test passed! Used config: {self._config_path or 'default'}")
            cleanup_needed = True

        except Exception:
            print(f"[DEBUG] Test failed! Table '{table_name}' kept for debugging.")
            cleanup_needed = False
            raise

        finally:
            self.test_helper.cleanup_debug_table(session, table_name, cleanup_needed)


if __name__ == "__main__":
    print("PGTestCaseHelper Custom Config Example")
    print("=" * 50)
    print()
    print("This example demonstrates:")
    print("1. Using PGTestCaseHelper with custom config file")
    print("2. Using PGTestCaseHelper with default config file")
    print("3. How to set custom config path in setUpClass")
    print()

    unittest.main(verbosity=2)
