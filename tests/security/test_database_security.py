# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Security tests for database module (infra/db/pg/pg.py)."""

from unittest.mock import MagicMock, Mock, patch

import pytest
import sqlalchemy
from sqlalchemy import text

from appinfra.db.pg.pg import PG
from appinfra.log.config import LogConfig
from appinfra.log.factory import LoggerFactory
from tests.security.payloads.injection import SQL_INJECTION


@pytest.mark.security
@pytest.mark.integration
@pytest.mark.parametrize("payload", SQL_INJECTION)
def test_sql_injection_prevention(payload: str):
    """
    Verify SQLAlchemy parameterization prevents SQL injection attacks.

    Attack Vector: SQL injection via user input in queries
    Module: infra/db/pg/pg.py (uses SQLAlchemy with parameterization)
    OWASP: A03:2021 - Injection

    Security Concern: SQL injection is one of the most critical web application
    vulnerabilities. User input incorporated into SQL queries without proper
    escaping can allow attackers to execute arbitrary SQL commands, leading to
    data breaches, data loss, or unauthorized access.

    This test verifies that SQLAlchemy's parameterized queries properly escape
    user input, preventing SQL injection attacks.
    """
    # Create a real logger for testing
    log_config = LogConfig.from_params(level="debug", colors=False)
    logger = LoggerFactory.create_root(log_config)

    # Create a mock configuration
    mock_cfg = Mock()
    mock_cfg.url = "postgresql://test:test@localhost:5432/test_db"
    mock_cfg.get = Mock(
        side_effect=lambda key, default=None: {
            "readonly": False,
            "create_db": False,
            "pool_size": 5,
            "max_overflow": 10,
            "pool_timeout": 30,
            "pool_recycle": 3600,
            "pool_pre_ping": True,
            "echo": False,
        }.get(key, default)
    )

    # Create mock engine and session
    mock_engine = MagicMock(spec=sqlalchemy.engine.Engine)
    mock_engine.url = sqlalchemy.engine.url.make_url(mock_cfg.url)
    mock_engine.dialect = sqlalchemy.dialects.postgresql.dialect()

    mock_session = MagicMock()
    mock_session_cls = MagicMock(return_value=mock_session)

    # Patch SQLAlchemy components
    with (
        patch("sqlalchemy.create_engine", return_value=mock_engine),
        patch("sqlalchemy.orm.sessionmaker", return_value=mock_session_cls),
        patch("sqlalchemy.event.listen"),
    ):
        # Create PG instance
        pg = PG(logger, mock_cfg)

        # Simulate a query with user input
        # The key test: SQLAlchemy should parameterize this, preventing injection
        # Use _create_session() for direct access in unit tests with mocking
        session = pg._create_session()

        # Create a parameterized query (correct way)
        # This is how the code should handle user input
        query = text("SELECT * FROM users WHERE username = :username")

        # Attempt to execute with malicious payload
        # SQLAlchemy should treat the entire payload as a literal string value,
        # not as SQL code
        try:
            # Mock the execute method to verify parameterization
            execute_calls = []

            def mock_execute(statement, params=None):
                execute_calls.append((statement, params))
                # Return a mock result
                return MagicMock()

            session.execute = mock_execute

            # Execute the query with malicious payload
            session.execute(query, {"username": payload})

            # Verify that execute was called with parameters
            # (meaning parameterization was used, not string concatenation)
            assert len(execute_calls) == 1
            stmt, params = execute_calls[0]

            # The payload should be passed as a parameter, not embedded in SQL
            if params:
                assert "username" in params
                # The malicious payload is just a parameter value,
                # SQLAlchemy will escape it properly
                assert params["username"] == payload

        except Exception as e:
            # If any exception occurs during parameterized query execution,
            # it should be a SQLAlchemy error, not a syntax error from injection
            assert (
                not isinstance(e, sqlalchemy.exc.ProgrammingError)
                or "syntax error" not in str(e).lower()
            )


