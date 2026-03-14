"""
PostgreSQL Test Helper Core - Debug Table Management.

This module provides the core functionality for managing debug tables in PostgreSQL tests.
Debug tables persist when tests fail (for debugging) but are cleaned up when tests succeed.
"""

import uuid
from typing import cast

import sqlalchemy

from appinfra.db.pg import PG

# Helper functions for PGTestHelperCore


def _get_debug_tables_to_cleanup(session) -> list[str]:
    """Get list of debug tables that need cleanup."""
    result = session.execute(
        sqlalchemy.text(
            """
            SELECT tablename FROM pg_tables
            WHERE schemaname = 'public'
            AND (tablename LIKE 'debug_test_table_%'
                 OR tablename LIKE 'example_debug_%'
                 OR tablename LIKE 'test_debug_%')
        """
        )
    )
    return [row[0] for row in result.fetchall()]


def _drop_debug_tables(session, tables_to_drop: list[str], lg) -> None:
    """Drop a list of debug tables."""
    for table_name in tables_to_drop:
        try:
            session.execute(sqlalchemy.text(f"DROP TABLE IF EXISTS {table_name}"))
            lg.info(f"   ✅ Removed: {table_name}")
        except Exception as e:
            lg.warning(f"   ⚠️  Could not remove {table_name}: {e}")
    session.commit()


def _get_default_table_schema(table_name: str) -> str:
    """Get default schema for debug table."""
    return f"""
        CREATE TABLE {table_name} (
            id SERIAL PRIMARY KEY,
            name VARCHAR(50),
            value INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """


def _check_table_exists(session, table_name: str) -> bool:
    """Check if a table exists in the public schema."""
    result = session.execute(
        sqlalchemy.text(
            """
            SELECT COUNT(*) FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = :table_name
        """
        ),
        {"table_name": table_name},
    )
    return cast(bool, result.fetchone()[0] > 0)


def _get_table_columns(session, table_name: str) -> list[dict]:
    """Get table column information."""
    columns_result = session.execute(
        sqlalchemy.text(
            """
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = :table_name
            ORDER BY ordinal_position
        """
        ),
        {"table_name": table_name},
    )
    return [dict(row) for row in columns_result.fetchall()]


def _get_table_contents(session, table_name: str, columns: list[dict]) -> list[dict]:
    """Get table contents as list of dictionaries."""
    contents_result = session.execute(sqlalchemy.text(f"SELECT * FROM {table_name}"))
    contents = []
    for row in contents_result.fetchall():
        row_dict = {}
        for i, column in enumerate(columns):
            row_dict[column["column_name"]] = row[i]
        contents.append(row_dict)
    return contents


