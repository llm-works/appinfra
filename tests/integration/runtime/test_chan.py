# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Chan between threads, coroutines and tasks: waiting, close, timeouts, stops."""

import asyncio
import threading
import time
from collections.abc import Callable, Iterator
from typing import Any
from unittest.mock import MagicMock

import pytest

from appinfra.runtime import Chan, ChanClosedError, Runtime, StoppedError, stopping


@pytest.fixture
def rt() -> Iterator[Runtime]:
    runtime = Runtime(MagicMock())
    runtime.start()
    yield runtime
    runtime.stop()


def _wait_until(condition: Callable[[], bool], timeout: float = 5.0) -> bool:
    """Poll *condition* until it holds; False once *timeout* passes. For changes
    that no event signals."""
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.01)
    return True


def _waiting(ch: Chan[Any], senders: int = 0, receivers: int = 0) -> bool:
    """True once *senders* sends and *receivers* receives wait on *ch*."""
    return len(ch._senders) == senders and len(ch._receivers) == receivers  # Private


class Call:
    """Runs a channel call on a thread of its own, keeping its outcome."""

    def __init__(self, fn: Callable[[], Any]) -> None:
        self.result: Any = None
        self.error: BaseException | None = None
        self._fn = fn
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            self.result = self._fn()
        except BaseException as e:
            self.error = e

    def join(self) -> None:
        self._thread.join(5.0)
        assert not self._thread.is_alive()

    @property
    def done(self) -> bool:
        return not self._thread.is_alive()


async def _parked(task: asyncio.Task[Any]) -> None:
    """Let *task* run until it waits on something."""
    for _ in range(3):
        await asyncio.sleep(0)
    assert not task.done()


class TestThreads:
    def test_without_a_buffer_a_send_waits_for_the_receiver(self):
        ch = Chan[int](0)
        send = Call(lambda: ch.send(1))
        assert _wait_until(lambda: _waiting(ch, senders=1))
        assert not send.done
        assert ch.recv() == 1
        send.join()
        assert send.error is None

    def test_a_send_on_a_full_buffer_completes_when_room_frees(self):
        ch = Chan[int](1)
        ch.send(1)
        send = Call(lambda: ch.send(2))
        assert _wait_until(lambda: _waiting(ch, senders=1))
        assert ch.recv() == 1
        send.join()
        assert ch.recv(timeout=0) == 2

    def test_waiting_receivers_are_served_in_the_order_they_came(self):
        ch = Chan[int](0)
        first = Call(ch.recv)
        assert _wait_until(lambda: _waiting(ch, receivers=1))
        second = Call(ch.recv)
        assert _wait_until(lambda: _waiting(ch, receivers=2))
        ch.send(1)
        ch.send(2)
        first.join()
        second.join()
        assert (first.result, second.result) == (1, 2)

    def test_close_wakes_every_waiting_receive(self):
        ch = Chan[int](1)
        calls = [Call(ch.recv) for _ in range(2)]
        assert _wait_until(lambda: _waiting(ch, receivers=2))
        ch.close()
        for call in calls:
            call.join()
            assert isinstance(call.error, ChanClosedError)

    def test_close_ends_a_waiting_send_without_delivering_it(self):
        ch = Chan[int](1)
        ch.send(1)
        send = Call(lambda: ch.send(2))
        assert _wait_until(lambda: _waiting(ch, senders=1))
        ch.close()
        send.join()
        assert isinstance(send.error, ChanClosedError)
        assert list(ch) == [1]

    def test_a_receive_that_times_out_leaves_no_waiter(self):
        """A later send must not hand its value to a receiver that left."""
        ch = Chan[int](0)
        with pytest.raises(TimeoutError):
            ch.recv(timeout=0.001)
        assert _waiting(ch)
        with pytest.raises(TimeoutError):
            ch.send(1, timeout=0)


