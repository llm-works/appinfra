# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for database interface.

Tests the Interface abstract base class including:
- Interface property definitions
- Concrete implementations
- Abstract property/method requirements
"""

import pytest

from appinfra.db.pg.interface import Interface

# =============================================================================
# Test Fixtures
# =============================================================================


class ConcreteInterfaceImpl(Interface):
    """Concrete implementation of Interface for testing."""

    def __init__(self):
        self._cfg = {"host": "localhost", "port": 5432}
        self._url = "postgresql://localhost:5432/test"
        self._engine = "mock_engine"

    @property
    def cfg(self):
        return self._cfg

    @property
    def url(self):
        return self._url

    @property
    def engine(self):
        return self._engine

    def connect(self):
        return "mock_connection"

    def migrate(self):
        pass

    def session(self):
        return "mock_session"


# =============================================================================
# Test Interface Abstract Base Class
# =============================================================================


@pytest.mark.unit
class TestInterface:
    """Test Interface abstract base class."""

    def test_cannot_instantiate_abstract_class(self):
        """Test that Interface cannot be instantiated directly."""
        with pytest.raises(TypeError):
            Interface()

    def test_concrete_implementation_cfg(self):
        """Test cfg property in concrete implementation."""
        impl = ConcreteInterfaceImpl()
        assert impl.cfg == {"host": "localhost", "port": 5432}

    def test_concrete_implementation_url(self):
        """Test url property in concrete implementation."""
        impl = ConcreteInterfaceImpl()
        assert impl.url == "postgresql://localhost:5432/test"

    def test_concrete_implementation_engine(self):
        """Test engine property in concrete implementation."""
        impl = ConcreteInterfaceImpl()
        assert impl.engine == "mock_engine"

    def test_concrete_implementation_connect(self):
        """Test connect() method in concrete implementation."""
        impl = ConcreteInterfaceImpl()
        assert impl.connect() == "mock_connection"

    def test_concrete_implementation_migrate(self):
        """Test migrate() method in concrete implementation."""
        impl = ConcreteInterfaceImpl()
        impl.migrate()  # Should not raise

    def test_concrete_implementation_session(self):
        """Test session() method in concrete implementation."""
        impl = ConcreteInterfaceImpl()
        assert impl.session() == "mock_session"


# =============================================================================
# Test Abstract Method Coverage
# =============================================================================


@pytest.mark.unit
class TestAbstractMethodCoverage:
    """Test abstract methods/properties to ensure full coverage."""

    def test_abstract_cfg_not_implemented(self):
        """Test that cfg property is abstract."""

        class PartialImpl(Interface):
            @property
            def url(self):
                return "url"

            @property
            def engine(self):
                return "engine"

            def connect(self):
                return None

            def migrate(self):
                pass

            def session(self):
                return None

        with pytest.raises(TypeError, match="abstract"):
            PartialImpl()

    def test_abstract_url_not_implemented(self):
        """Test that url property is abstract."""

        class PartialImpl(Interface):
            @property
            def cfg(self):
                return {}

            @property
            def engine(self):
                return "engine"

            def connect(self):
                return None

            def migrate(self):
                pass

            def session(self):
                return None

        with pytest.raises(TypeError, match="abstract"):
            PartialImpl()

    def test_abstract_engine_not_implemented(self):
        """Test that engine property is abstract."""

        class PartialImpl(Interface):
            @property
            def cfg(self):
                return {}

            @property
            def url(self):
                return "url"

            def connect(self):
                return None

            def migrate(self):
                pass

            def session(self):
                return None

        with pytest.raises(TypeError, match="abstract"):
            PartialImpl()

    def test_abstract_connect_not_implemented(self):
        """Test that connect() method is abstract."""

        class PartialImpl(Interface):
            @property
            def cfg(self):
                return {}

            @property
            def url(self):
                return "url"

            @property
            def engine(self):
                return "engine"

            def migrate(self):
                pass

            def session(self):
                return None

        with pytest.raises(TypeError, match="abstract"):
            PartialImpl()

    def test_abstract_migrate_not_implemented(self):
        """Test that migrate() method is abstract."""

        class PartialImpl(Interface):
            @property
            def cfg(self):
                return {}

            @property
            def url(self):
                return "url"

            @property
            def engine(self):
                return "engine"

            def connect(self):
                return None

            def session(self):
                return None

        with pytest.raises(TypeError, match="abstract"):
            PartialImpl()

    def test_abstract_session_not_implemented(self):
        """Test that session() method is abstract."""

        class PartialImpl(Interface):
            @property
            def cfg(self):
                return {}

            @property
            def url(self):
                return "url"

            @property
            def engine(self):
                return "engine"

            def connect(self):
                return None

            def migrate(self):
                pass

        with pytest.raises(TypeError, match="abstract"):
            PartialImpl()


# =============================================================================
# Test Incomplete Implementations
# =============================================================================


@pytest.mark.unit
class TestIncompleteImplementation:
    """Test that incomplete implementations raise errors."""

    def test_missing_all_methods(self):
        """Test that missing all methods prevents instantiation."""

        class IncompleteImpl(Interface):
            pass

        with pytest.raises(TypeError):
            IncompleteImpl()

    def test_missing_multiple_methods(self):
        """Test that missing multiple methods prevents instantiation."""

        class IncompleteImpl(Interface):
            @property
            def cfg(self):
                return {}

        with pytest.raises(TypeError):
            IncompleteImpl()


# =============================================================================
# Test Integration
# =============================================================================


@pytest.mark.integration
class TestInterfaceIntegration:
    """Test Interface integration with real implementations."""

    def test_pg_implements_interface(self):
        """Test PG class implements Interface."""
        from appinfra.db.pg.pg import PG

        # PG should be an instance of Interface
        # Note: We can't instantiate PG without a config file, so just verify inheritance
        assert issubclass(PG, Interface)

    def test_concrete_implementation_usage(self):
        """Test using concrete implementation in realistic scenario."""
        impl = ConcreteInterfaceImpl()

        # Access properties
        cfg = impl.cfg
        assert "host" in cfg
        assert cfg["port"] == 5432

        # Use methods
        connection = impl.connect()
        assert connection == "mock_connection"

        session = impl.session()
        assert session == "mock_session"

        # Migrate doesn't return anything
        impl.migrate()
