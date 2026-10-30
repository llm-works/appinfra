# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for dictionary interface.

Tests the DictInterface abstract base class including:
- Interface method definitions
- Concrete implementations
- Abstract method requirements
"""

import pytest

from appinfra.dict import DictInterface

# =============================================================================
# Test Concrete Implementation
# =============================================================================


class ConcreteDictImpl(DictInterface):
    """Concrete implementation of DictInterface for testing."""

    def __init__(self):
        self._data = {}

    def keys(self):
        return self._data.keys()

    def values(self):
        return self._data.values()

    def items(self):
        return self._data.items()

    def __contains__(self, key):
        return key in self._data

    def __getitem__(self, key):
        return self._data[key]

    def __setitem__(self, key, val):
        self._data[key] = val

    def has(self, key):
        return key in self._data

    def __len__(self):
        return len(self._data)


@pytest.mark.unit
class TestDictInterface:
    """Test DictInterface abstract base class."""

    def test_cannot_instantiate_abstract_class(self):
        """Test that DictInterface cannot be instantiated directly."""
        with pytest.raises(TypeError):
            DictInterface()

    def test_concrete_implementation_keys(self):
        """Test keys() method in concrete implementation."""
        impl = ConcreteDictImpl()
        impl["key1"] = "value1"
        impl["key2"] = "value2"

        keys = list(impl.keys())
        assert "key1" in keys
        assert "key2" in keys
        assert len(keys) == 2

    def test_concrete_implementation_values(self):
        """Test values() method in concrete implementation."""
        impl = ConcreteDictImpl()
        impl["key1"] = "value1"
        impl["key2"] = "value2"

        values = list(impl.values())
        assert "value1" in values
        assert "value2" in values
        assert len(values) == 2

    def test_concrete_implementation_items(self):
        """Test items() method in concrete implementation."""
        impl = ConcreteDictImpl()
        impl["key1"] = "value1"
        impl["key2"] = "value2"

        items = list(impl.items())
        assert ("key1", "value1") in items
        assert ("key2", "value2") in items
        assert len(items) == 2

    def test_concrete_implementation_contains(self):
        """Test __contains__() method (in operator)."""
        impl = ConcreteDictImpl()
        impl["key1"] = "value1"

        assert "key1" in impl
        assert "key2" not in impl

    def test_concrete_implementation_getitem(self):
        """Test __getitem__() method (bracket access)."""
        impl = ConcreteDictImpl()
        impl["key1"] = "value1"

        assert impl["key1"] == "value1"

    def test_concrete_implementation_getitem_missing_key(self):
        """Test __getitem__() raises KeyError for missing key."""
        impl = ConcreteDictImpl()

        with pytest.raises(KeyError):
            _ = impl["missing_key"]

    def test_concrete_implementation_setitem(self):
        """Test __setitem__() method (bracket assignment)."""
        impl = ConcreteDictImpl()
        impl["key1"] = "value1"

        assert impl["key1"] == "value1"

    def test_concrete_implementation_setitem_update(self):
        """Test __setitem__() updates existing key."""
        impl = ConcreteDictImpl()
        impl["key1"] = "value1"
        impl["key1"] = "value2"

        assert impl["key1"] == "value2"

    def test_concrete_implementation_has(self):
        """Test has() method."""
        impl = ConcreteDictImpl()
        impl["key1"] = "value1"

        assert impl.has("key1") is True
        assert impl.has("key2") is False

    def test_concrete_implementation_len(self):
        """Test __len__() method."""
        impl = ConcreteDictImpl()

        assert len(impl) == 0

        impl["key1"] = "value1"
        assert len(impl) == 1

        impl["key2"] = "value2"
        assert len(impl) == 2

    def test_concrete_implementation_empty(self):
        """Test empty dictionary-like object."""
        impl = ConcreteDictImpl()

        assert len(impl) == 0
        assert list(impl.keys()) == []
        assert list(impl.values()) == []
        assert list(impl.items()) == []


@pytest.mark.unit
class TestIncompleteImplementation:
    """Test that incomplete implementations raise errors."""

    def test_missing_keys_method(self):
        """Test that missing keys() method prevents instantiation."""

        class IncompleteImpl(DictInterface):
            def values(self):
                pass

            def items(self):
                pass

            def __contains__(self, key):
                pass

            def __getitem__(self, key):
                pass

            def __setitem__(self, key, val):
                pass

            def has(self, key):
                pass

            def __len__(self):
                pass

        with pytest.raises(TypeError):
            IncompleteImpl()

    def test_missing_multiple_methods(self):
        """Test that missing multiple methods prevents instantiation."""

        class IncompleteImpl(DictInterface):
            def keys(self):
                pass

        with pytest.raises(TypeError):
            IncompleteImpl()


@pytest.mark.unit
class TestAbstractMethodCoverage:
    """Test abstract methods to ensure full coverage."""

    def test_abstract_keys_not_implemented(self):
        """Test that keys() is abstract and raises TypeError if not implemented."""

        class PartialImpl(DictInterface):
            def values(self):
                return []

            def items(self):
                return []

            def __contains__(self, key):
                return False

            def __getitem__(self, key):
                return None

            def __setitem__(self, key, val):
                pass

            def has(self, key):
                return False

            def __len__(self):
                return 0

        with pytest.raises(TypeError, match="abstract"):
            PartialImpl()

    def test_abstract_values_not_implemented(self):
        """Test that values() is abstract."""

        class PartialImpl(DictInterface):
            def keys(self):
                return []

            def items(self):
                return []

            def __contains__(self, key):
                return False

            def __getitem__(self, key):
                return None

            def __setitem__(self, key, val):
                pass

            def has(self, key):
                return False

            def __len__(self):
                return 0

        with pytest.raises(TypeError, match="abstract"):
            PartialImpl()

    def test_abstract_items_not_implemented(self):
        """Test that items() is abstract."""

        class PartialImpl(DictInterface):
            def keys(self):
                return []

            def values(self):
                return []

            def __contains__(self, key):
                return False

            def __getitem__(self, key):
                return None

            def __setitem__(self, key, val):
                pass

            def has(self, key):
                return False

            def __len__(self):
                return 0

        with pytest.raises(TypeError, match="abstract"):
            PartialImpl()

    def test_abstract_contains_not_implemented(self):
        """Test that __contains__() is abstract."""

        class PartialImpl(DictInterface):
            def keys(self):
                return []

            def values(self):
                return []

            def items(self):
                return []

            def __getitem__(self, key):
                return None

            def __setitem__(self, key, val):
                pass

            def has(self, key):
                return False

            def __len__(self):
                return 0

        with pytest.raises(TypeError, match="abstract"):
            PartialImpl()

    def test_abstract_getitem_not_implemented(self):
        """Test that __getitem__() is abstract."""

        class PartialImpl(DictInterface):
            def keys(self):
                return []

            def values(self):
                return []

            def items(self):
                return []

            def __contains__(self, key):
                return False

            def __setitem__(self, key, val):
                pass

            def has(self, key):
                return False

            def __len__(self):
                return 0

        with pytest.raises(TypeError, match="abstract"):
            PartialImpl()

    def test_abstract_setitem_not_implemented(self):
        """Test that __setitem__() is abstract."""

        class PartialImpl(DictInterface):
            def keys(self):
                return []

            def values(self):
                return []

            def items(self):
                return []

            def __contains__(self, key):
                return False

            def __getitem__(self, key):
                return None

            def has(self, key):
                return False

            def __len__(self):
                return 0

        with pytest.raises(TypeError, match="abstract"):
            PartialImpl()

    def test_abstract_has_not_implemented(self):
        """Test that has() is abstract."""

        class PartialImpl(DictInterface):
            def keys(self):
                return []

            def values(self):
                return []

            def items(self):
                return []

            def __contains__(self, key):
                return False

            def __getitem__(self, key):
                return None

            def __setitem__(self, key, val):
                pass

            def __len__(self):
                return 0

        with pytest.raises(TypeError, match="abstract"):
            PartialImpl()

    def test_abstract_len_not_implemented(self):
        """Test that __len__() is abstract."""

        class PartialImpl(DictInterface):
            def keys(self):
                return []

            def values(self):
                return []

            def items(self):
                return []

            def __contains__(self, key):
                return False

            def __getitem__(self, key):
                return None

            def __setitem__(self, key, val):
                pass

            def has(self, key):
                return False

        with pytest.raises(TypeError, match="abstract"):
            PartialImpl()


@pytest.mark.integration
class TestDictInterfaceIntegration:
    """Test DictInterface in realistic scenarios."""

    def test_dict_like_usage(self):
        """Test using concrete implementation like a dict."""
        impl = ConcreteDictImpl()

        # Add items
        impl["name"] = "John"
        impl["age"] = 30
        impl["city"] = "New York"

        # Check existence
        assert "name" in impl
        assert impl.has("age")

        # Get items
        assert impl["name"] == "John"
        assert impl["age"] == 30

        # Iterate
        keys = set(impl.keys())
        assert keys == {"name", "age", "city"}

        # Update
        impl["age"] = 31
        assert impl["age"] == 31

        # Length
        assert len(impl) == 3
