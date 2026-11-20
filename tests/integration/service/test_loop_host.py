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
    """Returns from run() once release() is called, so a test can see it
    RUNNING first: a run() that ends before wait_healthy() looks counts as
    exiting during startup."""

    def __init__(self) -> None:
        super().__init__("returns")
        self._release: asyncio.Event | None = None

    async def run(self) -> None:
        self._release = asyncio.Event()
        self.entered.set()
        await self._release.wait()

    def release(self, host: LoopHost) -> None:
        """Let run() return; call once entered is set."""
        assert self._release is not None
        host.loop.call_soon_threadsafe(self._release.set)


class Boom(Parked):
    async def run(self) -> None:
        self.entered.set()
        raise RuntimeError("run failed")


class HoldsCancel(Parked):
    """When cancelled, run() returns only once release() is called."""

    def __init__(self) -> None:
        super().__init__("holds-cancel")
        self._hold = asyncio.Event()

    async def run(self) -> None:
        self.entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await self._hold.wait()

    def release(self, host: LoopHost) -> None:
        host.loop.call_soon_threadsafe(self._hold.set)


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


def _hold_loop(host: LoopHost) -> threading.Event:
    """Block the host's loop inside a callback until the returned event is set.
    Returns once the loop is blocked, so what is scheduled next runs in a later
    iteration, in the order scheduled."""
    held, release = threading.Event(), threading.Event()

    def hold() -> None:
        held.set()
        release.wait(5.0)

    host.loop.call_soon_threadsafe(hold)
    assert held.wait(5.0)
    return release


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
        assert svc.entered.wait(timeout=5.0)

        svc.release(host)

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

    def test_stop_right_after_start_tears_down(self, host):
        """Whether or not the task has begun when stop() lands, the service is
        torn down and the runner ends STOPPED."""
        for i in range(20):
            svc = Parked(name=f"quick-{i}")
            runner = host.runner(svc)
            runner.start()

            runner.stop()

            assert svc.torn_down.is_set()
            assert runner.state == State.STOPPED
            assert not runner.is_alive()

    def test_stop_from_another_thread_during_start_leaves_the_start_alone(self, host):
        """A stop() from another thread that lands while start() is between
        STARTING and scheduling the task does not report STOPPED before
        teardown; with no time to wait it returns, and the start completes."""
        svc = Parked()
        runner = host.runner(svc)
        starting, release = threading.Event(), threading.Event()

        def hold(_name: str, _old: State, new: State) -> None:
            if new == State.STARTING and not starting.is_set():
                starting.set()
                release.wait(5.0)  # holds start() before its task is scheduled

        runner.on_state_change(hold)
        first = threading.Thread(target=runner.start)
        first.start()
        try:
            assert starting.wait(5.0)
            runner.stop(timeout=0)  # the start is in progress: no time to wait
            assert runner.state == State.STARTING
        finally:
            release.set()
            first.join(5.0)

        assert svc.entered.wait(5.0)
        runner.stop()
        assert svc.torn_down.is_set()
        assert runner.state == State.STOPPED

    def test_stop_on_the_loop_during_a_start_raises_without_waiting(self, host):
        """A stop() on the loop thread while another thread is in start() raises
        at once: waiting for the start would block every service on the loop."""
        runner = host.runner(Parked())
        starting, release = threading.Event(), threading.Event()

        def hold(_name: str, _old: State, new: State) -> None:
            if new == State.STARTING and not starting.is_set():
                starting.set()
                release.wait(5.0)  # holds start() on its thread

        runner.on_state_change(hold)
        first = threading.Thread(target=runner.start)
        first.start()
        outcome: list[BaseException | None] = []
        done = threading.Event()

        def stop_on_loop() -> None:
            try:
                runner.stop(timeout=2.0)
                outcome.append(None)
            except BaseException as e:
                outcome.append(e)
            done.set()

        try:
            assert starting.wait(5.0)
            host.loop.call_soon_threadsafe(stop_on_loop)
            assert done.wait(10.0)
        finally:
            release.set()
            first.join(5.0)

        assert isinstance(outcome[0], RuntimeError)
        runner.stop()

    def test_task_ending_after_stop_gave_up_stops_the_runner(self, host):
        """A task that outlives stop()'s wait still moves the runner to
        STOPPED when it ends, so the runner can start again."""
        svc = HoldsCancel()
        runner = host.runner(svc)
        stopped = _on_state(runner, State.STOPPED)
        runner.start()
        assert svc.entered.wait(5.0)
        runner.stop(timeout=0)
        assert runner.state == State.STOPPING

        svc.release(host)

        assert stopped.wait(5.0)
        assert svc.torn_down.is_set()
        runner.start()
        runner.stop()
        assert runner.state == State.STOPPED

    def test_start_from_an_end_state_hook_runs_and_stops(self, host):
        """A FAILED hook that starts the runner again, on the loop as the run
        ends, gets a run that is alive and that stop() ends."""
        svc = FailsOnce()
        runner = host.runner(svc)
        restarted: list[bool] = []

        def restart(_name: str, _old: State, new: State) -> None:
            if new == State.FAILED and not restarted:
                restarted.append(True)
                runner.start()

        runner.on_state_change(restart)
        runner.start()

        assert svc.second_run.wait(5.0)
        assert runner.is_alive()
        runner.stop()
        assert runner.state == State.STOPPED
        assert not runner.is_alive()

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


