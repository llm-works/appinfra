# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for the Runtime and its tasks: on the loop, on threads, and stop."""

import asyncio
import threading
import time
from collections.abc import Callable, Iterator
from unittest.mock import MagicMock

import pytest

from appinfra.runtime import (
    LoopTask,
    Runtime,
    StopToken,
    Task,
    ThreadTask,
    stopping,
)

LOOP_THREAD = "test-rt"


class Parked:
    """An async function that waits on an event nothing sets; notes how it ends."""

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.cancelled = False

    async def run(self) -> None:
        self.entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise


class HoldsCancel:
    """When cancelled, returns only once *release* is set; blocks the loop."""

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()

    async def run(self) -> None:
        self.entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.release.wait(10.0)  # blocks the loop on purpose


class JoinsItsWorkerOnCancel:
    """Runs a worker thread on a token derived from its own and, cancelled,
    waits for that thread before letting the cancel through."""

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.work: StopToken | None = None

    async def run(self) -> None:
        self.work = stopping().child()
        worker = threading.Thread(target=self.work.wait, daemon=True)
        worker.start()
        self.entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await asyncio.to_thread(worker.join)
            raise


class WaitsOnAThread:
    """Hands its wait to a thread, on a token derived from its own."""

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.work: StopToken | None = None

    async def run(self) -> None:
        self.work = stopping().child()
        self.entered.set()
        await asyncio.to_thread(self.work.wait)


def _waits_for_stop() -> None:
    stopping().wait()


@pytest.fixture
def rt() -> Iterator[Runtime]:
    runtime = Runtime(MagicMock(), name=LOOP_THREAD)
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


def _hold_loop(rt: Runtime) -> threading.Event:
    """Block the runtime's loop until the returned event is set. Returns once
    the loop is blocked, so what is scheduled next runs in a later iteration,
    in the order scheduled."""
    held, release = threading.Event(), threading.Event()

    async def hold() -> None:
        held.set()
        release.wait(5.0)  # blocks the loop on purpose

    rt.spawn(hold)
    assert held.wait(5.0)
    return release


class TestLoopTask:
    """An async function as a task on the runtime's loop."""

    def test_many_tasks_share_the_loop_thread(self, rt):
        # A set, not a count: a thread an earlier test left may end meanwhile
        threads_before = set(threading.enumerate())
        fns = [Parked() for _ in range(50)]
        tasks = [rt.spawn(fn.run) for fn in fns]

        assert all(isinstance(task, LoopTask) for task in tasks)
        assert all(fn.entered.wait(timeout=5.0) for fn in fns)
        assert set(threading.enumerate()) <= threads_before
        for task in tasks:
            assert task.stop()

    def test_it_runs_on_the_loop_thread_with_its_args(self, rt):
        async def where(x: int) -> tuple[str, int]:
            return threading.current_thread().name, x

        task = rt.spawn(where, 21)
        assert _wait_until(lambda: not task.is_alive())
        assert task.result == (LOOP_THREAD, 21)

    def test_stop_cancels_it_and_stops_its_token(self, rt):
        fn = Parked()
        task = rt.spawn(fn.run)
        assert fn.entered.wait(timeout=5.0)

        assert task.stop()

        assert fn.cancelled
        assert task.token.is_set()
        assert not task.is_alive()
        assert task.exception is None

    def test_a_failure_fails_that_task_only(self, rt):
        async def boom() -> None:
            raise RuntimeError("run failed")

        other = Parked()
        other_task = rt.spawn(other.run)
        assert other.entered.wait(timeout=5.0)

        task = rt.spawn(boom)

        assert _wait_until(lambda: not task.is_alive())
        assert "run failed" in str(task.exception)
        assert other_task.is_alive()

    @pytest.mark.parametrize("exc_type", [SystemExit, KeyboardInterrupt])
    def test_an_exit_fails_that_task_only(self, rt, exc_type):
        """asyncio re-raises SystemExit and KeyboardInterrupt out of the loop,
        which would end every task on it; only the one task fails."""

        async def exits() -> None:
            raise exc_type()

        other = Parked()
        other_task = rt.spawn(other.run)
        assert other.entered.wait(timeout=5.0)

        task = rt.spawn(exits)

        assert _wait_until(lambda: not task.is_alive())
        assert isinstance(task.exception, exc_type)
        assert other_task.is_alive()
        # The loop runs on: a task spawned after it still runs
        later = Parked()
        rt.spawn(later.run)
        assert later.entered.wait(timeout=5.0)

    def test_stop_right_after_spawn_ends_it(self, rt):
        """Whether or not the task has begun when stop() lands, it ends."""
        for _ in range(20):
            task = rt.spawn(Parked().run)
            assert task.stop()
            assert not task.is_alive()

    def test_stop_on_the_loop_raises_without_waiting(self, rt):
        """Waiting on the loop thread would block every task on it."""
        target = rt.spawn(Parked().run)
        outcome: list[BaseException | None] = []

        async def stops() -> None:
            try:
                target.stop(timeout=2.0)
                outcome.append(None)
            except BaseException as e:
                outcome.append(e)

        stopper = rt.spawn(stops)
        assert _wait_until(lambda: not stopper.is_alive())
        assert isinstance(outcome[0], RuntimeError)

    def test_a_task_ending_after_stop_gave_up_ends_on_its_own(self, rt):
        fn = HoldsCancel()
        task = rt.spawn(fn.run)
        assert fn.entered.wait(5.0)
        assert not task.stop(timeout=0)
        assert task.is_alive()

        fn.release.set()

        assert _wait_until(lambda: not task.is_alive())


