# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for async services run as tasks on a LoopHost's event loop."""

import asyncio
import threading
import time
from collections.abc import Callable, Iterator
from unittest.mock import MagicMock

import pytest

from appinfra.service import (
    AsyncChannel,
    AsyncQueueChannelFactory,
    AsyncService,
    LoopHost,
    Message,
    RestartPolicy,
    Runner,
    State,
)

LOOP_THREAD = "test-loop"


class Parked(AsyncService):
    """Waits on an event nothing sets; notes how run() ends and where teardown runs."""

    def __init__(self, name: str = "parked") -> None:
        self._lg = MagicMock()
        self._name = name
        self.entered = threading.Event()
        self.cancelled = False
        self.torn_down = threading.Event()
        self.teardown_thread: str | None = None

    @property
    def name(self) -> str:
        return self._name

    async def run(self) -> None:
        self.entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise

    def teardown(self) -> None:
        self.teardown_thread = threading.current_thread().name
        self.torn_down.set()


class Returns(Parked):
    async def run(self) -> None:
        self.entered.set()


class Boom(Parked):
    async def run(self) -> None:
        self.entered.set()
        raise RuntimeError("run failed")


class FailsOnce(Parked):
    """Fails its first run(); parks in the second."""

    def __init__(self) -> None:
        super().__init__("fails-once")
        self.runs = 0
        self.second_run = threading.Event()

    async def run(self) -> None:
        self.runs += 1
        if self.runs == 1:
            raise RuntimeError("first run failed")
        self.second_run.set()
        await asyncio.Event().wait()


class Doubler(AsyncService):
    """Replies on its channel with the payload doubled."""

    def __init__(self, inbox: AsyncChannel) -> None:
        self._lg = MagicMock()
        self._inbox = inbox

    @property
    def name(self) -> str:
        return "doubler"

    async def run(self) -> None:
        while True:
            msg = await self._inbox.recv()
            await self._inbox.send(Message(id=msg.id, payload=msg.payload * 2))


@pytest.fixture
def host() -> Iterator[LoopHost]:
    host = LoopHost(name=LOOP_THREAD)
    host.start()
    yield host
    host.stop()


def _on_state(runner: Runner, state: State) -> threading.Event:
    """An event set when the runner enters *state*."""
    reached = threading.Event()
    runner.on_state_change(
        lambda _name, _old, new: reached.set() if new == state else None
    )
    return reached


def _wait_until(condition: Callable[[], bool], timeout: float = 5.0) -> bool:
    """Poll *condition* until it holds; False once *timeout* passes. For states
    that no event signals."""
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.01)
    return True


class TestTaskRunner:
    """An AsyncService under a TaskRunner on a LoopHost."""

    def test_many_services_share_the_loop_thread(self, host):
        threads_before = threading.active_count()
        services = [Parked(name=f"parked-{i}") for i in range(50)]
        runners = [host.runner(svc) for svc in services]
        for runner in runners:
            runner.start()

        assert all(svc.entered.wait(timeout=5.0) for svc in services)
        assert threading.active_count() == threads_before
        for runner in runners:
            runner.stop()
        assert {svc.teardown_thread for svc in services} == {LOOP_THREAD}

    def test_submit_gets_the_reply_of_an_async_service(self, host):
        pair = AsyncQueueChannelFactory().create_pair()
        runner = host.runner(Doubler(pair.child))
        runner.start()
        runner.wait_healthy(timeout=5.0)

        reply = asyncio.run_coroutine_threadsafe(
            pair.parent.submit(Message(payload=21), timeout=5.0), host.loop
        ).result(timeout=5.0)
        runner.stop()

        assert reply.payload == 42
        assert runner.state == State.STOPPED

    def test_stop_cancels_run_then_tears_down_on_the_loop(self, host):
        svc = Parked()
        runner = host.runner(svc)
        runner.start()
        runner.wait_healthy(timeout=5.0)
        assert svc.entered.wait(timeout=5.0)

        runner.stop()

        assert svc.cancelled
        assert svc.torn_down.is_set()
        assert svc.teardown_thread == LOOP_THREAD
        assert runner.state == State.STOPPED

    def test_run_returning_ends_the_service(self, host):
        svc = Returns()
        runner = host.runner(svc)
        done = _on_state(runner, State.DONE)
        runner.start()
        runner.wait_healthy(timeout=5.0)

        assert done.wait(timeout=5.0)
        assert svc.torn_down.is_set()

    def test_run_failing_fails_that_service_only(self, host):
        boom, other = Boom(name="boom"), Parked(name="other")
        boom_runner, other_runner = host.runner(boom), host.runner(other)
        failed = _on_state(boom_runner, State.FAILED)
        other_runner.start()
        assert other.entered.wait(timeout=5.0)

        boom_runner.start()

        assert failed.wait(timeout=5.0)
        assert "run failed" in str(boom_runner.exception)
        assert boom.torn_down.wait(timeout=5.0)
        assert other_runner.is_alive()
        other_runner.stop()

    def test_stop_that_lands_while_starting_skips_run(self, host):
        """A stop() between the STARTING transition and the task's start is
        not lost: the task tears the service down without running it."""
        svc = Parked()
        runner = host.runner(svc)
        # Hooks run synchronously in start(), so stop() lands inside the window
        runner.on_state_change(
            lambda _name, _old, new: runner.stop() if new == State.STARTING else None
        )

        runner.start()

        assert svc.torn_down.wait(timeout=5.0)
        assert not svc.entered.is_set()

    def test_check_restarts_a_failed_service(self, host):
        svc = FailsOnce()
        runner = host.runner(svc, RestartPolicy(max_retries=1, backoff=0.0))
        failed = _on_state(runner, State.FAILED)
        runner.start()
        assert failed.wait(timeout=5.0)
        assert _wait_until(lambda: not runner.is_alive())

        assert runner.check() is True

        assert svc.second_run.wait(timeout=5.0)
        assert runner.state == State.RUNNING
        runner.stop()

    def test_start_needs_a_running_host(self):
        runner = LoopHost().runner(Parked())

        with pytest.raises(RuntimeError, match="is not running"):
            runner.start()
        assert runner.state == State.CREATED


class TestLoopHostStop:
    def test_stop_ends_the_services_still_running(self):
        host = LoopHost(name=LOOP_THREAD)
        host.start()
        svc = Parked()
        runner = host.runner(svc)
        runner.start()
        runner.wait_healthy(timeout=5.0)
        assert svc.entered.wait(timeout=5.0)

        host.stop()

        assert svc.cancelled
        assert svc.torn_down.is_set()
        assert runner.state == State.DONE
