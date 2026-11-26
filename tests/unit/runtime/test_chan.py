# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Chan without waiting: the buffer, close, and calls that would wait refused."""

import pytest

from appinfra.runtime import Chan, ChanClosedError, select
from appinfra.runtime import ChanRecv as Recv
from appinfra.runtime import ChanSend as Send


class TestChan:
    def test_a_negative_capacity_is_refused(self):
        with pytest.raises(ValueError, match="capacity"):
            Chan[int](-1)

    def test_values_come_out_in_the_order_sent(self):
        ch = Chan[int](3)
        for i in range(3):
            ch.send(i)
        assert [ch.recv(), ch.recv(), ch.recv()] == [0, 1, 2]

    def test_a_send_with_no_room_and_no_wait_times_out(self):
        ch = Chan[int](1)
        ch.send(1)
        with pytest.raises(TimeoutError):
            ch.send(2, timeout=0)
        assert ch.recv() == 1
        assert not ch._senders  # Private: the refused send left nothing behind

    def test_without_a_buffer_a_send_needs_a_receiver(self):
        with pytest.raises(TimeoutError):
            Chan[int](0).send(1, timeout=0)

    def test_a_receive_without_waiting_returns_a_buffered_value(self):
        """timeout=0 takes a value already there; only an empty channel times out."""
        ch = Chan[int](1)
        ch.send(1)
        assert ch.recv(timeout=0) == 1
        with pytest.raises(TimeoutError):
            ch.recv(timeout=0)
        assert not ch._receivers  # Private: the refused receive left nothing behind

    def test_a_closed_channel_is_drained_then_raises(self):
        """Values buffered before close() are still received; then recv() raises."""
        ch = Chan[int](2)
        ch.send(1)
        ch.send(2)
        ch.close()
        assert [ch.recv(), ch.recv()] == [1, 2]
        with pytest.raises(ChanClosedError):
            ch.recv()

    def test_a_full_closed_channel_is_drained_then_raises(self):
        """A full buffer leaves no room for a close marker; close needs none."""
        ch = Chan[int](1)
        ch.send(1)
        ch.close()
        assert ch.recv(timeout=0) == 1
        with pytest.raises(ChanClosedError):
            ch.recv(timeout=0)

    def test_a_send_on_a_closed_channel_raises(self):
        ch = Chan[int](1)
        ch.close()
        ch.close()  # idempotent
        with pytest.raises(ChanClosedError):
            ch.send(1)

    def test_a_negative_timeout_is_refused(self):
        """It has no one meaning in Python (queue: an error, threading: wait
        for ever); here it is an error, ready or not."""
        ch = Chan[int](1)
        with pytest.raises(ValueError, match="timeout"):
            ch.send(1, timeout=-1)
        ch.send(1)
        with pytest.raises(ValueError, match="timeout"):
            ch.recv(timeout=-1)
        assert ch.recv(timeout=0) == 1  # the refused calls changed nothing

    def test_iteration_drains_and_ends_at_the_close(self):
        ch = Chan[int](3)
        for i in range(3):
            ch.send(i)
        ch.close()
        assert list(ch) == [0, 1, 2]


class TestUnbounded:
    """Chan(None): a send never waits, so values from senders that must not
    block arrive, in order."""

    def test_a_send_never_waits(self):
        ch = Chan[int](None)
        for i in range(10_000):
            ch.send(i, timeout=0)
        assert [ch.recv(timeout=0) for _ in range(10_000)] == list(range(10_000))
        assert not ch._senders  # Private: no send queued to wait

    def test_a_closed_channel_is_drained_then_raises(self):
        ch = Chan[int](None)
        ch.send(1)
        ch.send(2)
        ch.close()
        assert [ch.recv(timeout=0), ch.recv(timeout=0)] == [1, 2]
        with pytest.raises(ChanClosedError):
            ch.recv(timeout=0)

    def test_a_send_on_a_closed_channel_raises(self):
        ch = Chan[int](None)
        ch.close()
        with pytest.raises(ChanClosedError):
            ch.send(1, timeout=0)

    def test_a_select_send_is_always_ready(self):
        ch = Chan[int](None)
        ch.send(1)
        assert select(Send(ch, 2), timeout=0) == (0, None)
        assert [ch.recv(timeout=0), ch.recv(timeout=0)] == [1, 2]


class TestSelect:
    """select() over cases ready at once, or with nothing to wait for."""

    def test_a_ready_receive_returns_its_index_and_value(self):
        idle, ready = Chan[int](1), Chan[int](1)
        ready.send(7)
        assert select(Recv(idle), Recv(ready), timeout=0) == (1, 7)

    def test_a_ready_send_returns_its_index_and_delivers(self):
        full, room = Chan[int](1), Chan[int](1)
        full.send(1)
        assert select(Send(full, 2), Send(room, 3), timeout=0) == (1, None)
        assert room.recv(timeout=0) == 3
        assert full.recv(timeout=0) == 1

    def test_nothing_ready_without_waiting_times_out_and_queues_nothing(self):
        a, b = Chan[int](0), Chan[int](1)
        b.send(1)
        with pytest.raises(TimeoutError):
            select(Recv(a), Send(b, 2), timeout=0)
        assert not (a._receivers or b._senders)  # Private: no entry left

    def test_a_closed_channel_raises_with_the_case_index(self):
        open_, closed = Chan[int](1), Chan[int](1)
        closed.close()
        for case in (Recv(closed), Send(closed, 1)):
            with pytest.raises(ChanClosedError) as caught:
                select(Recv(open_), case, timeout=0)
            assert caught.value.index == 1

    def test_no_case_or_a_negative_timeout_is_refused(self):
        with pytest.raises(ValueError, match="case"):
            select(timeout=0)
        with pytest.raises(ValueError, match="timeout"):
            select(Recv(Chan[int](1)), timeout=-1)

    def test_ready_cases_are_chosen_at_random(self):
        """As in Go: a fixed order would starve the later cases. 100 draws
        from two ready cases miss one with probability 2**-99."""
        a, b = Chan[int](100), Chan[int](100)
        for i in range(100):
            a.send(i)
            b.send(i)
        chosen = {select(Recv(a), Recv(b), timeout=0)[0] for _ in range(100)}
        assert chosen == {0, 1}
