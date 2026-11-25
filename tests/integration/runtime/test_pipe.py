# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""pipe(): a channel between processes, its ends in one process or two."""

import asyncio
import contextlib
import multiprocessing as mp
import threading
from unittest import mock

import pytest

from appinfra.runtime import Chan, ChanClosedError, ChanRecv, ChanSend, select
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

# Larger than any OS pipe buffer: the writer blocks until the reader reads
_BIG = b"x" * 1_000_000


class _UndecodableError(Exception):
    """Pickles, but cannot be unpickled: its args do not fit its __init__."""

    def __init__(self, a: int, b: int) -> None:
        super().__init__(f"{a} {b}")


@pytest.fixture
def reported(monkeypatch: pytest.MonkeyPatch) -> list[BaseException]:
    """Errors reported through threading.excepthook, kept instead of printed."""
    errors: list[BaseException] = []
    monkeypatch.setattr(threading, "excepthook", lambda a: errors.append(a.exc_value))
    return errors


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


def _run_child(method: str, count: int, after_exit: bool = False) -> list[int]:
    """What this process receives from a child sending *count* values, until
    the channel closes; with *after_exit*, starting once the child is gone."""
    send, recv = pipe(5)
    inherited = recv if method == "fork" else None
    child = mp.get_context(method).Process(
        target=_send, args=(send, inherited, count), daemon=True
    )
    child.start()
    try:
        send.release()
        if after_exit:
            child.join(10.0)
            assert child.exitcode == 0
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
    def test_values_sent_before_the_sender_exited_are_all_received(self, method: str):
        """Every ack finds the sending side gone, so each ack write fails; the
        values still on the pipe are received all the same, until EOF."""
        assert _run_child(method, 3, after_exit=True) == [0, 1, 2]

    @pytest.mark.parametrize("method", METHODS)
    def test_the_sending_process_exiting_closes_the_channel(self, method: str):
        """No close(): EOF, once the child is gone, ends the channel."""
        assert _run_child(method, 0) == []


