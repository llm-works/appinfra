"""
Database management module for handling multiple database connections.

This module provides a database manager that can handle multiple database
connections of different types, supporting PostgreSQL and SQLite.

Requires: pip install appinfra[sql]
"""

try:
    from .db import Manager, UnknownDBTypeException
    from .pg import PG, Interface
    from .sqlite import SQLite
    from .utils import detach, detach_all
except ImportError as e:
    # Use ModuleNotFoundError.name for reliable detection of missing sqlalchemy
    if (
        isinstance(e, ModuleNotFoundError)
        and e.name
        and e.name.startswith("sqlalchemy")
    ):
        from ..errors import DependencyError

        raise DependencyError("sqlalchemy", "sql", "Database module") from e
    raise

__all__ = [
    "Manager",
    "UnknownDBTypeException",
    "PG",
    "SQLite",
    "Interface",
    "detach",
    "detach_all",
]
