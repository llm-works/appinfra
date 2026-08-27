# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Database management module for handling multiple database connections.

This module provides a database manager that can handle multiple database
connections of different types, supporting PostgreSQL and SQLite.
"""

from typing import Any

from ..log import Logger, LoggerFactory
from . import pg, sqlite


class UnknownDBTypeException(Exception):
    """
    Exception raised when an unsupported database type is encountered.

    Attributes:
        _url: The database URL that caused the exception
    """

    def __init__(self, url: str) -> None:
        """
        Initialize the unknown database type exception.

        Args:
            url (str): Database URL that is not supported
        """
        super().__init__(f"Unknown database type: {url}")
        self._url = url


# Helper functions for Manager.setup()


def _setup_postgresql_database(
    name: str, db_cfg: Any, lg: Any, lg_level: Any, dbs_dict: dict
) -> None:
    """Set up a PostgreSQL database connection."""
    dbs_dict[name] = pg.PG(lg, db_cfg, query_lg_level=lg_level)
    lg.debug("registered pg", extra={"db": name} | db_cfg.dict())


def _setup_sqlite_database(name: str, db_cfg: Any, lg: Any, dbs_dict: dict) -> None:
    """Set up a SQLite database connection."""
    dbs_dict[name] = sqlite.SQLite(lg, db_cfg)
    lg.debug("registered sqlite", extra={"db": name, "url": db_cfg.url})


def _handle_unknown_db_type(name: str, url: str, lg: Any, setup_errors: dict) -> None:
    """Handle unsupported database types."""
    error_msg = f"unsupported database type in URL: {url}"
    lg.error(error_msg, extra={"db": name, "url": url})
    setup_errors[name] = UnknownDBTypeException(url)


def _setup_single_database(
    name: str, cfg: Any, lg: Any, lg_level: Any, dbs: dict, errors: dict
) -> bool:
    """Set up a single database connection based on URL type."""
    url = cfg.url
    if url.startswith("postgresql") or url.startswith("postgres://"):
        _setup_postgresql_database(name, cfg, lg, lg_level, dbs)
        return True
    elif url.startswith("sqlite"):
        _setup_sqlite_database(name, cfg, lg, dbs)
        return True
    else:
        _handle_unknown_db_type(name, url, lg, errors)
        return False


def _check_setup_results(successful_count: int, setup_errors: dict, lg: Any) -> None:
    """Check setup results and log summary."""
    if successful_count == 0:
        raise RuntimeError("Failed to setup any database connections")

    if len(setup_errors) > 0:
        lg.warning(
            f"setup completed with {len(setup_errors)} errors",
            extra={"successful": successful_count, "failed": len(setup_errors)},
        )


class Manager:
    """
    Database manager for handling multiple database connections.

    Provides centralized management of database connections with support
    for different database types. Currently supports PostgreSQL databases.

    Features:
    - Multiple named database connections
    - Configuration validation
    - Health checks and monitoring
    - Error handling and recovery
    - Connection lifecycle management
    """

    def __init__(self, lg: Logger, cfg: Any) -> None:
        """
        Initialize the database manager.

        Args:
            lg: Logger instance for database operations
            cfg: Configuration object containing database settings

        Raises:
            ValueError: If configuration is invalid
            AttributeError: If required configuration keys are missing
        """
        if cfg is None:
            raise ValueError("Configuration cannot be None")
        if lg is None:
            raise ValueError("Logger cannot be None")

        self._cfg = cfg
        self._lg = LoggerFactory.derive(lg, "db")
        self._dbs: dict[str, Any] = {}
        self._setup_errors: dict[str, Exception] = {}

    def setup(self) -> None:
        """
        Set up all configured database connections.

        Creates database connections based on the configuration and
        registers them with the manager. Handles partial failures gracefully.

        Raises:
            UnknownDBTypeException: If an unsupported database type is encountered
            ValueError: If database configuration is invalid
            AttributeError: If required configuration keys are missing
        """
        if not hasattr(self._cfg, "dbs") or not self._cfg.dbs:
            raise ValueError("No database configurations found in 'dbs' section")

        if not hasattr(self._cfg, "logging"):
            self._lg.warning("no logging configuration found, using defaults")

        lg_level = (
            None  # Database query logging is now controlled via topics: "/infra/db/**"
        )
        successful_setups = 0

        for name, cfg in self._cfg.dbs.items():
            try:
                self._validate_db_config(name, cfg)
                if _setup_single_database(
                    name, cfg, self._lg, lg_level, self._dbs, self._setup_errors
                ):
                    successful_setups += 1
            except Exception as e:
                error_msg = f"failed to setup database '{name}': {e}"
                self._lg.error(error_msg, extra={"db": name, "exception": e})
                self._setup_errors[name] = e

        _check_setup_results(successful_setups, self._setup_errors, self._lg)

    def _validate_db_config(self, name: str, cfg: Any) -> None:
        """
        Validate database configuration.

        Args:
            name (str): Database name
            cfg: Database configuration object

        Raises:
            ValueError: If configuration is invalid
            AttributeError: If required keys are missing
        """
        if not hasattr(cfg, "url") or not cfg.url:
            raise ValueError(f"Database '{name}' missing required 'url' field")

        if not isinstance(cfg.url, str):
            raise ValueError(f"Database '{name}' URL must be a string")

        # Validate URL format - accept PostgreSQL or SQLite
        valid_prefixes = ("postgresql://", "postgres://", "sqlite://", "sqlite:///")
        if not cfg.url.startswith(valid_prefixes):
            raise ValueError(
                f"Database '{name}' URL must start with a supported prefix: "
                f"postgresql://, postgres://, or sqlite://"
            )

    def db(self, name: str) -> Any:
        """
        Get a database connection by name.

        Args:
            name (str): Name of the database connection

        Returns:
            Database connection instance

        Raises:
            KeyError: If database connection doesn't exist
            RuntimeError: If database setup failed
        """
        if name not in self._dbs:
            if name in self._setup_errors:
                raise RuntimeError(
                    f"Database '{name}' setup failed: {self._setup_errors[name]}"
                )
            else:
                raise KeyError(f"Database connection '{name}' not found")

        return self._dbs[name]

    def list_databases(self) -> list[str]:
        """
        Get list of available database connections.

        Returns:
            list: List of database names
        """
        return list(self._dbs.keys())

    def get_setup_errors(self) -> dict:
        """
        Get setup errors for failed database connections.

        Returns:
            dict: Dictionary mapping database names to error objects
        """
        return self._setup_errors.copy()

    def health_check(self, name: str | None = None) -> dict:
        """
        Perform health check on database connection(s).

        Args:
            name (str, optional): Specific database name to check. If None, checks all.

        Returns:
            dict: Health check results
        """
        results = {}

        if name:
            databases_to_check = [name] if name in self._dbs else []
        else:
            databases_to_check = list(self._dbs.keys())

        for db_name in databases_to_check:
            try:
                db = self._dbs[db_name]
                # Simple health check - try to connect
                conn = db.connect()
                conn.close()
                results[db_name] = {"status": "healthy", "error": None}
                self._lg.debug("health check passed", extra={"db": db_name})
            except Exception as e:
                results[db_name] = {"status": "unhealthy", "error": str(e)}
                self._lg.error(
                    "health check failed", extra={"db": db_name, "error": str(e)}
                )

        return results

    def close_all(self) -> None:
        """
        Close all database connections.

        Attempts to close all active database connections gracefully.
        Logs any errors encountered during closure.
        """
        for name, db in self._dbs.items():
            try:
                if hasattr(db, "engine") and hasattr(db.engine, "dispose"):
                    db.engine.dispose()
                self._lg.debug("closed database connection", extra={"db": name})
            except Exception as e:
                self._lg.error(
                    "error closing database connection",
                    extra={"db": name, "error": str(e)},
                )

        self._dbs.clear()
        self._lg.info("closed all database connections")

    def get_stats(self) -> dict:
        """
        Get statistics about database connections.

        Returns:
            dict: Statistics including connection counts and setup errors
        """
        return {
            "total_configured": len(self._cfg.dbs) if hasattr(self._cfg, "dbs") else 0,
            "successful_setups": len(self._dbs),
            "failed_setups": len(self._setup_errors),
            "available_databases": list(self._dbs.keys()),
            "failed_databases": list(self._setup_errors.keys()),
        }
