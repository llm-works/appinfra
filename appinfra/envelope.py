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
            return hmac.compare_digest(self._value, other._value)
        return NotImplemented

    __hash__ = None  # type: ignore[assignment]
