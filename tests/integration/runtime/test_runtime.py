# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for the Runtime and its tasks: on the loop, on threads, ids, and stop."""

import asyncio
import threading
import time
from collections.abc import Callable, Iterator
from unittest.mock import MagicMock

import pytest

from appinfra.runtime import (
    Chan,
    ChanClosedError,
    Runtime,
    StoppedError,
    StopToken,
    TaskEnd,
    stopping,
    task_id,
)
from appinfra.runtime.chan import pipe
from appinfra.runtime.loop import LoopHost
from appinfra.runtime.task import LoopTask, ThreadTask
from appinfra.testing import FakeClock


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


async def _park() -> None:
    await asyncio.Event().wait()


def _waits_for_stop() -> StopToken:
    token = stopping()
    token.wait()
    return token


class WaitsForStop:
    """_waits_for_stop() that notes it has begun: a task whose token stops
    before its call begins skips the call, so a test that reads the returned
    token waits for *entered* before it cancels or stops."""

    def __init__(self) -> None:
        self.entered = threading.Event()

    def __call__(self) -> StopToken:
        self.entered.set()
        return _waits_for_stop()


class IgnoresItsToken:
    """Runs until *release* is set, whatever its token says; notes it has
    begun, so a test cancels or stops it only once it runs."""

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()

    def __call__(self) -> bool:
        self.entered.set()
        return self.release.wait(10.0)


def _boom() -> None:
    raise ValueError("boom")


class _UndecodableError(Exception):
    """Pickles, but cannot be unpickled: its args do not fit its __init__."""

    def __init__(self, a: int, b: int) -> None:
        super().__init__(f"{a} {b}")


def _raises_undecodable() -> None:
    raise _UndecodableError(1, 2)


def _raises_stopped_error() -> None:
    raise StoppedError("not a stop")


def _failing_callback() -> None:
    raise ValueError("callback failed")


def _interrupting_callback() -> None:
    raise KeyboardInterrupt


