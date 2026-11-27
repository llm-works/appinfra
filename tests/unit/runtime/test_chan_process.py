# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Chan(n, process=True) in its own process: what a send stores, and what
may be pickled."""

from __future__ import annotations

import pickle
import threading
from typing import Any

import pytest

from appinfra.runtime import Chan, select
from appinfra.runtime import ChanSend as Send


class TestCopy:
    def test_a_send_stores_a_copy(self) -> None:
        sent = {"a": [1, 2]}
        ch: Chan[Any] = Chan(1, process=True)
        ch.send(sent)
        got = ch.recv(timeout=0)
        assert got == sent
        assert got is not sent

    def test_a_select_send_stores_a_copy(self) -> None:
        sent = {"a": [1, 2]}
        ch: Chan[Any] = Chan(1, process=True)
        assert select(Send(ch, sent), timeout=0) == (0, None)
        got = ch.recv(timeout=0)
        assert got == sent
        assert got is not sent

    def test_a_send_case_reused_stores_a_copy_each_time(self) -> None:
        """One copy per select, not one per case: a receiver changing what
        it got does not change what the case sends next."""
        ch: Chan[Any] = Chan(1, process=True)
        case = Send(ch, {"items": []})
        select(case, timeout=0)
        first = ch.recv(timeout=0)
        first["items"].append(1)
        select(case, timeout=0)
        second = ch.recv(timeout=0)
        assert second is not first
        assert second == {"items": []}

    def test_a_local_chan_stores_the_value_itself(self) -> None:
        sent = {"a": [1, 2]}
        ch: Chan[Any] = Chan(1)
        ch.send(sent)
        assert ch.recv(timeout=0) is sent

    def test_a_value_that_cannot_be_pickled_fails_at_the_sender(self) -> None:
        ch: Chan[Any] = Chan(1, process=True)
        with pytest.raises(TypeError):
            ch.send(threading.Lock())
        assert len(ch) == 0

    def test_a_process_chan_in_a_value_is_kept_as_itself(self) -> None:
        """A channel is a reference, as in Go: a reply channel inside a
        message is the same channel on the receiving side."""
        reply: Chan[Any] = Chan(1, process=True)
        ch: Chan[Any] = Chan(1, process=True)
        ch.send(("ask", reply))
        _, got = ch.recv(timeout=0)
        assert got is reply

    def test_a_local_chan_in_a_value_is_refused_at_the_sender(self) -> None:
        ch: Chan[Any] = Chan(1, process=True)
        with pytest.raises(TypeError, match="process=True"):
            ch.send(("ask", Chan(1)))
        assert len(ch) == 0


class TestPickle:
    def test_a_local_chan_is_refused(self) -> None:
        with pytest.raises(TypeError, match="process=True"):
            pickle.dumps(Chan(1))

    def test_a_process_chan_is_refused_outside_a_link(self) -> None:
        with pytest.raises(TypeError, match="link"):
            pickle.dumps(Chan(1, process=True))
