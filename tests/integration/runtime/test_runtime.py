# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for the Runtime and its tasks: on the loop, on threads, ids, and stop."""

import asyncio
import contextvars
import threading
import time
import traceback
from collections.abc import Callable, Iterator
from unittest.mock import MagicMock

import pytest

from appinfra.runtime import (
    Chan,
    ChanClosedError,
    Runtime,
    StoppedError,
    StopToken,
    Task,
    TaskDone,
    stopping,
    task_id,
)
from appinfra.runtime.chan import pipe
from appinfra.runtime.loop import LoopHost, _LoopTask
from appinfra.runtime.thread import _ThreadTask
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


class _UnformattableName(str):
    """A name that raises where it is formatted."""

    def __format__(self, spec: str) -> str:
        raise ValueError("cannot format")


class _PicklesOnce:
    """Pickles the first time only, as a result another thread is changing
    can: pickled again, it raises."""

    def __init__(self) -> None:
        self._pickled = 0

    def __reduce__(self) -> tuple[type, tuple[()]]:
        self._pickled += 1
        if self._pickled > 1:
            raise RuntimeError("changed while pickled")
        return _PicklesOnce, ()


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


def _tracked(rt: Runtime, t: Task) -> bool:
    """True while the runtime holds *t*, for its stop(): until it ends."""
    return t.id in rt._tasks  # Private: the tasks still running


def _hold_loop(rt: Runtime) -> threading.Event:
    """Block the runtime's loop until the returned event is set. Returns once
    the loop is blocked, so what is scheduled next runs in a later iteration,
    in the order scheduled."""
    held, release = threading.Event(), threading.Event()

    async def hold() -> None:
        held.set()
        release.wait(5.0)  # blocks the loop on purpose

    rt.spawn(hold).detach()
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
            t.cancel()
            with pytest.raises(StoppedError):
                t.wait(timeout=5.0)

    def test_it_runs_on_the_loop_thread_with_its_args(self, rt):
        """Every async task runs on the one loop thread, not the caller's."""

        async def where(x: int) -> tuple[threading.Thread, int]:
            return threading.current_thread(), x

        first, x = rt.spawn(where, 21).wait(timeout=5.0)
        second, _ = rt.spawn(where, 0).wait(timeout=5.0)
        assert x == 21
        assert first is second
        assert first is not threading.current_thread()

    def test_cancel_cancels_it_and_stops_its_token(self, rt):
        fn = Parked()
        t = rt.spawn(fn.run)
        assert fn.entered.wait(timeout=5.0)

        t.cancel()

        with pytest.raises(StoppedError):  # it produced no result
            t.wait(timeout=5.0)
        assert fn.cancelled
        assert fn.token is not None and fn.token.is_set()

    def test_a_failure_fails_that_task_only(self, rt):
        other = Parked()
        other_task_id = rt.spawn(other.run)
        assert other.entered.wait(timeout=5.0)

        with pytest.raises(ValueError, match="boom"):
            rt.spawn(_async_boom).wait(timeout=5.0)
        assert other_task_id.alive()

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
            rt.spawn(exits).wait(timeout=5.0)
        assert other_task_id.alive()
        # The loop runs on: a task spawned after it still runs
        later = Parked()
        rt.spawn(later.run)
        assert later.entered.wait(timeout=5.0)

    def test_cancel_right_after_spawn_ends_it(self, rt):
        """Whether or not the task has begun when the cancel lands, it ends."""
        for _ in range(20):
            t = rt.spawn(Parked().run)
            t.cancel()
            with pytest.raises(StoppedError):
                t.wait(timeout=5.0)

    def test_a_task_stopped_before_its_first_step_never_runs(self, rt):
        """A parent that returns right after spawning stops its token, and
        with it the child's, after the child's task is created but before its
        first step: the child is a stop, its function never called."""
        ran = threading.Event()

        async def child() -> None:
            ran.set()

        async def spawns_and_returns() -> Task:
            return rt.spawn(child)

        t = rt.spawn(spawns_and_returns).wait(timeout=5.0)
        with pytest.raises(StoppedError):
            t.wait(timeout=5.0)
        assert not ran.is_set()

    def test_a_task_cancelled_before_its_first_step_never_runs(self, rt):
        release = _hold_loop(rt)
        fn = Parked()
        try:
            t = rt.spawn(fn.run)  # its creation is queued behind the hold
            t.cancel()
        finally:
            release.set()
        with pytest.raises(StoppedError):
            t.wait(timeout=5.0)
        assert not fn.entered.is_set()

    def test_wait_on_the_loop_is_refused(self, rt):
        """Waiting on the loop thread would block every task on it."""
        target = rt.spawn(Parked().run)

        async def waits() -> None:
            target.wait(timeout=2.0)

        with pytest.raises(RuntimeError, match="block"):
            rt.spawn(waits).wait(timeout=5.0)

    def test_waiting_on_a_running_thread_task_on_the_loop_is_refused(self, rt):
        """Joining the thread would block every task on the loop."""
        release = threading.Event()
        target = rt.spawn(release.wait, 10.0)

        async def waits() -> None:
            target.wait(timeout=1.0)  # unrefused, it blocks the loop for 1 s

        try:
            with pytest.raises(RuntimeError, match="block"):
                rt.spawn(waits).wait(timeout=5.0)
        finally:
            release.set()
        assert target.wait(timeout=5.0) is True

    def test_an_ended_thread_task_is_collected_on_the_loop(self, rt):
        target = rt.spawn(lambda: 42)
        assert _wait_until(lambda: not target.alive())

        async def collects() -> int:
            return target.wait(timeout=0)

        assert rt.spawn(collects).wait(timeout=5.0) == 42

    def test_waits_that_time_out_leave_nothing_behind(self, rt):
        """Polling a long-running task must not grow it by one waiter per poll."""
        fn = Parked()
        t = rt.spawn(fn.run)
        assert fn.entered.wait(5.0)
        for _ in range(100):
            with pytest.raises(TimeoutError):
                t.wait(timeout=0)
        assert _wait_until(lambda: not t._t._waiters)  # Private: registered waits

    def test_a_task_ending_after_a_wait_gave_up_ends_on_its_own(self, rt):
        fn = HoldsCancel()
        t = rt.spawn(fn.run)
        assert fn.entered.wait(5.0)
        t.cancel()
        with pytest.raises(TimeoutError):
            t.wait(timeout=0)
        assert t.alive()

        fn.release.set()

        t.wait(timeout=5.0)