@pytest.fixture
def reported(monkeypatch: pytest.MonkeyPatch) -> list[BaseException]:
    """Errors reported through threading.excepthook, kept instead of printed."""
    errors: list[BaseException] = []
    monkeypatch.setattr(threading, "excepthook", lambda a: errors.append(a.exc_value))
    return errors


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
        task_ids = [rt.spawn(fn.run) for fn in fns]

        assert all(fn.entered.wait(timeout=5.0) for fn in fns)
        assert set(threading.enumerate()) <= threads_before
        for t in task_ids:
            rt.cancel(t)
            with pytest.raises(StoppedError):
                rt.wait(t, timeout=5.0)

    def test_it_runs_on_the_loop_thread_with_its_args(self, rt):
        """Every async task runs on the one loop thread, not the caller's."""

        async def where(x: int) -> tuple[threading.Thread, int]:
            return threading.current_thread(), x

        first, x = rt.wait(rt.spawn(where, 21), timeout=5.0)
        second, _ = rt.wait(rt.spawn(where, 0), timeout=5.0)
        assert x == 21
        assert first is second
        assert first is not threading.current_thread()

    def test_cancel_cancels_it_and_stops_its_token(self, rt):
        fn = Parked()
        t = rt.spawn(fn.run)
        assert fn.entered.wait(timeout=5.0)

        rt.cancel(t)

        with pytest.raises(StoppedError):  # it produced no result
            rt.wait(t, timeout=5.0)
        assert fn.cancelled
        assert fn.token is not None and fn.token.is_set()

    def test_a_failure_fails_that_task_only(self, rt):
        other = Parked()
        other_task_id = rt.spawn(other.run)
        assert other.entered.wait(timeout=5.0)

        with pytest.raises(ValueError, match="boom"):
            rt.wait(rt.spawn(_async_boom), timeout=5.0)
        assert rt.alive(other_task_id)

    @pytest.mark.parametrize("exc_type", [SystemExit, KeyboardInterrupt])
    def test_an_exit_fails_that_task_only(self, rt, exc_type):
        """asyncio re-raises SystemExit and KeyboardInterrupt out of the loop,
        which would end every task on it; only the one task fails."""

        async def exits() -> None:
            raise exc_type()

        other = Parked()
        other_task_id = rt.spawn(other.run)
        assert other.entered.wait(timeout=5.0)

        with pytest.raises(exc_type):
            rt.wait(rt.spawn(exits), timeout=5.0)
        assert rt.alive(other_task_id)
        # The loop runs on: a task spawned after it still runs
        later = Parked()
        rt.spawn(later.run)
        assert later.entered.wait(timeout=5.0)

    def test_cancel_right_after_spawn_ends_it(self, rt):
        """Whether or not the task has begun when the cancel lands, it ends."""
        for _ in range(20):
            t = rt.spawn(Parked().run)
            rt.cancel(t)
            with pytest.raises(StoppedError):
                rt.wait(t, timeout=5.0)

    def test_a_task_cancelled_before_its_first_step_never_runs(self, rt):
        release = _hold_loop(rt)
        fn = Parked()
        try:
            t = rt.spawn(fn.run)  # its creation is queued behind the hold
            rt.cancel(t)
        finally:
            release.set()
        with pytest.raises(StoppedError):
            rt.wait(t, timeout=5.0)
        assert not fn.entered.is_set()

    def test_wait_on_the_loop_is_refused(self, rt):
        """Waiting on the loop thread would block every task on it."""
        target = rt.spawn(Parked().run)

        async def waits() -> None:
            rt.wait(target, timeout=2.0)

        with pytest.raises(RuntimeError, match="block"):
            rt.wait(rt.spawn(waits), timeout=5.0)

    def test_waiting_on_a_running_thread_task_on_the_loop_is_refused(self, rt):
        """Joining the thread would block every task on the loop."""
        release = threading.Event()
        target = rt.spawn(release.wait, 10.0)

        async def waits() -> None:
            rt.wait(target, timeout=1.0)  # unrefused, it blocks the loop for 1 s

        try:
            with pytest.raises(RuntimeError, match="block"):
                rt.wait(rt.spawn(waits), timeout=5.0)
        finally:
            release.set()
        assert rt.wait(target, timeout=5.0) is True

    def test_an_ended_thread_task_is_collected_on_the_loop(self, rt):
        target = rt.spawn(lambda: 42)
        assert _wait_until(lambda: not rt.alive(target))

        async def collects() -> int:
            return rt.wait(target, timeout=0)

        assert rt.wait(rt.spawn(collects), timeout=5.0) == 42

    def test_waits_that_time_out_leave_nothing_behind(self, rt):
        """Polling a long-running task must not grow it by one waiter per poll."""
        fn = Parked()
        t = rt.spawn(fn.run)
        assert fn.entered.wait(5.0)
        for _ in range(100):
            with pytest.raises(TimeoutError):
                rt.wait(t, timeout=0)
        task = rt._tasks[t]  # Private: the task behind the id
        assert _wait_until(lambda: not task._waiters)  # Private: registered waits

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
        """Neither the caller's thread nor the loop's."""

        async def on_loop() -> threading.Thread:
            return threading.current_thread()

        def where(x: int) -> tuple[threading.Thread, int]:
            return threading.current_thread(), x

        loop_thread = rt.wait(rt.spawn(on_loop), timeout=5.0)
        thread, x = rt.wait(rt.spawn(where, 21), timeout=5.0)
        assert x == 21
        assert thread not in (threading.current_thread(), loop_thread)

    def test_its_thread_name_carries_its_id(self, rt):
        """A thread dump ties the thread to the task's log records."""
        t = rt.spawn(lambda: threading.current_thread().name)
        assert rt.wait(t, timeout=5.0) == f"appinfra-task-{t}"

    def test_cancel_stops_its_token(self, rt):
        fn = WaitsForStop()
        t = rt.spawn(fn)
        assert fn.entered.wait(5.0)
        rt.cancel(t)
        assert rt.wait(t, timeout=5.0).is_set()

    def test_a_failure_comes_back_from_wait(self, rt):
        with pytest.raises(ValueError, match="boom"):
            rt.wait(rt.spawn(_boom), timeout=5.0)

    def test_an_ended_task_is_collected_before_its_thread_finishes(
        self, rt, monkeypatch
    ):
        """Once the runtime has recorded the end, wait() collects the outcome,
        even while the task's thread has not yet run its last line."""
        in_window, release = threading.Event(), threading.Event()
        real_on_end = Runtime._on_end

        def on_end_then_hold(self: Runtime, task: object) -> None:
            real_on_end(self, task)
            in_window.set()
            release.wait(10.0)  # holds the thread after the end is recorded

        monkeypatch.setattr(Runtime, "_on_end", on_end_then_hold)
        t = rt.spawn(lambda: 42)
        try:
            assert in_window.wait(5.0)
            assert not rt.alive(t)
            assert rt.wait(t, timeout=0) == 42
        finally:
            release.set()

    def test_wait_gives_up_on_a_task_that_ignores_its_token(self, rt):
        fn = IgnoresItsToken()
        t = rt.spawn(fn)
        assert fn.entered.wait(5.0)
        rt.cancel(t)
        try:
            with pytest.raises(TimeoutError):
                rt.wait(t, timeout=0)
            assert rt.alive(t)
        finally:
            fn.release.set()
        assert rt.wait(t, timeout=5.0) is True

    def test_a_task_waiting_for_itself_is_refused(self, rt):
        def waits_for_itself() -> None:
            rt.wait(task_id(), timeout=1.0)

        with pytest.raises(RuntimeError, match="itself"):
            rt.wait(rt.spawn(waits_for_itself), timeout=5.0)