class BlocksTeardown(Parked):
    """Its teardown(), run on the loop, blocks until released."""

    def __init__(self) -> None:
        super().__init__("blocks-teardown")
        self.release = threading.Event()

    def teardown(self) -> None:
        self.release.wait(5.0)
        super().teardown()


class TestLoopHostStop:
    def test_stop_that_times_out_keeps_the_host_until_shutdown_ends(self):
        """A stop() whose wait ends before the shutdown does leaves the host
        running, not started anew; a later stop() waits for the shutdown."""
        host = LoopHost(name=LOOP_THREAD)
        host.start()
        svc = BlocksTeardown()
        runner = host.runner(svc)
        runner.start()
        assert svc.entered.wait(5.0)

        host.stop(timeout=0)  # the shutdown blocks in teardown()
        try:
            with pytest.raises(RuntimeError, match="already started"):
                host.start()
        finally:
            svc.release.set()
        host.stop()

        assert svc.torn_down.is_set()
        assert not runner.is_alive()
        with pytest.raises(RuntimeError, match="is not running"):
            host.loop

    def test_stop_tears_down_a_service_whose_task_has_not_begun(self):
        """The host stopping between a task's creation and its first step still
        tears the service down and ends its runner."""
        host = LoopHost(name=LOOP_THREAD)
        host.start()
        release = _hold_loop(host)
        svc = Parked()
        runner = host.runner(svc)
        runner.start()  # its task's creation is queued behind the hold
        stopper = threading.Thread(target=host.stop)
        stopper.start()
        # Private: once stop() leaves its locked block, the loop's stop is queued
        # right after the task's creation, so the loop stops in the iteration
        # that creates the task, before the task's first step
        assert _wait_until(lambda: host._closing)
        with host._lock:
            pass

        release.set()
        stopper.join(timeout=5.0)

        assert svc.torn_down.is_set()
        assert not svc.entered.is_set()
        assert not runner.is_alive()

    def test_start_while_the_host_stops_is_refused(self):
        """A start() once stop() has begun raises, and tears down what setup()
        opened."""
        host = LoopHost(name=LOOP_THREAD)
        host.start()
        release = _hold_loop(host)
        stopper = threading.Thread(target=host.stop)
        stopper.start()
        # Private: the window in which stop() has begun but the loop still runs
        assert _wait_until(lambda: host._closing)
        svc = Parked()
        runner = host.runner(svc)

        try:
            with pytest.raises(RuntimeError, match="is stopping"):
                runner.start()
        finally:
            release.set()
            stopper.join(timeout=5.0)

        assert runner.state == State.FAILED
        assert svc.torn_down.is_set()
        assert not runner.is_alive()

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