class TestThreadTask:
    """A function as a task on a thread of its own."""

    def test_it_runs_on_a_thread_of_its_own_with_its_args(self, rt):
        """Neither the caller's thread nor the loop's."""

        async def on_loop() -> threading.Thread:
            return threading.current_thread()

        def where(x: int) -> tuple[threading.Thread, int]:
            return threading.current_thread(), x

        loop_thread = rt.spawn(on_loop).wait(timeout=5.0)
        thread, x = rt.spawn(where, 21).wait(timeout=5.0)
        assert x == 21
        assert thread not in (threading.current_thread(), loop_thread)

    def test_its_thread_name_carries_its_id(self, rt):
        """A thread dump ties the thread to the task's log records."""
        t = rt.spawn(lambda: threading.current_thread().name)
        assert t.wait(timeout=5.0) == f"appinfra-task-{t.id}"

    def test_cancel_stops_its_token(self, rt):
        fn = WaitsForStop()
        t = rt.spawn(fn)
        assert fn.entered.wait(5.0)
        t.cancel()
        assert t.wait(timeout=5.0).is_set()

    def test_a_failure_comes_back_from_wait(self, rt):
        with pytest.raises(ValueError, match="boom"):
            rt.spawn(_boom).wait(timeout=5.0)

    def test_an_ended_task_is_collected_before_its_thread_finishes(
        self, rt, monkeypatch
    ):
        """Once the runtime has recorded the end, wait() collects the outcome,
        even while the task's thread has not yet run its last line."""
        in_window, release = threading.Event(), threading.Event()
        real_on_end = rt._end_hook  # Private: what every task reports its end to

        def on_end_then_hold(task: object) -> None:
            real_on_end(task)
            in_window.set()
            release.wait(10.0)  # holds the thread after the end is recorded

        monkeypatch.setattr(rt, "_end_hook", on_end_then_hold)
        t = rt.spawn(lambda: 42)
        try:
            assert in_window.wait(5.0)
            assert not t.alive()
            assert t.wait(timeout=0) == 42
        finally:
            release.set()

    def test_wait_gives_up_on_a_task_that_ignores_its_token(self, rt):
        fn = IgnoresItsToken()
        t = rt.spawn(fn)
        assert fn.entered.wait(5.0)
        t.cancel()
        try:
            with pytest.raises(TimeoutError):
                t.wait(timeout=0)
            assert t.alive()
        finally:
            fn.release.set()
        assert t.wait(timeout=5.0) is True

    def test_a_task_waiting_for_itself_is_refused(self, rt):
        me: list[Task] = []
        spawned = threading.Event()

        def waits_for_itself() -> None:
            assert spawned.wait(5.0)
            me[0].wait(timeout=1.0)

        me.append(rt.spawn(waits_for_itself))
        spawned.set()
        with pytest.raises(RuntimeError, match="itself"):
            me[0].wait(timeout=5.0)

    @pytest.mark.parametrize("on_loop", [True, False], ids=["loop", "thread"])
    def test_a_worker_in_the_tasks_context_waiting_for_it_is_refused(self, rt, on_loop):
        """asyncio.to_thread() copies the task's context to a thread that is
        neither the loop's nor the task's own: the task would wait for the
        worker waiting for it."""
        me: list[Task] = []
        spawned = threading.Event()

        async def awaits_a_worker() -> None:
            assert spawned.wait(5.0)
            await asyncio.to_thread(me[0].wait, 5.0)  # the timeout is the failure path

        def runs_a_loop() -> None:
            asyncio.run(awaits_a_worker())

        me.append(rt.spawn(awaits_a_worker if on_loop else runs_a_loop))
        spawned.set()
        with pytest.raises(RuntimeError, match="itself"):
            me[0].wait(timeout=10.0)


class TestTaskIds:
    def test_task_ids_count_up_and_are_never_reused(self, rt):
        first = rt.spawn(lambda: None)
        first.wait(timeout=5.0)
        second = rt.spawn(lambda: None)
        assert second.id > first.id
        second.wait(timeout=5.0)

    @pytest.mark.parametrize("on_loop", [True, False], ids=["loop", "thread"])
    def test_a_task_knows_its_own_task_id(self, rt, on_loop):
        async def mine_async() -> int:
            return task_id()

        def mine() -> int:
            return task_id()

        t = rt.spawn(mine_async if on_loop else mine)
        assert t.wait(timeout=5.0) == t.id

    def test_tid_and_stopping_outside_a_task_are_refused(self):
        with pytest.raises(RuntimeError, match="outside a task"):
            task_id()
        with pytest.raises(RuntimeError, match="outside a task"):
            stopping()


