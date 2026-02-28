"""
Unit tests for appinfra.db.pg.testing module.

Tests the utility functions and fixture factories without requiring a database.
"""

from unittest.mock import Mock

import pytest

from appinfra.db.pg.testing import (
    _create_extensions_in_db,
    _setup_database_with_lock,
    make_migrate_fixture,
)


@pytest.mark.unit
class TestMakeMigrateFixture:
    """Test make_migrate_fixture factory."""

    def test_returns_callable(self):
        """Test that make_migrate_fixture returns a fixture function."""
        mock_base = Mock()
        result = make_migrate_fixture(mock_base)

        # Should return a function (the fixture)
        assert callable(result)

    def test_accepts_extensions_parameter(self):
        """Test that make_migrate_fixture accepts extensions list."""
        mock_base = Mock()
        result = make_migrate_fixture(mock_base, extensions=["vector", "postgis"])

        assert callable(result)

    def test_returns_different_fixtures_for_different_bases(self):
        """Test that each call returns a new fixture function."""
        mock_base1 = Mock()
        mock_base2 = Mock()

        fixture1 = make_migrate_fixture(mock_base1)
        fixture2 = make_migrate_fixture(mock_base2)

        # Should be different function objects
        assert fixture1 is not fixture2


@pytest.mark.unit
class TestSetupDatabaseWithLock:
    """Test _setup_database_with_lock helper."""

    def test_skips_when_create_db_false(self):
        """Test that function returns early when create_db is not set."""
        config = {"url": "postgresql://localhost/test"}
        # Should not raise - just returns early (no DB connection attempted)
        _setup_database_with_lock(config)

    def test_skips_when_create_db_not_present(self):
        """Test that function returns early when create_db key is missing."""
        config = {"url": "postgresql://localhost/test"}
        _setup_database_with_lock(config)


@pytest.mark.unit
class TestCreateExtensionsInDb:
    """Test _create_extensions_in_db helper."""

    def test_skips_when_no_extensions(self):
        """Test that function returns early with empty extensions."""
        # Should not raise or try to connect
        _create_extensions_in_db("postgresql://localhost/test", [])
