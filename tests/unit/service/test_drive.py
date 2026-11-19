# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for how runners drive each service form, and which forms they accept."""

import threading
from collections import deque
from collections.abc import Callable, Sequence
from typing import Any
from unittest.mock import MagicMock

import pytest

from appinfra.service import (
    ChannelClosedError,
    ChannelFullError,
    ChannelTimeoutError,
    Message,
    RunnerFactory,
    ScheduledService,
    Service,
    StepService,
    ThreadRunner,
)
from appinfra.service.runner.drive import WAIT_SLICE, drive

_TIMEOUT = object()
"""In a FakeInbox's messages: recv() times out once here."""


class FakeInbox:
    """Hands out its messages, then reports itself closed; records what is sent.

    send() raises each of *send_errors* in turn, calling *on_send_error* first,
    before it accepts a message.
    """

    def __init__(
        self,
        *messages: Any,
        send_errors: Sequence[Exception] | None = None,
        on_send_error: Callable[[], None] | None = None,
    ) -> None:
        self._messages = deque(messages)
        self._send_errors = deque(send_errors or [])
        self._on_send_error = on_send_error
        self.sent: list[tuple[Any, float | None]] = []
        self.send_timeouts: list[float | None] = []
        self.recvs = 0

    def recv(self, timeout: float | None = None) -> Any:
        self.recvs += 1
        if not self._messages:
            raise ChannelClosedError("Channel is closed")
        msg = self._messages.popleft()
        if msg is _TIMEOUT:
            raise ChannelTimeoutError("timeout")
        return msg

    def send(self, message: Any, timeout: float | None = None) -> None:
        self.send_timeouts.append(timeout)
        if self._send_errors:
            if self._on_send_error is not None:
                self._on_send_error()
            raise self._send_errors.popleft()
        self.sent.append((message, timeout))

    def submit(self, request: Any, timeout: float | None = None) -> Any:
        raise AssertionError("drive() never submits")

    def close(self) -> None:
        pass

    @property
    def is_closed(self) -> bool:
        return not self._messages


class FakeStop:
    """A stop signal that is set after *waits* calls to wait(); never, if None."""

    def __init__(self, waits: int | None = None) -> None:
        self._waits_left = waits
        self.timeouts: list[float | None] = []

    def is_set(self) -> bool:
        return self._waits_left is not None and self._waits_left <= 0

    def wait(self, timeout: float | None = None) -> bool:
        self.timeouts.append(timeout)
        if self._waits_left is not None:
            self._waits_left -= 1
        return self.is_set()


class Doubler(StepService):
    """Replies with the payload doubled; no reply for a None payload."""

    def __init__(self) -> None:
        self._lg = MagicMock()
        self.seen: list[Any] = []

    @property
    def name(self) -> str:
        return "doubler"

    def step(self, msg: Message) -> Message | None:
        self.seen.append(msg.payload)
        if msg.payload is None:
            return None
        return Message(id=msg.id, payload=msg.payload * 2)


class Ticker(ScheduledService):
    interval = 5.0

    def __init__(self) -> None:
        self._lg = MagicMock()
        self.ticks = 0

    @property
    def name(self) -> str:
        return "ticker"

    def tick(self) -> None:
        self.ticks += 1


class Once(Service):
    def __init__(self) -> None:
        self._lg = MagicMock()
        self.runs = 0

    @property
    def name(self) -> str:
        return "once"

    def run(self) -> None:
        self.runs += 1


class StepAndTick(StepService, ScheduledService):
    """A step service that is also a scheduled one."""

    def __init__(self) -> None:
        self._lg = MagicMock()

    @property
    def name(self) -> str:
        return "both"

    def step(self, msg: Message) -> None:
        raise AssertionError("a service of two kinds is never driven")

    def tick(self) -> None:
        raise AssertionError("a service of two kinds is never driven")