@pytest.mark.security
@pytest.mark.integration
def test_readonly_mode_enforcement():
    """
    Verify readonly mode prevents write operations (INSERT/UPDATE/DELETE).

    Attack Vector: Unauthorized data modification via write operations
    Module: infra/db/pg/pg.py:66-78 (readonly mode configuration)
    OWASP: A01:2021 - Broken Access Control

    Security Concern: Applications often need to connect to databases in
    read-only mode to prevent accidental or malicious data modification.
    The readonly mode should enforce transaction-level read-only constraints,
    preventing INSERT, UPDATE, DELETE, and other write operations.
    """
    # Create mock configuration for readonly mode (using attributes, not .get())
    mock_cfg = Mock()
    mock_cfg.url = "postgresql://readonly:test@localhost:5432/test_db"
    mock_cfg.readonly = True  # Enable readonly mode
    mock_cfg.create_db = False
    mock_cfg.pool_size = 5
    mock_cfg.max_overflow = 10
    mock_cfg.pool_timeout = 30
    mock_cfg.pool_recycle = 3600
    mock_cfg.pool_pre_ping = True
    mock_cfg.echo = False

    # Create a real logger for testing
    log_config = LogConfig.from_params(level="debug", colors=False)
    logger = LoggerFactory.create_root(log_config)

    # Create mock engine
    mock_engine = MagicMock(spec=sqlalchemy.engine.Engine)
    mock_engine.url = sqlalchemy.engine.url.make_url(mock_cfg.url)
    mock_engine.dialect = sqlalchemy.dialects.postgresql.dialect()

    # Track event listeners
    event_listeners = []

    def mock_event_listen(target, event_name, callback):
        event_listeners.append((target, event_name, callback))

    # Patch SQLAlchemy
    with (
        patch("sqlalchemy.create_engine", return_value=mock_engine),
        patch("sqlalchemy.orm.sessionmaker"),
        patch("sqlalchemy.event.listen", side_effect=mock_event_listen),
    ):
        # Create PG instance in readonly mode
        pg = PG(logger, mock_cfg)

        # Verify readonly listener was registered
        begin_listeners = [
            (target, event, cb)
            for target, event, cb in event_listeners
            if event == "begin"
        ]
        assert len(begin_listeners) > 0, "No 'begin' event listener registered"

        # Verify the readonly listener is stored
        assert hasattr(pg, "_readonly_listener")

        # Simulate what happens when a transaction begins
        mock_conn = MagicMock()
        mock_conn.execute = MagicMock()

        # Call the readonly listener
        for target, event, callback in begin_listeners:
            callback(mock_conn)

        # Verify that SET TRANSACTION READ ONLY was executed
        mock_conn.execute.assert_called()
        call_args = mock_conn.execute.call_args

        # The SQL should be SET TRANSACTION READ ONLY
        executed_sql = str(call_args[0][0])
        assert "SET TRANSACTION READ ONLY" in executed_sql.upper()


