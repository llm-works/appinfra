#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
PGTestCaseHelper Comprehensive Example

This comprehensive example demonstrates all the key features of PGTestCaseHelper for
PostgreSQL testing with automatic debug table management.

What This Example Demonstrates:
- [OK] Success/Failure Scenarios: Shows how tables are cleaned up on success and kept on failure
- [TOOL] Custom Table Schemas: Demonstrates advanced table creation with custom schemas
- [CHART] Table Inspection: Shows how to inspect debug tables for debugging
- [BUILDING] Complex Scenarios: Real-world testing examples with business logic
- [BROOM] Debug Table Management: Automatic cleanup and management features

Running the Example:
    # From the project root
    # From the infra project root
    ~/.venv/bin/python examples/pg_test_helper_example.py

Example Tests:

1. test_simple_decorator_example (NEW!)
   - Demonstrates the new @debug_table decorator
   - Much cleaner code - no manual cleanup_needed management
   - Access session and table_name as self.session and self.table_name
   - Test passes -> table gets cleaned up automatically

2. test_decorator_failure_example (NEW!)
   - Shows decorator with a failing test
   - Table is kept for debugging automatically
   - No try/except/finally blocks needed

3. test_decorator_custom_schema_example (NEW!)
   - Uses decorator with custom table schema
   - Demonstrates JSONB and complex data types
   - Test passes -> table gets cleaned up automatically

4. test_successful_operation
   - Original manual approach for comparison
   - Creates a simple table with user data
   - Test passes -> table gets cleaned up automatically
   - Shows the "success" path with multiple assertions

5. test_failing_operation
   - Original manual approach for comparison
   - Creates a table with product data
   - Test fails (expecting 2 rows but getting 3)
   - Table is kept for debugging
   - Shows the "failure" path with helpful debug messages

6. test_custom_schema
   - Original manual approach for comparison
   - Uses create_debug_table_with_schema() for custom table structure
   - Creates a user actions table with JSONB metadata
   - Demonstrates complex data types and relationships
   - Test passes -> table gets cleaned up

7. test_table_inspection
   - Original manual approach for comparison
   - Creates a table with employee data
   - Demonstrates table inspection capabilities
   - Shows how to use inspect_debug_table() and list_debug_tables()
   - Tests both success and failure scenarios

8. test_complex_scenario
   - Original manual approach for comparison
   - Creates a realistic e-commerce orders table
   - Demonstrates complex business logic testing
   - Shows multiple assertions and data validation
   - Real-world testing scenario with meaningful data

Expected Output:
    PGTestCaseHelper Comprehensive Example
    ============================================================

    This example demonstrates:
    1. Basic success/failure scenarios
    2. Custom table schemas
    3. Table inspection capabilities
    4. Complex real-world testing scenarios
    5. Debug table management

    === Running successful test ===
    [OK] Test passed! Table 'example_success_XXXXX' will be cleaned up.

    === Running failing test ===
    [DEBUG] Test failed! Table 'example_failure_XXXXX' kept for debugging.
       You can inspect it with: SELECT * FROM example_failure_XXXXX;
       Table contains 3 rows

    === Running custom schema test ===
    [OK] Custom schema test passed! Table 'custom_test_XXXXX' will be cleaned up.

    === Running table inspection test ===
    [OK] Table inspection test passed! Table 'inspection_test_XXXXX' will be cleaned up.

    === Running complex scenario test ===
    [OK] Complex scenario test passed! Table 'complex_test_XXXXX' will be cleaned up.

    ============================================================
    Example Summary:
    Tests run: 5
    Failures: 1
    Errors: 0

    Failures (expected for demo purposes):
      - test_failing_operation

    ============================================================
    Key Features Demonstrated:
    [OK] Debug tables persist on test failure
    [OK] Debug tables clean up on test success
    [OK] Custom schema support
    [OK] Table inspection capabilities
    [OK] Complex testing scenarios
    [OK] Automatic cleanup of previous debug tables

