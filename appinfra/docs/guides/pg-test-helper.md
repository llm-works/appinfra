---
title: PGTestCaseHelper Guide
keywords:
  - postgresql
  - postgres
  - test database
  - debug tables
  - test helper
  - pg fixtures
  - integration test
  - cleanup
aliases:
  - pg-helper
  - postgres-testing
---

# PGTestCaseHelper Guide

PostgreSQL test helper that manages debug tables: persists them when tests fail (for debugging),
cleans up on success.

## Quick Start

```python
from tests.helpers.pg.helper import PGTestCaseHelper
import sqlalchemy


class TestMyFeature(PGTestCaseHelper):
    def test_my_feature(self):
        session, table_name, cleanup_needed = self.test_helper.create_debug_table(
            "my_test"
        )

        try:
            # Create table and test
            session.execute(
                sqlalchemy.text(
                    f"CREATE TABLE {table_name} (id SERIAL, name VARCHAR(50))"
                )
            )
            session.execute(
                sqlalchemy.text(f"INSERT INTO {table_name} (name) VALUES ('test')")
            )
            session.commit()

            # Assertions
            result = session.execute(
                sqlalchemy.text(f"SELECT COUNT(*) FROM {table_name}")
            )
            self.assertEqual(result.fetchone()[0], 1)

            cleanup_needed = True  # Success - cleanup table
        except Exception:
            cleanup_needed = False  # Failure - keep table for debugging
            raise
        finally:
            self.test_helper.cleanup_debug_table(session, table_name, cleanup_needed)
```

## Core Methods

**create_debug_table(prefix="debug_test_table")**
- Returns: `(session, table_name, cleanup_flag)`
- Creates unique debug table

**cleanup_debug_table(session, table_name, cleanup_needed)**
- Cleans up table if `cleanup_needed=True`
- Keeps table for debugging if `cleanup_needed=False`

**create_debug_table_with_schema(prefix, schema)**
- Custom table schema (use `{table_name}` placeholder)

**Utility methods:**
- `list_debug_tables()` - List all debug tables
- `inspect_debug_table(name)` - Get table structure and contents
- `cleanup_all_debug_tables()` - Manual cleanup

## Examples

### Custom Schema
```python
schema = """
    CREATE TABLE {table_name} (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
"""
session, table_name, cleanup_needed = self.test_helper.create_debug_table_with_schema(
    "users", schema
)
```

### Custom Config
```python
class TestMyFeature(PGTestCaseHelper):
    @classmethod
    def setUpClass(cls):
        cls.set_config_path("path/to/config.yaml")
        super().setUpClass()
```

### Inspect Table
```python
table_info = self.test_helper.inspect_debug_table(table_name)
print(f"Rows: {table_info['row_count']}")
print(f"Columns: {[col['column_name'] for col in table_info['columns']]}")
```

## Best Practices

- Always use try/except/finally pattern
- Set `cleanup_needed=True` on success, `False` on failure
- Use descriptive table name prefixes
- Inspect failed tables to debug issues