class TestTaskIds:
    def test_task_ids_count_up_and_are_never_reused(self, rt):
        first = rt.spawn(lambda: None)
        rt.wait(first, timeout=5.0)
        second = rt.spawn(lambda: None)
        assert second > first
        rt.wait(second, timeout=5.0)

    @pytest.mark.parametrize("on_loop", [True, False], ids=["loop", "thread"])
    def test_a_task_knows_its_own_task_id(self, rt, on_loop):
        async def mine_async() -> int:
            return task_id()

        def mine() -> int:
            return task_id()

        t = rt.spawn(mine_async if on_loop else mine)
        assert rt.wait(t, timeout=5.0) == t

    def test_tid_and_stopping_outside_a_task_are_refused(self):
        with pytest.raises(RuntimeError, match="outside a task"):
            task_id()
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
            # The log call, not the reaping before it: it comes after the pop
            assert _wait_until(lambda: lg.warning.called)
            assert not _known(rt, t)
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
        fn = WaitsForStop()
        with Runtime(MagicMock()) as rt:
            done = rt.spawn(lambda: 42)
            stopped = rt.spawn(fn)
            assert fn.entered.wait(5.0)
            assert _wait_until(lambda: not rt.alive(done))
        assert rt.wait(done, timeout=0) == 42
        assert rt.wait(stopped, timeout=0).is_set()