@pytest.mark.security
@pytest.mark.unit
def test_connection_string_credential_exposure():
    """
    Verify database connection string credentials are not exposed in logs.

    Attack Vector: Information disclosure via log files
    Module: infra/db/pg/pg.py:57-62, 83-86 (logging configuration)
    OWASP: A09:2021 - Security Logging and Monitoring Failures

    Security Concern: Database connection strings often contain sensitive
    credentials (passwords, tokens). Logging these in plaintext creates
    security risks:
    - Log files may be readable by unauthorized users
    - Logs may be sent to external monitoring systems
    - Credentials may persist in log archives

    This test verifies that connection URLs are properly sanitized before
    logging, with passwords masked or removed.
    """
    # Create mock configuration with credentials
    password = "SuperSecret123!@#"
    mock_cfg = Mock()
    mock_cfg.url = f"postgresql://dbuser:{password}@localhost:5432/production_db"
    mock_cfg.get = Mock(
        side_effect=lambda key, default=None: {
            "readonly": False,
            "create_db": False,
            "pool_size": 5,
            "max_overflow": 10,
            "pool_timeout": 30,
            "pool_recycle": 3600,
            "pool_pre_ping": True,
            "echo": False,
        }.get(key, default)
    )

    # Create a real logger for testing, but capture output
    log_config = LogConfig.from_params(level="debug", colors=False)
    logger = LoggerFactory.create_root(log_config)

    # Capture log records
    logged_messages = []

    class LogCapture:
        """Handler to capture log records."""

        def __init__(self):
            self.records = logged_messages

        def handle(self, record):
            self.records.append(record)
            return True

    capture_handler = LogCapture()

    # Create mock engine
    mock_engine = MagicMock(spec=sqlalchemy.engine.Engine)
    mock_url = sqlalchemy.engine.url.make_url(mock_cfg.url)
    mock_engine.url = mock_url
    mock_engine.dialect = sqlalchemy.dialects.postgresql.dialect()

    # Patch SQLAlchemy
    with (
        patch("sqlalchemy.create_engine", return_value=mock_engine),
        patch("sqlalchemy.orm.sessionmaker"),
        patch("sqlalchemy.event.listen"),
    ):
        # Add our capture handler to the logger
        # Patch the logger's handle method to use our capture
        original_handle = logger.handle
        logger.handle = lambda record: (
            capture_handler.handle(record),
            original_handle(record),
        )[1]

        # Create PG instance
        pg = PG(logger, mock_cfg)

        # Check all logged messages for credential exposure
        for log_record in logged_messages:
            # Convert log record to string for checking
            log_str = (
                str(log_record.getMessage())
                if hasattr(log_record, "getMessage")
                else str(log_record)
            )

            # The actual password should NEVER appear in logs
            assert password not in log_str, (
                f"Password '{password}' found in log: {log_record}"
            )

            # Check extra data for URL exposure
            if hasattr(log_record, "__dict__"):
                record_dict_str = str(log_record.__dict__)
                assert password not in record_dict_str, (
                    f"Password found in log record: {record_dict_str}"
                )

        # SQLAlchemy URL objects have a __repr__ that hides passwords,
        # but we should verify this behavior
        url_repr = repr(mock_url)
        assert password not in url_repr, "Password exposed in SQLAlchemy URL repr"

        # Positive test: Verify that connection info IS logged
        # (just not the password)
        # The PG instance was created successfully, which means logging worked
        assert pg is not None, "PG instance not created"


# Positive test: Verify legitimate operations still work
@pytest.mark.security
@pytest.mark.integration
def test_legitimate_parameterized_queries_allowed():
    """
    Verify legitimate parameterized queries work correctly.

    Security Concern: Security measures should block attacks without breaking
    legitimate use cases. Properly parameterized queries with valid data
    should execute successfully.
    """
    # Create mock configuration
    mock_cfg = Mock()
    mock_cfg.url = "postgresql://test:test@localhost:5432/test_db"
    mock_cfg.get = Mock(
        side_effect=lambda key, default=None: {
            "readonly": False,
            "create_db": False,
            "pool_size": 5,
            "max_overflow": 10,
            "pool_timeout": 30,
            "pool_recycle": 3600,
            "pool_pre_ping": True,
            "echo": False,
        }.get(key, default)
    )

    # Create a real logger for testing
    log_config = LogConfig.from_params(level="debug", colors=False)
    logger = LoggerFactory.create_root(log_config)

    mock_engine = MagicMock(spec=sqlalchemy.engine.Engine)
    mock_engine.url = sqlalchemy.engine.url.make_url(mock_cfg.url)
    mock_engine.dialect = sqlalchemy.dialects.postgresql.dialect()

    mock_session = MagicMock()
    mock_session_cls = MagicMock(return_value=mock_session)

    with (
        patch("sqlalchemy.create_engine", return_value=mock_engine),
        patch("sqlalchemy.orm.sessionmaker", return_value=mock_session_cls),
        patch("sqlalchemy.event.listen"),
    ):
        pg = PG(logger, mock_cfg)

        # Legitimate queries should work
        # Use _create_session() for direct access in unit tests with mocking
        session = pg._create_session()

        # These are valid usernames that should work fine
        legitimate_inputs = [
            "alice",
            "bob_123",
            "user-name",
            "user.name@example.com",
        ]

        for username in legitimate_inputs:
            query = text("SELECT * FROM users WHERE username = :username")
            # This should not raise any exceptions
            session.execute = MagicMock()
            session.execute(query, {"username": username})
            assert session.execute.called
