# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""pipe(): a channel between processes, its ends in one process or two."""

import multiprocessing as mp
import threading

import pytest

from appinfra.runtime import ChanClosedError, ChanRecv, ChanSend, select
from appinfra.runtime.chan import PipeRecvEnd, PipeSendEnd, pipe

METHODS = [
    pytest.param(
        "fork",
        marks=pytest.mark.skipif(
            "fork" not in mp.get_all_start_methods(), reason="no fork start method"
        ),
    ),
    "spawn",
]

# The test process runs threads; a child forked from it uses only the pipe
pytestmark = pytest.mark.filterwarnings(
    "ignore:This process .* is multi-threaded:DeprecationWarning"
)


def _send(
    send: PipeSendEnd[int], inherited: PipeRecvEnd[int] | None, count: int
) -> None:
    """Child target: send 0..count-1 and close; with no count, exit without
    a close."""
    if inherited is not None:
        inherited.release()
    sender = send.open()
    if count:
        for i in range(count):
            sender.send(i)
        sender.close()


def _run_child(method: str, count: int) -> list[int]:
    """What this process receives from a child sending *count* values, until
    the channel closes."""
    send, recv = pipe(5)
    inherited = recv if method == "fork" else None
    child = mp.get_context(method).Process(
        target=_send, args=(send, inherited, count), daemon=True
    )
    child.start()
    try:
        send.release()
        chan, received = recv.open(), []
        with pytest.raises(ChanClosedError):
            while True:  # the timeout is the failure path
                received.append(chan.recv(timeout=10.0))
        return received
    finally:
        child.join(10.0)
        if child.is_alive():
            child.kill()


class TestAcrossProcesses:
    @pytest.mark.parametrize("method", METHODS)
    def test_values_arrive_in_order_then_the_close(self, method: str):
        assert _run_child(method, 5) == [0, 1, 2, 3, 4]

    @pytest.mark.parametrize("method", METHODS)
    def test_the_sending_process_exiting_closes_the_channel(self, method: str):
        """No close(): EOF, once the child is gone, ends the channel."""
        assert _run_child(method, 0) == []


class TestInOneProcess:
    """Both ends here: the relay is the same, without a second process."""

    def test_a_capacity_below_one_is_refused(self):
        with pytest.raises(ValueError, match="capacity"):
            pipe(0)

    def test_at_most_capacity_values_are_sent_and_not_received(self):
        send, recv = pipe(2)
        sender, chan = send.open(), recv.open()
        sender.send(1)
        sender.send(2)
        with pytest.raises(TimeoutError):  # no room until a value is received
            sender.send(3, timeout=0)
        assert chan.recv(timeout=10.0) == 1
        sender.send(3, timeout=10.0)
        sender.close()
        assert list(chan) == [2, 3]

    def test_a_close_on_the_receiving_side_reaches_the_sender(self):
        """A send either finds room left from before the close, or the
        close: no ack comes back once the receiving side closed."""
        send, recv = pipe(2)
        sender, chan = send.open(), recv.open()
        chan.close()
        with pytest.raises(ChanClosedError):
            for _ in range(3):
                sender.send(0, timeout=10.0)

    def test_a_value_that_cannot_be_pickled_raises_in_the_send(self):
        send, recv = pipe(1)
        sender, chan = send.open(), recv.open()
        with pytest.raises(TypeError, match="pickle"):
            sender.send(threading.Lock())
        sender.send(1)
        assert chan.recv(timeout=10.0) == 1
        sender.close()

    def test_select_sends_and_receives_on_the_ends(self):
        send, recv = pipe(1)
        sender, chan = send.open(), recv.open()
        assert select(ChanSend(sender, 7), timeout=10.0) == (0, None)
        assert select(ChanRecv(chan), timeout=10.0) == (0, 7)
        sender.close()

    def test_an_end_is_opened_or_released_once(self):
        send, recv = pipe(1)
        send.release()
        with pytest.raises(RuntimeError, match="already"):
            send.open()
        recv.open().close()
        with pytest.raises(RuntimeError, match="already"):
            recv.release()

    @pytest.mark.asyncio
    async def test_asend_and_arecv_on_the_loop(self):
        send, recv = pipe(1)
        sender, chan = send.open(), recv.open()
        await sender.asend(5, timeout=10.0)
        assert await chan.arecv(timeout=10.0) == 5
        sender.close()
