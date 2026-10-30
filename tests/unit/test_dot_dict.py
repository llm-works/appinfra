# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for DotDict implementation.

Tests key DotDict features including:
- Dictionary-style and attribute-style access
- Nested structure support
- Path traversal with dot notation
- Type conversions
- Error handling
"""

import pytest

from appinfra.dot_dict import DotDict, DotDictPathNotFoundError

# =============================================================================
# Test DotDict Basic Operations
# =============================================================================


@pytest.mark.unit
class TestDotDictBasicOperations:
    """Test basic DotDict operations."""

    def test_init_empty(self):
        """Test creating empty DotDict."""
        dd = DotDict()
        assert len(dd) == 0

    def test_init_with_kwargs(self):
        """Test creating DotDict with initial values."""
        dd = DotDict(name="John", age=30)
        assert dd.name == "John"
        assert dd.age == 30

    def test_init_with_dict(self):
        """Test creating DotDict from dict positional argument."""
        dd = DotDict({"name": "John", "age": 30})
        assert dd.name == "John"
        assert dd.age == 30

    def test_init_with_dict_and_kwargs(self):
        """Test creating DotDict with both dict and kwargs (kwargs override)."""
        dd = DotDict({"name": "John", "age": 30}, age=25, city="NYC")
        assert dd.name == "John"
        assert dd.age == 25  # kwargs override
        assert dd.city == "NYC"

    def test_init_with_nested_dict(self):
        """Test creating DotDict from nested dict."""
        dd = DotDict({"user": {"name": "John", "age": 30}})
        assert dd.user.name == "John"
        assert dd.user.age == 30

    def test_init_with_multiple_positional_args_raises(self):
        """Test that multiple positional arguments raise TypeError."""
        with pytest.raises(TypeError, match="takes at most 1 positional argument"):
            DotDict({"a": 1}, {"b": 2})

    def test_init_with_non_dict_positional_raises(self):
        """Test that non-dict positional argument raises TypeError."""
        with pytest.raises(TypeError, match="argument must be a dict"):
            DotDict("not a dict")

    def test_init_with_data_keyword(self):
        """Test that 'data' can still be used as a keyword argument."""
        dd = DotDict(data="some_value")
        assert dd.data == "some_value"

    def test_init_with_dict_method_names(self):
        """Test that dict method names work correctly as data keys."""
        dd = DotDict({"keys": 1, "values": 2, "items": 3})
        # Should return data, not methods (via _DATA_PRIORITY_ATTRS)
        assert dd.keys == 1
        assert dd.values == 2
        assert dd.items == 3
        # Dict-style access should also work
        assert dd["keys"] == 1
        assert dd["values"] == 2
        assert dd["items"] == 3

    def test_init_with_nested_dict_method_names(self):
        """Test nested DotDict with dict method names."""
        dd = DotDict({"config": {"keys": "value1", "items": "value2"}})
        assert dd.config.keys == "value1"
        assert dd.config.items == "value2"

    def test_init_with_deeply_nested_structure(self):
        """Test DotDict with deeply nested dict structures."""
        dd = DotDict(
            {
                "level1": {
                    "level2": {"level3": {"level4": {"value": "deep"}}},
                    "sibling": "shallow",
                }
            }
        )
        assert dd.level1.level2.level3.level4.value == "deep"
        assert dd.level1.sibling == "shallow"

    def test_init_with_mixed_types(self):
        """Test DotDict with mixed value types."""
        dd = DotDict(
            {
                "string": "text",
                "number": 42,
                "float": 3.14,
                "bool": True,
                "none": None,
                "list": [1, 2, 3],
                "nested": {"key": "value"},
            }
        )
        assert dd.string == "text"
        assert dd.number == 42
        assert dd.float == 3.14
        assert dd.bool is True
        assert dd.none is None
        assert dd.list == [1, 2, 3]
        assert dd.nested.key == "value"

    def test_set_method(self):
        """Test set() method."""
        dd = DotDict()
        dd.set(key1="value1", key2="value2")
        assert dd.key1 == "value1"
        assert dd.key2 == "value2"

    def test_set_method_returns_self(self):
        """Test set() returns self for chaining."""
        dd = DotDict()
        result = dd.set(key="value")
        assert result is dd

    def test_attribute_style_access(self):
        """Test accessing values via attributes."""
        dd = DotDict(name="John")
        assert dd.name == "John"

    def test_dict_style_access(self):
        """Test accessing values via dictionary syntax."""
        dd = DotDict(name="John")
        assert dd["name"] == "John"

    def test_setitem(self):
        """Test setting values via dictionary syntax."""
        dd = DotDict()
        dd["name"] = "John"
        assert dd.name == "John"

    def test_setitem_overwrite(self):
        """Test overwriting existing key via dictionary syntax."""
        dd = DotDict(name="John")
        dd["name"] = "Jane"
        assert dd.name == "Jane"

    def test_contains(self):
        """Test 'in' operator."""
        dd = DotDict(name="John")
        assert "name" in dd
        assert "age" not in dd

    def test_len(self):
        """Test len() function."""
        dd = DotDict(key1="val1", key2="val2")
        assert len(dd) == 2

    def test_keys(self):
        """Test keys() method."""
        dd = DotDict(key1="val1", key2="val2")
        keys = list(dd.keys())
        assert "key1" in keys
        assert "key2" in keys

    def test_values(self):
        """Test values() method."""
        dd = DotDict(key1="val1", key2="val2")
        values = list(dd.values())
        assert "val1" in values
        assert "val2" in values

    def test_items(self):
        """Test items() method."""
        dd = DotDict(key1="val1", key2="val2")
        items = list(dd.items())
        assert ("key1", "val1") in items
        assert ("key2", "val2") in items

    def test_str(self):
        """Test __str__() method."""
        dd = DotDict(name="John")
        result = str(dd)
        assert isinstance(result, str)
        assert "name" in result

    def test_dict_method(self):
        """Test dict() method."""
        dd = DotDict(name="John", age=30)
        result = dd.dict()
        assert isinstance(result, dict)
        assert result["name"] == "John"
        assert result["age"] == 30

    def test_clear(self):
        """Test clear() method."""
        dd = DotDict(key1="val1", key2="val2")
        dd.clear()
        assert len(dd) == 0

    def test_getitem_missing_key(self):
        """Test getting missing key returns None."""
        dd = DotDict()
        assert dd["missing"] is None


# =============================================================================
# Test Nested Structures
# =============================================================================


@pytest.mark.unit
class TestDotDictNestedStructures:
    """Test DotDict nested structure support."""

    def test_nested_dict_conversion(self):
        """Test automatic conversion of nested dicts to DotDict."""
        dd = DotDict(database={"host": "localhost", "port": 5432})
        assert isinstance(dd.database, DotDict)
        assert dd.database.host == "localhost"
        assert dd.database.port == 5432

    def test_deeply_nested_dict(self):
        """Test deeply nested dictionary structures."""
        dd = DotDict(
            server={"database": {"connection": {"host": "localhost", "port": 5432}}}
        )
        assert isinstance(dd.server, DotDict)
        assert isinstance(dd.server.database, DotDict)
        assert isinstance(dd.server.database.connection, DotDict)
        assert dd.server.database.connection.host == "localhost"

    def test_list_with_nested_dicts(self):
        """Test list containing dictionaries."""
        dd = DotDict(
            servers=[
                {"name": "server1", "port": 8080},
                {"name": "server2", "port": 8081},
            ]
        )
        assert isinstance(dd.servers, list)
        assert isinstance(dd.servers[0], DotDict)
        assert dd.servers[0].name == "server1"
        assert dd.servers[1].port == 8081

    def test_list_with_simple_values(self):
        """Test list containing simple values."""
        dd = DotDict(numbers=[1, 2, 3, 4])
        assert dd.numbers == [1, 2, 3, 4]

    def test_nested_dict_to_dict_method(self):
        """Test dict() method with nested DotDict."""
        dd = DotDict(database={"host": "localhost"})
        result = dd.dict()
        assert isinstance(result, dict)
        assert isinstance(result["database"], dict)
        assert result["database"]["host"] == "localhost"


# =============================================================================
# Test Key Type Conversions
# =============================================================================


@pytest.mark.unit
class TestDotDictKeyConversions:
    """Test key type conversion in DotDict."""

    def test_string_keys_work(self):
        """Test that string keys work normally."""
        dd = DotDict()
        dd.set(my_key="value")
        assert dd.my_key == "value"


# =============================================================================
# Test Path Operations
# =============================================================================


@pytest.mark.unit
class TestDotDictPathOperations:
    """Test DotDict path traversal operations."""

    def test_has_simple_path(self):
        """Test has() with simple key."""
        dd = DotDict(name="John")
        assert dd.has("name") is True
        assert dd.has("age") is False

    def test_has_nested_path(self):
        """Test has() with dot-separated path."""
        dd = DotDict(database={"host": "localhost", "port": 5432})
        assert dd.has("database.host") is True
        assert dd.has("database.user") is False

    def test_has_deeply_nested_path(self):
        """Test has() with deeply nested path."""
        dd = DotDict(server={"database": {"connection": {"host": "localhost"}}})
        assert dd.has("server.database.connection.host") is True
        assert dd.has("server.database.connection.port") is False

    def test_has_empty_path(self):
        """Test has() with empty path returns False."""
        dd = DotDict(name="John")
        assert dd.has("") is False

    def test_has_path_with_empty_components(self):
        """Test has() with path containing empty components."""
        dd = DotDict(database={"host": "localhost"})
        # Path with double dots should skip empty components
        assert dd.has("database..host") is True

    def test_get_simple_path(self):
        """Test get() with simple key."""
        dd = DotDict(name="John")
        assert dd.get("name") == "John"

    def test_get_nested_path(self):
        """Test get() with dot-separated path."""
        dd = DotDict(database={"host": "localhost", "port": 5432})
        assert dd.get("database.host") == "localhost"
        assert dd.get("database.port") == 5432

    def test_get_deeply_nested_path(self):
        """Test get() with deeply nested path."""
        dd = DotDict(server={"database": {"connection": {"host": "localhost"}}})
        assert dd.get("server.database.connection.host") == "localhost"

    def test_get_with_default(self):
        """Test get() with default value."""
        dd = DotDict(name="John")
        assert dd.get("age", default=25) == 25

    def test_get_missing_path_with_default(self):
        """Test get() returns default for missing path."""
        dd = DotDict(database={"host": "localhost"})
        assert dd.get("database.user", default="admin") == "admin"

    def test_get_missing_path_returns_none(self):
        """Test get() returns None when path not found (dict.get() semantics)."""
        dd = DotDict(name="John")
        assert dd.get("age") is None

    def test_get_empty_path_with_default(self):
        """Test get() with empty path returns default."""
        dd = DotDict(name="John")
        assert dd.get("", default="default") == "default"

    def test_get_empty_path_returns_none(self):
        """Test get() with empty path returns None (dict.get() semantics)."""
        dd = DotDict(name="John")
        assert dd.get("") is None

    def test_get_with_max_steps_up(self):
        """Test get() with max_steps_up parameter."""
        dd = DotDict(config={"value": "global"})
        # This tests the hierarchy search feature
        result = dd.get("config.value", max_steps_up=1)
        assert result == "global"


# =============================================================================
# Test DotDictPathNotFoundError
# =============================================================================


@pytest.mark.unit
class TestDotDictPathNotFoundError:
    """Test DotDictPathNotFoundError exception class."""

    def test_exception_attributes(self):
        """Test exception stores obj and path."""
        dd = DotDict(name="John")
        exc = DotDictPathNotFoundError(dd, "missing.path")
        assert exc.obj is dd
        assert exc.path == "missing.path"

    def test_exception_can_be_raised(self):
        """Test exception can be raised and caught."""
        dd = DotDict(name="John")
        with pytest.raises(DotDictPathNotFoundError):
            raise DotDictPathNotFoundError(dd, "some.path")


# =============================================================================
# Test Integration Scenarios
# =============================================================================


@pytest.mark.integration
class TestDotDictIntegration:
    """Test real-world DotDict usage scenarios."""

    def test_configuration_workflow(self):
        """Test using DotDict for configuration."""
        config = DotDict(
            database={
                "host": "localhost",
                "port": 5432,
                "credentials": {"user": "admin", "password": "secret"},
            },
            server={"host": "0.0.0.0", "port": 8080},
        )

        # Access nested values
        assert config.database.host == "localhost"
        assert config.database.credentials.user == "admin"

        # Check paths
        assert config.has("database.credentials.user")
        assert config.get("database.credentials.user") == "admin"

        # Update values
        config["database"]["port"] = 5433
        assert config.database.port == 5433

    def test_mixed_access_patterns(self):
        """Test mixing attribute and dictionary access."""
        dd = DotDict(user={"name": "John", "settings": {"theme": "dark"}})

        # Mix attribute and dictionary access
        assert dd.user["name"] == "John"
        assert dd["user"].name == "John"
        assert dd.user.settings["theme"] == "dark"

    def test_chaining_operations(self):
        """Test method chaining."""
        dd = DotDict().set(name="John").set(age=30)
        assert dd.name == "John"
        assert dd.age == 30


# =============================================================================
# Test dict Subclass Behavior
# =============================================================================


@pytest.mark.unit
class TestDotDictIsDict:
    """Test that DotDict is a proper dict subclass."""

    def test_isinstance_dict(self):
        """Test that isinstance(DotDict(), dict) returns True."""
        dd = DotDict()
        assert isinstance(dd, dict)

    def test_isinstance_dict_with_data(self):
        """Test isinstance with data."""
        dd = DotDict(name="John", age=30)
        assert isinstance(dd, dict)

    def test_nested_dotdict_isinstance(self):
        """Test that nested DotDicts are also dicts."""
        dd = DotDict(database={"host": "localhost"})
        assert isinstance(dd.database, dict)


# =============================================================================
# Test require() Method
# =============================================================================


@pytest.mark.unit
class TestDotDictRequire:
    """Test DotDict require() method."""

    def test_require_existing_key(self):
        """Test require() returns value for existing key."""
        dd = DotDict(name="John")
        assert dd.require("name") == "John"

    def test_require_nested_path(self):
        """Test require() with nested path."""
        dd = DotDict(database={"host": "localhost", "port": 5432})
        assert dd.require("database.host") == "localhost"

    def test_require_missing_key_raises(self):
        """Test require() raises DotDictPathNotFoundError for missing key."""
        dd = DotDict(name="John")
        with pytest.raises(DotDictPathNotFoundError) as exc_info:
            dd.require("age")
        assert exc_info.value.path == "age"
        assert "age" in str(exc_info.value)

    def test_require_missing_nested_path_raises(self):
        """Test require() raises for missing nested path."""
        dd = DotDict(database={"host": "localhost"})
        with pytest.raises(DotDictPathNotFoundError) as exc_info:
            dd.require("database.user")
        assert exc_info.value.path == "database.user"

    def test_require_none_value_succeeds(self):
        """Test require() succeeds when value is None (key exists)."""
        dd = DotDict(value=None)
        assert dd.require("value") is None
