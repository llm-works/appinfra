# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Unit tests for appinfra.db.pg.testing module.

Tests the utility functions and fixture factories without requiring a database.
"""

import itertools
from unittest.mock import Mock, patch

import pytest

from appinfra.db.pg.testing import (
    _create_extensions_in_db,
    _migrated_pg,
    _setup_database_with_lock,
    make_migrate_fixture,
    pg_test_schema,
)
from appinfra.envelope import Envelope


class TestPgTestSchemaSuite:
    """The suite prefix becomes part of a schema name."""

    def test_suite_with_a_trailing_newline_is_rejected(self, monkeypatch):
        monkeypatch.setenv("_APPINFRA_CHECK_PYTEST_SUITE", "unit\n")
        with pytest.raises(ValueError, match="_APPINFRA_CHECK_PYTEST_SUITE"):
            pg_test_schema.__wrapped__("gw0")


class TestMigratedPgSchemaName:
    """The derived migrate schema must fit PostgreSQL's 63-character names."""

    def test_too_long_a_name_fails_before_any_database_work(self):
        worker_schema = "a" * 51 + "_master"  # longest pg_test_schema allows
        with (
            patch("appinfra.db.pg.testing._migrate_ids", itertools.count(1000)),
            patch("appinfra.db.pg.testing._setup_database_with_lock") as setup,
            pytest.raises(ValueError, match="_APPINFRA_CHECK_PYTEST_SUITE"),
            _migrated_pg({}, Mock(), worker_schema, Mock(), None),
        ):
            pass
        setup.assert_not_called()


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


class TestSetupDatabaseWithLock:
    """Test _setup_database_with_lock helper."""

    def test_skips_when_create_db_false(self):
        """Test that function returns early when create_db is False."""
        config = {"url": "postgresql://localhost/test", "create_db": False}
        # Should not raise - just returns early (no DB connection attempted)
        _setup_database_with_lock(config)

    def test_skips_when_create_db_not_present(self):
        """Test that function returns early when create_db key is missing."""
        config = {"url": "postgresql://localhost/test"}
        _setup_database_with_lock(config)

    def test_a_secret_url_is_opened_for_its_connections(self):
        """A URL built from a secret arrives as an Envelope."""
        config = {
            "url": Envelope("postgresql://app:s3cret@localhost/test"),
            "create_db": True,
        }
        with (
            patch("sqlalchemy.create_engine") as create_engine,
            patch("sqlalchemy_utils.database_exists", return_value=True) as exists,
        ):
            _setup_database_with_lock(config)

        lock_url = create_engine.call_args.args[0]
        assert lock_url == "postgresql://app:s3cret@localhost/postgres"
        assert exists.call_args.args[0] == "postgresql://app:s3cret@localhost/test"


class TestCreateExtensionsInDb:
    """Test _create_extensions_in_db helper."""

    def test_skips_when_no_extensions(self):
        """Test that function returns early with empty extensions."""
        # Should not raise or try to connect
        _create_extensions_in_db("postgresql://localhost/test", [])

    def test_skips_a_name_with_a_trailing_newline(self):
        with patch("sqlalchemy.create_engine") as create_engine:
            _create_extensions_in_db("postgresql://localhost/test", ["vector\n"])
        create_engine.return_value.connect.assert_not_called()