class TestInOneProcess:
    """Both ends here: the relay is the same, without a second process."""

    def test_a_capacity_below_one_is_refused(self):
        with pytest.raises(ValueError, match="capacity"):
            pipe(0)

    def test_sends_wait_once_capacity_values_are_buffered_here(self):
        """With nobody receiving: capacity values on their way, one with the
        writer, capacity in the buffer; the next send finds no room."""
        send, recv = pipe(2)
        sender, chan = send.open(), recv.open()
        for i in range(5):
            sender.send(i, timeout=10.0)
        with pytest.raises(TimeoutError):
            sender.send(5, timeout=0)
        assert chan.recv(timeout=10.0) == 0
        sender.send(5, timeout=10.0)  # room again: one value was received
        assert [chan.recv(timeout=10.0) for _ in range(5)] == [1, 2, 3, 4, 5]
        sender.close()
        with pytest.raises(ChanClosedError):
            chan.recv(timeout=10.0)

    def test_sends_without_waiting_find_room_whatever_the_writer_does(self):
        """capacity sends in a row, the sending thread never yielding to the
        writer: each finds room in this process's buffer."""
        send, recv = pipe(3)
        sender, chan = send.open(), recv.open()
        for i in range(3):
            sender.send(i, timeout=0)
        assert [chan.recv(timeout=10.0) for _ in range(3)] == [0, 1, 2]
        sender.close()

    def test_a_close_on_the_receiving_side_reaches_the_sender(self):
        """A send either finds room left from before the close, or the
        close: no ack comes back once the receiving side closed. Room for
        at most 2 * capacity + 1 values: buffered, with the writer, on the pipe."""
        send, recv = pipe(2)
        sender, chan = send.open(), recv.open()
        chan.close()
        with pytest.raises(ChanClosedError):
            for _ in range(6):
                sender.send(0, timeout=10.0)

    def test_a_closed_receiver_holds_no_connection(self):
        """The reader closes the wake pipe's write end too as it ends. The
        sender sees the close once the reader closed its acks end, after
        the wake pipe."""
        send, recv = pipe(1)
        sender, chan = send.open(), recv.open()
        chan.close()
        with pytest.raises(ChanClosedError):
            for _ in range(4):  # room for at most 2 * capacity + 1 values
                sender.send(0, timeout=10.0)
        assert chan._wake is None  # Private: the wake pipe's write end

    def test_a_value_that_cannot_be_pickled_raises_in_the_send(self):
        send, recv = pipe(1)
        sender, chan = send.open(), recv.open()
        with pytest.raises(TypeError, match="pickle"):
            sender.send(threading.Lock())
        sender.send(1)
        assert chan.recv(timeout=10.0) == 1
        sender.close()

    def test_a_value_that_cannot_be_unpickled_is_reported_and_skipped(self, reported):
        """It fails in the reader, where no caller can catch it: reported
        through threading.excepthook. The channel goes on, and the value's
        room comes back: with capacity 1, nothing else would get through."""
        send, recv = pipe(1)
        sender, chan = send.open(), recv.open()
        sender.send(_UndecodableError(1, 2))
        for i in range(3):
            sender.send(i, timeout=10.0)
            assert chan.recv(timeout=10.0) == i
        assert len(reported) == 1
        assert isinstance(reported[0], TypeError)
        sender.close()

    def test_select_sends_and_receives_on_the_ends(self):
        send, recv = pipe(1)
        sender, chan = send.open(), recv.open()
        assert select(ChanSend(sender, 7), timeout=10.0) == (0, None)
        assert select(ChanRecv(chan), timeout=10.0) == (0, 7)
        sender.close()

    def test_the_receiving_end_only_receives(self):
        """Its channel is the pipe's: a value sent into it here would pass
        for one that came through the pipe."""
        send, recv = pipe(1)
        sender, chan = send.open(), recv.open()
        assert not isinstance(chan, Chan)
        assert not hasattr(chan, "send")
        assert not hasattr(chan, "asend")
        sender.close()

    def test_a_select_case_keeps_the_end_and_value_it_was_given(self):
        """The channels and pickled bytes underneath stay out of reach."""
        send, recv = pipe(1)
        sender, chan = send.open(), recv.open()
        case = ChanSend(sender, 7)
        assert (case.chan, case.value) == (sender, 7)
        assert ChanRecv(chan).chan is chan
        sender.close()

    def test_an_end_is_opened_or_released_once(self):
        send, recv = pipe(1)
        send.release()
        with pytest.raises(RuntimeError, match="already"):
            send.open()
        recv.open().close()
        with pytest.raises(RuntimeError, match="already"):
            recv.release()

    def test_a_sender_whose_second_thread_cannot_start_closes_the_channel(self):
        """open() raises, and the writer it started ends: the receiving side
        sees the close, not a writer nobody can reach holding the pipe open."""
        send, recv = pipe(1)
        start, started = threading.Thread.start, []

        def start_one(thread: threading.Thread) -> None:
            started.append(thread)
            if len(started) > 1:
                raise RuntimeError("can't start new thread")
            start(thread)

        with (
            mock.patch.object(threading.Thread, "start", start_one),
            pytest.raises(RuntimeError, match="start new thread"),
        ):
            send.open()
        with pytest.raises(ChanClosedError):
            recv.open().recv(timeout=10.0)  # the timeout is the failure path

    @pytest.mark.parametrize(
        ("end", "fails", "closed"),
        [
            ("send", 1, ("data", "acks")),
            ("send", 2, ("acks",)),  # data is the writer's, which ends and closes it
            ("recv", 1, ("data", "acks", "wake", "wake_w")),
        ],
        ids=["sender-writer", "sender-counter", "receiver-reader"],
    )
    def test_an_end_whose_thread_cannot_start_closes_its_connections(
        self, end: str, fails: int, closed: tuple[str, ...]
    ):
        """At once: not once the traceback holding them is dropped, which a
        logged error can put off for good."""
        ends = dict(zip(("send", "recv"), pipe(1)))
        data, acks = ends[end]._conns[0]  # Private: the end's connections
        conns = {"data": data, "acks": acks}
        start, started, real_pipe = threading.Thread.start, [], mp.Pipe

        def recording_pipe(duplex: bool) -> tuple:
            conns["wake"], conns["wake_w"] = real_pipe(duplex)
            return conns["wake"], conns["wake_w"]

        def start_until_nth(thread: threading.Thread) -> None:
            started.append(thread)
            if len(started) == fails:
                raise RuntimeError("can't start new thread")
            start(thread)

        with (
            mock.patch.object(threading.Thread, "start", start_until_nth),
            mock.patch.object(mp, "Pipe", recording_pipe),
            pytest.raises(RuntimeError, match="start new thread"),
        ):
            ends[end].open()
        assert [name for name in closed if not conns[name].closed] == []
        ends["recv" if end == "send" else "send"].release()

    def test_close_on_a_loop_does_not_wait_for_the_writer(self):
        """Nobody receives, so the writer is stuck on a full OS pipe with the
        second value; a close() waiting for it would block the loop for good."""
        send, recv = pipe(5)
        sender, chan = send.open(), recv.open()

        async def send_and_close() -> None:
            for _ in range(2):
                await sender.asend(_BIG, timeout=10.0)
            sender.close()

        runner = threading.Thread(target=asyncio.run, args=(send_and_close(),))
        runner.start()
        runner.join(10.0)  # the deadline is the failure path
        blocked = runner.is_alive()
        # Draining lets the writer finish, which also frees a blocked close()
        assert [len(chan.recv(timeout=10.0)) for _ in range(2)] == [len(_BIG)] * 2
        with pytest.raises(ChanClosedError):
            chan.recv(timeout=10.0)
        runner.join(10.0)
        assert not blocked

    def test_a_cancelled_aclose_leaves_no_wait_behind(self):
        """Nobody receives, so the writer waits for room for good. Cancelling
        aclose() must not leave a wait that asyncio.run() then joins."""
        send, recv = pipe(1)
        sender, chan = send.open(), recv.open()
        for i in range(3):  # on the pipe, with the writer, in the buffer
            sender.send(i, timeout=10.0)

        async def cancel_aclose() -> None:
            closing = asyncio.create_task(sender.aclose())
            for _ in range(3):
                await asyncio.sleep(0)  # aclose() is waiting by now
            closing.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await closing

        runner = threading.Thread(target=asyncio.run, args=(cancel_aclose(),))
        runner.start()
        runner.join(10.0)  # the deadline is the failure path
        blocked = runner.is_alive()
        # Draining lets the writer end, which also frees a blocked asyncio.run()
        assert [chan.recv(timeout=10.0) for _ in range(3)] == [0, 1, 2]
        with pytest.raises(ChanClosedError):
            chan.recv(timeout=10.0)
        runner.join(10.0)
        assert not blocked

    @pytest.mark.asyncio
    async def test_aclose_waits_while_the_loop_receives(self):
        """Both ends on one loop: aclose() waits for the writer off the loop,
        so the receiving task drains the pipe meanwhile."""
        send, recv = pipe(5)
        sender, chan = send.open(), recv.open()

        async def receive() -> list[bytes]:
            return [value async for value in chan]

        receiving = asyncio.create_task(receive())
        for _ in range(3):
            await sender.asend(_BIG, timeout=10.0)
        await asyncio.wait_for(sender.aclose(), 10.0)
        assert len(await asyncio.wait_for(receiving, 10.0)) == 3

    @pytest.mark.asyncio
    async def test_asend_and_arecv_on_the_loop(self):
        send, recv = pipe(1)
        sender, chan = send.open(), recv.open()
        await sender.asend(5, timeout=10.0)
        assert await chan.arecv(timeout=10.0) == 5
        sender.close()