class TestHandle:
    """What spawn() returns is the API, and only that."""

    def test_its_public_surface_is_the_api(self):
        public = {name for name in dir(Task) if not name.startswith("_")}
        assert public == {"id", "name", "wait", "cancel", "alive", "detach"}

    def test_it_holds_nothing_but_the_task(self, rt):
        t = rt.spawn(lambda: None)
        with pytest.raises(AttributeError):
            t.id = 7  # type: ignore[misc]
        with pytest.raises(AttributeError):
            t.extra = 1  # type: ignore[attr-defined]
        t.wait(timeout=5.0)

    def test_it_reads_as_its_id_and_state(self, rt):
        release = threading.Event()
        t = rt.spawn(release.wait, 5.0)
        assert repr(t) == f"<Task {t.id} running>"
        release.set()
        t.wait(timeout=5.0)
        assert repr(t) == f"<Task {t.id} ended>"


class TestNames:
    """spawn(name=): who a task is, wherever it shows."""

    @pytest.mark.parametrize("on_loop", [True, False], ids=["loop", "thread"])
    def test_a_named_task_carries_its_name(self, rt, on_loop):
        """On the handle, its thread or asyncio task, and its repr."""

        async def async_mine() -> str:
            task = asyncio.current_task()
            assert task is not None
            return task.get_name()

        def mine() -> str:
            return threading.current_thread().name

        t = rt.spawn(async_mine if on_loop else mine, name="db")
        assert t.name == "db"
        assert t.wait(timeout=5.0) == f"appinfra-task-{t.id}-db"
        assert repr(t) == f"<Task {t.id} db ended>"

    def test_an_unnamed_task_has_no_name(self, rt):
        t = rt.spawn(lambda: None)
        assert t.name is None
        t.wait(timeout=5.0)

    def test_its_end_carries_its_name(self, rt):
        done = Chan[TaskDone](1)
        t = rt.spawn(abs, -1, name="db", done=done)
        assert done.recv(timeout=5.0) == TaskDone(t.id, "db", 1, None)

    def test_a_detached_failure_is_logged_with_its_name(self):
        lg = MagicMock()
        with Runtime(lg) as rt:
            rt.spawn(_boom, name="db").detach()
            assert _wait_until(lambda: lg.warning.called)
        assert lg.warning.call_args.kwargs["extra"]["task_name"] == "db"

    def test_a_name_of_a_str_subclass_is_taken_as_a_plain_str(self, rt):
        """Formatted on the loop for the asyncio task's name, a subclass that
        raised there would leave a task that never ends."""

        async def returns() -> int:
            return 42

        t = rt.spawn(returns, name=_UnformattableName("db"))
        assert type(t.name) is str
        assert t.name == "db"
        assert t.wait(timeout=5.0) == 42  # the timeout is the failure path

    def test_a_name_that_is_not_a_string_is_refused(self, rt):
        """It travels to whoever receives the end, also through a pipe."""
        with pytest.raises(TypeError, match="name"):
            rt.spawn(abs, 1, name=7)
        assert not rt._root._children  # Private: no token left behind


_VAR: contextvars.ContextVar[str] = contextvars.ContextVar("_VAR", default="unset")


class TestContext:
    """A task runs in a copy of the spawner's contextvars, as asyncio's
    create_task() and to_thread() do."""

    @pytest.mark.parametrize("on_loop", [True, False], ids=["loop", "thread"])
    def test_a_task_sees_the_spawners_values_and_keeps_its_own(self, rt, on_loop):
        async def async_reads() -> str:
            seen = _VAR.get()
            _VAR.set("task")
            return seen

        def reads() -> str:
            seen = _VAR.get()
            _VAR.set("task")
            return seen

        reset = _VAR.set("spawner")
        try:
            assert rt.spawn(async_reads if on_loop else reads).wait(5.0) == "spawner"
            assert _VAR.get() == "spawner"  # the task's set stays its own
        finally:
            _VAR.reset(reset)


