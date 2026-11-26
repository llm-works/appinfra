# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Service errors cross process boundaries: an isolated service's process
reports its errors to the parent pickled."""

import pickle
from types import SimpleNamespace

import pytest

from appinfra.service import (
    ChannelResponseError,
    CycleError,
    DependencyFailedError,
    DependencyNotRunningError,
    HealthTimeoutError,
    InvalidTransitionError,
    RunError,
    SetupError,
    State,
)

ERRORS = [
    SetupError("svc", "no database"),
    RunError("svc", "exited during startup"),
    HealthTimeoutError("svc", 1.5),
    DependencyFailedError("api", "db"),
    DependencyNotRunningError("api", "db"),
    InvalidTransitionError("svc", State.CREATED, State.RUNNING),
    CycleError(["a", "b"]),
    ChannelResponseError(SimpleNamespace(error="refused")),
]


@pytest.mark.parametrize("error", ERRORS, ids=lambda e: type(e).__name__)
def test_an_error_survives_pickling(error: Exception) -> None:
    """Its type, message and attributes come back as they were."""
    copy = pickle.loads(pickle.dumps(error))

    assert type(copy) is type(error)
    assert str(copy) == str(error)
    assert vars(copy).keys() == vars(error).keys()
    for name, value in vars(error).items():
        if not isinstance(value, SimpleNamespace):  # compared by identity
            assert getattr(copy, name) == value
