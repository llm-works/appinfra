# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for appinfra.security.envelope module."""

import pytest

from appinfra.security.envelope import Envelope


class TestEnvelope:
    """Envelope must mask itself in every string form and only expose via reveal()."""

    def test_str_returns_mask(self):
        assert str(Envelope("hunter2")) == "***"

    def test_repr_returns_mask(self):
        assert repr(Envelope("hunter2")) == "Envelope('***')"

    def test_format_returns_mask(self):
        assert f"{Envelope('hunter2')}" == "***"
        assert f"{Envelope('hunter2'):>10}" == "***"

    def test_reveal_returns_plaintext(self):
        assert Envelope("hunter2").reveal() == "hunter2"

    def test_equality_compares_underlying(self):
        assert Envelope("a") == Envelope("a")
        assert Envelope("a") != Envelope("b")

    def test_not_a_str(self):
        # Type boundary: consumers cannot pass Envelope where str is required
        # without going through .reveal() first.
        assert not isinstance(Envelope("x"), str)

    def test_unhashable(self):
        with pytest.raises(TypeError):
            {Envelope("x")}

    def test_rejects_non_str_value(self):
        with pytest.raises(TypeError):
            Envelope(123)  # type: ignore[arg-type]

    def test_rejects_envelope_value(self):
        # Constructor is strict: only str accepted. Boundary code that wants
        # to accept Envelope too must go through Envelope.ensure().
        with pytest.raises(TypeError):
            Envelope(Envelope("x"))  # type: ignore[arg-type]

    def test_ensure_none_passes_through(self):
        assert Envelope.ensure(None) is None

    def test_ensure_str_wraps(self):
        result = Envelope.ensure("hunter2")
        assert isinstance(result, Envelope)
        assert result.reveal() == "hunter2"

    def test_ensure_envelope_preserves_identity(self):
        existing = Envelope("hunter2")
        assert Envelope.ensure(existing) is existing

    def test_ensure_rejects_other_types(self):
        with pytest.raises(TypeError):
            Envelope.ensure(123)  # type: ignore[arg-type]
