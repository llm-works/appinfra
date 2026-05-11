"""
Tests for SQLite database interface.
"""

from unittest.mock import Mock, patch

import pytest
import sqlalchemy
from sqlalchemy import Column, Integer, String, text
from sqlalchemy.orm import declarative_base

from appinfra.db.sqlite import SQLite


@pytest.fixture
def mock_logger():
    """Create a mock logger."""
    logger = Mock()
    logger.debug = Mock()
    logger.info = Mock()
    logger.warning = Mock()
    logger.error = Mock()
    return logger


@pytest.fixture
def memory_config():
    """Create in-memory SQLite config."""
    config = Mock(spec=["url"])
    config.url = "sqlite:///:memory:"
    return config


@pytest.fixture
def sqlite_db(mock_logger, memory_config):
    """Create SQLite instance with in-memory database."""
    with patch(
        "appinfra.db.sqlite.sqlite.LoggerFactory.derive", return_value=mock_logger
    ):
        return SQLite(mock_logger, memory_config)


@pytest.mark.unit
class TestSQLiteInit:
    """Test SQLite initialization."""

    def test_init_with_memory_url(self, mock_logger, memory_config):
        """Test initialization with in-memory database."""
        with patch(
            "appinfra.db.sqlite.sqlite.LoggerFactory.derive", return_value=mock_logger
        ):
            db = SQLite(mock_logger, memory_config)
            assert db.url == "sqlite:///:memory:"

    def test_init_with_file_url(self, mock_logger, tmp_path):
        """Test initialization with file-based database."""
        db_path = tmp_path / "test.db"
        config = Mock()
        config.url = f"sqlite:///{db_path}"

        with patch(
            "appinfra.db.sqlite.sqlite.LoggerFactory.derive", return_value=mock_logger
        ):
            db = SQLite(mock_logger, config)
            assert "test.db" in db.url

    def test_init_raises_on_none_logger(self, memory_config):
        """Test raises ValueError when logger is None."""
        with pytest.raises(ValueError, match="Logger cannot be None"):
            SQLite(None, memory_config)

    def test_init_raises_on_none_config(self, mock_logger):
        """Test raises ValueError when config is None."""
        with pytest.raises(ValueError, match="Configuration cannot be None"):
            SQLite(mock_logger, None)

    def test_init_raises_on_missing_url(self, mock_logger):
        """Test raises ValueError when URL is missing."""
        config = Mock(spec=[])  # No url attribute
        with pytest.raises(ValueError, match="missing required 'url' field"):
            SQLite(mock_logger, config)

    def test_init_raises_on_invalid_url(self, mock_logger):
        """Test raises ValueError when URL is not SQLite."""
        config = Mock()
        config.url = "postgresql://localhost/db"
        with pytest.raises(ValueError, match="Invalid SQLite URL"):
            SQLite(mock_logger, config)


@pytest.mark.unit
class TestSQLiteProperties:
    """Test SQLite properties."""

    def test_cfg_property(self, sqlite_db, memory_config):
        """Test cfg property returns config."""
        assert sqlite_db.cfg == memory_config

    def test_url_property(self, sqlite_db):
        """Test url property returns URL string."""
        assert sqlite_db.url == "sqlite:///:memory:"

    def test_engine_property(self, sqlite_db):
        """Test engine property returns SQLAlchemy engine."""
        assert isinstance(sqlite_db.engine, sqlalchemy.engine.Engine)


@pytest.mark.unit
class TestSQLiteConnect:
    """Test SQLite connect method."""

    def test_connect_returns_connection(self, sqlite_db):
        """Test connect returns a connection object."""
        conn = sqlite_db.connect()
        assert conn is not None
        conn.close()

    def test_connection_can_execute(self, sqlite_db):
        """Test connection can execute queries."""
        conn = sqlite_db.connect()
        result = conn.execute(text("SELECT 1"))
        assert result.fetchone()[0] == 1
        conn.close()


@pytest.mark.unit
class TestSQLiteSession:
    """Test SQLite session method."""

    def test_session_returns_session(self, sqlite_db):
        """Test session returns a session object via context manager."""
        with sqlite_db.session() as session:
            assert session is not None

    def test_session_can_execute(self, sqlite_db):
        """Test session can execute queries."""
        with sqlite_db.session() as session:
            result = session.execute(text("SELECT 1"))
            assert result.fetchone()[0] == 1

    def test_session_autocommit_raises_not_implemented(self, sqlite_db):
        """Test session(autocommit=True) raises NotImplementedError."""
        with pytest.raises(
            NotImplementedError, match="SQLite does not support AUTOCOMMIT"
        ):
            with sqlite_db.session(autocommit=True):
                pass


@pytest.mark.unit
class TestSQLiteMigrate:
    """Test SQLite migrate method."""

    def test_migrate_creates_tables(self, sqlite_db):
        """Test migrate creates tables from Base metadata."""
        Base = declarative_base()

        class TestUser(Base):
            __tablename__ = "test_users"
            id = Column(Integer, primary_key=True)
            name = Column(String(50))

        sqlite_db.migrate(Base)

        # Verify table was created
        conn = sqlite_db.connect()
        result = conn.execute(
            text(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='test_users'"
            )
        )
        assert result.fetchone() is not None
        conn.close()


@pytest.mark.unit
class TestSQLiteDispose:
    """Test SQLite dispose method."""

    def test_dispose_closes_connections(self, sqlite_db):
        """Test dispose closes engine connections."""
        # Create some connections
        conn = sqlite_db.connect()
        conn.close()

        # Dispose should not raise
        sqlite_db.dispose()


@pytest.mark.unit
class TestSQLiteEngineKwargs:
    """Test SQLite engine configuration."""

    def test_check_same_thread_default(self, mock_logger, memory_config):
        """Test check_same_thread defaults to False."""
        with patch(
            "appinfra.db.sqlite.sqlite.LoggerFactory.derive", return_value=mock_logger
        ):
            db = SQLite(mock_logger, memory_config)
            # Engine was created, should work in multi-threaded context
            assert db.engine is not None

    def test_check_same_thread_configured(self, mock_logger):
        """Test check_same_thread can be configured."""
        config = Mock()
        config.url = "sqlite:///:memory:"
        config.check_same_thread = True

        with patch(
            "appinfra.db.sqlite.sqlite.LoggerFactory.derive", return_value=mock_logger
        ):
            db = SQLite(mock_logger, config)
            assert db.engine is not None

    def test_echo_configured(self, mock_logger):
        """Test echo can be enabled."""
        config = Mock()
        config.url = "sqlite:///:memory:"
        config.echo = True

        with patch(
            "appinfra.db.sqlite.sqlite.LoggerFactory.derive", return_value=mock_logger
        ):
            db = SQLite(mock_logger, config)
            assert db.engine is not None
