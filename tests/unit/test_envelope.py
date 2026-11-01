# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for appinfra.envelope module."""

import copy
import pickle

import pytest

from appinfra.envelope import Envelope


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

    def test_equality_handles_non_ascii(self):
        assert Envelope("pässword") == Envelope("pässword")
        assert Envelope("pässword") != Envelope("passwörd")
        assert Envelope("\ud800") == Envelope("\ud800")  # lone surrogate

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

    def test_wrapping_an_envelope_returns_it(self):
        # Like str(s) is s: a value that may or may not be wrapped normalizes
        # with Envelope(value), without nesting or copying
        existing = Envelope("x")
        assert Envelope(existing) is existing

    def test_optional_passes_none_through(self):
        """For a setting that may be absent; Envelope(None) itself raises."""
        assert Envelope.optional(None) is None
        with pytest.raises(TypeError):
            Envelope(None)  # type: ignore[arg-type]

    def test_optional_wraps_a_value(self):
        wrapped = Envelope.optional("x")
        assert isinstance(wrapped, Envelope) and wrapped.reveal() == "x"
        existing = Envelope("y")
        assert Envelope.optional(existing) is existing
        assert Envelope.optional("") == Envelope("")  # empty is a value, not absent

    def test_optional_rejects_non_str_value(self):
        with pytest.raises(TypeError):
            Envelope.optional(123)  # type: ignore[arg-type]

    def test_copy_returns_the_same_envelope(self):
        existing = Envelope("x")
        assert copy.copy(existing) is existing
        assert copy.deepcopy(existing) is existing
        assert copy.deepcopy({"pass": existing})["pass"] is existing

    def test_pickle_round_trip_keeps_the_value(self):
        restored = pickle.loads(pickle.dumps(Envelope("hunter2")))
        assert isinstance(restored, Envelope)
        assert restored.reveal() == "hunter2"
