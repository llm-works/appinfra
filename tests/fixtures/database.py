# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Database fixtures for testing.

Provides fixtures for database connections, mock databases,
and database-related test utilities.
"""

from collections.abc import Generator
from typing import Any
from unittest.mock import MagicMock, Mock

import pytest


@pytest.fixture
def mock_db_connection() -> Generator[Mock, None, None]:
    """
    Provide a mock database connection for testing.

    Yields:
        Mock: Mock database connection object
    """
    conn = Mock()
    conn.execute = Mock(return_value=Mock(fetchall=Mock(return_value=[])))
    conn.commit = Mock()
    conn.rollback = Mock()
    conn.close = Mock()
    conn.closed = False

    yield conn

    # Cleanup
    conn.close()


@pytest.fixture
def mock_db_cursor() -> Mock:
    """
    Provide a mock database cursor for testing.

    Returns:
        Mock: Mock database cursor
    """
    cursor = Mock()
    cursor.execute = Mock()
    cursor.fetchone = Mock(return_value=None)
    cursor.fetchall = Mock(return_value=[])
    cursor.fetchmany = Mock(return_value=[])
    cursor.rowcount = 0
    cursor.description = []

    return cursor


@pytest.fixture
def sample_db_config() -> dict[str, Any]:
    """
    Provide sample database configuration for testing.

    Returns:
        dict: Database configuration
    """
    return {
        "host": "localhost",
        "port": 5432,
        "database": "test_db",
        "user": "test_user",
        "password": "test_password",
        "pool_size": 5,
        "max_overflow": 10,
        "timeout": 30,
    }


@pytest.fixture
def mock_pg_connection(mock_db_cursor: Mock) -> Generator[Mock, None, None]:
    """
    Provide a mock PostgreSQL connection for testing.

    Args:
        mock_db_cursor: Mock database cursor fixture

    Yields:
        Mock: Mock PostgreSQL connection
    """
    conn = MagicMock()
    conn.cursor = Mock(return_value=mock_db_cursor)
    conn.commit = Mock()
    conn.rollback = Mock()
    conn.close = Mock()
    conn.closed = False
    conn.autocommit = False

    yield conn

    conn.close()
