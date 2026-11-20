# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for a step service run on a thread, over the channel its runner owns."""

import threading
from typing import Any
from unittest.mock import MagicMock

import pytest

from appinfra.service import (
    ChannelTimeoutError,
    Message,
    RunnerFactory,
    RunnerWithChannel,
    State,
    StepService,
)


class Doubler(StepService):
    """Replies with the payload doubled."""

    def __init__(self) -> None:
        self._lg = MagicMock()

    @property
    def name(self) -> str:
        return "doubler"

    def step(self, msg: Message) -> Message:
        return Message(id=msg.id, payload=msg.payload * 2)


class Recorder(StepService):
    """Records each payload and replies with nothing."""

    def __init__(self) -> None:
        self._lg = MagicMock()
        self.payloads: list[Any] = []
        self.received = threading.Event()

    @property
    def name(self) -> str:
        return "recorder"

    def step(self, msg: Message) -> None:
        self.payloads.append(msg.payload)
        self.received.set()


class Boom(StepService):
    def __init__(self) -> None:
        self._lg = MagicMock()

    @property
    def name(self) -> str:
        return "boom"

    def step(self, msg: Message) -> None:
        raise RuntimeError("step failed")


class TornDown(Recorder):
    """A Recorder that notes the thread its teardown() runs on."""

    def __init__(self) -> None:
        super().__init__()
        self.teardown_thread: str | None = None
        self.torn_down = threading.Event()

    def teardown(self) -> None:
        self.teardown_thread = threading.current_thread().name
        self.torn_down.set()


class BoomTornDown(TornDown):
    def step(self, msg: Message) -> None:
        raise RuntimeError("step failed")


def _started(svc: StepService) -> RunnerWithChannel:
    result = RunnerFactory(MagicMock()).create_thread_runner_with_channel(svc)
    result.runner.start()
    result.runner.wait_healthy(timeout=5.0)
    return result


def _on_state(result: RunnerWithChannel, state: State) -> threading.Event:
    """An event set when the runner enters *state*."""
    reached = threading.Event()
    result.runner.on_state_change(
        lambda _name, _old, new: reached.set() if new == state else None
    )
    return reached


class TestStepServiceOnThread:
    """StepService under ThreadRunner."""

    def test_submit_gets_the_reply_step_returns(self):
        result = _started(Doubler())
        try:
            reply = result.channel.submit(Message(payload=21), timeout=5.0)
        finally:
            result.runner.stop()

        assert reply.payload == 42
        assert result.runner.state == State.STOPPED

    def test_no_reply_when_step_returns_none(self):
        svc = Recorder()
        result = _started(svc)
        result.channel.send(Message(payload="a"))
        assert svc.received.wait(timeout=5.0)
        result.runner.stop()

        assert svc.payloads == ["a"]
        with pytest.raises(ChannelTimeoutError):
            result.channel.recv(timeout=0)

    def test_step_exception_fails_the_runner(self):
        result = _started(Boom())
        failed = _on_state(result, State.FAILED)

        result.channel.send(Message(payload=1))

        assert failed.wait(timeout=5.0)
        assert "step failed" in str(result.runner.exception)

    def test_closed_inbox_ends_the_service(self):
        result = _started(Recorder())
        done = _on_state(result, State.DONE)

        result.service_channel.close()

        assert done.wait(timeout=5.0)
        assert result.runner.exception is None


class TestStepServiceTeardown:
    """teardown() runs on the service thread once the loop has ended, however it ends."""

    def test_after_stop(self):
        svc = TornDown()
        result = _started(svc)

        result.runner.stop()

        assert svc.torn_down.is_set()
        assert svc.teardown_thread == "svc-recorder"

    def test_after_the_inbox_closes(self):
        svc = TornDown()
        result = _started(svc)

        result.service_channel.close()

        assert svc.torn_down.wait(timeout=5.0)
        assert svc.teardown_thread == "svc-recorder"

    def test_after_step_fails(self):
        svc = BoomTornDown()
        result = _started(svc)

        result.channel.send(Message(payload=1))

        assert svc.torn_down.wait(timeout=5.0)
        assert svc.teardown_thread == "svc-recorder"

    def test_after_a_stop_that_lands_while_starting(self):
        """A stop() between the STARTING transition and the thread's start ends
        the loop as soon as it runs; start() must not discard it."""
        svc = TornDown()
        result = RunnerFactory(MagicMock()).create_thread_runner_with_channel(svc)
        runner = result.runner
        # Hooks run synchronously in start(), so stop() lands inside the window
        runner.on_state_change(
            lambda _name, _old, new: runner.stop() if new == State.STARTING else None
        )
        try:
            runner.start()

            assert svc.torn_down.wait(timeout=5.0)
        finally:
            result.service_channel.close()  # ends a loop the stop() failed to end