class TestOutcomes:
    def test_the_runtime_forgets_a_task_as_it_ends(self, rt):
        release = threading.Event()
        t = rt.spawn(release.wait, 5.0)
        assert _tracked(rt, t)
        release.set()
        assert _wait_until(lambda: not _tracked(rt, t))

    def test_every_wait_gets_the_result(self, rt):
        t = rt.spawn(lambda: 42)
        assert t.wait(timeout=5.0) == 42
        assert t.wait(timeout=0) == 42

    def test_every_wait_raises_the_failure(self, rt):
        t = rt.spawn(_boom)
        with pytest.raises(ValueError) as first:
            t.wait(timeout=5.0)
        with pytest.raises(ValueError) as second:
            t.wait(timeout=0)
        assert second.value is first.value

    def test_every_wait_raises_it_from_the_tasks_own_traceback(self, rt):
        """Raised again as is, the stored exception would collect every
        wait's frames, and keep their locals alive."""
        t = rt.spawn(_boom)
        depths = []
        for _ in range(3):
            with pytest.raises(ValueError) as caught:
                t.wait(timeout=5.0)
            depths.append(len(traceback.extract_tb(caught.value.__traceback__)))
        assert depths[0] == depths[1] == depths[2]

    @pytest.mark.parametrize("on_loop", [True, False], ids=["loop", "thread"])
    def test_a_stop_iteration_is_one_runtime_error_however_waited_for(
        self, rt, on_loop
    ):
        """A coroutine turns StopIteration into RuntimeError (PEP 479), and
        asyncio refuses it in a Future: from either kind of task, wait() and
        await raise the same RuntimeError, caused by it."""

        async def async_raises() -> None:
            raise StopIteration

        def raises() -> None:
            raise StopIteration

        t = rt.spawn(async_raises if on_loop else raises)
        with pytest.raises(RuntimeError, match="StopIteration") as waited:
            t.wait(timeout=5.0)

        async def awaits() -> None:
            await asyncio.wait_for(t, 5.0)

        with pytest.raises(RuntimeError, match="StopIteration") as awaited:
            asyncio.run(awaits())
        assert awaited.value is waited.value
        assert isinstance(waited.value.__cause__, StopIteration)

    def test_detaching_an_ended_task_logs_its_failure_once(self):
        lg = MagicMock()
        with Runtime(lg) as rt:
            t = rt.spawn(_boom)
            assert _wait_until(lambda: not t.alive())
            lg.warning.assert_not_called()  # not detached as it ended
            t.detach()
            t.detach()
        lg.warning.assert_called_once()

    def test_wait_on_a_detached_task_is_refused(self, rt):
        t = rt.spawn(_waits_for_stop)
        t.detach()
        with pytest.raises(RuntimeError, match="detached"):
            t.wait()
        t.cancel()

    def test_a_detached_failure_is_logged(self):
        lg = MagicMock()
        with Runtime(lg) as rt:
            rt.spawn(_boom).detach()
            assert _wait_until(lambda: lg.warning.called)
        lg.warning.assert_called_once()
        args, kwargs = lg.warning.call_args
        assert args[0] == "task failed"
        assert isinstance(kwargs["extra"]["exception"], ValueError)

    def test_a_failure_collected_by_wait_is_not_logged(self):
        lg = MagicMock()
        with Runtime(lg) as rt, pytest.raises(ValueError):
            rt.spawn(_boom).wait(timeout=5.0)
        lg.warning.assert_not_called()

    def test_outcomes_stay_to_be_waited_for_after_stop(self):
        fn = WaitsForStop()
        with Runtime(MagicMock()) as rt:
            done = rt.spawn(lambda: 42)
            stopped = rt.spawn(fn)
            assert fn.entered.wait(5.0)
            assert _wait_until(lambda: not done.alive())
        assert done.wait(timeout=0) == 42
        assert stopped.wait(timeout=0).is_set()


