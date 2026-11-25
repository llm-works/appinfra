# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for the Runtime and its tasks: on the loop, on threads, tids, and stop."""

import asyncio
import threading
import time
from collections.abc import Callable, Iterator
from unittest.mock import MagicMock

import pytest

from appinfra.runtime import Runtime, StopToken, stopping, tid

LOOP_THREAD = "runtime-loop"


class Parked:
    """An async function that waits on an event nothing sets; notes how it ends."""

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.cancelled = False
        self.token: StopToken | None = None

    async def run(self) -> None:
        self.token = stopping()
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


def _waits_for_stop() -> StopToken:
    token = stopping()
    token.wait()
    return token


def _boom() -> None:
    raise ValueError("boom")


async def _async_boom() -> None:
    raise ValueError("boom")


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


def _known(rt: Runtime, t: int) -> bool:
    """True if the runtime still knows task *t*: running, or ended and not
    reaped."""
    try:
        rt.alive(t)
    except LookupError:
        return False
    return True


def _hold_loop(rt: Runtime) -> threading.Event:
    """Block the runtime's loop until the returned event is set. Returns once
    the loop is blocked, so what is scheduled next runs in a later iteration,
    in the order scheduled."""
    held, release = threading.Event(), threading.Event()

    async def hold() -> None:
        held.set()
        release.wait(5.0)  # blocks the loop on purpose

    rt.detach(rt.spawn(hold))
    assert held.wait(5.0)
    return release


class TestLoopTask:
    """An async function as a task on the runtime's loop."""

    def test_many_tasks_share_the_loop_thread(self, rt):
        # A set, not a count: a thread an earlier test left may end meanwhile
        threads_before = set(threading.enumerate())
        fns = [Parked() for _ in range(50)]
        tids = [rt.spawn(fn.run) for fn in fns]

        assert all(fn.entered.wait(timeout=5.0) for fn in fns)
        assert set(threading.enumerate()) <= threads_before
        for t in tids:
            rt.cancel(t)
            rt.wait(t, timeout=5.0)

    def test_it_runs_on_the_loop_thread_with_its_args(self, rt):
        async def where(x: int) -> tuple[str, int]:
            return threading.current_thread().name, x

        assert rt.wait(rt.spawn(where, 21), timeout=5.0) == (LOOP_THREAD, 21)

    def test_cancel_cancels_it_and_stops_its_token(self, rt):
        fn = Parked()
        t = rt.spawn(fn.run)
        assert fn.entered.wait(timeout=5.0)

        rt.cancel(t)

        assert rt.wait(t, timeout=5.0) is None
        assert fn.cancelled
        assert fn.token is not None and fn.token.is_set()

    def test_a_failure_fails_that_task_only(self, rt):
        other = Parked()
        other_tid = rt.spawn(other.run)
        assert other.entered.wait(timeout=5.0)

        with pytest.raises(ValueError, match="boom"):
            rt.wait(rt.spawn(_async_boom), timeout=5.0)
        assert rt.alive(other_tid)

    @pytest.mark.parametrize("exc_type", [SystemExit, KeyboardInterrupt])
    def test_an_exit_fails_that_task_only(self, rt, exc_type):
        """asyncio re-raises SystemExit and KeyboardInterrupt out of the loop,
        which would end every task on it; only the one task fails."""

        async def exits() -> None:
            raise exc_type()

        other = Parked()
        other_tid = rt.spawn(other.run)
        assert other.entered.wait(timeout=5.0)

        with pytest.raises(exc_type):
            rt.wait(rt.spawn(exits), timeout=5.0)
        assert rt.alive(other_tid)
        # The loop runs on: a task spawned after it still runs
        later = Parked()
        rt.spawn(later.run)
        assert later.entered.wait(timeout=5.0)

    def test_cancel_right_after_spawn_ends_it(self, rt):
        """Whether or not the task has begun when the cancel lands, it ends."""
        for _ in range(20):
            t = rt.spawn(Parked().run)
            rt.cancel(t)
            rt.wait(t, timeout=5.0)

    def test_a_task_cancelled_before_its_first_step_never_runs(self, rt):
        release = _hold_loop(rt)
        fn = Parked()
        try:
            t = rt.spawn(fn.run)  # its creation is queued behind the hold
            rt.cancel(t)
        finally:
            release.set()
        rt.wait(t, timeout=5.0)
        assert not fn.entered.is_set()

    def test_wait_on_the_loop_is_refused(self, rt):
        """Waiting on the loop thread would block every task on it."""
        target = rt.spawn(Parked().run)

        async def waits() -> None:
            rt.wait(target, timeout=2.0)

        with pytest.raises(RuntimeError, match="block"):
            rt.wait(rt.spawn(waits), timeout=5.0)

    def test_a_task_ending_after_a_wait_gave_up_ends_on_its_own(self, rt):
        fn = HoldsCancel()
        t = rt.spawn(fn.run)
        assert fn.entered.wait(5.0)
        rt.cancel(t)
        with pytest.raises(TimeoutError):
            rt.wait(t, timeout=0)
        assert _known(rt, t)  # a wait that timed out does not reap

        fn.release.set()

        rt.wait(t, timeout=5.0)