class TestLoop:
    @pytest.mark.asyncio
    async def test_iteration_receives_until_the_close(self):
        ch = Chan[int](0)

        async def produce() -> None:
            for i in range(3):
                await ch.asend(i)
            ch.close()

        producer = asyncio.create_task(produce())
        assert [i async for i in ch] == [0, 1, 2]
        await producer

    @pytest.mark.asyncio
    async def test_close_wakes_every_waiting_receive(self):
        ch = Chan[int](1)
        tasks = [asyncio.create_task(ch.arecv()) for _ in range(2)]
        for task in tasks:
            await _parked(task)
        ch.close()
        for task in tasks:
            with pytest.raises(ChanClosedError):
                await asyncio.wait_for(task, timeout=5.0)

    @pytest.mark.asyncio
    async def test_close_ends_a_waiting_send(self):
        ch = Chan[int](1)
        await ch.asend(1)
        send = asyncio.create_task(ch.asend(2))
        await _parked(send)
        ch.close()
        with pytest.raises(ChanClosedError):
            await asyncio.wait_for(send, timeout=5.0)

    @pytest.mark.asyncio
    async def test_a_send_on_a_full_buffer_completes_when_room_frees(self):
        ch = Chan[int](1)
        await ch.asend(1)
        send = asyncio.create_task(ch.asend(2))
        await _parked(send)
        assert await ch.arecv() == 1
        await asyncio.wait_for(send, timeout=5.0)
        assert await ch.arecv(timeout=0) == 2

    @pytest.mark.asyncio
    async def test_a_receive_that_times_out_leaves_no_waiter(self):
        ch = Chan[int](0)
        with pytest.raises(TimeoutError):
            await ch.arecv(timeout=0.001)
        assert _waiting(ch)

    @pytest.mark.asyncio
    async def test_a_cancelled_receive_leaves_no_waiter(self):
        ch = Chan[int](0)
        recv = asyncio.create_task(ch.arecv())
        await _parked(recv)
        recv.cancel()
        with pytest.raises(asyncio.CancelledError):
            await recv
        assert _waiting(ch)

    @pytest.mark.asyncio
    async def test_a_value_handed_to_a_cancelled_receive_is_not_lost(self):
        """The receive is cancelled after the value was handed to it, before it
        resumed: the value goes back to the front of the channel."""
        ch = Chan[int](0)
        recv = asyncio.create_task(ch.arecv())
        await _parked(recv)
        await ch.asend(1)  # handed over at once: the receive is waiting
        recv.cancel()
        with pytest.raises(asyncio.CancelledError):
            await recv
        assert await ch.arecv(timeout=0) == 1

    @pytest.mark.asyncio
    async def test_a_blocking_call_on_the_loop_is_refused(self):
        """It would block the loop, and with it whatever would end the wait."""
        ch = Chan[int](0)
        with pytest.raises(RuntimeError, match="await arecv"):
            ch.recv()
        assert _waiting(ch)

    @pytest.mark.asyncio
    async def test_values_given_back_keep_their_send_order(self):
        """Two receives handed 1 and 2 are cancelled before they resume; their
        cleanups run in the order they resume, first 1's, then 2's. The values
        still come back out as sent."""
        ch = Chan[int](0)
        first = asyncio.create_task(ch.arecv())
        await _parked(first)
        second = asyncio.create_task(ch.arecv())
        await _parked(second)
        await ch.asend(1)  # handed to the first receive
        await ch.asend(2)  # handed to the second
        first.cancel()
        second.cancel()
        for task in (first, second):
            with pytest.raises(asyncio.CancelledError):
                await task
        assert [await ch.arecv(timeout=0), await ch.arecv(timeout=0)] == [1, 2]

    @pytest.mark.asyncio
    async def test_a_value_given_back_keeps_a_waiting_sender_waiting(self):
        """A given-back value overfills the buffer. Taking it frees no slot:
        a sender waiting on a channel without a buffer still waits for a
        receiver to take its own value."""
        ch = Chan[int](0)
        recv = asyncio.create_task(ch.arecv())
        await _parked(recv)
        await ch.asend(1)  # handed over at once: the receive is waiting
        recv.cancel()
        with pytest.raises(asyncio.CancelledError):
            await recv  # 1 goes back to the buffer
        send = asyncio.create_task(ch.asend(2))
        await _parked(send)

        assert await ch.arecv(timeout=0) == 1
        await _parked(send)  # nobody has received 2 yet
        assert await ch.arecv(timeout=0) == 2
        await asyncio.wait_for(send, timeout=5.0)

    @pytest.mark.asyncio
    async def test_a_blocking_call_is_refused_on_the_loop_even_when_ready(self):
        """Refusing only the calls that happen to wait would make the error
        depend on timing: code that passes at low load would fail under load."""
        ch = Chan[int](1)
        with pytest.raises(RuntimeError, match="await asend"):
            ch.send(1)
        await ch.asend(1)
        with pytest.raises(RuntimeError, match="await arecv"):
            ch.recv()
        with pytest.raises(RuntimeError, match="await arecv"):
            list(ch)
        assert await ch.arecv(timeout=0) == 1  # the value is still there

    @pytest.mark.asyncio
    async def test_a_negative_timeout_is_refused_on_the_loop(self):
        """Blocking or async, ready or not: only 0 means do not wait."""
        ch = Chan[int](1)
        for call in (lambda: ch.send(1, timeout=-1), lambda: ch.recv(timeout=-1)):
            with pytest.raises(ValueError, match="timeout"):
                call()
        with pytest.raises(ValueError, match="timeout"):
            await ch.asend(1, timeout=-1)
        await ch.asend(1)
        with pytest.raises(ValueError, match="timeout"):
            await ch.arecv(timeout=-1)
        assert await ch.arecv(timeout=0) == 1

    @pytest.mark.asyncio
    async def test_a_call_without_waiting_is_allowed_on_the_loop(self):
        """Sync code the loop runs, which cannot await, uses timeout=0."""
        ch = Chan[int](1)
        ch.send(1, timeout=0)
        with pytest.raises(TimeoutError):
            ch.send(2, timeout=0)
        assert ch.recv(timeout=0) == 1
        with pytest.raises(TimeoutError):
            ch.recv(timeout=0)