class TestTokens:
    @pytest.mark.parametrize("on_loop", [True, False], ids=["loop", "thread"])
    def test_a_task_spawned_by_a_task_derives_from_its_token(self, rt, on_loop):
        """Cancelling a task stops every task it spawned."""
        children: list[Task] = []
        child, spawned = WaitsForStop(), threading.Event()

        async def async_parent() -> None:
            children.append(rt.spawn(child))
            spawned.set()
            await asyncio.Event().wait()

        def parent() -> None:
            children.append(rt.spawn(child))
            spawned.set()
            stopping().wait()

        t = rt.spawn(async_parent if on_loop else parent)
        # The child can enter before spawn() returns to the parent: both
        assert spawned.wait(5.0)
        assert child.entered.wait(5.0)

        t.cancel()

        assert children[0].wait(timeout=5.0).is_set()

    def test_an_ended_task_leaves_the_token_tree(self, rt):
        """A runtime running many short tasks keeps no token for each one."""

        async def on_loop() -> None:
            pass

        task_ids = [rt.spawn(on_loop) for _ in range(10)]
        task_ids += [rt.spawn(lambda: None) for _ in range(10)]
        for t in task_ids:
            t.wait(timeout=5.0)
        assert not rt._root._children  # Private: the root's set of children

    @pytest.mark.parametrize("on_loop", [True, False], ids=["loop", "thread"])
    def test_a_task_that_ends_on_its_own_stops_its_token(self, rt, on_loop):
        """Work the task derived from its token is told to stop once it ends."""

        async def async_returns() -> StopToken:
            return stopping().child()

        def returns() -> StopToken:
            return stopping().child()

        derived = rt.spawn(async_returns if on_loop else returns).wait(timeout=5.0)
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

        def parent() -> Task:
            stopping().stop()  # the parent's token: the child derives from it
            return rt.spawn(async_marks if on_loop else marks)

        child = rt.spawn(parent).wait(timeout=5.0)
        with pytest.raises(StoppedError):  # it produced no result
            child.wait(timeout=5.0)
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
        t.cancel()
        assert t.wait(timeout=5.0) == "done"

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
            rt.spawn(async_raises if on_loop else raises).wait(timeout=5.0)
        assert caught.value is error

    def test_a_cancelled_error_raised_without_a_stop_is_a_failure(self, rt):
        """On the loop, CancelledError is a stop only when the task's token is
        stopped: one the function raises on its own is its failure."""

        async def raises() -> None:
            raise asyncio.CancelledError()

        with pytest.raises(asyncio.CancelledError):
            rt.spawn(raises).wait(timeout=5.0)

    def test_a_cancelled_error_raised_before_a_stop_stays_a_failure(self, rt):
        """A stop that lands after the function raised, before its end is
        recorded, does not turn the failure into a stop."""

        async def raises_then_is_stopped() -> None:
            # Runs before the task's end is recorded: asyncio schedules that
            # after the raise, behind this
            asyncio.get_running_loop().call_soon(stopping().stop)
            raise asyncio.CancelledError()

        with pytest.raises(asyncio.CancelledError):
            rt.spawn(raises_then_is_stopped).wait(timeout=5.0)

    def test_a_detached_task_failing_with_a_stopped_error_is_logged(self):
        lg = MagicMock()
        with Runtime(lg) as rt:
            rt.spawn(_raises_stopped_error).detach()
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
        assert t.wait(timeout=5.0) == "done"
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
        t.cancel()
        with pytest.raises(StoppedError):
            t.wait(timeout=5.0)
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
        assert not loop_task.alive()
        assert not thread_task.alive()  # waited for
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
        assert t.wait(timeout=5.0) == "done"
        assert not rt._root._children  # Private: its end ran in full
        assert [type(e) for e in reported] == [KeyboardInterrupt]

        async def later() -> str:
            return "loop runs"

        assert rt.spawn(later).wait(timeout=5.0) == "loop runs"

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
            t.cancel()
        with pytest.raises(StoppedError):
            t.wait(timeout=5.0)  # cancelled all the same

        parked = Parked()
        loop_task = rt.spawn(parked.run)
        assert parked.entered.wait(5.0)
        entered.clear()
        rt.spawn(parks)
        assert entered.wait(5.0)
        with pytest.raises(KeyboardInterrupt):
            rt.stop()
        assert parked.cancelled  # the loop's stop ran all the same
        assert not loop_task.alive()


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
        spawned: list[list[Task]] = [[] for _ in range(8)]

        def called(n: int) -> None:
            with lock:
                calls.append(n)

        def spawner(i: int) -> None:
            start.wait(5.0)
            for j in range(50):
                spawned[i].append(rt.spawn(called, i * 50 + j))

        threads = [threading.Thread(target=spawner, args=(i,)) for i in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10.0)
        tasks = [t for chunk in spawned for t in chunk]
        for t in tasks:
            t.wait(timeout=5.0)
        assert len({t.id for t in tasks}) == 400
        assert sorted(calls) == list(range(400))

    @pytest.mark.parametrize("on_loop", [True, False], ids=["loop", "thread"])
    def test_spawns_racing_stop_are_refused_or_ended(self, on_loop):
        """Every spawn either raises, or its task has ended once stop() returns:
        none slips past stop() and runs on."""
        rt = Runtime(MagicMock())
        rt.start()
        start = threading.Barrier(5)
        spawned: list[Task] = []
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
        assert all(not t.alive() for t in spawned)