class TestThreadTask:
    """A function as a task on a thread of its own."""

    def test_it_runs_on_a_thread_of_its_own_with_its_args(self, rt):
        def where(x: int) -> tuple[str, int]:
            return threading.current_thread().name, x

        task = rt.spawn(where, 21)
        assert isinstance(task, ThreadTask)
        assert _wait_until(lambda: not task.is_alive())
        assert task.result == ("task-where", 21)

    def test_stop_stops_its_token_and_waits_for_it(self, rt):
        task = rt.spawn(_waits_for_stop)
        assert task.stop(timeout=5.0)
        assert task.token.is_set()
        assert not task.is_alive()

    def test_a_failure_is_kept(self, rt):
        def boom() -> None:
            raise ValueError("boom")

        task = rt.spawn(boom)
        assert _wait_until(lambda: not task.is_alive())
        assert isinstance(task.exception, ValueError)
        assert task.result is None

    def test_stop_gives_up_on_a_task_that_ignores_its_token(self, rt):
        release = threading.Event()
        task = rt.spawn(release.wait, 10.0)
        try:
            assert not task.stop(timeout=0)
            assert task.is_alive()
        finally:
            release.set()
        assert _wait_until(lambda: not task.is_alive())


class TestTokens:
    def test_stopping_outside_a_task_is_refused(self):
        with pytest.raises(RuntimeError, match="outside a task"):
            stopping()

    def test_each_task_sees_its_own_token(self, rt):
        async def on_loop() -> StopToken:
            return stopping()

        tasks = [rt.spawn(on_loop), rt.spawn(stopping)]
        assert _wait_until(lambda: not any(t.is_alive() for t in tasks))
        assert [t.result for t in tasks] == [t.token for t in tasks]

    @pytest.mark.parametrize("on_loop", [True, False], ids=["loop", "thread"])
    def test_a_task_spawned_by_a_task_derives_from_its_token(self, rt, on_loop):
        """Stopping a task stops every task it spawned."""
        children: list[Task] = []

        async def async_parent() -> None:
            children.append(rt.spawn(_waits_for_stop))
            await asyncio.Event().wait()

        def parent() -> None:
            children.append(rt.spawn(_waits_for_stop))
            stopping().wait()

        task = rt.spawn(async_parent if on_loop else parent)
        assert _wait_until(lambda: bool(children))

        assert task.stop()

        assert _wait_until(lambda: not children[0].is_alive())
        assert children[0].token.is_set()

    def test_an_ended_task_leaves_the_token_tree(self, rt):
        """A runtime running many short tasks keeps no token for each one."""

        async def on_loop() -> None:
            pass

        tasks = [rt.spawn(on_loop) for _ in range(10)]
        tasks += [rt.spawn(lambda: None) for _ in range(10)]
        assert _wait_until(lambda: not any(t.is_alive() for t in tasks))
        assert not rt._root._children  # Private: the root's set of children

    def test_an_ended_task_leaves_the_runtime(self, rt):
        task = rt.spawn(lambda: None)
        assert _wait_until(lambda: not task.is_alive())
        assert _wait_until(lambda: task not in rt.tasks)

    def test_a_failure_is_logged(self):
        lg = MagicMock()

        def boom() -> None:
            raise ValueError("boom")

        with Runtime(lg, name=LOOP_THREAD) as rt:
            task = rt.spawn(boom)
            assert _wait_until(lambda: not task.is_alive())
        lg.warning.assert_called_once()
        args, kwargs = lg.warning.call_args
        assert args[0] == "task failed"
        assert kwargs["extra"]["exception"] is task.exception