class TestTokens:
    @pytest.mark.parametrize("on_loop", [True, False], ids=["loop", "thread"])
    def test_a_task_spawned_by_a_task_derives_from_its_token(self, rt, on_loop):
        """Cancelling a task stops every task it spawned."""
        children: list[int] = []
        child = WaitsForStop()

        async def async_parent() -> None:
            children.append(rt.spawn(child))
            await asyncio.Event().wait()

        def parent() -> None:
            children.append(rt.spawn(child))
            stopping().wait()

        t = rt.spawn(async_parent if on_loop else parent)
        assert child.entered.wait(5.0)

        rt.cancel(t)

        assert rt.wait(children[0], timeout=5.0).is_set()

    def test_an_ended_task_leaves_the_token_tree(self, rt):
        """A runtime running many short tasks keeps no token for each one."""

        async def on_loop() -> None:
            pass

        task_ids = [rt.spawn(on_loop) for _ in range(10)]
        task_ids += [rt.spawn(lambda: None) for _ in range(10)]
        for t in task_ids:
            rt.wait(t, timeout=5.0)
        assert not rt._root._children  # Private: the root's set of children

    @pytest.mark.parametrize("on_loop", [True, False], ids=["loop", "thread"])
    def test_a_task_that_ends_on_its_own_stops_its_token(self, rt, on_loop):
        """Work the task derived from its token is told to stop once it ends."""

        async def async_returns() -> StopToken:
            return stopping().child()

        def returns() -> StopToken:
            return stopping().child()

        derived = rt.wait(rt.spawn(async_returns if on_loop else returns), timeout=5.0)
        assert derived.is_set()

    @pytest.mark.parametrize("on_loop", [True, False], ids=["loop", "thread"])
    def test_a_task_whose_token_is_stopped_before_it_starts_never_runs(
        self, rt, on_loop
    ):
        """A child of a stopped token is born stopped; the call is skipped on
        either kind, as a cancel before the first step skips it on the loop."""
        entered = threading.Event()

        async def async_marks() -> None:
            entered.set()

        def marks() -> None:
            entered.set()

        def parent() -> int:
            stopping().stop()  # the parent's token: the child derives from it
            return rt.spawn(async_marks if on_loop else marks)

        child = rt.wait(rt.spawn(parent), timeout=5.0)
        with pytest.raises(StoppedError):  # it produced no result
            rt.wait(child, timeout=5.0)
        assert not entered.is_set()

    @pytest.mark.parametrize("on_loop", [True, False], ids=["loop", "thread"])
    def test_a_task_that_returns_after_its_stop_returns_its_value(self, rt, on_loop):
        """The function saw the stop and chose what to return: that is its
        result, not a stop."""
        entered = threading.Event()

        async def async_returns() -> str:
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                return "done"
            return "unreachable"

        def returns() -> str:
            entered.set()
            stopping().wait()
            return "done"

        t = rt.spawn(async_returns if on_loop else returns)
        assert entered.wait(5.0)
        rt.cancel(t)
        assert rt.wait(t, timeout=5.0) == "done"

    @pytest.mark.parametrize("on_loop", [True, False], ids=["loop", "thread"])
    def test_a_stopped_error_raised_without_a_stop_is_a_failure(self, rt, on_loop):
        """StoppedError ends a task cleanly only when its token is stopped;
        raised otherwise, it is the task's failure, kept and raised as is."""
        error = StoppedError("not a stop")

        async def async_raises() -> None:
            raise error

        def raises() -> None:
            raise error

        with pytest.raises(StoppedError) as caught:
            rt.wait(rt.spawn(async_raises if on_loop else raises), timeout=5.0)
        assert caught.value is error

    def test_a_cancelled_error_raised_without_a_stop_is_a_failure(self, rt):
        """On the loop, CancelledError is a stop only when the task's token is
        stopped: one the function raises on its own is its failure."""

        async def raises() -> None:
            raise asyncio.CancelledError()

        with pytest.raises(asyncio.CancelledError):
            rt.wait(rt.spawn(raises), timeout=5.0)

    def test_a_detached_task_failing_with_a_stopped_error_is_logged(self):
        lg = MagicMock()
        with Runtime(lg) as rt:
            rt.detach(rt.spawn(_raises_stopped_error))
            assert _wait_until(lambda: lg.warning.called)
        args, _ = lg.warning.call_args
        assert args[0] == "task failed"