class TestSpawnHooks:
    """spawn(token=, done=): for a layer that runs its own units as tasks,
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
        assert t.wait(timeout=5.0).is_set()
        assert not parent._children

    def test_a_task_spawned_with_a_token_leaves_it_running(self, rt):
        parent = StopToken()
        rt.spawn(lambda: None, token=parent).wait(timeout=5.0)
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
            t.wait(timeout=5.0)
        assert not entered.is_set()

    def test_stop_ends_a_task_spawned_with_an_outside_token(self):
        fn = WaitsForStop()
        with Runtime(MagicMock()) as rt:
            t = rt.spawn(fn, token=StopToken())
            assert fn.entered.wait(5.0)
        assert t.wait(timeout=0).is_set()

    @pytest.mark.parametrize("on_loop", [True, False], ids=["loop", "thread"])
    def test_its_end_is_sent_with_what_it_returned(self, rt, on_loop):
        async def async_returns() -> int:
            return 42

        done = Chan[TaskDone](1)
        t = rt.spawn(async_returns if on_loop else (lambda: 42), done=done)
        assert done.recv(timeout=5.0) == TaskDone(t.id, None, 42, None)

    @pytest.mark.parametrize("on_loop", [True, False], ids=["loop", "thread"])
    def test_its_end_is_sent_with_its_failure_which_is_not_logged(self, on_loop):
        lg, done = MagicMock(), Chan[TaskDone](1)
        with Runtime(lg) as rt:
            rt.spawn(_async_boom if on_loop else _boom, done=done)
            assert isinstance(done.recv(timeout=5.0).error, ValueError)
        lg.warning.assert_not_called()

    @pytest.mark.parametrize("on_loop", [True, False], ids=["loop", "thread"])
    def test_its_end_is_sent_with_its_stop_as_a_stopped_error(self, rt, on_loop):
        """As wait() raises it: a stop is an error, as Go's ctx.Err() is."""
        parked, entered = Parked(), threading.Event()

        def stops() -> None:
            entered.set()
            stopping().wait()
            raise StoppedError("stopped")

        done = Chan[TaskDone](1)
        t = rt.spawn(parked.run if on_loop else stops, done=done)
        assert (parked.entered if on_loop else entered).wait(5.0)
        t.cancel()
        end = done.recv(timeout=5.0)
        assert (end.task_id, end.result) == (t.id, None)
        assert isinstance(end.error, StoppedError)

    def test_a_task_with_done_is_forgotten_as_it_ends_not_waited_for(self, rt):
        fn, done = WaitsForStop(), Chan[TaskDone](1)
        t = rt.spawn(fn, done=done)
        with pytest.raises(RuntimeError, match="detached"):
            t.wait()
        assert fn.entered.wait(5.0)
        t.cancel()
        done.recv(timeout=5.0)
        assert not _tracked(rt, t)  # forgotten before its end is sent

    @pytest.mark.parametrize("on_loop", [True, False], ids=["loop", "thread"])
    def test_tasks_ending_on_a_full_channel_do_not_wait_for_room(self, rt, on_loop):
        """Their ends wait on the loop instead, and none is lost."""

        async def async_returns(i: int) -> int:
            return i

        done = Chan[TaskDone](1)
        tasks = [
            rt.spawn(async_returns if on_loop else abs, i, done=done) for i in range(20)
        ]
        # All ended with nobody receiving, on room for one end
        assert _wait_until(lambda: not any(t.alive() for t in tasks))
        received = [done.recv(timeout=5.0) for _ in range(20)]
        assert {end.task_id for end in received} == {t.id for t in tasks}
        assert sorted(end.result for end in received) == list(range(20))

    def test_an_end_on_a_closed_channel_is_dropped(self, reported):
        lg, done = MagicMock(), Chan[TaskDone](1)
        done.close()
        with Runtime(lg) as rt:
            t = rt.spawn(_boom, done=done)
            assert _wait_until(lambda: not t.alive())
        lg.warning.assert_not_called()
        assert not reported

    def test_an_end_waiting_for_room_is_dropped_as_the_channel_closes(self, rt):
        done = Chan[TaskDone](1)
        first, second = rt.spawn(abs, 1, done=done), rt.spawn(abs, 2, done=done)
        assert _wait_until(lambda: not first.alive() and not second.alive())
        assert _wait_until(lambda: len(rt._sending) == 1)  # Private: ends waiting
        done.close()
        assert _wait_until(lambda: not rt._sending)
        assert done.recv(timeout=5.0).task_id in (first.id, second.id)  # buffered
        with pytest.raises(ChanClosedError):
            done.recv(timeout=5.0)

    def test_an_end_arrives_through_a_pipe(self, rt):
        send, recv = pipe(1)
        sender, chan = send.open(), recv.open()
        t = rt.spawn(abs, -3, done=sender)
        assert chan.recv(timeout=5.0) == TaskDone(t.id, None, 3, None)
        sender.close()

    def test_an_unpicklable_end_arrives_through_a_pipe_as_a_runtime_error(self, rt):
        send, recv = pipe(1)
        sender, chan = send.open(), recv.open()
        t = rt.spawn(threading.Lock, done=sender)  # returns a lock
        end = chan.recv(timeout=5.0)
        assert (end.task_id, end.result) == (t.id, None)
        assert isinstance(end.error, RuntimeError)
        assert "pickle" in str(end.error)
        sender.close()

    def test_an_end_that_cannot_be_unpickled_arrives_as_a_runtime_error(self, rt):
        """It pickles, but the receiving side could not unpickle it, and would
        skip it: the end must still arrive, once per task."""
        send, recv = pipe(1)
        sender, chan = send.open(), recv.open()
        t = rt.spawn(_raises_undecodable, done=sender)
        end = chan.recv(timeout=5.0)  # the timeout is the failure path
        assert (end.task_id, end.result) == (t.id, None)
        assert isinstance(end.error, RuntimeError)
        assert "_Undecodable" in str(end.error)
        sender.close()

    @pytest.mark.parametrize("full", [False, True], ids=["at-once", "once-room"])
    def test_an_end_is_sent_as_the_bytes_that_were_checked(self, rt, full):
        """Pickled again, a result another thread changes meanwhile can fail
        where the check passed, and the end would be lost. A full pipe sends
        it from the loop, later."""
        send, recv = pipe(1)
        sender, chan = send.open(), recv.open()
        # The reader holds the first, the writer the second, the buffer the third
        sent = list(range(3)) if full else []
        for value in sent:
            sender.send(value, timeout=5.0)
        t = rt.spawn(_PicklesOnce, done=sender)
        # Its end sent, or deferred, before anything is received: a receive
        # first would make room, and the end go at once
        assert _wait_until(lambda: not t._t.is_running())  # Private: end sent
        if full:  # Private: the end waits on the loop
            assert _wait_until(lambda: len(rt._sending) == 1)
        else:
            assert not rt._sending
        assert [chan.recv(timeout=5.0) for _ in sent] == sent
        end = chan.recv(timeout=5.0)  # the timeout is the failure path
        assert (end.task_id, end.error) == (t.id, None)
        assert isinstance(end.result, _PicklesOnce)
        sender.close()

    def test_an_end_waiting_for_room_is_refused_once_the_loop_is_stopping(
        self, monkeypatch
    ):
        """Scheduled past the host's gate, its send would start after the loop
        took the tasks to cancel, and outlive the loop. The loop is held, so
        stop() is under way when the task ends; the send is never scheduled."""
        sends: list[tuple] = []
        monkeypatch.setattr(Runtime, "_send_later", lambda _, *a: sends.append(a))
        rt, done, finish = Runtime(MagicMock()), Chan[TaskDone](1), threading.Event()
        rt.start()
        done.send(TaskDone(0, None, None, None))  # full
        t = rt.spawn(finish.wait, 10.0, done=done)  # ends when told, not on stop
        release = _hold_loop(rt)
        stopper = threading.Thread(target=rt.stop)
        stopper.start()
        try:
            assert _wait_until(lambda: rt._host._closing)  # Private: stop() begun
            finish.set()
            assert _wait_until(lambda: not t._t.is_running())  # Private: its end sent
        finally:
            release.set()
            stopper.join(10.0)
        assert sends == []

    def test_stop_sends_the_end_of_each_task_it_ends(self):
        parked, waits = Parked(), WaitsForStop()
        done = Chan[TaskDone](2)
        with Runtime(MagicMock()) as rt:
            on_loop = rt.spawn(parked.run, done=done)
            on_thread = rt.spawn(waits, done=done)
            assert parked.entered.wait(5.0)
            assert waits.entered.wait(5.0)
        received = {end.task_id: end for end in (done.recv(0), done.recv(0))}
        assert isinstance(received[on_loop.id].error, StoppedError)
        assert received[on_thread.id].result.is_set()
        with pytest.raises(TimeoutError):  # one end each
            done.recv(0)

    def test_a_refused_spawn_sends_no_end(self):
        done = Chan[TaskDone](1)
        with pytest.raises(RuntimeError, match="not running"):
            Runtime(MagicMock()).spawn(lambda: None, done=done)
        with pytest.raises(TimeoutError):
            done.recv(0)


