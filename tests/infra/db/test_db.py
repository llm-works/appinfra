# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for appinfra.db.db module (database manager).

Comprehensive tests for the database Manager class, covering initialization,
setup, connection management, health checks, and error handling.
"""

from unittest.mock import Mock, patch

import pytest

from appinfra.db.db import Manager, UnknownDBTypeException
from appinfra.log import Logger

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_logger():
    """Provide a mock logger for testing."""
    lg = Mock(spec=Logger)
    lg.debug = Mock()
    lg.info = Mock()
    lg.warning = Mock()
    lg.error = Mock()
    return lg


@pytest.fixture
def valid_pg_config():
    """Provide valid PostgreSQL database configuration."""
    # Create mock database configs with dict() method
    # Note: Only postgresql:// works, not postgres:// (despite validation accepting both)
    main_db_cfg = Mock(url="postgresql://localhost:5432/testdb")
    main_db_cfg.dict.return_value = {"url": "postgresql://localhost:5432/testdb"}

    replica_db_cfg = Mock(url="postgresql://localhost:5433/testdb")
    replica_db_cfg.dict.return_value = {"url": "postgresql://localhost:5433/testdb"}

    cfg = Mock()
    cfg.dbs = {
        "main": main_db_cfg,
        "replica": replica_db_cfg,
    }
    cfg.logging = Mock(pg_level=None)
    return cfg


@pytest.fixture
def invalid_config_no_dbs():
    """Provide configuration without dbs section."""
    cfg = Mock()
    del cfg.dbs  # Remove dbs attribute
    return cfg


@pytest.fixture
def invalid_config_empty_dbs():
    """Provide configuration with empty dbs."""
    cfg = Mock()
    cfg.dbs = {}
    return cfg


@pytest.fixture
def config_with_invalid_url():
    """Provide configuration with invalid database URL."""
    bad_db_cfg = Mock(url="mysql://localhost:3306/testdb")  # Unsupported
    bad_db_cfg.dict.return_value = {"url": "mysql://localhost:3306/testdb"}

    cfg = Mock()
    cfg.dbs = {
        "bad_db": bad_db_cfg,
    }
    cfg.logging = Mock(pg_level=None)
    return cfg


@pytest.fixture
def config_missing_url():
    """Provide configuration with missing URL."""
    cfg = Mock()
    cfg.dbs = {
        "no_url_db": Mock(spec=[]),  # No url attribute
    }
    return cfg


# =============================================================================
# Manager Initialization Tests
# =============================================================================


@pytest.mark.unit
class TestManagerInitialization:
    """Test Manager initialization and validation."""

    def test_init_with_valid_inputs(self, mock_logger, valid_pg_config):
        """Test successful initialization with valid inputs."""
        with patch("appinfra.db.db.LoggerFactory.derive") as mock_derive:
            mock_derive.return_value = mock_logger
            manager = Manager(mock_logger, valid_pg_config)

            assert manager._cfg == valid_pg_config
            assert manager._lg == mock_logger
            assert manager._dbs == {}
            assert manager._setup_errors == {}
            mock_derive.assert_called_once_with(mock_logger, "db")

    def test_init_with_none_config(self, mock_logger):
        """Test initialization fails with None config."""
        with pytest.raises(ValueError, match="Configuration cannot be None"):
            Manager(mock_logger, None)

    def test_init_with_none_logger(self, valid_pg_config):
        """Test initialization fails with None logger."""
        with pytest.raises(ValueError, match="Logger cannot be None"):
            Manager(None, valid_pg_config)

    def test_init_with_both_none(self):
        """Test initialization fails with both None."""
        # Config is checked first
        with pytest.raises(ValueError, match="Configuration cannot be None"):
            Manager(None, None)


# =============================================================================
# Manager Setup Tests
# =============================================================================


@pytest.mark.unit
class TestManagerSetup:
    """Test database connection setup."""

    def test_setup_with_no_dbs_config(self, mock_logger, invalid_config_no_dbs):
        """Test setup fails when dbs section is missing."""
        with patch("appinfra.db.db.LoggerFactory.derive", return_value=mock_logger):
            manager = Manager(mock_logger, invalid_config_no_dbs)

            with pytest.raises(ValueError, match="No database configurations found"):
                manager.setup()

    def test_setup_with_empty_dbs(self, mock_logger, invalid_config_empty_dbs):
        """Test setup fails when dbs section is empty."""
        with patch("appinfra.db.db.LoggerFactory.derive", return_value=mock_logger):
            manager = Manager(mock_logger, invalid_config_empty_dbs)

            with pytest.raises(ValueError, match="No database configurations found"):
                manager.setup()

    @patch("appinfra.db.db.pg.PG")
    def test_setup_postgresql_success(
        self, mock_pg_class, mock_logger, valid_pg_config
    ):
        """Test successful setup of PostgreSQL databases."""
        mock_pg_instance = Mock()
        mock_pg_class.return_value = mock_pg_instance

        with patch("appinfra.db.db.LoggerFactory.derive", return_value=mock_logger):
            manager = Manager(mock_logger, valid_pg_config)
            manager.setup()

            # Should create 2 PG instances (main and replica)
            assert mock_pg_class.call_count == 2
            assert len(manager._dbs) == 2
            assert "main" in manager._dbs
            assert "replica" in manager._dbs
            assert len(manager._setup_errors) == 0

    @patch("appinfra.db.db.sqlite.SQLite")
    def test_setup_sqlite_success(self, mock_sqlite_class, mock_logger):
        """Test successful setup of SQLite database."""
        mock_sqlite_instance = Mock()
        mock_sqlite_class.return_value = mock_sqlite_instance

        sqlite_cfg = Mock(url="sqlite:///:memory:")
        cfg = Mock()
        cfg.dbs = {"test_db": sqlite_cfg}
        cfg.logging = Mock(pg_level=None)

        with patch("appinfra.db.db.LoggerFactory.derive", return_value=mock_logger):
            manager = Manager(mock_logger, cfg)
            manager.setup()

            mock_sqlite_class.assert_called_once()
            assert len(manager._dbs) == 1
            assert "test_db" in manager._dbs
            assert len(manager._setup_errors) == 0

    def test_setup_with_unsupported_db_type(self, mock_logger, config_with_invalid_url):
        """Test setup with unsupported database type."""
        with patch("appinfra.db.db.LoggerFactory.derive", return_value=mock_logger):
            manager = Manager(mock_logger, config_with_invalid_url)

            with pytest.raises(
                RuntimeError, match="Failed to setup any database connections"
            ):
                manager.setup()

            # Should have setup error recorded (ValueError from validation, not UnknownDBTypeException)
            assert len(manager._setup_errors) == 1
            assert "bad_db" in manager._setup_errors
            assert isinstance(manager._setup_errors["bad_db"], ValueError)

    def test_setup_with_missing_url(self, mock_logger, config_missing_url):
        """Test setup fails when database config is missing URL."""
        with patch("appinfra.db.db.LoggerFactory.derive", return_value=mock_logger):
            manager = Manager(mock_logger, config_missing_url)

            with pytest.raises(
                RuntimeError, match="Failed to setup any database connections"
            ):
                manager.setup()

            assert len(manager._setup_errors) == 1
            assert "no_url_db" in manager._setup_errors

    @patch("appinfra.db.db.pg.PG")
    def test_setup_partial_failure(self, mock_pg_class, mock_logger):
        """Test setup with partial failures (some succeed, some fail)."""
        # First DB succeeds, second fails
        mock_pg_class.side_effect = [Mock(), Exception("Connection failed")]

        good_db_cfg = Mock(url="postgresql://localhost:5432/test")
        good_db_cfg.dict.return_value = {"url": "postgresql://localhost:5432/test"}

        bad_db_cfg = Mock(url="postgresql://localhost:5433/test")
        bad_db_cfg.dict.return_value = {"url": "postgresql://localhost:5433/test"}

        cfg = Mock()
        cfg.dbs = {
            "good_db": good_db_cfg,
            "bad_db": bad_db_cfg,
        }
        cfg.logging = Mock(pg_level=None)

        with patch("appinfra.db.db.LoggerFactory.derive", return_value=mock_logger):
            manager = Manager(mock_logger, cfg)
            manager.setup()  # Should not raise, partial success is allowed

            assert len(manager._dbs) == 1
            assert "good_db" in manager._dbs
            assert len(manager._setup_errors) == 1
            assert "bad_db" in manager._setup_errors

            # Should log warning about errors
            mock_logger.warning.assert_called()

    def test_setup_without_logging_config(self, mock_logger):
        """Test setup warns when logging config is missing."""
        main_db_cfg = Mock(url="postgresql://localhost:5432/test")
        main_db_cfg.dict.return_value = {"url": "postgresql://localhost:5432/test"}

        cfg = Mock()
        cfg.dbs = {
            "main": main_db_cfg,
        }
        del cfg.logging  # No logging section

        with patch("appinfra.db.db.LoggerFactory.derive", return_value=mock_logger):
            with patch("appinfra.db.db.pg.PG"):
                manager = Manager(mock_logger, cfg)
                manager.setup()

                # Should warn about missing logging config
                mock_logger.warning.assert_any_call(
                    "no logging configuration found, using defaults"
                )


# =============================================================================
# Database Access Tests
# =============================================================================


@pytest.mark.unit
class TestDatabaseAccess:
    """Test database connection retrieval."""

    @patch("appinfra.db.db.pg.PG")
    def test_db_returns_existing_connection(
        self, mock_pg_class, mock_logger, valid_pg_config
    ):
        """Test db() returns existing database connection."""
        mock_pg_instance = Mock()
        mock_pg_class.return_value = mock_pg_instance

        with patch("appinfra.db.db.LoggerFactory.derive", return_value=mock_logger):
            manager = Manager(mock_logger, valid_pg_config)
            manager.setup()

            db = manager.db("main")
            assert db == mock_pg_instance

    def test_db_raises_keyerror_for_nonexistent(self, mock_logger, valid_pg_config):
        """Test db() raises KeyError for non-existent database."""
        with patch("appinfra.db.db.LoggerFactory.derive", return_value=mock_logger):
            manager = Manager(mock_logger, valid_pg_config)
            # Don't call setup(), so no databases exist

            with pytest.raises(
                KeyError, match="Database connection 'nonexistent' not found"
            ):
                manager.db("nonexistent")

    def test_db_raises_runtimeerror_for_failed_setup(
        self, mock_logger, config_with_invalid_url
    ):
        """Test db() raises RuntimeError for database with failed setup."""
        with patch("appinfra.db.db.LoggerFactory.derive", return_value=mock_logger):
            manager = Manager(mock_logger, config_with_invalid_url)

            try:
                manager.setup()
            except RuntimeError:
                pass  # Expected failure

            with pytest.raises(RuntimeError, match="Database 'bad_db' setup failed"):
                manager.db("bad_db")


# =============================================================================
# Database Listing Tests
# =============================================================================


@pytest.mark.unit
class TestDatabaseListing:
    """Test database listing functionality."""

    @patch("appinfra.db.db.pg.PG")
    def test_list_databases(self, mock_pg_class, mock_logger, valid_pg_config):
        """Test list_databases returns all available databases."""
        with patch("appinfra.db.db.LoggerFactory.derive", return_value=mock_logger):
            manager = Manager(mock_logger, valid_pg_config)
            manager.setup()

            databases = manager.list_databases()
            assert len(databases) == 2
            assert "main" in databases
            assert "replica" in databases

    def test_list_databases_empty(self, mock_logger, valid_pg_config):
        """Test list_databases returns empty list before setup."""
        with patch("appinfra.db.db.LoggerFactory.derive", return_value=mock_logger):
            manager = Manager(mock_logger, valid_pg_config)
            # Don't call setup()

            databases = manager.list_databases()
            assert databases == []


# =============================================================================
# Error Tracking Tests
# =============================================================================


@pytest.mark.unit
class TestErrorTracking:
    """Test setup error tracking."""

    def test_get_setup_errors_empty(self, mock_logger, valid_pg_config):
        """Test get_setup_errors returns empty dict for successful setup."""
        with patch("appinfra.db.db.LoggerFactory.derive", return_value=mock_logger):
            with patch("appinfra.db.db.pg.PG"):
                manager = Manager(mock_logger, valid_pg_config)
                manager.setup()

                errors = manager.get_setup_errors()
                assert errors == {}

    def test_get_setup_errors_returns_failures(
        self, mock_logger, config_with_invalid_url
    ):
        """Test get_setup_errors returns failures."""
        with patch("appinfra.db.db.LoggerFactory.derive", return_value=mock_logger):
            manager = Manager(mock_logger, config_with_invalid_url)

            try:
                manager.setup()
            except RuntimeError:
                pass

            errors = manager.get_setup_errors()
            assert len(errors) == 1
            assert "bad_db" in errors
            # Validation rejects mysql://, so it's ValueError not UnknownDBTypeException
            assert isinstance(errors["bad_db"], ValueError)

    def test_get_setup_errors_returns_copy(self, mock_logger, config_with_invalid_url):
        """Test get_setup_errors returns a copy, not original dict."""
        with patch("appinfra.db.db.LoggerFactory.derive", return_value=mock_logger):
            manager = Manager(mock_logger, config_with_invalid_url)

            try:
                manager.setup()
            except RuntimeError:
                pass

            errors = manager.get_setup_errors()
            errors["new_key"] = "modified"

            # Original should not be modified
            assert "new_key" not in manager._setup_errors


# =============================================================================
# Health Check Tests
# =============================================================================


@pytest.mark.unit
class TestHealthCheck:
    """Test database health check functionality."""

    @patch("appinfra.db.db.pg.PG")
    def test_health_check_all_healthy(
        self, mock_pg_class, mock_logger, valid_pg_config
    ):
        """Test health_check with all databases healthy."""
        mock_db = Mock()
        mock_conn = Mock()
        mock_db.connect.return_value = mock_conn
        mock_pg_class.return_value = mock_db

        with patch("appinfra.db.db.LoggerFactory.derive", return_value=mock_logger):
            manager = Manager(mock_logger, valid_pg_config)
            manager.setup()

            results = manager.health_check()

            assert len(results) == 2
            assert results["main"]["status"] == "healthy"
            assert results["main"]["error"] is None
            assert results["replica"]["status"] == "healthy"
            assert mock_conn.close.call_count == 2

    @patch("appinfra.db.db.pg.PG")
    def test_health_check_single_database(
        self, mock_pg_class, mock_logger, valid_pg_config
    ):
        """Test health_check for a single database."""
        mock_db = Mock()
        mock_conn = Mock()
        mock_db.connect.return_value = mock_conn
        mock_pg_class.return_value = mock_db

        with patch("appinfra.db.db.LoggerFactory.derive", return_value=mock_logger):
            manager = Manager(mock_logger, valid_pg_config)
            manager.setup()

            results = manager.health_check(name="main")

            assert len(results) == 1
            assert "main" in results
            assert results["main"]["status"] == "healthy"

    @patch("appinfra.db.db.pg.PG")
    def test_health_check_connection_failure(
        self, mock_pg_class, mock_logger, valid_pg_config
    ):
        """Test health_check with connection failure."""
        mock_db = Mock()
        mock_db.connect.side_effect = Exception("Connection refused")
        mock_pg_class.return_value = mock_db

        with patch("appinfra.db.db.LoggerFactory.derive", return_value=mock_logger):
            manager = Manager(mock_logger, valid_pg_config)
            manager.setup()

            results = manager.health_check()

            assert results["main"]["status"] == "unhealthy"
            assert "Connection refused" in results["main"]["error"]

    def test_health_check_nonexistent_database(self, mock_logger, valid_pg_config):
        """Test health_check for non-existent database returns empty results."""
        with patch("appinfra.db.db.LoggerFactory.derive", return_value=mock_logger):
            with patch("appinfra.db.db.pg.PG"):
                manager = Manager(mock_logger, valid_pg_config)
                manager.setup()

                results = manager.health_check(name="nonexistent")

                assert results == {}


# =============================================================================
# Connection Management Tests
# =============================================================================


@pytest.mark.unit
class TestConnectionManagement:
    """Test database connection lifecycle management."""

    @patch("appinfra.db.db.pg.PG")
    def test_close_all_disposes_engines(
        self, mock_pg_class, mock_logger, valid_pg_config
    ):
        """Test close_all disposes all database engines."""
        mock_engine = Mock()
        mock_engine.dispose = Mock()

        mock_db = Mock()
        mock_db.engine = mock_engine
        mock_pg_class.return_value = mock_db

        with patch("appinfra.db.db.LoggerFactory.derive", return_value=mock_logger):
            manager = Manager(mock_logger, valid_pg_config)
            manager.setup()

            manager.close_all()

            # Should dispose both engines
            assert mock_engine.dispose.call_count == 2
            assert len(manager._dbs) == 0
            mock_logger.info.assert_called_with("closed all database connections")

    @patch("appinfra.db.db.pg.PG")
    def test_close_all_handles_errors(
        self, mock_pg_class, mock_logger, valid_pg_config
    ):
        """Test close_all handles errors gracefully."""
        mock_engine = Mock()
        mock_engine.dispose.side_effect = Exception("Dispose failed")

        mock_db = Mock()
        mock_db.engine = mock_engine
        mock_pg_class.return_value = mock_db

        with patch("appinfra.db.db.LoggerFactory.derive", return_value=mock_logger):
            manager = Manager(mock_logger, valid_pg_config)
            manager.setup()

            # Should not raise exception
            manager.close_all()

            # Should log errors
            assert mock_logger.error.call_count == 2  # One for each failed close
            assert len(manager._dbs) == 0

    def test_close_all_on_empty_manager(self, mock_logger, valid_pg_config):
        """Test close_all on manager with no connections."""
        with patch("appinfra.db.db.LoggerFactory.derive", return_value=mock_logger):
            manager = Manager(mock_logger, valid_pg_config)
            # Don't call setup()

            # Should not raise exception
            manager.close_all()

            mock_logger.info.assert_called_with("closed all database connections")


# =============================================================================
# Statistics Tests
# =============================================================================


@pytest.mark.unit
class TestStatistics:
    """Test database statistics functionality."""

    @patch("appinfra.db.db.pg.PG")
    def test_get_stats_after_successful_setup(
        self, mock_pg_class, mock_logger, valid_pg_config
    ):
        """Test get_stats returns correct statistics after successful setup."""
        with patch("appinfra.db.db.LoggerFactory.derive", return_value=mock_logger):
            manager = Manager(mock_logger, valid_pg_config)
            manager.setup()

            stats = manager.get_stats()

            assert stats["total_configured"] == 2
            assert stats["successful_setups"] == 2
            assert stats["failed_setups"] == 0
            assert len(stats["available_databases"]) == 2
            assert len(stats["failed_databases"]) == 0

    def test_get_stats_after_failed_setup(self, mock_logger, config_with_invalid_url):
        """Test get_stats returns correct statistics after failed setup."""
        with patch("appinfra.db.db.LoggerFactory.derive", return_value=mock_logger):
            manager = Manager(mock_logger, config_with_invalid_url)

            try:
                manager.setup()
            except RuntimeError:
                pass

            stats = manager.get_stats()

            assert stats["total_configured"] == 1
            assert stats["successful_setups"] == 0
            assert stats["failed_setups"] == 1
            assert len(stats["available_databases"]) == 0
            assert "bad_db" in stats["failed_databases"]

    @patch("appinfra.db.db.pg.PG")
    def test_get_stats_after_partial_failure(self, mock_pg_class, mock_logger):
        """Test get_stats with partial failures."""
        mock_pg_class.side_effect = [Mock(), Exception("Connection failed")]

        good_db_cfg = Mock(url="postgresql://localhost:5432/test")
        good_db_cfg.dict.return_value = {"url": "postgresql://localhost:5432/test"}

        bad_db_cfg = Mock(url="postgresql://localhost:5433/test")
        bad_db_cfg.dict.return_value = {"url": "postgresql://localhost:5433/test"}

        cfg = Mock()
        cfg.dbs = {
            "good_db": good_db_cfg,
            "bad_db": bad_db_cfg,
        }
        cfg.logging = Mock(pg_level=None)

        with patch("appinfra.db.db.LoggerFactory.derive", return_value=mock_logger):
            manager = Manager(mock_logger, cfg)
            manager.setup()

            stats = manager.get_stats()

            assert stats["total_configured"] == 2
            assert stats["successful_setups"] == 1
            assert stats["failed_setups"] == 1
            assert "good_db" in stats["available_databases"]
            assert "bad_db" in stats["failed_databases"]

    def test_get_stats_before_setup(self, mock_logger, valid_pg_config):
        """Test get_stats before setup is called."""
        with patch("appinfra.db.db.LoggerFactory.derive", return_value=mock_logger):
            manager = Manager(mock_logger, valid_pg_config)

            stats = manager.get_stats()

            assert stats["total_configured"] == 2
            assert stats["successful_setups"] == 0
            assert stats["failed_setups"] == 0
            assert len(stats["available_databases"]) == 0
            assert len(stats["failed_databases"]) == 0


# =============================================================================
# Configuration Validation Tests
# =============================================================================


@pytest.mark.unit
class TestConfigurationValidation:
    """Test database configuration validation."""

    @patch("appinfra.db.db.pg.PG")
    def test_validate_accepts_postgresql_url(self, mock_pg_class, mock_logger):
        """Test validation accepts postgresql:// URLs."""
        test_db_cfg = Mock(url="postgresql://localhost:5432/test")
        test_db_cfg.dict.return_value = {"url": "postgresql://localhost:5432/test"}

        cfg = Mock()
        cfg.dbs = {
            "test": test_db_cfg,
        }
        cfg.logging = Mock(pg_level=None)

        with patch("appinfra.db.db.LoggerFactory.derive", return_value=mock_logger):
            manager = Manager(mock_logger, cfg)
            manager.setup()  # Should not raise

            assert len(manager._dbs) == 1

    def test_validate_accepts_postgres_url(self, mock_logger):
        """Test validation accepts postgres:// URLs as valid PostgreSQL."""
        # Both postgres:// and postgresql:// are accepted as PostgreSQL URLs
        test_db_cfg = Mock(url="postgres://localhost:5432/test")
        test_db_cfg.dict.return_value = {"url": "postgres://localhost:5432/test"}

        cfg = Mock()
        cfg.dbs = {
            "test": test_db_cfg,
        }
        cfg.logging = Mock(pg_level=None)

        with patch("appinfra.db.db.LoggerFactory.derive", return_value=mock_logger):
            manager = Manager(mock_logger, cfg)

            # Validation should pass for postgres:// URLs
            # Setup will fail for connection reasons, not URL validation
            manager._validate_db_config("test", test_db_cfg)
            # No exception means validation passed

    def test_validate_rejects_invalid_url_scheme(self, mock_logger):
        """Test validation rejects invalid URL schemes."""
        cfg = Mock()
        cfg.dbs = {
            "test": Mock(url="mysql://localhost:3306/test"),
        }
        cfg.logging = Mock(pg_level=None)

        with patch("appinfra.db.db.LoggerFactory.derive", return_value=mock_logger):
            manager = Manager(mock_logger, cfg)

            with pytest.raises(
                RuntimeError, match="Failed to setup any database connections"
            ):
                manager.setup()

    def test_validate_rejects_non_string_url(self, mock_logger):
        """Test validation rejects non-string URLs."""
        cfg = Mock()
        cfg.dbs = {
            "test": Mock(url=12345),  # Not a string
        }
        cfg.logging = Mock(pg_level=None)

        with patch("appinfra.db.db.LoggerFactory.derive", return_value=mock_logger):
            manager = Manager(mock_logger, cfg)

            with pytest.raises(
                RuntimeError, match="Failed to setup any database connections"
            ):
                manager.setup()


# =============================================================================
# UnknownDBTypeException Tests
# =============================================================================


@pytest.mark.unit
class TestUnknownDBTypeException:
    """Test UnknownDBTypeException."""

    def test_exception_message(self):
        """Test exception message format."""
        url = "mysql://localhost:3306/test"
        exc = UnknownDBTypeException(url)

        assert str(exc) == f"Unknown database type: {url}"
        assert exc._url == url

    def test_exception_inheritance(self):
        """Test exception inherits from Exception."""
        exc = UnknownDBTypeException("test_url")
        assert isinstance(exc, Exception)