Debugging Failed Tests:
    After running the example, check the database for leftover tables:

    psql -h 127.0.0.1 -p 25432 -U postgres -d unittest -c "
    SELECT tablename FROM pg_tables
    WHERE schemaname = 'public' AND tablename LIKE 'example_%';"

    Inspect the data:

    psql -h 127.0.0.1 -p 25432 -U postgres -d unittest -c "
    SELECT * FROM example_failure_XXXXX;"

Key Features Demonstrated:
    1. Automatic cleanup: Successful tests clean up their tables
    2. Debug persistence: Failed tests keep tables for inspection
    3. Custom schemas: Support for complex table structures with JSONB, constraints, etc.
    4. Table inspection: Built-in utilities to examine debug tables
    5. Complex scenarios: Real-world testing with business logic
    6. Clear messaging: Helpful debug output and guidance

Integration with Your Tests:

Option 1: Using the @debug_table Decorator (RECOMMENDED!)
    The easiest and cleanest way to use PGTestCaseHelper is with the decorator:

    from tests.helpers.pg.helper import PGTestCaseHelper

    class MyTest(PGTestCaseHelper):
        @PGTestCaseHelper.debug_table("my_test")
        def test_my_feature(self):
            # Access session and table_name as self.session and self.table_name
            self.session.execute(sqlalchemy.text(f"INSERT INTO {self.table_name} ..."))
            self.session.commit()

            # Test assertions
            result = self.session.execute(sqlalchemy.text(f"SELECT COUNT(*) FROM {self.table_name}"))
            count = result.fetchone()[0]
            self.assertEqual(count, 1)

            # No cleanup needed - decorator handles it automatically!

    @PGTestCaseHelper.debug_table("custom_test", custom_schema="CREATE TABLE {table_name} (id SERIAL, data TEXT)")
    def test_with_custom_schema(self):
        # Test with custom schema - decorator handles everything
        pass

Option 2: Manual Setup (Original Approach)
    If you need more control, you can use the manual approach:

    from tests.helpers.pg.helper import PGTestCaseHelper

    class MyTest(PGTestCaseHelper):
        def test_my_feature(self):
            session, table_name, cleanup_needed = self.test_helper.create_debug_table("my_test")

            try:
                # Your test logic here
                # Create tables, insert data, run assertions

                cleanup_needed = True  # Mark for cleanup if test passes

            except Exception as e:
                cleanup_needed = False  # Keep table for debugging if test fails
                raise

            finally:
                self.test_helper.cleanup_debug_table(session, table_name, cleanup_needed)

Option 3: Manual Setup with PGTestHelperCore
    If you need custom setup, you can use PGTestHelperCore directly:

    from tests.helpers.pg.helper_core import PGTestHelperCore

    class MyTest(unittest.TestCase):
        def setUp(self):
            # Your custom setup here
            self.pg = your_pg_instance
            self.test_helper = PGTestHelperCore(self.pg)

        def test_my_feature(self):
            session, table_name, cleanup_needed = self.test_helper.create_debug_table("my_test")

            try:
                # Your test logic here
                cleanup_needed = True

            except Exception as e:
                cleanup_needed = False
                raise

            finally:
                self.test_helper.cleanup_debug_table(session, table_name, cleanup_needed)

Benefits of the New Architecture:
- [OK] Zero boilerplate: Use @debug_table decorator for automatic cleanup management
- [OK] Clean code: No more try/except/finally blocks or cleanup_needed variables
- [OK] Consistent setup: All tests use the same configuration and connection logic
- [OK] Easy maintenance: Common setup logic is centralized in one place
- [OK] Flexible: Can still use manual approach or PGTestHelperCore for custom needs
- [OK] Comprehensive: Single example covers all major use cases including the new decorator