class TestAcrossTaskKinds:
    def test_a_thread_task_sends_to_a_loop_task(self, rt: Runtime):
        ch = Chan[int](0)

        def produce() -> None:
            for i in range(3):
                ch.send(i)
            ch.close()

        async def consume() -> list[int]:
            return [i async for i in ch]

        consumer = rt.spawn(consume)
        rt.detach(rt.spawn(produce))
        assert rt.wait(consumer, timeout=5.0) == [0, 1, 2]

    def test_a_loop_task_sends_to_a_thread_task(self, rt: Runtime):
        ch = Chan[int](1)

        async def produce() -> None:
            for i in range(3):
                await ch.asend(i)
            ch.close()

        consumer = rt.spawn(lambda: list(ch))
        rt.detach(rt.spawn(produce))
        assert rt.wait(consumer, timeout=5.0) == [0, 1, 2]


class TestStop:
    def test_a_waiting_thread_task_ends_cleanly_on_a_cancel(self, rt: Runtime):
        ch = Chan[int](0)
        stopped = threading.Event()

        def consume() -> None:
            try:
                ch.recv()
            except StoppedError:
                stopped.set()
                raise

        t = rt.spawn(consume)
        assert _wait_until(lambda: _waiting(ch, receivers=1))
        rt.cancel(t)
        with pytest.raises(StoppedError):  # it produced no result
            rt.wait(t, timeout=5.0)
        assert stopped.is_set()
        assert _waiting(ch)

    def test_a_waiting_loop_task_ends_cleanly_when_its_token_stops(self, rt: Runtime):
        """Its parent ends, which stops its token without cancelling it."""
        ch = Chan[int](0)
        stopped = threading.Event()

        async def consume() -> None:
            try:
                await ch.arecv()
            except StoppedError:
                stopped.set()
                raise

        async def parent() -> int:
            child = rt.spawn(consume)
            while not _waiting(ch, receivers=1):  # until the child waits
                await asyncio.sleep(0)
            return child

        child = rt.wait(rt.spawn(parent), timeout=5.0)
        with pytest.raises(StoppedError):
            rt.wait(child, timeout=5.0)
        assert stopped.is_set()

    def test_a_detached_task_ended_by_a_stop_is_not_logged_as_failed(self):
        lg = MagicMock()
        rt = Runtime(lg)
        rt.start()
        ch = Chan[int](0)
        t = rt.spawn(ch.recv)
        assert _wait_until(lambda: _waiting(ch, receivers=1))
        rt.detach(t)
        rt.stop()
        assert _waiting(ch)
        lg.warning.assert_not_called()

    def test_a_stopped_task_still_drains_what_needs_no_wait(self, rt: Runtime):
        ch = Chan[str](1)
        ch.send("a")

        def drain() -> list[str]:
            stopping().stop()
            got = [ch.recv()]
            try:
                ch.recv()
            except StoppedError:
                got.append("stopped")
            return got

        assert rt.wait(rt.spawn(drain), timeout=5.0) == ["a", "stopped"]
