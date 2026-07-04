"""
Helpers for normalizing values placed in log ``extra={...}`` before they are
JSON-encoded or pickled.

Certain opaque objects (notably ``sqlalchemy.engine.url.URL``) are tuple
subclasses whose ``str()`` form is the canonical, human-meaningful
representation. The stdlib JSON encoder would otherwise destructure them
positionally and the multiprocessing queue sanitizer would strip them to a
plain ``tuple``. ``coerce_leaf`` / ``coerce_tree`` give those values their
preferred string form before either path runs.
"""

from typing import Any


def coerce_leaf(value: Any) -> Any:
    """Return the preferred serialization form of ``value`` or ``value`` itself.

    The result is ``value`` (unchanged) when no coercion applies, so callers
    can use identity (``coerced is not value``) to detect a transformation.
    """
    if _is_sqlalchemy_url(value):
        return str(value)
    return value


def coerce_tree(value: Any, _seen: set[int] | None = None) -> Any:
    """Recursively apply ``coerce_leaf`` through dict/list/tuple/set containers.

    Container types are walked so that opaque values nested inside extras are
    coerced wherever they appear. Plain scalars and non-container objects
    that ``coerce_leaf`` does not transform are returned as-is.
    """
    if _seen is None:
        _seen = set()

    coerced = coerce_leaf(value)
    if coerced is not value:
        return coerced

    if isinstance(value, (dict, list, tuple, set)):
        obj_id = id(value)
        if obj_id in _seen:
            return "<cyclic reference>"
        _seen = _seen | {obj_id}

    if isinstance(value, dict):
        return {coerce_leaf(k): coerce_tree(v, _seen) for k, v in value.items()}
    if isinstance(value, list):
        return [coerce_tree(v, _seen) for v in value]
    if isinstance(value, tuple):
        return tuple(coerce_tree(v, _seen) for v in value)
    if isinstance(value, set):
        return {coerce_tree(v, _seen) for v in value}
    return value


def _is_sqlalchemy_url(value: Any) -> bool:
    """Duck-type check: avoid importing sqlalchemy as a hard dependency."""
    cls = type(value)
    return cls.__module__ == "sqlalchemy.engine.url" and cls.__name__ == "URL"