class TestAwait:
    """``await task``: wait() for a coroutine, on the runtime's loop or another."""

    @pytest.mark.parametrize("on_loop", [True, False], ids=["loop", "thread"])
    def test_a_loop_task_awaits_a_task(self, rt, on_loop):
        async def async_returns(n: int) -> int:
            return abs(n)

        async def parent() -> int:
            return await rt.spawn(async_returns if on_loop else abs, -42)

        assert rt.spawn(parent).wait(timeout=5.0) == 42

    @pytest.mark.asyncio
    async def test_a_coroutine_on_another_loop_awaits_a_task(self, rt):
        t = rt.spawn(abs, -42)
        assert await asyncio.wait_for(t, 5.0) == 42
        assert await t == 42  # as often as wanted

    @pytest.mark.asyncio
    async def test_it_raises_what_the_task_raised(self, rt):
        with pytest.raises(ValueError, match="boom"):
            await asyncio.wait_for(rt.spawn(_boom), 5.0)

    @pytest.mark.asyncio
    async def test_it_raises_stopped_error_for_a_stopped_task(self, rt):
        parked = Parked()
        t = rt.spawn(parked.run)
        assert parked.entered.wait(5.0)
        t.cancel()
        with pytest.raises(StoppedError):
            await asyncio.wait_for(t, 5.0)

    @pytest.mark.asyncio
    async def test_a_cancelled_await_leaves_the_task_and_no_wake(self, rt):
        """A timeout on the await, from asyncio.wait_for() or asyncio.timeout(),
        is such a cancel."""
        fn = WaitsForStop()
        t = rt.spawn(fn)
        # Entered: a cancel before would skip the call, and wait() would
        # raise StoppedError rather than return the token
        assert fn.entered.wait(5.0)
        awaiting = asyncio.ensure_future(t)
        for _ in range(3):
            await asyncio.sleep(0)  # the await is waiting by now
        assert t._t.wakes  # Private: the wakes of the awaits waiting
        awaiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await awaiting
        assert not t._t.wakes
        t.cancel()
        assert t.wait(timeout=5.0).is_set()

    @pytest.mark.asyncio
    async def test_two_awaits_both_get_the_result(self, rt):
        release = threading.Event()
        t = rt.spawn(release.wait, 5.0)

        async def awaits() -> bool:
            return await t

        # Two coroutines: gather() awaits a repeated argument only once
        both = asyncio.gather(awaits(), awaits())
        await asyncio.sleep(0)  # both are waiting by now
        assert len(t._t.wakes or ()) == 2  # Private: one wake per await
        release.set()
        assert await asyncio.wait_for(both, 5.0) == [True, True]

    @pytest.mark.asyncio
    async def test_awaiting_a_detached_task_is_refused(self, rt):
        t = rt.spawn(_waits_for_stop)
        t.detach()
        with pytest.raises(RuntimeError, match="detached"):
            await t
        t.cancel()

    @pytest.mark.parametrize("on_loop", [True, False], ids=["loop", "thread"])
    def test_a_task_awaiting_itself_is_refused(self, rt, on_loop):
        """It would wait for its own end forever; a thread task awaits on a
        loop of its own."""
        me: list[Task] = []
        spawned = threading.Event()

        async def awaits_itself() -> None:
            assert spawned.wait(5.0)
            await asyncio.wait_for(me[0], 5.0)  # the timeout is the failure path

        def runs_a_loop() -> None:
            asyncio.run(awaits_itself())

        me.append(rt.spawn(awaits_itself if on_loop else runs_a_loop))
        spawned.set()
        with pytest.raises(RuntimeError, match="itself"):
            me[0].wait(timeout=10.0)