class TestFailingStopCallback:
    """A callback on a task's token that raises is reported; it cuts nothing
    short that stops the token."""

    @pytest.mark.parametrize("on_loop", [True, False], ids=["loop", "thread"])
    def test_a_task_that_returns_still_ends(self, rt, reported, on_loop):
        async def async_returns() -> str:
            stopping()._on_stop(_failing_callback)
            return "done"

        def returns() -> str:
            stopping()._on_stop(_failing_callback)
            return "done"

        t = rt.spawn(async_returns if on_loop else returns)
        assert rt.wait(t, timeout=5.0) == "done"
        assert [str(e) for e in reported] == ["callback failed"]
        # Its end ran in full: the token left the tree
        assert not rt._root._children  # Private: the root's set of children

    def test_cancel_still_cancels_a_parked_loop_task(self, rt, reported):
        """The cancel is scheduled although the token's stop ran a failing
        callback; the task, which never looks at its token, ends."""
        entered = threading.Event()

        async def parks() -> None:
            stopping()._on_stop(_failing_callback)
            entered.set()
            await asyncio.Event().wait()

        t = rt.spawn(parks)
        assert entered.wait(5.0)
        rt.cancel(t)
        with pytest.raises(StoppedError):
            rt.wait(t, timeout=5.0)
        assert len(reported) == 1

    def test_stop_still_stops_the_loop_and_waits_for_threads(self, reported):
        rt = Runtime(MagicMock())
        rt.start()
        parked = Parked()
        loop_task = rt.spawn(parked.run)
        assert parked.entered.wait(5.0)
        entered = threading.Event()

        def waits() -> None:
            stopping()._on_stop(_failing_callback)
            entered.set()
            stopping().wait()

        thread_task = rt.spawn(waits)
        assert entered.wait(5.0)
        rt.stop()
        assert parked.cancelled  # the loop's stop cancelled it
        assert not rt.alive(loop_task)
        assert not rt.alive(thread_task)  # waited for
        assert len(reported) == 1

    @pytest.mark.parametrize("on_loop", [True, False], ids=["loop", "thread"])
    def test_an_interrupt_at_a_tasks_end_is_reported(self, rt, reported, on_loop):
        """A task ends on its own thread or the loop's, never the main one: an
        interrupt there is a callback's bug. The task ends in full, and the
        loop, which asyncio would end with it, runs on."""

        async def async_returns() -> str:
            stopping()._on_stop(_interrupting_callback)
            return "done"

        def returns() -> str:
            stopping()._on_stop(_interrupting_callback)
            return "done"

        t = rt.spawn(async_returns if on_loop else returns)
        assert rt.wait(t, timeout=5.0) == "done"
        assert not rt._root._children  # Private: its end ran in full
        assert [type(e) for e in reported] == [KeyboardInterrupt]

        async def later() -> str:
            return "loop runs"

        assert rt.wait(rt.spawn(later), timeout=5.0) == "loop runs"

    def test_ctrl_c_in_cancel_or_stop_reaches_the_caller_after_the_work(self):
        """On the main thread the interrupt is Ctrl-C: it reaches the caller,
        once the cancel is scheduled and the shutdown done."""
        rt = Runtime(MagicMock())
        rt.start()
        entered = threading.Event()

        async def parks() -> None:
            stopping()._on_stop(_interrupting_callback)
            entered.set()
            await asyncio.Event().wait()

        t = rt.spawn(parks)
        assert entered.wait(5.0)
        with pytest.raises(KeyboardInterrupt):
            rt.cancel(t)
        with pytest.raises(StoppedError):
            rt.wait(t, timeout=5.0)  # cancelled all the same

        parked = Parked()
        loop_task = rt.spawn(parked.run)
        assert parked.entered.wait(5.0)
        entered.clear()
        rt.spawn(parks)
        assert entered.wait(5.0)
        with pytest.raises(KeyboardInterrupt):
            rt.stop()
        assert parked.cancelled  # the loop's stop ran all the same
        assert not rt.alive(loop_task)


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

    def test_concurrent_spawns_get_distinct_ids_and_run_once_each(self, rt):
        """Spawns from many threads at once: one id per spawn, one call each."""
        calls: list[int] = []
        lock = threading.Lock()
        start = threading.Barrier(8)
        ids: list[list[int]] = [[] for _ in range(8)]

        def called(n: int) -> None:
            with lock:
                calls.append(n)

        def spawner(i: int) -> None:
            start.wait(5.0)
            for j in range(50):
                ids[i].append(rt.spawn(called, i * 50 + j))

        threads = [threading.Thread(target=spawner, args=(i,)) for i in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10.0)
        all_ids = [t for chunk in ids for t in chunk]
        for t in all_ids:
            rt.wait(t, timeout=5.0)
        assert len(set(all_ids)) == 400
        assert sorted(calls) == list(range(400))

    @pytest.mark.parametrize("on_loop", [True, False], ids=["loop", "thread"])
    def test_spawns_racing_stop_are_refused_or_ended(self, on_loop):
        """Every spawn either raises, or its task has ended once stop() returns:
        none slips past stop() and runs on."""
        rt = Runtime(MagicMock())
        rt.start()
        start = threading.Barrier(5)
        spawned: list[int] = []
        lock = threading.Lock()

        def spawner() -> None:
            start.wait(5.0)
            for _ in range(100):
                try:
                    t = rt.spawn(_park if on_loop else _waits_for_stop)
                except RuntimeError:
                    return  # refused: the runtime is stopping
                with lock:
                    spawned.append(t)

        threads = [threading.Thread(target=spawner) for _ in range(4)]
        for thread in threads:
            thread.start()
        start.wait(5.0)
        rt.stop(timeout=5.0)
        for thread in threads:
            thread.join(10.0)
        assert all(not rt.alive(t) for t in spawned)


