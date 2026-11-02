# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Envelope: a sensitive value that stays masked until it is used.

A config value marked ``!secret`` loads as an Envelope, and code that needs a
secret (a database password, a token) takes one. It travels wrapped and is
opened with ``.reveal()`` only where the plaintext is consumed.
"""

from __future__ import annotations

import hmac
from typing import Any


class Envelope:
    """
    Masked-by-default wrapper for a sensitive string value.

    Not a ``str`` subclass. Every string-form conversion (``str``, ``repr``,
    ``format``) returns ``'***'`` so the value cannot leak through logging,
    f-strings, ``%``-formatting, or ``print``. The plaintext is only
    available via ``.reveal()``.

    Immutable. Like ``str(s) is s``, ``Envelope(e)`` returns ``e`` itself, so
    code that takes ``str | Envelope`` normalizes with ``Envelope(value)`` and
    consumes the text with ``Envelope(value).reveal()``; envelopes never nest.
    ``copy`` and ``deepcopy`` return the same object. Any type other than
    ``str`` or ``Envelope`` raises ``TypeError``.

    Equality compares underlying values so config round-trips work in tests.
    Hashing is deliberately omitted; secrets should not be dict keys or set
    members.

    As a pydantic field type it takes a str or an Envelope, without
    ``arbitrary_types_allowed``. A python-mode dump keeps the Envelope, which
    loads back; a JSON dump writes ``'***'``, which does not, as with
    ``pydantic.SecretStr``.
    """

    __slots__ = ("_value",)
    _MASK = "***"
    _value: str

    def __new__(cls, value: str | Envelope) -> Envelope:
        if isinstance(value, Envelope):
            return value
        if not isinstance(value, str):
            raise TypeError(f"Envelope requires a str, got {type(value).__name__}")
        envelope = super().__new__(cls)
        envelope._value = value
        return envelope

    @classmethod
    def optional(cls, value: str | Envelope | None) -> Envelope | None:
        """``Envelope(value)``, or None for None: for a setting that may be absent.

        ``Envelope(None)`` raises; this names the absence at the call site.
        """
        return None if value is None else cls(value)

    def __reduce__(self) -> tuple[type[Envelope], tuple[str]]:
        # __new__ takes the value; copyreg's default rebuild passes none
        return (Envelope, (self._value,))

    def __copy__(self) -> Envelope:
        return self

    def __deepcopy__(self, memo: dict[int, object]) -> Envelope:
        return self

    def reveal(self) -> str:
        """Return the underlying plaintext. The only path to the raw value."""
        return self._value

    def __str__(self) -> str:
        return self._MASK

    def __repr__(self) -> str:
        return f"Envelope('{self._MASK}')"

    def __format__(self, format_spec: str) -> str:
        return self._MASK

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Envelope):
            # compare_digest takes str only if it is ASCII; bytes cover any value,
            # and surrogatepass encodes the lone surrogates a str may hold
            return hmac.compare_digest(
                self._value.encode("utf-8", "surrogatepass"),
                other._value.encode("utf-8", "surrogatepass"),
            )
        return NotImplemented

    __hash__ = None  # type: ignore[assignment]

    @classmethod
    def __get_pydantic_core_schema__(cls, source: Any, handler: Any) -> Any:
        """Pydantic hook: validate a str or an Envelope; write the mask in JSON.

        Pydantic calls it only once it is imported, so appinfra keeps no
        dependency on pydantic.
        """
        from pydantic_core import core_schema

        return core_schema.no_info_plain_validator_function(
            _validate,
            serialization=core_schema.plain_serializer_function_ser_schema(
                _mask, when_used="json"
            ),
        )

    @classmethod
    def __get_pydantic_json_schema__(cls, schema: Any, handler: Any) -> dict[str, Any]:
        """Pydantic hook: a string that is written, never read back."""
        return {"type": "string", "format": "password", "writeOnly": True}


def _validate(value: object) -> Envelope:
    """Pydantic validator; a ValueError, unlike Envelope()'s TypeError, becomes a
    ValidationError."""
    if not isinstance(value, (str, Envelope)):
        raise ValueError(f"Envelope requires a str, got {type(value).__name__}")
    return Envelope(value)


def _mask(_value: Envelope) -> str:
    """Pydantic JSON serializer: the mask, never the plaintext."""
    return Envelope._MASK
