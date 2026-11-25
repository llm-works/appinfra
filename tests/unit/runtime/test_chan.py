# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Chan without waiting: the buffer, close, and calls that would wait refused."""

import pytest

from appinfra.runtime import Chan, ChanClosedError


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

    def test_iteration_drains_and_ends_at_the_close(self):
        ch = Chan[int](3)
        for i in range(3):
            ch.send(i)
        ch.close()
        assert list(ch) == [0, 1, 2]