class TestSpawnHooks:
    """spawn(token=, on_end=): for a layer that runs its own units as tasks,
    under its own tokens, and learns of their ends."""

    def test_a_task_spawned_with_a_token_derives_from_it(self, rt):
        """Not from the spawner's: it stops with the given token, and leaves
        that token's tree, not the runtime's, as it ends."""
        parent, fn = StopToken(), WaitsForStop()
        t = rt.spawn(fn, token=parent)
        assert fn.entered.wait(5.0)
        assert parent._children  # Private: the token's set of children
        assert not rt._root._children
        parent.stop()
        assert rt.wait(t, timeout=5.0).is_set()
        assert not parent._children

    def test_a_task_spawned_with_a_token_leaves_it_running(self, rt):
        parent = StopToken()
        rt.wait(rt.spawn(lambda: None, token=parent), timeout=5.0)
        assert not parent.is_set()

    @pytest.mark.parametrize("on_loop", [True, False], ids=["loop", "thread"])
    def test_a_task_spawned_with_a_stopped_token_never_runs(self, rt, on_loop):
        entered = threading.Event()

        async def async_marks() -> None:
            entered.set()

        def marks() -> None:
            entered.set()

        parent = StopToken()
        parent.stop()
        t = rt.spawn(async_marks if on_loop else marks, token=parent)
        with pytest.raises(StoppedError):
            rt.wait(t, timeout=5.0)
        assert not entered.is_set()

    def test_stop_ends_a_task_spawned_with_an_outside_token(self):
        fn = WaitsForStop()
        with Runtime(MagicMock()) as rt:
            t = rt.spawn(fn, token=StopToken())
            assert fn.entered.wait(5.0)
        assert rt.wait(t, timeout=0).is_set()

    @pytest.mark.parametrize("on_loop", [True, False], ids=["loop", "thread"])
    def test_its_end_is_sent_with_what_it_returned(self, rt, on_loop):
        async def async_returns() -> int:
            return 42

        ends = Chan[TaskEnd](1)
        t = rt.spawn(async_returns if on_loop else (lambda: 42), ends=ends)
        assert ends.recv(timeout=5.0) == TaskEnd(t, 42, None, False)

    @pytest.mark.parametrize("on_loop", [True, False], ids=["loop", "thread"])
    def test_its_end_is_sent_with_its_failure_which_is_not_logged(self, on_loop):
        lg, ends = MagicMock(), Chan[TaskEnd](1)
        with Runtime(lg) as rt:
            rt.spawn(_async_boom if on_loop else _boom, ends=ends)
            assert isinstance(ends.recv(timeout=5.0).exception, ValueError)
        lg.warning.assert_not_called()

    @pytest.mark.parametrize("on_loop", [True, False], ids=["loop", "thread"])
    def test_its_end_is_sent_with_its_stop(self, rt, on_loop):
        parked, entered = Parked(), threading.Event()

        def stops() -> None:
            entered.set()
            stopping().wait()
            raise StoppedError("stopped")

        ends = Chan[TaskEnd](1)
        t = rt.spawn(parked.run if on_loop else stops, ends=ends)
        assert (parked.entered if on_loop else entered).wait(5.0)
        rt.cancel(t)
        assert ends.recv(timeout=5.0) == TaskEnd(t, None, None, True)

    def test_a_task_with_ends_is_reaped_as_it_ends_not_waited_for(self, rt):
        fn, ends = WaitsForStop(), Chan[TaskEnd](1)
        t = rt.spawn(fn, ends=ends)
        with pytest.raises(RuntimeError, match="detached"):
            rt.wait(t)
        assert fn.entered.wait(5.0)
        rt.cancel(t)
        ends.recv(timeout=5.0)
        assert not _known(rt, t)  # reaped before its end is sent

    @pytest.mark.parametrize("on_loop", [True, False], ids=["loop", "thread"])
    def test_tasks_ending_on_a_full_channel_do_not_wait_for_room(self, rt, on_loop):
        """Their ends wait on the loop instead, and none is lost."""

        async def async_returns(i: int) -> int:
            return i

        ends = Chan[TaskEnd](1)
        ids = {
            rt.spawn(async_returns if on_loop else abs, i, ends=ends) for i in range(20)
        }
        # All ended and reaped with nobody receiving, on room for one end
        assert _wait_until(lambda: not any(_known(rt, t) for t in ids))
        received = [ends.recv(timeout=5.0) for _ in range(20)]
        assert {end.task_id for end in received} == ids
        assert sorted(end.result for end in received) == list(range(20))

    def test_an_end_on_a_closed_channel_is_dropped(self, reported):
        lg, ends = MagicMock(), Chan[TaskEnd](1)
        ends.close()
        with Runtime(lg) as rt:
            t = rt.spawn(_boom, ends=ends)
            assert _wait_until(lambda: not _known(rt, t))
        lg.warning.assert_not_called()
        assert not reported

    def test_an_end_waiting_for_room_is_dropped_as_the_channel_closes(self, rt):
        ends = Chan[TaskEnd](1)
        first, second = rt.spawn(abs, 1, ends=ends), rt.spawn(abs, 2, ends=ends)
        assert _wait_until(lambda: not _known(rt, first) and not _known(rt, second))
        assert _wait_until(lambda: len(rt._sending) == 1)  # Private: ends waiting
        ends.close()
        assert _wait_until(lambda: not rt._sending)
        assert ends.recv(timeout=5.0).task_id in (first, second)  # buffered
        with pytest.raises(ChanClosedError):
            ends.recv(timeout=5.0)

    def test_an_end_arrives_through_a_pipe(self, rt):
        send, recv = pipe(1)
        sender, chan = send.open(), recv.open()
        t = rt.spawn(abs, -3, ends=sender)
        assert chan.recv(timeout=5.0) == TaskEnd(t, 3, None, False)
        sender.close()

    def test_an_unpicklable_end_arrives_through_a_pipe_as_a_runtime_error(self, rt):
        send, recv = pipe(1)
        sender, chan = send.open(), recv.open()
        t = rt.spawn(threading.Lock, ends=sender)  # returns a lock
        end = chan.recv(timeout=5.0)
        assert (end.task_id, end.result, end.stopped) == (t, None, False)
        assert isinstance(end.exception, RuntimeError)
        assert "pickle" in str(end.exception)
        sender.close()

    def test_an_end_that_cannot_be_unpickled_arrives_as_a_runtime_error(self, rt):
        """It pickles, but the receiving side could not unpickle it, and would
        skip it: the end must still arrive, once per task."""
        send, recv = pipe(1)
        sender, chan = send.open(), recv.open()
        t = rt.spawn(_raises_undecodable, ends=sender)
        end = chan.recv(timeout=5.0)  # the timeout is the failure path
        assert (end.task_id, end.result, end.stopped) == (t, None, False)
        assert isinstance(end.exception, RuntimeError)
        assert "_Undecodable" in str(end.exception)
        sender.close()

    def test_stop_sends_the_end_of_each_task_it_ends(self):
        parked, waits = Parked(), WaitsForStop()
        ends = Chan[TaskEnd](2)
        with Runtime(MagicMock()) as rt:
            on_loop = rt.spawn(parked.run, ends=ends)
            on_thread = rt.spawn(waits, ends=ends)
            assert parked.entered.wait(5.0)
            assert waits.entered.wait(5.0)
        received = {end.task_id: end for end in (ends.recv(0), ends.recv(0))}
        assert received[on_loop] == TaskEnd(on_loop, None, None, True)
        assert received[on_thread].result.is_set()
        with pytest.raises(TimeoutError):  # one end each
            ends.recv(0)

    def test_a_refused_spawn_sends_no_end(self):
        ends = Chan[TaskEnd](1)
        with pytest.raises(RuntimeError, match="not running"):
            Runtime(MagicMock()).spawn(lambda: None, ends=ends)
        with pytest.raises(TimeoutError):
            ends.recv(0)


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
        fn = IgnoresItsToken()
        rt = Runtime(lg)
        rt.start()
        t = rt.spawn(fn)
        assert fn.entered.wait(5.0)
        try:
            rt.stop(timeout=0)
            lg.warning.assert_called_once()
            assert lg.warning.call_args.args[0] == "task did not end in time"
        finally:
            fn.release.set()
        assert rt.wait(t, timeout=5.0) is True

    def test_the_loop_gets_what_is_left_of_the_budget(self, monkeypatch):
        """Time stop() spends before the loop's stop counts against the one
        budget: the loop gets what is left, not the full timeout."""
        rt = Runtime(MagicMock())
        rt.start()
        rt.spawn(Parked().run)
        loop_timeouts: list[float] = []
        real_token_stop, real_host_stop = StopToken.stop, LoopHost.stop
        with FakeClock(modules=["appinfra.runtime.runtime"]) as clock:

            def slow_token_stop(token: StopToken) -> None:
                clock.sleep(0.4)  # stopping tokens takes time before the loop's stop
                real_token_stop(token)

            def recording_host_stop(host: LoopHost, timeout: float = 5.0) -> None:
                loop_timeouts.append(timeout)
                real_host_stop(host, 5.0)  # the real loop gets real time to end

            monkeypatch.setattr(StopToken, "stop", slow_token_stop)
            monkeypatch.setattr(LoopHost, "stop", recording_host_stop)
            try:
                rt.stop(timeout=1.0)
            finally:
                monkeypatch.undo()
        assert loop_timeouts and loop_timeouts[0] < 1.0

    def test_stop_shares_one_timeout_across_the_tasks_it_waits_for(self, monkeypatch):
        """Thread tasks that ignore their tokens get what is left of one budget,
        not the full timeout each; a loop task is not waited for again once the
        loop has stopped."""
        fns = [IgnoresItsToken() for _ in range(3)]
        rt = Runtime(MagicMock())
        rt.start()
        hung = [rt.spawn(fn) for fn in fns]
        assert all(fn.entered.wait(5.0) for fn in fns)
        rt.spawn(Parked().run)
        thread_waits: list[float | None] = []
        loop_waits: list[float | None] = []
        with FakeClock(modules=["appinfra.runtime.runtime"]) as clock:

            def thread_wait(task: ThreadTask, timeout: float | None = None) -> bool:
                thread_waits.append(timeout)
                clock.sleep(timeout or 0.0)
                return False  # still running: the budget is used up

            def loop_wait(task: LoopTask, timeout: float | None = None) -> bool:
                loop_waits.append(timeout)
                return True

            monkeypatch.setattr(ThreadTask, "wait", thread_wait)
            monkeypatch.setattr(LoopTask, "wait", loop_wait)
            try:
                rt.stop(timeout=1.0)
            finally:
                monkeypatch.undo()
                for fn in fns:
                    fn.release.set()
        assert thread_waits == [1.0, 0.0, 0.0]
        assert loop_waits == []
        for t in hung:
            rt.wait(t, timeout=5.0)

    def test_stop_reaches_a_task_spawned_from_another_runtime(self):
        """A task spawned by another runtime's task derives its token from that
        task, not from this runtime's root; stop() still stops it."""
        lg = MagicMock()
        rt_a, rt_b = Runtime(MagicMock()), Runtime(lg)
        rt_a.start()
        rt_b.start()
        onto_b: list[int] = []
        child = WaitsForStop()
        release = threading.Event()

        def spawns_onto_b() -> None:
            onto_b.append(rt_b.spawn(child))
            release.wait(10.0)  # stays alive, so its token is not stopped

        try:
            rt_a.spawn(spawns_onto_b)
            assert child.entered.wait(5.0)
            rt_b.stop(timeout=5.0)  # the deadline is the failure path
            lg.warning.assert_not_called()
            assert rt_b.wait(onto_b[0], timeout=0).is_set()
        finally:
            release.set()
            rt_a.stop()
            rt_b.stop()

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