class TestThreadTask:
    """A function as a task on a thread of its own."""

    def test_it_runs_on_a_thread_of_its_own_with_its_args(self, rt):
        def where(x: int) -> tuple[str, int]:
            return threading.current_thread().name, x

        t = rt.spawn(where, 21)
        assert rt.wait(t, timeout=5.0) == (f"task-{t}", 21)

    def test_cancel_stops_its_token(self, rt):
        t = rt.spawn(_waits_for_stop)
        rt.cancel(t)
        assert rt.wait(t, timeout=5.0).is_set()

    def test_a_failure_comes_back_from_wait(self, rt):
        with pytest.raises(ValueError, match="boom"):
            rt.wait(rt.spawn(_boom), timeout=5.0)

    def test_wait_gives_up_on_a_task_that_ignores_its_token(self, rt):
        release = threading.Event()
        t = rt.spawn(release.wait, 10.0)
        rt.cancel(t)
        try:
            with pytest.raises(TimeoutError):
                rt.wait(t, timeout=0)
            assert rt.alive(t)
        finally:
            release.set()
        assert rt.wait(t, timeout=5.0) is True

    def test_a_task_waiting_for_itself_is_refused(self, rt):
        def waits_for_itself() -> None:
            rt.wait(tid(), timeout=1.0)

        with pytest.raises(RuntimeError, match="itself"):
            rt.wait(rt.spawn(waits_for_itself), timeout=5.0)


class TestTids:
    def test_tids_count_up_and_are_never_reused(self, rt):
        first = rt.spawn(lambda: None)
        rt.wait(first, timeout=5.0)
        second = rt.spawn(lambda: None)
        assert second > first
        rt.wait(second, timeout=5.0)

    @pytest.mark.parametrize("on_loop", [True, False], ids=["loop", "thread"])
    def test_a_task_knows_its_own_tid(self, rt, on_loop):
        async def mine_async() -> int:
            return tid()

        def mine() -> int:
            return tid()

        t = rt.spawn(mine_async if on_loop else mine)
        assert rt.wait(t, timeout=5.0) == t

    def test_tid_and_stopping_outside_a_task_are_refused(self):
        with pytest.raises(RuntimeError, match="outside a task"):
            tid()
        with pytest.raises(RuntimeError, match="outside a task"):
            stopping()

    @pytest.mark.parametrize("op", ["wait", "cancel", "alive", "detach"])
    def test_an_unknown_tid_is_refused(self, rt, op):
        with pytest.raises(LookupError, match="no task 999"):
            getattr(rt, op)(999)


class TestZombies:
    def test_an_ended_task_stays_until_waited_for(self, rt):
        t = rt.spawn(lambda: 42)
        assert _wait_until(lambda: not rt.alive(t))
        assert _known(rt, t)
        assert rt.wait(t, timeout=5.0) == 42
        assert not _known(rt, t)

    def test_a_reaped_task_is_gone(self, rt):
        t = rt.spawn(lambda: 42)
        rt.wait(t, timeout=5.0)
        with pytest.raises(LookupError):
            rt.wait(t, timeout=5.0)

    def test_a_detached_task_is_reaped_when_it_ends(self, rt):
        release = threading.Event()
        t = rt.spawn(release.wait, 5.0)
        rt.detach(t)
        assert _known(rt, t)
        release.set()
        assert _wait_until(lambda: not _known(rt, t))

    def test_detaching_an_ended_task_reaps_it(self, rt):
        t = rt.spawn(lambda: None)
        assert _wait_until(lambda: not rt.alive(t))
        rt.detach(t)
        assert not _known(rt, t)

    def test_wait_on_a_detached_task_is_refused(self, rt):
        t = rt.spawn(_waits_for_stop)
        rt.detach(t)
        with pytest.raises(RuntimeError, match="detached"):
            rt.wait(t)
        rt.cancel(t)

    def test_a_detached_failure_is_logged(self):
        lg = MagicMock()
        with Runtime(lg) as rt:
            t = rt.spawn(_boom)
            rt.detach(t)
            assert _wait_until(lambda: not _known(rt, t))
        lg.warning.assert_called_once()
        args, kwargs = lg.warning.call_args
        assert args[0] == "task failed"
        assert isinstance(kwargs["extra"]["exception"], ValueError)

    def test_a_failure_collected_by_wait_is_not_logged(self):
        lg = MagicMock()
        with Runtime(lg) as rt, pytest.raises(ValueError):
            rt.wait(rt.spawn(_boom), timeout=5.0)
        lg.warning.assert_not_called()

    def test_outcomes_stay_to_be_waited_for_after_stop(self):
        with Runtime(MagicMock()) as rt:
            done = rt.spawn(lambda: 42)
            stopped = rt.spawn(_waits_for_stop)
            assert _wait_until(lambda: not rt.alive(done))
        assert rt.wait(done, timeout=0) == 42
        assert rt.wait(stopped, timeout=0).is_set()


