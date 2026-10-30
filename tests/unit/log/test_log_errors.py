# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for the logging exceptions."""

import pickle

import pytest

from appinfra.log.errors import (
    InvalidLogLevelError,
    LoggerExistsError,
    LoggerNotFoundError,
    ReservedKeyError,
)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("error", "attr", "value", "message"),
    [
        (LoggerExistsError("/svc"), "name", "/svc", "logger '/svc' already exists"),
        (LoggerNotFoundError("/svc"), "name", "/svc", "no logger named '/svc'"),
        (InvalidLogLevelError("loud"), "level", "loud", "Invalid log level: loud"),
        (
            ReservedKeyError({"name", "msg"}),
            "keys",
            frozenset({"name", "msg"}),
            "Reserved key(s) in log extra: msg, name. "
            "These are LogRecord attributes and cannot be used.",
        ),
    ],
)
def test_survives_pickling(error, attr, value, message):
    """A worker's exception reaches the parent with its attribute and message intact."""
    restored = pickle.loads(pickle.dumps(error))

    assert type(restored) is type(error)
    assert getattr(restored, attr) == value
    assert str(restored) == str(error) == message