class PGTestHelperCore:
    """
    Core helper class for managing debug tables in PostgreSQL tests.

    Features:
    - Creates debug tables that persist on test failure but clean up on success
    - Automatically cleans up previous debug tables when tests run
    - Provides clear debug messages and table inspection guidance
    """

    def __init__(self, pg_instance: PG):
        """
        Initialize the test helper.

        Args:
            pg_instance: PostgreSQL instance to use for database operations
        """
        self.pg = pg_instance
        self.lg = pg_instance._lg  # Use the logger from the PG instance
        self._cleanup_previous_tables()

    def _cleanup_previous_tables(self):
        """Clean up any leftover debug tables from previous test runs."""
        try:
            cleanup_session = self.pg.session()
            tables_to_drop = _get_debug_tables_to_cleanup(cleanup_session)

            if tables_to_drop:
                self.lg.info(
                    f"🧹 Cleaning up {len(tables_to_drop)} leftover debug tables from previous runs..."
                )
                _drop_debug_tables(cleanup_session, tables_to_drop, self.lg)
                self.lg.info("🧹 Cleanup complete!")
            else:
                self.lg.info("🧹 No leftover debug tables found")

            cleanup_session.close()

        except Exception as e:
            self.lg.warning(f"⚠️  Warning: Could not cleanup previous tables: {e}")

    def create_debug_table(
        self, table_name_prefix: str = "debug_test_table"
    ) -> tuple[sqlalchemy.orm.Session, str, bool]:
        """
        Create a debug table that persists on test failure but gets cleaned up on success.

        Args:
            table_name_prefix: Prefix for the table name (default: "debug_test_table")

        Returns:
            tuple: (session, table_name, cleanup_needed_flag)
                - session: Database session for the test
                - table_name: Unique name of the created table
                - cleanup_needed: Boolean flag (initially False, set to True if test succeeds)
        """
        session = self.pg.session()
        # Use UUID suffix to avoid collisions in parallel test runs
        unique_suffix = uuid.uuid4().hex[:8]
        test_table_name = f"{table_name_prefix}_{unique_suffix}"
        cleanup_needed = False
        return session, test_table_name, cleanup_needed

    def cleanup_debug_table(
        self, session: sqlalchemy.orm.Session, table_name: str, cleanup_needed: bool
    ):
        """
        Clean up debug table if test passed.

        Args:
            session: Database session
            table_name: Name of table to potentially cleanup
            cleanup_needed: Boolean flag indicating if cleanup should happen
        """
        try:
            session.close()

            # Only cleanup if test passed
            if cleanup_needed:
                try:
                    cleanup_session = self.pg.session()
                    cleanup_session.execute(sqlalchemy.text(f"DROP TABLE {table_name}"))
                    cleanup_session.commit()  # Commit the DROP TABLE
                    cleanup_session.close()
                    self.lg.info(
                        f"✅ Cleaned up table '{table_name}' after successful test"
                    )
                except Exception as cleanup_error:
                    self.lg.warning(
                        f"⚠️  Warning: Could not cleanup table '{table_name}': {cleanup_error}"
                    )
            else:
                self.lg.info(f"🔍 Table '{table_name}' left for debugging")
                self.lg.info(f"   You can inspect it with: SELECT * FROM {table_name};")

        except Exception as e:
            self.lg.warning(f"⚠️  Warning: Error during cleanup: {e}")

    def create_debug_table_with_schema(
        self, table_name_prefix: str = "debug_test_table", schema: str | None = None
    ) -> tuple[sqlalchemy.orm.Session, str, bool]:
        """
        Create a debug table with a custom schema.

        Args:
            table_name_prefix: Prefix for the table name
            schema: SQL schema for the table (if None, uses a simple default schema)

        Returns:
            tuple: (session, table_name, cleanup_needed_flag)
        """
        session, table_name, cleanup_needed = self.create_debug_table(table_name_prefix)

        if schema is None:
            schema = _get_default_table_schema(table_name)

        try:
            formatted_schema = schema.format(table_name=table_name)
            session.execute(sqlalchemy.text(formatted_schema))
            session.commit()
            self.lg.info(
                "Created debug table with custom schema",
                extra={"table_name": table_name},
            )
            return session, table_name, cleanup_needed

        except Exception as e:
            session.close()
            self.lg.error(
                "Failed to create debug table",
                extra={"table_name": table_name, "error": str(e)},
            )
            raise

    def list_debug_tables(self) -> list[str]:
        """
        List all current debug tables in the database.

        Returns:
            List of debug table names
        """
        session = self.pg.session()
        try:
            result = session.execute(
                sqlalchemy.text(
                    """
                SELECT tablename FROM pg_tables
                WHERE schemaname = 'public'
                AND (tablename LIKE 'debug_test_table_%'
                     OR tablename LIKE 'example_debug_%'
                     OR tablename LIKE 'test_debug_%')
                ORDER BY tablename
            """
                )
            )

            return [row[0] for row in result.fetchall()]

        except Exception as e:
            self.lg.warning("could not list debug tables", extra={"error": str(e)})
            return []
        finally:
            session.close()

    def inspect_debug_table(self, table_name: str) -> dict | None:
        """
        Inspect a debug table and return its contents.

        Args:
            table_name: Name of the table to inspect

        Returns:
            Dictionary with table info and contents, or None if table doesn't exist
        """
        session = self.pg.session()
        try:
            if not _check_table_exists(session, table_name):
                return None

            columns = _get_table_columns(session, table_name)
            contents = _get_table_contents(session, table_name, columns)

            return {
                "table_name": table_name,
                "columns": columns,
                "contents": contents,
                "row_count": len(contents),
            }

        except Exception as e:
            self.lg.warning(
                "Could not inspect debug table",
                extra={"table_name": table_name, "error": str(e)},
            )
            return None
        finally:
            session.close()

    def cleanup_all_debug_tables(self):
        """Manually clean up all debug tables (useful for cleanup scripts)."""
        self._cleanup_previous_tables()
