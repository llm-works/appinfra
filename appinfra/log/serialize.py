# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

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

import json
import logging
import traceback
from typing import Any

from ..security.envelope import Envelope


def record_traceback(record: logging.LogRecord) -> str | None:
    """Return a record's exception traceback as text, wherever logging put it.

    Checked in order: ``exc_info`` (the full tuple), ``exc_text`` (exc_info
    already formatted, as ``MPQueueHandler`` does before pickling),
    ``extra["exception"]`` (from its ``__traceback__``), and
    ``extra["exception_formatted"]`` (``MPQueueHandler``'s rendering of it).
    """
    if record.exc_info and record.exc_info[0] is not None:
        return _format_exception(record.exc_info)
    if record.exc_text:
        return record.exc_text
    extra = getattr(record, "__infra__extra", None) or {}
    exc = extra.get("exception")
    if isinstance(exc, BaseException):
        return _format_exception((type(exc), exc, exc.__traceback__))
    formatted = extra.get("exception_formatted")
    return formatted if isinstance(formatted, str) else None


def _format_exception(exc_info: Any) -> str:
    try:
        return "".join(traceback.format_exception(*exc_info))
    except Exception:
        return f"Exception formatting failed: {exc_info[1]}"


def sanitize_extra(extra: dict[str, Any]) -> dict[str, Any]:
    """Return a JSON-serializable copy of a log record's ``extra`` fields.

    Each value is walked with ``coerce_tree`` first, so opaque types with a
    preferred ``__str__`` form reach the encoder as their string form rather
    than being destructured; a value that still cannot be encoded (an
    exception object, for one) becomes its ``str()``.
    """
    sanitized = {}
    for key, value in extra.items():
        key = coerce_leaf(key)
        try:
            value = coerce_tree(value)
            json.dumps(value)
            sanitized[key] = value
        except Exception:
            sanitized[key] = str(value)
    return sanitized


def coerce_leaf(value: Any) -> Any:
    """Return the preferred serialization form of ``value`` or ``value`` itself.

    The result is ``value`` (unchanged) when no coercion applies, so callers
    can use identity (``coerced is not value``) to detect a transformation.
    """
    if isinstance(value, Envelope):
        return str(value)
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
