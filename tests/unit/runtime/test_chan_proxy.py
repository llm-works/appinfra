# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""A proxy of a process Chan, as a type: what it must define itself."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from appinfra.runtime.chan.chan import Chan
from appinfra.runtime.chan.proxy import _ChanProxy

# Chan's own, inherited: they use only recv(), arecv() and _process, which
# the proxy has (each tested through a proxy in tests/integration/runtime/test_proxy.py)
INHERITED = {"__iter__", "__next__", "__aiter__", "__anext__", "__reduce__"}


def test_every_operation_of_a_chan_is_the_proxys_own() -> None:
    """One Chan defines and the proxy inherits would run Chan's local code on
    state the proxy does not have: an operation added to Chan must be added
    here too, or shown to use only what the proxy has."""
    operations = {
        name
        for name, attr in vars(Chan).items()
        if callable(attr) and (not name.startswith("_") or name.startswith("__"))
    }
    assert operations - set(vars(_ChanProxy)) - INHERITED == set()


def test_a_chans_local_state_is_not_made() -> None:
    """It lives at the home: used here by mistake, it fails at once."""
    proxy: _ChanProxy[int] = _ChanProxy(MagicMock(), 1)
    with pytest.raises(AttributeError):
        proxy._lock  # noqa: B018