class TestDriveStep:
    """drive() with a StepService."""

    def test_reply_goes_back_on_the_inbox(self):
        """A reply step() returns is sent on the inbox; None sends nothing."""
        request = Message(payload=21)
        inbox = FakeInbox(request, Message(payload=None))
        svc = Doubler()

        drive(svc, FakeStop(), inbox)

        assert svc.seen == [21, None]
        [(reply, timeout)] = inbox.sent
        assert (reply.id, reply.payload, timeout) == (request.id, 42, WAIT_SLICE)

    def test_full_inbox_holds_the_reply_until_there_is_room(self):
        """While the inbox is full, the reply is retried in slices, not failed."""
        full = [ChannelFullError("full"), ChannelFullError("full")]
        inbox = FakeInbox(Message(payload=21), send_errors=full)

        drive(Doubler(), FakeStop(), inbox)

        [(reply, _)] = inbox.sent
        assert reply.payload == 42
        assert inbox.send_timeouts == [WAIT_SLICE] * 3

    def test_reply_still_unsent_at_stop_is_dropped(self):
        """A stop while the inbox is full ends the loop without the reply."""
        stop = threading.Event()
        inbox = FakeInbox(
            Message(payload=1),
            Message(payload=2),
            send_errors=[ChannelFullError("full")],
            on_send_error=stop.set,
        )
        svc = Doubler()

        drive(svc, stop, inbox)

        assert svc.seen == [1]
        assert inbox.sent == []

    def test_inbox_closed_while_replying_ends_the_loop(self):
        """An inbox that closes while a reply waits for room ends the loop."""
        inbox = FakeInbox(
            Message(payload=1),
            Message(payload=2),
            send_errors=[ChannelClosedError("Channel is closed")],
        )
        svc = Doubler()

        drive(svc, FakeStop(), inbox)

        assert svc.seen == [1]
        assert inbox.sent == []

    def test_recv_timeout_keeps_the_loop_going(self):
        """A recv() that times out is retried; the next message still reaches step()."""
        inbox = FakeInbox(_TIMEOUT, Message(payload=1))
        svc = Doubler()

        drive(svc, FakeStop(), inbox)

        assert svc.seen == [1]

    def test_closed_inbox_ends_the_loop(self):
        """drive() returns once the inbox is closed."""
        inbox = FakeInbox()

        drive(Doubler(), FakeStop(), inbox)

        assert inbox.recvs == 1

    def test_stop_set_ends_the_loop_before_recv(self):
        """With stop already set, drive() returns without receiving."""
        stop = FakeStop(waits=0)
        inbox = FakeInbox(Message(payload=1))

        drive(Doubler(), stop, inbox)

        assert inbox.recvs == 0

    def test_step_exception_propagates(self):
        """An exception from step() reaches the runner."""

        class Boom(Doubler):
            def step(self, msg: Message) -> None:
                raise RuntimeError("step failed")

        with pytest.raises(RuntimeError, match="step failed"):
            drive(Boom(), FakeStop(), FakeInbox(Message(payload=1)))


class TestDriveScheduledAndRun:
    """drive() with a ScheduledService and a service with its own run()."""

    def test_ticks_then_waits_interval_until_stopped(self):
        """tick() runs, then the loop waits interval seconds, until stop is set."""
        svc = Ticker()
        stop = FakeStop(waits=3)

        drive(svc, stop, None)

        assert svc.ticks == 3
        assert stop.timeouts == [5.0, 5.0, 5.0]

    def test_run_is_called_once(self):
        """run() is called once; drive() returns when it does."""
        svc = Once()

        drive(svc, FakeStop(waits=1), None)

        assert svc.runs == 1

    @pytest.mark.parametrize(
        ("svc", "method"),
        [(Doubler(), "step"), (Ticker(), "tick")],
        ids=["step", "scheduled"],
    )
    def test_run_refuses_a_service_the_runner_loops(self, svc: Service, method: str):
        with pytest.raises(TypeError, match=f"driven through {method}"):
            svc.run()


class TestRunnerForms:
    """Which services, and inboxes, a runner accepts."""

    def test_non_service_is_refused(self):
        with pytest.raises(TypeError, match="must be a Service"):
            ThreadRunner(object())  # type: ignore[arg-type]  # the runtime check under test

    def test_step_and_scheduled_at_once_is_refused(self):
        with pytest.raises(
            TypeError, match="more than one of StepService, ScheduledService"
        ):
            ThreadRunner(StepAndTick(), inbox=FakeInbox())

    def test_drive_refuses_step_and_scheduled_at_once(self):
        """drive() checks too: a subprocess runs it without a runner's check."""
        with pytest.raises(
            TypeError, match="more than one of StepService, ScheduledService"
        ):
            drive(StepAndTick(), FakeStop(), FakeInbox())

    def test_step_service_needs_an_inbox(self):
        with pytest.raises(ValueError, match="needs an inbox channel"):
            ThreadRunner(Doubler())

    @pytest.mark.parametrize("svc", [Ticker(), Once()], ids=["scheduled", "run"])
    def test_other_services_take_no_inbox(self, svc: Service):
        with pytest.raises(ValueError, match="takes no inbox channel"):
            ThreadRunner(svc, inbox=MagicMock())

    def test_factory_gives_a_step_service_the_service_side_as_inbox(self):
        result = RunnerFactory(MagicMock()).create_thread_runner_with_channel(Doubler())

        assert result.runner.inbox is result.service_channel

    def test_factory_gives_other_services_no_inbox(self):
        result = RunnerFactory(MagicMock()).create_thread_runner_with_channel(Once())

        assert result.runner.inbox is None
