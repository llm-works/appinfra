"""
Dictionary-like object implementation with nested structure support.

This module provides DotDict, a class that behaves like a dictionary but allows
attribute-style access and supports nested dictionary/object structures with
dot-notation path traversal.

Also provides DataDotDict, a typed variant with field declarations for IDE
autocomplete and required field validation, while preserving dict-native behavior.
"""

import builtins
import datetime
from collections.abc import Callable
from typing import Any, ClassVar, Self

from . import time as timeutils
from .dict import DictInterface


class DotDict(dict, DictInterface):
    """
    Dictionary subclass with attribute-style access and nested structure support.

    Provides a convenient way to work with configuration data and other structured
    information using both dictionary-style and attribute-style access patterns.
    Supports automatic conversion of nested dictionaries to DotDict instances.

    Since DotDict subclasses dict, isinstance(dotdict, dict) returns True.
    """

    # Keys that would shadow critical methods and are not allowed.
    _RESERVED_KEYS = frozenset(
        {
            "set",
            "to_dict",
            "dict",
            "get",
            "has",
            "require",
            "clear",
        }
    )

    # Dict method names that can be used as data keys via attribute access.
    # When accessing these as attributes, data takes priority over methods.
    # Includes all dict methods except those in _RESERVED_KEYS.
    _DATA_PRIORITY_ATTRS = frozenset(
        {"keys", "values", "items", "copy", "pop", "popitem", "setdefault", "update"}
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """
        Initialize DotDict with initial key-value pairs.

        Supports both dict positional argument and keyword arguments,
        matching the built-in dict() API.

        Args:
            *args: Optional dict as first positional argument
            **kwargs: Initial key-value pairs to set

        Raises:
            TypeError: If more than one positional argument or non-dict positional argument

        Examples:
            DotDict({"a": 1, "b": 2})  # From dict
            DotDict(a=1, b=2)           # From kwargs
            DotDict({"a": 1}, b=2)      # Both (kwargs override)
        """
        super().__init__()
        if args:
            if len(args) > 1:
                raise TypeError(
                    f"DotDict() takes at most 1 positional argument ({len(args)} given)"
                )
            if not isinstance(args[0], dict):
                raise TypeError(
                    f"DotDict() argument must be a dict, not {type(args[0]).__name__!r}"
                )
            self.set(**args[0])
        self.set(**kwargs)

    def __getattribute__(self, name: str) -> Any:
        """
        Get attribute, prioritizing data over methods for certain names.

        For keys, values, items - if the name exists as data, return the data.
        Otherwise, fall through to normal attribute resolution.

        Args:
            name: Attribute name to get

        Returns:
            Value associated with the name
        """
        # For data-priority attrs, check if key exists in dict data first
        if name in DotDict._DATA_PRIORITY_ATTRS:
            if dict.__contains__(self, name):
                return dict.__getitem__(self, name)
        return super().__getattribute__(name)

    def __getattr__(self, key: str) -> Any:
        """
        Get value by attribute-style access (fallback for missing attributes).

        Args:
            key: Attribute name to get

        Returns:
            Value associated with the key

        Raises:
            AttributeError: If key doesn't exist (enables getattr(obj, key, default))
        """
        if dict.__contains__(self, key):
            return dict.__getitem__(self, key)
        raise AttributeError(f"'{type(self).__name__}' has no attribute '{key}'")

    def __setattr__(self, key: str, value: Any) -> None:
        """
        Set value by attribute-style access.

        Args:
            key: Attribute name to set
            value: Value to set
        """
        self._set_item(key, value)

    def set(self, **kwargs: Any) -> Self:
        """
        Set multiple key-value pairs, with automatic nested object creation.

        Args:
            **kwargs: Key-value pairs to set

        Returns:
            self: For method chaining
        """
        for key, val in kwargs.items():
            self._set_item(key, val)
        return self

    def _set_item(self, key: Any, val: Any) -> None:
        """
        Set a single key-value pair with automatic nested object creation.

        Args:
            key: Key to set (will be converted to string if needed)
            val: Value to set

        Raises:
            ValueError: If key would shadow a method name
        """
        # Convert date keys to strings
        if isinstance(key, datetime.date):
            key = timeutils.date_to_str(key)
        elif not isinstance(key, str):
            # Convert non-string keys to strings
            key = str(key)

        # Prevent shadowing methods
        if key in self._RESERVED_KEYS:
            raise ValueError(
                f"Key '{key}' is reserved and cannot be used (would shadow method)"
            )

        # Handle nested dictionaries (but not DotDict instances)
        if isinstance(val, dict) and not isinstance(val, DotDict):
            super().__setitem__(key, DotDict(**val))
        # Handle lists with potential nested structures
        elif isinstance(val, list):
            super().__setitem__(key, list(map(self._map_entry, val)))
        # Handle simple values
        else:
            super().__setitem__(key, val)

    def clear(self) -> None:
        """
        Clear all items from the dictionary.
        """
        super().clear()

    @staticmethod
    def _map_entry(entry: Any) -> Any:
        """
        Map a list entry to appropriate object type.

        Args:
            entry: Entry to map

        Returns:
            DotDict or original entry: Mapped entry
        """
        if isinstance(entry, dict):
            return DotDict(**entry)
        return entry

    def dict(self) -> builtins.dict[str, Any]:
        """
        Convert the object to a plain dictionary representation.

        Only converts one level - nested DotDicts are converted to plain dicts,
        but their contents are not recursively processed.

        Returns:
            dict: Dictionary representation with nested DotDict instances converted
        """
        result: builtins.dict[str, Any] = {}
        # Use super().items() to always get dict method, not data
        for key, val in super().items():
            result[key] = val.dict() if isinstance(val, DotDict) else val
        return result

    def to_dict(self) -> builtins.dict[str, Any]:
        """
        Recursively convert DotDict and all nested structures to plain dicts.

        Handles nested DotDicts, lists containing DotDicts, and other structures.

        Returns:
            dict: Fully converted dictionary with no DotDict instances
        """
        result: builtins.dict[str, Any] = {}
        # Use super().items() to always get dict method, not data
        for key, val in super().items():
            if isinstance(val, DotDict):
                result[key] = val.to_dict()
            elif isinstance(val, list):
                result[key] = [
                    item.to_dict() if isinstance(item, DotDict) else item
                    for item in val
                ]
            elif isinstance(val, builtins.dict):
                # Handle plain dicts that might contain DotDicts
                result[key] = {
                    k: v.to_dict() if isinstance(v, DotDict) else v
                    for k, v in val.items()
                }
            else:
                result[key] = val
        return result

    def __getitem__(self, key: str) -> Any:
        """
        Get value by key with dictionary-style access.

        Returns None for missing keys instead of raising KeyError,
        matching the historical DotDict behavior.

        Args:
            key: Key to get

        Returns:
            Value or None if key doesn't exist
        """
        try:
            return super().__getitem__(key)
        except KeyError:
            return None

    def __setitem__(self, key: str, val: Any) -> None:
        """
        Set value by key with dictionary-style access.

        Args:
            key: Key to set
            val: Value to set
        """
        self._set_item(key, val)

    def __repr__(self) -> str:
        """
        Get repr of the object.

        Returns:
            str: Repr showing DotDict with contents
        """
        return f"DotDict({super().__repr__()})"

    def has(self, path: str) -> bool:
        """
        Check if a dot-separated path exists in the object.

        Args:
            path (str): Dot-separated path to check (e.g., "database.host")

        Returns:
            bool: True if the path exists
        """
        if not path:
            return False

        cur: Any = self
        for item in path.split("."):
            if not item:  # Skip empty components
                continue
            if isinstance(cur, dict) and item in cur:
                cur = cur[item]
            else:
                return False
        return True

    def get(self, path: str, default: Any = None, max_steps_up: int = 0) -> Any:
        """
        Get value by dot-separated path with fallback support.

        Follows standard dict.get() semantics: returns default (None) if path not found.

        Args:
            path (str): Dot-separated path to get (e.g., "database.host")
            default: Default value to return if path not found (default: None)
            max_steps_up (int): Maximum number of steps up the hierarchy to search

        Returns:
            Value: Found value or default
        """
        if not path:
            return default

        cur: Any = self
        history: list[Any] = []
        components = [
            item for item in path.split(".") if item
        ]  # Filter empty components

        for i, item in enumerate(components):
            if isinstance(cur, dict) and item in cur:
                history.append(cur)
                cur = cur[item]
                if i == len(components) - 1:
                    return cur
            elif i == len(components) - 1:
                # Try searching up the hierarchy
                for j in range(min(max_steps_up, len(history))):
                    if isinstance(history[-j - 1], dict) and item in history[-j - 1]:
                        return history[-j - 1][item]
                break
            else:
                break
        return default

    def require(self, path: str) -> Any:
        """
        Get value by dot-separated path, raising an error if not found.

        Unlike get(), this method raises DotDictPathNotFoundError if the path
        doesn't exist, making it clear when a configuration value is required.

        Args:
            path (str): Dot-separated path to get (e.g., "database.host")

        Returns:
            Value at the path

        Raises:
            DotDictPathNotFoundError: If the path doesn't exist
        """
        if not self.has(path):
            raise DotDictPathNotFoundError(self, path)
        return self.get(path)


class DotDictPathNotFoundError(Exception):
    """
    Exception raised when a required path is not found in a DotDict.

    Attributes:
        obj: The DotDict instance where the path was not found
        path: The path that was not found
    """

    def __init__(self, obj: DotDict, path: str) -> None:
        """
        Initialize the path not found error.

        Args:
            obj: DotDict instance
            path (str): Path that was not found
        """
        self.obj = obj
        self.path = path
        super().__init__(f"Required path '{path}' not found")


# =============================================================================
# DataDotDict - Typed DotDict with field declarations
# =============================================================================


class _FieldSpec:
    """Specification for a field with a default factory."""

    __slots__ = ("default_factory",)

    def __init__(self, default_factory: Callable[[], Any]) -> None:
        self.default_factory = default_factory


def field(*, default_factory: Callable[[], Any]) -> Any:
    """
    Declare a field with a factory for mutable defaults.

    Use this for fields with mutable default values (list, dict, set) to ensure
    each instance gets its own copy.

    Args:
        default_factory: Zero-argument callable that returns the default value.

    Returns:
        Field specification (resolved by DataDotDict.__init__).

    Example:
        class Result(DataDotDict):
            errors: list = field(default_factory=list)
            metadata: dict = field(default_factory=dict)
    """
    return _FieldSpec(default_factory)


# Types that are mutable and shouldn't be used as direct defaults
_MUTABLE_TYPES = (list, dict, set)


def _is_skippable_field(name: str, type_hint: Any) -> bool:
    """Check if a field annotation should be skipped (private or ClassVar)."""
    if name.startswith("_"):
        return True
    if hasattr(type_hint, "__origin__") and type_hint.__origin__ is ClassVar:
        return True
    return False


def _process_field(
    cls: type,
    name: str,
    defaults: dict[str, Any],
    factories: dict[str, Callable[[], Any]],
    required: set[str],
) -> None:
    """Process a single field annotation, extracting default or marking required."""
    # Check cls.__dict__ directly, not hasattr (which sees inherited attributes)
    if name not in cls.__dict__:
        required.add(name)
        return

    default = cls.__dict__[name]

    if isinstance(default, _FieldSpec):
        factories[name] = default.default_factory
        required.discard(name)  # Subclass default overrides parent required
    elif isinstance(default, _MUTABLE_TYPES):
        raise TypeError(
            f"Mutable default for field '{name}' is not allowed. "
            f"Use field(default_factory={type(default).__name__}) instead."
        )
    else:
        defaults[name] = default
        required.discard(name)  # Subclass default overrides parent required

    # Remove class attribute so it doesn't shadow instance dict values
    delattr(cls, name)


def _collect_parent_fields(
    cls: type,
) -> tuple[dict[str, Any], dict[str, Callable[[], Any]], set[str], set[str]]:
    """Collect field metadata from parent DataDotDict classes."""
    # Import here to avoid circular reference at module level
    from appinfra.dot_dict import DataDotDict

    defaults: dict[str, Any] = {}
    factories: dict[str, Callable[[], Any]] = {}
    required: set[str] = set()
    declared: set[str] = set()

    for klass in reversed(cls.__mro__):
        if klass is DataDotDict or not isinstance(klass, type):
            continue
        if issubclass(klass, DataDotDict) and klass is not cls:
            defaults.update(klass._field_defaults)
            factories.update(klass._field_factories)
            required.update(klass._required_fields)
            declared.update(klass._declared_fields)

    return defaults, factories, required, declared


def _merge_positional_dict(
    cls_name: str, args: tuple[Any, ...], kwargs: dict[str, Any]
) -> dict[str, Any]:
    """Merge positional dict argument into kwargs (like DotDict)."""
    if not args:
        return kwargs
    if len(args) > 1:
        raise TypeError(
            f"{cls_name}() takes at most 1 positional argument ({len(args)} given)"
        )
    if not isinstance(args[0], dict):
        raise TypeError(
            f"{cls_name}() argument must be a dict, not {type(args[0]).__name__!r}"
        )
    return {**args[0], **kwargs}


class DataDotDict(DotDict):
    """
    DotDict with declared fields, defaults, and optional strict mode.

    Provides dataclass-like field declarations while preserving DotDict's
    dict-native behavior (no serialization methods needed).

    Features:
        - Field declarations with type hints (IDE autocomplete)
        - Required fields (no default) validated on init
        - Default values for optional fields
        - Mutable defaults via field(default_factory=...)
        - __post_init__ hook for computed fields
        - Optional strict mode to reject undeclared fields

    Example:
        class RunResult(DataDotDict):
            status: str                              # required
            method: str = "sft"                      # optional with default
            metrics: dict = field(default_factory=dict)  # mutable default

            def __post_init__(self):
                self.summary = f"{self.status}: {self.method}"

        result = RunResult(status="completed")
        result.method   # "sft"
        result.metrics  # {} (fresh dict per instance)
    """

    # Class-level configuration
    _strict: ClassVar[bool] = False
    _field_defaults: ClassVar[dict[str, Any]] = {}
    _field_factories: ClassVar[dict[str, Callable[[], Any]]] = {}
    _required_fields: ClassVar[frozenset[str]] = frozenset()
    _declared_fields: ClassVar[frozenset[str]] = frozenset()

    def __init_subclass__(cls, strict: bool = False, **kwargs: Any) -> None:
        """Configure subclass field definitions."""
        super().__init_subclass__(**kwargs)
        cls._strict = strict

        # Collect inherited field metadata from parent classes
        defaults, factories, required, declared = _collect_parent_fields(cls)

        # Process this class's own annotations (may override inherited)
        for name, type_hint in getattr(cls, "__annotations__", {}).items():
            if _is_skippable_field(name, type_hint):
                continue
            declared.add(name)
            _process_field(cls, name, defaults, factories, required)

        cls._field_defaults = defaults
        cls._field_factories = factories
        cls._required_fields = frozenset(required)
        cls._declared_fields = frozenset(declared)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize with field validation and defaults."""
        kwargs = _merge_positional_dict(type(self).__name__, args, kwargs)

        # Validate required fields
        missing = self._required_fields - kwargs.keys()
        if missing:
            raise TypeError(f"Missing required field(s): {', '.join(sorted(missing))}")

        # Validate strict mode
        if self._strict:
            extra = kwargs.keys() - self._declared_fields
            if extra:
                raise TypeError(
                    f"Unknown field(s) in strict mode: {', '.join(sorted(extra))}"
                )

        # Apply defaults (static defaults first, then factories)
        for name, default in self._field_defaults.items():
            if name not in kwargs:
                kwargs[name] = default
        for name, factory in self._field_factories.items():
            if name not in kwargs:
                kwargs[name] = factory()

        super().__init__(**kwargs)

        # Look up __post_init__ on the class, not instance (avoids matching data keys)
        post_init = getattr(type(self), "__post_init__", None)
        if callable(post_init):
            post_init(self)

    def __repr__(self) -> str:
        """Show class name in repr."""
        return f"{type(self).__name__}({dict.__repr__(self)})"
