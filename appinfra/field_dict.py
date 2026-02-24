"""
FieldDict - Typed DotDict with field declarations.

Provides dataclass-like field declarations while preserving DotDict's
dict-native behavior (no serialization methods needed).
"""

from collections.abc import Callable
from typing import Any, ClassVar, get_origin

from .dot_dict import DotDict


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
        Field specification (resolved by FieldDict.__init__).

    Example:
        class Result(FieldDict):
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
    # Handle evaluated ClassVar (e.g., ClassVar[int])
    if get_origin(type_hint) is ClassVar:
        return True
    # Handle postponed annotations (strings like "ClassVar[str]" or "typing.ClassVar")
    if isinstance(type_hint, str) and "ClassVar" in type_hint:
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
        defaults.pop(name, None)  # Clear any parent static default
        required.discard(name)  # Subclass default overrides parent required
    elif isinstance(default, _MUTABLE_TYPES):
        raise TypeError(
            f"Mutable default for field '{name}' is not allowed. "
            f"Use field(default_factory={type(default).__name__}) instead."
        )
    else:
        defaults[name] = default
        factories.pop(name, None)  # Clear any parent factory default
        required.discard(name)  # Subclass default overrides parent required

    # Remove class attribute so it doesn't shadow instance dict values
    delattr(cls, name)


def _collect_parent_fields(
    cls: type,
) -> tuple[dict[str, Any], dict[str, Callable[[], Any]], set[str], set[str]]:
    """Collect field metadata from parent FieldDict classes."""
    defaults: dict[str, Any] = {}
    factories: dict[str, Callable[[], Any]] = {}
    required: set[str] = set()
    declared: set[str] = set()

    for klass in reversed(cls.__mro__):
        if klass is FieldDict or not isinstance(klass, type):
            continue
        if issubclass(klass, FieldDict) and klass is not cls:
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


class FieldDict(DotDict):
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
        class RunResult(FieldDict):
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