This makes database testing much easier by automatically managing debug tables based on test outcomes!
"""

import sys
import unittest
from pathlib import Path

# Allow running from a source checkout without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import sqlalchemy

try:
    from tests.helpers.pg.helper import PGTestCaseHelper
except ImportError:
    print("This example requires test infrastructure (tests.helpers.pg.helper).")
    print("Please run from within the development environment with tests installed,")
    print("or run: pip install -e .[dev]")
    sys.exit(0)


class TestPGHelperExample(PGTestCaseHelper):
    """Comprehensive example tests demonstrating PGTestCaseHelper usage."""

    def _create_decorator_test_table(self):
        """Create test table for decorator example."""
        self.session.execute(
            sqlalchemy.text(
                f"""
                CREATE TABLE {self.table_name} (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(50),
                    value INTEGER
                )
                """
            )
        )

    def _insert_decorator_test_data(self):
        """Insert test data for decorator example."""
        self.session.execute(
            sqlalchemy.text(
                f"""
                INSERT INTO {self.table_name} (name, value) VALUES
                ('Alice', 100),
                ('Bob', 200),
                ('Charlie', 300)
                """
            )
        )
        self.session.commit()

    @PGTestCaseHelper.debug_table("example_success")
    def test_simple_decorator_example(self):
        """Example using the new debug_table decorator - much cleaner!"""
        print("\n=== Running decorator example ===")

        self._create_decorator_test_table()
        self._insert_decorator_test_data()

        result = self.session.execute(
            sqlalchemy.text(f"SELECT COUNT(*) FROM {self.table_name}")
        )
        count = result.fetchone()[0]
        self.assertEqual(count, 3)

        print(
            f"[OK] Decorator example passed! Table '{self.table_name}' will be cleaned up automatically."
        )

    def _create_failure_test_table(self):
        """Create table for failure example."""
        self.session.execute(
            sqlalchemy.text(
                f"""
                CREATE TABLE {self.table_name} (
                    id SERIAL PRIMARY KEY,
                    product VARCHAR(50),
                    price DECIMAL(10,2)
                )
                """
            )
        )

    def _insert_failure_test_data(self):
        """Insert test data for failure example."""
        self.session.execute(
            sqlalchemy.text(
                f"""
                INSERT INTO {self.table_name} (product, price) VALUES
                ('Widget A', 19.99),
                ('Widget B', 29.99),
                ('Widget C', 39.99)
                """
            )
        )
        self.session.commit()

    @PGTestCaseHelper.debug_table("example_failure")
    def test_decorator_failure_example(self):
        """Example using decorator with a failing test."""
        print("\n=== Running decorator failure example ===")

        self._create_failure_test_table()
        self._insert_failure_test_data()

        result = self.session.execute(
            sqlalchemy.text(f"SELECT COUNT(*) FROM {self.table_name}")
        )
        count = result.fetchone()[0]
        self.assertEqual(count, 2)

    @PGTestCaseHelper.debug_table(
        "example_custom",
        custom_schema="""
            CREATE TABLE {table_name} (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                action VARCHAR(100) NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                metadata JSONB
            )
        """,
    )
    def test_decorator_custom_schema_example(self):
        """Example using decorator with custom schema."""
        print("\n=== Running decorator custom schema example ===")

        # Insert test data with JSON metadata
        self.session.execute(
            sqlalchemy.text(
                f"""
                INSERT INTO {self.table_name} (user_id, action, metadata) VALUES
                (1, 'login', '{{"ip": "192.168.1.1", "user_agent": "Chrome"}}'),
                (2, 'logout', '{{"ip": "192.168.1.2", "user_agent": "Firefox"}}'),
                (1, 'purchase', '{{"amount": 99.99, "currency": "USD"}}')
                """
            )
        )

        self.session.commit()

        # Test the data
        result = self.session.execute(
            sqlalchemy.text(f"SELECT COUNT(*) FROM {self.table_name}")
        )
        count = result.fetchone()[0]
        self.assertEqual(count, 3)

        print(
            f"[OK] Decorator custom schema example passed! Table '{self.table_name}' will be cleaned up automatically."
        )

    def _create_simple_table(self, session, table_name):
        """Create simple test table."""
        session.execute(
            sqlalchemy.text(
                f"""
            CREATE TABLE {table_name} (
                id SERIAL PRIMARY KEY,
                name VARCHAR(50),
                value INTEGER
            )
        """
            )
        )

    def _insert_simple_data(self, session, table_name):
        """Insert simple test data."""
        session.execute(
            sqlalchemy.text(
                f"""
            INSERT INTO {table_name} (name, value) VALUES
            ('Alice', 100),
            ('Bob', 200),
            ('Charlie', 300)
        """
            )
        )
        session.commit()

    def _verify_simple_data(self, session, table_name):
        """Verify simple test data."""
        result = session.execute(sqlalchemy.text(f"SELECT COUNT(*) FROM {table_name}"))
        self.assertEqual(result.fetchone()[0], 3)

        result = session.execute(
            sqlalchemy.text(f"SELECT value FROM {table_name} WHERE name = 'Alice'")
        )
        self.assertEqual(result.fetchone()[0], 100)

    def test_successful_operation(self):
        """Example test that succeeds - table will be cleaned up."""
        print("\n=== Running successful test ===")

        session, table_name, cleanup_needed = self.test_helper.create_debug_table(
            "example_success"
        )

        try:
            self._create_simple_table(session, table_name)
            self._insert_simple_data(session, table_name)
            self._verify_simple_data(session, table_name)

            print(f"[OK] Test passed! Table '{table_name}' will be cleaned up.")
            cleanup_needed = True

        except Exception:
            cleanup_needed = False
            print(
                f"[DEBUG] DEBUG: Test failed! Table '{table_name}' kept for debugging."
            )
            raise

        finally:
            self.test_helper.cleanup_debug_table(session, table_name, cleanup_needed)

    def _create_product_table(self, session, table_name):
        """Create product table for failing test."""
        session.execute(
            sqlalchemy.text(
                f"""
            CREATE TABLE {table_name} (
                id SERIAL PRIMARY KEY,
                product VARCHAR(50),
                price DECIMAL(10,2)
            )
        """
            )
        )

    def _insert_product_data(self, session, table_name):
        """Insert product test data."""
        session.execute(
            sqlalchemy.text(
                f"""
            INSERT INTO {table_name} (product, price) VALUES
            ('Widget A', 19.99),
            ('Widget B', 29.99),
            ('Widget C', 39.99)
        """
            )
        )
        session.commit()

    def _verify_failing_condition(self, session, table_name):
        """Verify failing condition (expects 2 rows, gets 3)."""
        result = session.execute(sqlalchemy.text(f"SELECT COUNT(*) FROM {table_name}"))
        count = result.fetchone()[0]
        self.assertEqual(count, 2)  # This will fail!
        return count

    def test_failing_operation(self):
        """Example test that fails - table will be kept for debugging."""
        print("\n=== Running failing test ===")

        session, table_name, cleanup_needed = self.test_helper.create_debug_table(
            "example_failure"
        )

        try:
            self._create_product_table(session, table_name)
            self._insert_product_data(session, table_name)
            count = self._verify_failing_condition(session, table_name)
            cleanup_needed = True

        except Exception:
            cleanup_needed = False
            print(f"[DEBUG] Test failed! Table '{table_name}' kept for debugging.")
            print(f"   You can inspect it with: SELECT * FROM {table_name};")
            print(
                f"   Table contains {count if 'count' in locals() else 'unknown'} rows"
            )
            raise

        finally:
            self.test_helper.cleanup_debug_table(session, table_name, cleanup_needed)

    def _get_user_actions_schema(self):
        """Get schema for user actions table."""
        return """
            CREATE TABLE {table_name} (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                action VARCHAR(100) NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                metadata JSONB
            )
        """

    def _insert_user_actions_data(self, session, table_name):
        """Insert user actions test data."""
        session.execute(
            sqlalchemy.text(
                f"""
            INSERT INTO {table_name} (user_id, action, metadata) VALUES
            (1, 'login', '{{"ip": "192.168.1.1", "user_agent": "Chrome"}}'),
            (2, 'logout', '{{"ip": "192.168.1.2", "user_agent": "Firefox"}}'),
            (1, 'purchase', '{{"amount": 99.99, "currency": "USD"}}')
        """
            )
        )
        session.commit()

    def _verify_user_actions_data(self, session, table_name):
        """Verify user actions data."""
        result = session.execute(sqlalchemy.text(f"SELECT COUNT(*) FROM {table_name}"))
        self.assertEqual(result.fetchone()[0], 3)

        result = session.execute(
            sqlalchemy.text(f"SELECT COUNT(*) FROM {table_name} WHERE user_id = 1")
        )
        self.assertEqual(result.fetchone()[0], 2)

    def test_custom_schema(self):
        """Example test using custom table schema."""
        print("\n=== Running custom schema test ===")

        custom_schema = self._get_user_actions_schema()
        session, table_name, cleanup_needed = (
            self.test_helper.create_debug_table_with_schema(
                "custom_test", custom_schema
            )
        )

        try:
            self._insert_user_actions_data(session, table_name)
            self._verify_user_actions_data(session, table_name)

            print(
                f"[OK] Custom schema test passed! Table '{table_name}' will be cleaned up."
            )
            cleanup_needed = True

        except Exception:
            cleanup_needed = False
            print(
                f"[ERROR] Custom schema test failed! Table '{table_name}' kept for debugging."
            )
            raise

        finally:
            self.test_helper.cleanup_debug_table(session, table_name, cleanup_needed)

    def _create_employee_table(self, session, table_name):
        """Create employee table for inspection test."""
        session.execute(
            sqlalchemy.text(
                f"""
            CREATE TABLE {table_name} (
                id SERIAL PRIMARY KEY,
                name VARCHAR(50),
                age INTEGER,
                active BOOLEAN DEFAULT TRUE,
                department VARCHAR(30)
            )
        """
            )
        )

    def _insert_employee_data(self, session, table_name):
        """Insert employee test data."""
        session.execute(
            sqlalchemy.text(
                f"""
            INSERT INTO {table_name} (name, age, active, department) VALUES
            ('John', 25, TRUE, 'Engineering'),
            ('Jane', 30, FALSE, 'Marketing'),
            ('Bob', 35, TRUE, 'Engineering'),
            ('Alice', 28, TRUE, 'Sales')
        """
            )
        )
        session.commit()

    def _verify_table_inspection(self, session, table_name):
        """Verify table inspection capabilities."""
        table_info = self.test_helper.inspect_debug_table(table_name)
        self.assertIsNotNone(table_info)
        self.assertEqual(table_info["table_name"], table_name)
        self.assertEqual(table_info["row_count"], 4)
        self.assertEqual(len(table_info["columns"]), 5)

        debug_tables = self.test_helper.list_debug_tables()
        self.assertIn(table_name, debug_tables)

        result = session.execute(
            sqlalchemy.text(f"SELECT COUNT(*) FROM {table_name} WHERE active = TRUE")
        )
        self.assertEqual(result.fetchone()[0], 3)

    def _print_inspection_debug_info(self, table_name):
        """Print inspection debug information on failure."""
        print(f"\n[CHART] Inspecting table '{table_name}':")
        table_info = self.test_helper.inspect_debug_table(table_name)

        if table_info:
            print(
                f"   Columns: {[col['column_name'] for col in table_info['columns']]}"
            )
            print(f"   Rows: {len(table_info['contents'])}")
            print("   Data:")
            for row in table_info["contents"]:
                print(f"     {row}")
        else:
            print(
                f"   Could not inspect table '{table_name}' - check database connection"
            )

    def test_table_inspection(self):
        """Example test demonstrating table inspection capabilities."""
        print("\n=== Running table inspection test ===")

        session, table_name, cleanup_needed = self.test_helper.create_debug_table(
            "inspection_test"
        )

        try:
            self._create_employee_table(session, table_name)
            self._insert_employee_data(session, table_name)
            self._verify_table_inspection(session, table_name)

            print(
                f"[OK] Table inspection test passed! Table '{table_name}' will be cleaned up."
            )
            cleanup_needed = True

        except Exception:
            cleanup_needed = False
            print(f"[DEBUG] Test failed! Table '{table_name}' kept for debugging.")
            self._print_inspection_debug_info(table_name)
            raise

        finally:
            self.test_helper.cleanup_debug_table(session, table_name, cleanup_needed)

    def _create_orders_table(self, session, table_name):
        """Create orders table for complex scenario."""
        session.execute(
            sqlalchemy.text(
                f"""
            CREATE TABLE {table_name} (
                id SERIAL PRIMARY KEY,
                order_id VARCHAR(20) UNIQUE NOT NULL,
                customer_id INTEGER NOT NULL,
                order_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                total_amount DECIMAL(10,2) NOT NULL,
                status VARCHAR(20) DEFAULT 'pending',
                shipping_address TEXT,
                payment_method VARCHAR(30)
            )
        """
            )
        )

    def _insert_test_orders(self, session, table_name):
        """Insert test order data."""
        session.execute(
            sqlalchemy.text(
                f"""
            INSERT INTO {table_name} (order_id, customer_id, total_amount, status, shipping_address, payment_method) VALUES
            ('ORD-001', 1001, 149.99, 'shipped', '123 Main St, City, State', 'credit_card'),
            ('ORD-002', 1002, 89.50, 'pending', '456 Oak Ave, City, State', 'paypal'),
            ('ORD-003', 1001, 299.99, 'delivered', '123 Main St, City, State', 'credit_card'),
            ('ORD-004', 1003, 75.00, 'cancelled', '789 Pine Rd, City, State', 'credit_card')
        """
            )
        )
        session.commit()

    def _verify_order_business_logic(self, session, table_name):
        """Verify business logic for orders."""
        # Total orders count
        result = session.execute(sqlalchemy.text(f"SELECT COUNT(*) FROM {table_name}"))
        self.assertEqual(result.fetchone()[0], 4)

        # Orders by customer
        result = session.execute(
            sqlalchemy.text(
                f"SELECT COUNT(*) FROM {table_name} WHERE customer_id = 1001"
            )
        )
        self.assertEqual(result.fetchone()[0], 2)

        # Total revenue
        result = session.execute(
            sqlalchemy.text(
                f"SELECT SUM(total_amount) FROM {table_name} WHERE status != 'cancelled'"
            )
        )
        self.assertEqual(float(result.fetchone()[0]), 539.48)

        # Orders by status
        result = session.execute(
            sqlalchemy.text(
                f"SELECT COUNT(*) FROM {table_name} WHERE status = 'pending'"
            )
        )
        self.assertEqual(result.fetchone()[0], 1)

    def test_complex_scenario(self):
        """Example of a more complex testing scenario."""
        print("\n=== Running complex scenario test ===")

        session, table_name, cleanup_needed = self.test_helper.create_debug_table(
            "complex_test"
        )

        try:
            self._create_orders_table(session, table_name)
            self._insert_test_orders(session, table_name)
            self._verify_order_business_logic(session, table_name)

            print(
                f"[OK] Complex scenario test passed! Table '{table_name}' will be cleaned up."
            )
            cleanup_needed = True

        except Exception:
            cleanup_needed = False
            print(
                f"[DEBUG] Complex scenario test failed! Table '{table_name}' kept for debugging."
            )
            print(f"   You can inspect it with: SELECT * FROM {table_name};")
            raise

        finally:
            self.test_helper.cleanup_debug_table(session, table_name, cleanup_needed)


def _print_demo_summary(result):
    """Print test execution summary."""
    print("\n" + "=" * 60)
    print("Example Summary:")
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")

    if result.failures:
        print("\nFailures (expected for demo purposes):")
        for test, traceback in result.failures:
            print(f"  - {test}")

    if result.errors:
        print("\nErrors:")
        for test, traceback in result.errors:
            print(f"  - {test}: {traceback}")


def _print_key_features():
    """Print key features demonstrated by examples."""
    print("\n" + "=" * 60)
    print("Key Features Demonstrated:")
    print("[OK] Debug tables persist on test failure")
    print("[OK] Debug tables clean up on test success")
    print("[OK] Custom schema support")
    print("[OK] Table inspection capabilities")
    print("[OK] Complex testing scenarios")
    print("[OK] Automatic cleanup of previous debug tables")


def run_examples():
    """Run the example tests with detailed output."""
    print("PGTestCaseHelper Comprehensive Example")
    print("=" * 60)
    print()
    print("This example demonstrates:")
    print("1. Basic success/failure scenarios")
    print("2. Custom table schemas")
    print("3. Table inspection capabilities")
    print("4. Complex real-world testing scenarios")
    print("5. Debug table management")
    print()

    # Create test suite
    suite = unittest.TestLoader().loadTestsFromTestCase(TestPGHelperExample)

    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    _print_demo_summary(result)
    _print_key_features()


if __name__ == "__main__":
    run_examples()