class TestSpawn:
    def test_spawn_needs_a_running_runtime(self):
        runtime = Runtime(MagicMock())
        with pytest.raises(RuntimeError, match="not running"):
            runtime.spawn(_waits_for_stop)
        runtime.start()
        runtime.stop()
        with pytest.raises(RuntimeError, match="not running"):
            runtime.spawn(_waits_for_stop)

    def test_a_runtime_starts_once(self):
        """Single use: not started again while running nor after stop()."""
        rt = Runtime(MagicMock(), name="once")
        rt.start()
        with pytest.raises(RuntimeError, match="started already"):
            rt.start()
        rt.stop()
        with pytest.raises(RuntimeError, match="started already"):
            rt.start()

    def test_a_refused_spawn_leaves_no_token_behind(self):
        rt = Runtime(MagicMock())
        with pytest.raises(RuntimeError):
            rt.spawn(_waits_for_stop)
        assert not rt._root._children  # Private: the root's set of children


class TestStop:
    def test_stop_ends_the_tasks_still_running(self):
        fn = Parked()
        with Runtime(MagicMock(), name=LOOP_THREAD) as rt:
            on_loop = rt.spawn(fn.run)
            on_thread = rt.spawn(_waits_for_stop)
            assert fn.entered.wait(timeout=5.0)

        assert fn.cancelled
        assert not on_loop.is_alive()
        assert not on_thread.is_alive()
        assert rt.tasks == set()

    def test_stop_signals_the_token_before_cancelling(self):
        """The runtime stops each task's token before it cancels the task: a
        task that waits for its worker on cancel would otherwise wait for a
        token that only its end stops."""
        rt = Runtime(MagicMock(), name=LOOP_THREAD)
        rt.start()
        fn = JoinsItsWorkerOnCancel()
        task = rt.spawn(fn.run)
        assert fn.entered.wait(timeout=5.0)
        try:
            rt.stop(timeout=5.0)  # the deadline is the failure path
            assert not task.is_alive()
        finally:
            if fn.work is not None:
                fn.work.stop()  # release the worker if the test failed
            rt.stop()

    def test_stop_releases_work_derived_from_the_token(self):
        """The thread waiting on a child of the task's token holds the loop's
        default executor; unless that token stops, the loop never ends."""
        rt = Runtime(MagicMock(), name=LOOP_THREAD)
        rt.start()
        fn = WaitsOnAThread()
        task = rt.spawn(fn.run)
        assert fn.entered.wait(timeout=5.0)
        try:
            rt.stop(timeout=5.0)  # the deadline is the failure path
            assert fn.work is not None and fn.work.is_set()
            assert not task.is_alive()
        finally:
            if fn.work is not None:
                fn.work.stop()  # release the thread if the test failed

    def test_a_task_not_begun_when_stop_comes_never_runs(self):
        """The runtime stopping between a task's spawn and its first step still
        ends it, without calling it."""
        rt = Runtime(MagicMock(), name=LOOP_THREAD)
        rt.start()
        release = _hold_loop(rt)
        fn = Parked()
        task = rt.spawn(fn.run)  # its creation is queued behind the hold
        stopper = threading.Thread(target=rt.stop)
        stopper.start()
        assert _wait_until(lambda: rt._closing)  # Private: stop() has begun

        release.set()
        stopper.join(timeout=5.0)

        assert not stopper.is_alive()
        assert not fn.entered.is_set()
        assert not task.is_alive()

    def test_spawn_while_the_runtime_stops_is_refused(self):
        rt = Runtime(MagicMock(), name=LOOP_THREAD)
        rt.start()
        release = _hold_loop(rt)
        stopper = threading.Thread(target=rt.stop)
        stopper.start()
        # Private: the window in which stop() has begun but the loop still runs
        assert _wait_until(lambda: rt._closing)

        try:
            with pytest.raises(RuntimeError, match="not running"):
                rt.spawn(_waits_for_stop)
        finally:
            release.set()
            stopper.join(timeout=5.0)

    def test_a_task_that_ignores_its_token_is_logged_and_left(self):
        """A thread cannot be killed: stop() reports it and returns."""
        lg = MagicMock()
        release = threading.Event()
        rt = Runtime(lg, name=LOOP_THREAD)
        rt.start()
        task = rt.spawn(release.wait, 10.0)
        try:
            rt.stop(timeout=0)
            lg.warning.assert_called_once()
            assert lg.warning.call_args.args[0] == "task did not end in time"
        finally:
            release.set()
        assert _wait_until(lambda: not task.is_alive())

    def test_stop_on_the_loop_thread_is_refused(self, rt):
        outcome: list[BaseException] = []

        async def stops() -> None:
            try:
                rt.stop()
            except RuntimeError as e:
                outcome.append(e)

        task = rt.spawn(stops)
        assert _wait_until(lambda: not task.is_alive())
        assert "loop thread" in str(outcome[0])