class TestTokens:
    @pytest.mark.parametrize("on_loop", [True, False], ids=["loop", "thread"])
    def test_a_task_spawned_by_a_task_derives_from_its_token(self, rt, on_loop):
        """Cancelling a task stops every task it spawned."""
        children: list[int] = []

        async def async_parent() -> None:
            children.append(rt.spawn(_waits_for_stop))
            await asyncio.Event().wait()

        def parent() -> None:
            children.append(rt.spawn(_waits_for_stop))
            stopping().wait()

        t = rt.spawn(async_parent if on_loop else parent)
        assert _wait_until(lambda: bool(children))

        rt.cancel(t)

        assert rt.wait(children[0], timeout=5.0).is_set()

    def test_an_ended_task_leaves_the_token_tree(self, rt):
        """A runtime running many short tasks keeps no token for each one."""

        async def on_loop() -> None:
            pass

        tids = [rt.spawn(on_loop) for _ in range(10)]
        tids += [rt.spawn(lambda: None) for _ in range(10)]
        for t in tids:
            rt.wait(t, timeout=5.0)
        assert not rt._root._children  # Private: the root's set of children


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
        rt = Runtime(MagicMock())
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
        with Runtime(MagicMock()) as rt:
            on_loop = rt.spawn(fn.run)
            on_thread = rt.spawn(_waits_for_stop)
            assert fn.entered.wait(timeout=5.0)

        assert fn.cancelled
        assert not rt.alive(on_loop)
        assert not rt.alive(on_thread)

    def test_stop_signals_the_token_before_cancelling(self):
        """The runtime stops each task's token before it cancels the task: a
        task that waits for its worker on cancel would otherwise wait for a
        token that only its end stops."""
        rt = Runtime(MagicMock())
        rt.start()
        fn = JoinsItsWorkerOnCancel()
        t = rt.spawn(fn.run)
        assert fn.entered.wait(timeout=5.0)
        try:
            rt.stop(timeout=5.0)  # the deadline is the failure path
            assert not rt.alive(t)
        finally:
            if fn.work is not None:
                fn.work.stop()  # release the worker if the test failed
            rt.stop()

    def test_stop_releases_work_derived_from_the_token(self):
        """The thread waiting on a child of the task's token holds the loop's
        default executor; unless that token stops, the loop never ends."""
        rt = Runtime(MagicMock())
        rt.start()
        fn = WaitsOnAThread()
        t = rt.spawn(fn.run)
        assert fn.entered.wait(timeout=5.0)
        try:
            rt.stop(timeout=5.0)  # the deadline is the failure path
            assert fn.work is not None and fn.work.is_set()
            assert not rt.alive(t)
        finally:
            if fn.work is not None:
                fn.work.stop()  # release the thread if the test failed

    def test_a_task_not_begun_when_stop_comes_never_runs(self):
        """The runtime stopping between a task's spawn and its first step still
        ends it, without calling it."""
        rt = Runtime(MagicMock())
        rt.start()
        release = _hold_loop(rt)
        fn = Parked()
        t = rt.spawn(fn.run)  # its creation is queued behind the hold
        stopper = threading.Thread(target=rt.stop)
        stopper.start()
        assert _wait_until(lambda: rt._closing)  # Private: stop() has begun

        release.set()
        stopper.join(timeout=5.0)

        assert not stopper.is_alive()
        assert not fn.entered.is_set()
        assert not rt.alive(t)

    def test_spawn_while_the_runtime_stops_is_refused(self):
        rt = Runtime(MagicMock())
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
        rt = Runtime(lg)
        rt.start()
        t = rt.spawn(release.wait, 10.0)
        try:
            rt.stop(timeout=0)
            lg.warning.assert_called_once()
            assert lg.warning.call_args.args[0] == "task did not end in time"
        finally:
            release.set()
        assert rt.wait(t, timeout=5.0) is True

    def test_stop_on_the_loop_thread_is_refused(self, rt):
        async def stops() -> None:
            rt.stop()

        with pytest.raises(RuntimeError, match="loop thread"):
            rt.wait(rt.spawn(stops), timeout=5.0)

    def test_a_task_stopping_the_runtime_does_not_wait_for_itself(self):
        rt = Runtime(MagicMock())
        rt.start()
        t = rt.spawn(rt.stop, 5.0)
        assert rt.wait(t, timeout=10.0) is None
        assert rt._closing  # Private: the runtime stopped
