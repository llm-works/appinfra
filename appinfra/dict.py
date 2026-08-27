# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Dictionary-like interface definition.

This module provides an abstract base class that defines the interface
for dictionary-like objects, ensuring consistent behavior across
different dictionary implementations.
"""

from abc import ABC, abstractmethod
from collections.abc import ItemsView, KeysView, ValuesView
from typing import Any


class DictInterface(ABC):
    """
    Abstract base class defining the interface for dictionary-like objects.

    Provides a standard interface that dictionary-like classes must implement,
    ensuring consistent behavior and enabling polymorphism across different
    dictionary implementations. This interface extends the standard dictionary
    protocol with additional methods like `has()` for key checking.
    """

    @abstractmethod
    def keys(self) -> KeysView[str]:
        """
        Get all keys in the dictionary-like object.

        Returns:
            dict_keys: All keys in the object
        """
        pass  # pragma: no cover

    @abstractmethod
    def values(self) -> ValuesView[Any]:
        """
        Get all values in the dictionary-like object.

        Returns:
            dict_values: All values in the object
        """
        pass  # pragma: no cover

    @abstractmethod
    def items(self) -> ItemsView[str, Any]:
        """
        Get all key-value pairs in the dictionary-like object.

        Returns:
            dict_items: All key-value pairs in the object
        """
        pass  # pragma: no cover

    @abstractmethod
    def __contains__(self, key: Any) -> bool:
        """
        Check if a key exists in the dictionary-like object.

        Args:
            key: Key to check for existence

        Returns:
            bool: True if key exists, False otherwise
        """
        pass  # pragma: no cover

    @abstractmethod
    def __getitem__(self, key: str) -> Any:
        """
        Get a value by key using dictionary-style access.

        Args:
            key: Key to retrieve value for

        Returns:
            Value associated with the key

        Raises:
            KeyError: If key is not found
        """
        pass  # pragma: no cover

    @abstractmethod
    def __setitem__(self, key: str, val: Any) -> None:
        """
        Set a value by key using dictionary-style access.

        Args:
            key: Key to set
            val: Value to associate with the key
        """
        pass  # pragma: no cover

    @abstractmethod
    def has(self, key: str) -> bool:
        """
        Check if a key exists in the dictionary-like object.

        This is an alternative to the `in` operator, providing a more
        explicit way to check for key existence.

        Args:
            key: Key to check for existence

        Returns:
            bool: True if key exists, False otherwise
        """
        pass  # pragma: no cover

    @abstractmethod
    def __len__(self) -> int:
        """
        Get the number of items in the dictionary-like object.

        Returns:
            int: Number of key-value pairs in the object
        """
        pass  # pragma: no cover
