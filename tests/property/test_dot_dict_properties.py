# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Property-based tests for DotDict."""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from appinfra.dot_dict import DotDict

# Strategy for valid Python identifiers (DotDict keys must be valid attribute names)
# Exclude 'self' and 'cls' as they conflict with **kwargs unpacking in __init__
# Also exclude DotDict reserved method names that cannot be used as keys
RESERVED_KWARGS = {"self", "cls"}
RESERVED_METHOD_NAMES = {
    "set",
    "clear",
    "dict",
    "to_dict",
    "get",
    "has",
    "require",
}
valid_key = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz",
    min_size=1,
    max_size=10,
).filter(
    lambda s: (
        s.isidentifier()
        and not s.startswith("_")
        and s not in RESERVED_KWARGS
        and s not in RESERVED_METHOD_NAMES
    )
)


@pytest.mark.property
@pytest.mark.unit
class TestDotDictProperties:
    """Property-based tests for DotDict."""

    @given(key=valid_key, value=st.text(max_size=50))
    def test_set_get_roundtrip(self, key: str, value: str) -> None:
        """Setting and getting a value should roundtrip correctly."""
        d = DotDict()
        d[key] = value
        assert d[key] == value
        assert getattr(d, key) == value

    @given(
        key1=valid_key,
        key2=valid_key,
        value=st.text(max_size=50),
    )
    def test_nested_set_get_roundtrip(self, key1: str, key2: str, value: str) -> None:
        """Nested values should roundtrip correctly."""
        if key1 == key2:
            return  # Skip same-key case

        d = DotDict()
        d[key1] = {key2: value}

        # Access nested value
        nested = d[key1]
        assert isinstance(nested, DotDict)
        assert nested[key2] == value

    @given(
        keys=st.lists(valid_key, min_size=1, max_size=4, unique=True),
        value=st.integers(),
    )
    @settings(max_examples=50)
    def test_deep_nesting(self, keys: list[str], value: int) -> None:
        """Deeply nested structures should work correctly."""
        # Build nested dict
        nested: dict = {keys[-1]: value}
        for key in reversed(keys[:-1]):
            nested = {key: nested}

        d = DotDict(**nested)

        # Navigate to value
        current = d
        for key in keys[:-1]:
            current = current[key]
            assert isinstance(current, DotDict)

        assert current[keys[-1]] == value

    @given(key=valid_key, value=st.integers())
    def test_dict_method_returns_dict(self, key: str, value: int) -> None:
        """The dict() method should return a proper dict."""
        d = DotDict()
        d[key] = value
        result = d.dict()
        assert isinstance(result, dict)
        assert result[key] == value

    @given(
        keys=st.lists(valid_key, min_size=1, max_size=5, unique=True),
        values=st.lists(st.integers(), min_size=1, max_size=5),
    )
    @settings(max_examples=50)
    def test_multiple_keys(self, keys: list[str], values: list[int]) -> None:
        """Multiple keys should all be accessible."""
        d = DotDict()
        pairs = list(zip(keys, values))

        for key, value in pairs:
            d[key] = value

        for key, value in pairs:
            assert d[key] == value

    @given(key=valid_key)
    def test_missing_key_behavior(self, key: str) -> None:
        """Test behavior for missing keys (dict.get() semantics)."""
        d = DotDict()
        # __getitem__ returns None for missing keys
        assert d[key] is None
        # get() returns None for missing keys (dict.get() semantics)
        assert d.get(key) is None
        # get() returns default if provided
        assert d.get(key, default="fallback") == "fallback"

    @given(key=st.sampled_from(list(RESERVED_METHOD_NAMES)), value=st.integers())
    def test_reserved_keys_raise_error(self, key: str, value: int) -> None:
        """Reserved method names cannot be used as keys."""
        d = DotDict()
        with pytest.raises(ValueError, match="reserved"):
            d[key] = value
