# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Traceable base class for hierarchical attribute access.

This module provides the Traceable base class that enables hierarchical
attribute lookup through parent-child relationships.
"""

from __future__ import annotations

from typing import Any

from ..constants import MAX_TRACE_DEPTH
from ..errors import AttrNotFoundError


class Traceable:
    """
    Base class that provides hierarchical attribute tracing.

    Enables objects to access attributes from their parent hierarchy,
    allowing for inheritance-like behavior in composition patterns.
    """

    def __init__(self, parent: Traceable | None = None):
        """
        Initialize the traceable object.

        Args:
            parent: Parent traceable object (optional)
        """
        self._parent = parent

    @property
    def parent(self) -> Traceable | None:
        """
        Get the parent object.

        Returns:
            Traceable or None: Parent object
        """
        return self._parent

    def set_parent(self, parent: Traceable | None) -> None:
        """
        Set the parent object.

        This method allows changing the parent after construction while
        maintaining proper encapsulation. It validates the parent is a
        Traceable instance if not None.

        Args:
            parent: New parent traceable object (optional)

        Raises:
            TypeError: If parent is not None and not a Traceable instance
        """
        if parent is not None and not isinstance(parent, Traceable):
            raise TypeError(
                f"Parent must be a Traceable instance, got {type(parent).__name__}"
            )
        self._parent = parent

    def _check_trace_limits(self, name: str, _visited: set, _depth: int) -> None:
        """Check recursion depth and circular reference limits."""
        # Check recursion depth limit
        if _depth >= MAX_TRACE_DEPTH:
            raise AttrNotFoundError(
                f"{name} (maximum trace depth of {MAX_TRACE_DEPTH} exceeded)"
            )

        # Check for circular reference
        obj_id = id(self)
        if obj_id in _visited:
            raise AttrNotFoundError(
                f"{name} (circular reference detected in parent hierarchy)"
            )
        _visited.add(obj_id)

    def _find_local_attr(self, name: str) -> tuple[bool, Any]:
        """Find attribute locally (instance or class), returns (found, value)."""
        # Check instance attributes (in __dict__) - doesn't trigger properties
        if name in self.__dict__:
            return True, getattr(self, name)

        # Check class attributes (properties, methods, class variables)
        for cls in self.__class__.__mro__:
            if name in cls.__dict__:
                return True, getattr(self, name)

        return False, None

    def trace_attr(
        self, name: str, _visited: set | None = None, _depth: int = 0
    ) -> Any:
        """
        Trace an attribute through the parent hierarchy with cycle detection.

        Searches for an attribute in the current object, and if not found,
        recursively searches up the parent chain. Detects circular references
        to prevent infinite loops and enforces maximum recursion depth.

        Uses __dict__ and class inspection to check for attribute existence
        without triggering property getters, which prevents infinite loops
        when properties use trace_attr() internally.

        Args:
            name: Attribute name to search for
            _visited: Internal parameter for cycle detection (do not use)
            _depth: Internal parameter for recursion depth tracking (do not use)

        Returns:
            Attribute value from the hierarchy

        Raises:
            AttrNotFoundError: If attribute is not found in the hierarchy,
                               if a circular reference is detected, or if
                               maximum trace depth is exceeded
        """
        # Initialize visited set on first call
        if _visited is None:
            _visited = set()

        # Check limits and circular references
        self._check_trace_limits(name, _visited, _depth)

        # Try to find attribute locally
        found, value = self._find_local_attr(name)
        if found:
            return value

        # Attribute not found locally - check parent
        if self.parent is None:
            raise AttrNotFoundError(name)

        return self.parent.trace_attr(name, _visited, _depth + 1)

    def trace_root(self) -> Traceable:
        """
        Find the root object in the hierarchy.

        Returns:
            Traceable: The root object (object with no parent)
        """
        if self.parent is None:
            return self
        return self.parent.trace_root()

    def has_attr(self, name: str) -> bool:
        """
        Check if an attribute exists in the hierarchy.

        Args:
            name: Attribute name to check

        Returns:
            bool: True if attribute exists in the hierarchy
        """
        try:
            self.trace_attr(name)
            return True
        except AttrNotFoundError:
            return False

    def get_attr_or_default(self, name: str, default: Any = None) -> Any:
        """
        Get an attribute from the hierarchy or return default.

        Args:
            name: Attribute name to get
            default: Default value if attribute not found

        Returns:
            Attribute value or default
        """
        try:
            return self.trace_attr(name)
        except AttrNotFoundError:
            return default