class TestStop:
    def test_stop_ends_the_tasks_still_running(self):
        fn = Parked()
        with Runtime(MagicMock()) as rt:
            on_loop = rt.spawn(fn.run)
            on_thread = rt.spawn(_waits_for_stop)
            assert fn.entered.wait(timeout=5.0)

        assert fn.cancelled
        assert not on_loop.alive()
        assert not on_thread.alive()

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
            assert not t.alive()
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
            assert not t.alive()
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
        assert not t.alive()

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
        assert t.wait(timeout=5.0) is True

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

            def thread_join(task: _ThreadTask, timeout: float | None = None) -> bool:
                thread_waits.append(timeout)
                clock.sleep(timeout or 0.0)
                return False  # still running: the budget is used up

            def loop_join(task: _LoopTask, timeout: float | None = None) -> bool:
                loop_waits.append(timeout)
                return True

            monkeypatch.setattr(_ThreadTask, "join", thread_join)
            monkeypatch.setattr(_LoopTask, "join", loop_join)
            try:
                rt.stop(timeout=1.0)
            finally:
                monkeypatch.undo()
                for fn in fns:
                    fn.release.set()
        assert thread_waits == [1.0, 0.0, 0.0]
        assert loop_waits == []
        for t in hung:
            t.wait(timeout=5.0)

    def test_stop_reaches_a_task_spawned_from_another_runtime(self):
        """A task spawned by another runtime's task derives its token from that
        task, not from this runtime's root; stop() still stops it."""
        lg = MagicMock()
        rt_a, rt_b = Runtime(MagicMock()), Runtime(lg)
        rt_a.start()
        rt_b.start()
        onto_b: list[Task] = []
        child, spawned = WaitsForStop(), threading.Event()
        release = threading.Event()

        def spawns_onto_b() -> None:
            onto_b.append(rt_b.spawn(child))
            spawned.set()
            release.wait(10.0)  # stays alive, so its token is not stopped

        try:
            rt_a.spawn(spawns_onto_b)
            # The child can enter before spawn() returns to its spawner: both
            assert spawned.wait(5.0)
            assert child.entered.wait(5.0)
            rt_b.stop(timeout=5.0)  # the deadline is the failure path
            lg.warning.assert_not_called()
            assert onto_b[0].wait(timeout=0).is_set()
        finally:
            release.set()
            rt_a.stop()
            rt_b.stop()

    def test_stop_on_the_loop_thread_is_refused(self, rt):
        async def stops() -> None:
            rt.stop()

        with pytest.raises(RuntimeError, match="loop thread"):
            rt.spawn(stops).wait(timeout=5.0)

    def test_a_task_stopping_the_runtime_does_not_wait_for_itself(self):
        rt = Runtime(MagicMock())
        rt.start()
        t = rt.spawn(rt.stop, 5.0)
        assert t.wait(timeout=10.0) is None
        assert rt._closing  # Private: the runtime stopped


def _exits() -> None:
    """A callback on the loop that raises SystemExit, as a task's step does
    once the task raises it: asyncio re-raises it out of the loop."""
    raise SystemExit()


class _CleansUpSlowly:
    """Parks; once cancelled, takes a few iterations of the loop to clean up."""

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.cleaned = threading.Event()
        # Held here: the task parked on it is then reachable from the test.
        # Else the task, its waiter and this event form a cycle nothing
        # holds, which the garbage collector destroys while still pending
        self.parked: asyncio.Event | None = None

    async def run(self) -> None:
        self.parked = asyncio.Event()
        self.entered.set()
        try:
            await self.parked.wait()
        except asyncio.CancelledError:
            for _ in range(3):
                await asyncio.sleep(0)
            self.cleaned.set()
            raise


def _hold_host(host: LoopHost) -> threading.Event:
    """Block the host's loop until the returned event is set. Returns once the
    loop is blocked, so what is scheduled next runs in one iteration, in the
    order scheduled."""
    held, release = threading.Event(), threading.Event()

    def hold() -> None:
        held.set()
        release.wait(5.0)  # blocks the loop on purpose

    host.loop.call_soon_threadsafe(hold)
    assert held.wait(5.0)
    return release


def _stop_queued(host: LoopHost) -> threading.Thread:
    """Start host.stop() on a thread of its own; returns once its stop of the
    loop is queued."""
    stopping = threading.Thread(target=host.stop, args=(5.0,))
    stopping.start()
    assert _wait_until(lambda: host._closing)  # Private: stop() begun
    with host._lock:  # Private: stop() queues the loop's stop under it
        pass
    return stopping


class TestLoopHostStop:
    def test_an_exit_just_before_a_stop_still_lets_the_tasks_finish(self):
        """An exit leaves the loop's run with its stop still queued: that stop
        must not end the run that waits for the cancelled tasks to finish."""
        host = LoopHost()
        host.start()
        slow = _CleansUpSlowly()
        asyncio.run_coroutine_threadsafe(slow.run(), host.loop)
        assert slow.entered.wait(5.0)
        release = _hold_host(host)
        try:
            host.loop.call_soon_threadsafe(_exits)
            stopping = _stop_queued(host)
        finally:
            release.set()
        stopping.join(10.0)  # the deadline is the failure path
        assert slow.cleaned.is_set()
        assert host._thread is None  # Private: stop() saw the thread end

    def test_a_stop_run_just_before_an_exit_still_ends_the_loop(self):
        """The loop's stop and an exit in one iteration: the exit leaves
        run_forever(), which forgets the stop on its way out. The loop must
        not be resumed as if no stop had been asked for: no second one comes."""
        host = LoopHost()
        host.start()
        release = _hold_host(host)
        try:
            stopping = _stop_queued(host)
            # Behind the stop, in the same iteration once the hold returns
            host._loop.call_soon_threadsafe(_exits)  # Private: closing refuses
        finally:
            release.set()
        stopping.join(10.0)  # the deadline is the failure path
        assert host._thread is None  # Private: stop() saw the thread end
