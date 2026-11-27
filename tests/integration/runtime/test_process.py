# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for tasks spawned with process=True: a call in a child process."""

from __future__ import annotations

import multiprocessing as mp
import os
import pickle
import signal
import sys
import threading
import types
from collections.abc import Iterator
from multiprocessing.context import SpawnProcess
from typing import Any
from unittest.mock import MagicMock

import pytest

from appinfra.runtime import (
    Chan,
    ProcessDetail,
    ProcessExitError,
    Runtime,
    StoppedError,
    StopToken,
    TaskDone,
    TaskKind,
    pipe,
    stopping,
    task_id,
)
from appinfra.runtime import process as process_module
from appinfra.runtime.process import _stop_on_signal

# The child imports these by name: module level, as the spawn method needs


def double(n: int) -> int:
    return n * 2


def fails(message: str) -> None:
    raise ValueError(message)


def returns_unpicklable() -> Any:
    return threading.Lock()


def returns_a_child_only_class() -> Any:
    """Returns an instance of a class only the child can import: it pickles and
    unpickles there, not in the parent."""
    module = types.ModuleType("child_only")
    exec("class Thing:\n    pass\n", module.__dict__)  # noqa: S102
    sys.modules["child_only"] = module
    return module.Thing()


def exits_hard(code: int) -> None:
    os._exit(code)


def killed() -> None:
    os.kill(os.getpid(), signal.SIGKILL)


def child_pid() -> int:
    return os.getpid()


def returns_on_stop(started: Any) -> int:
    """Waits for its stop, then returns its task id, as the child sees it."""
    started.set()
    stopping().wait()
    return task_id()


def raises_on_stop(started: Any) -> None:
    started.set()
    stopping().wait()
    raise StoppedError()


def ignores_everything(started: Any = None) -> None:
    """Ignores its stop and SIGTERM: only a kill ends it. Sets *started*, if
    given, once SIGTERM is ignored."""
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    if started is not None:
        started.set()
    threading.Event().wait()


def holds_its_argument(_: Any) -> None:
    """Takes an argument, then ignores its stop and SIGTERM as
    ignores_everything() does."""
    ignores_everything()


class HeldAfterStart(SpawnProcess):
    """A child process whose start() returns only once released: it holds the
    parent thread between the child's start and its publication. At module
    level, as the child unpickles it; the events are the class's, so they are
    not pickled with it."""

    held = threading.Event()
    release = threading.Event()

    def start(self) -> None:
        super().start()
        HeldAfterStart.held.set()
        HeldAfterStart.release.wait(30.0)


class SlowToPickle:
    """An argument whose pickling, inside Process.start() in the parent, waits
    until released: it holds a child between spawn() and its start."""

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()

    def __reduce__(self) -> tuple[Any, ...]:
        self.entered.set()
        self.release.wait(30.0)
        return (int, (0,))


@pytest.fixture
def rt() -> Iterator[Runtime]:
    runtime = Runtime(MagicMock())
    runtime.start()
    yield runtime
    runtime.stop()


class TestOutcome:
    def test_the_result_comes_back(self, rt: Runtime) -> None:
        assert rt.spawn(double, 21, process=True).wait(timeout=30.0) == 42

    def test_it_runs_in_another_process(self, rt: Runtime) -> None:
        assert rt.spawn(child_pid, process=True).wait(timeout=30.0) != os.getpid()

    def test_an_exception_comes_back_with_the_childs_traceback(
        self, rt: Runtime
    ) -> None:
        t = rt.spawn(fails, "no", process=True)
        with pytest.raises(ValueError, match="no") as caught:
            t.wait(timeout=30.0)
        assert any("in fails" in note for note in caught.value.__notes__)

    def test_the_childs_traceback_survives_a_done_pipe(self, rt: Runtime) -> None:
        """A pipe pickles the end again: the traceback, a note on the error,
        comes along."""
        send, recv = pipe(1)
        sender, chan = send.open(), recv.open()
        rt.spawn(fails, "no", done=sender, process=True)
        end = chan.recv(timeout=30.0)
        assert isinstance(end.error, ValueError)
        assert any("in fails" in note for note in getattr(end.error, "__notes__", ()))
        sender.close()

    def test_an_unpicklable_result_is_named(self, rt: Runtime) -> None:
        t = rt.spawn(returns_unpicklable, process=True)
        with pytest.raises(RuntimeError, match="unpicklable"):
            t.wait(timeout=30.0)

    def test_an_outcome_the_parent_cannot_unpickle_is_named(self, rt: Runtime) -> None:
        """The child's round trip passes, the parent's load fails: a RuntimeError
        naming the task, caused by the load's error."""
        t = rt.spawn(returns_a_child_only_class, process=True)
        with pytest.raises(RuntimeError, match=f"task {t.id}") as caught:
            t.wait(timeout=30.0)
        assert isinstance(caught.value.__cause__, ModuleNotFoundError)

    def test_an_exit_without_an_outcome_names_the_exit_code(self, rt: Runtime) -> None:
        t = rt.spawn(exits_hard, 3, process=True)
        with pytest.raises(ProcessExitError) as caught:
            t.wait(timeout=30.0)
        assert caught.value.exitcode == 3

    def test_a_killed_child_names_the_signal(self, rt: Runtime) -> None:
        t = rt.spawn(killed, process=True)
        with pytest.raises(ProcessExitError) as caught:
            t.wait(timeout=30.0)
        assert caught.value.exitcode == -signal.SIGKILL

    def test_an_exit_without_an_outcome_reaches_a_done_pipe_as_itself(
        self, rt: Runtime
    ) -> None:
        """Through a pipe the end is pickled again: the receiver gets the same
        ProcessExitError, with its exit code, as a waiter would."""
        send, recv = pipe(1)
        sender, chan = send.open(), recv.open()
        rt.spawn(exits_hard, 3, done=sender, process=True)
        end = chan.recv(timeout=30.0)
        assert isinstance(end.error, ProcessExitError)
        assert end.error.exitcode == 3
        sender.close()

    def test_a_pipe_that_fails_to_open_leaves_none_open(
        self, rt: Runtime, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The second Pipe() fails: the task fails with its error, and the ends
        of the first are closed, not left to the collector."""
        real = mp.get_context("spawn")
        opened: list[Any] = []

        class SecondPipeFails:
            def __getattr__(self, name: str) -> Any:
                return getattr(real, name)

            def Pipe(self, duplex: bool = True) -> Any:  # noqa: N802
                if opened:
                    raise OSError("no more descriptors")
                pair = real.Pipe(duplex=duplex)
                opened.extend(pair)
                return pair

        monkeypatch.setattr(
            process_module.mp, "get_context", lambda _: SecondPipeFails()
        )
        with pytest.raises(OSError, match="no more descriptors"):
            rt.spawn(double, 1, process=True).wait(timeout=30.0)
        assert len(opened) == 2
        assert all(conn.closed for conn in opened)

    def test_a_reaped_child_is_closed_and_signals_after_it_are_harmless(
        self, rt: Runtime, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A finished task holds no Process descriptors, and a late terminate()
        or kill(), as a stop racing the end sends, does nothing."""
        real = mp.get_context("spawn")
        started: list[Any] = []

        class KeepsProcess:
            def __getattr__(self, name: str) -> Any:
                return getattr(real, name)

            def Process(self, *args: Any, **kwargs: Any) -> Any:  # noqa: N802
                process = real.Process(*args, **kwargs)
                started.append(process)
                return process

        monkeypatch.setattr(process_module.mp, "get_context", lambda _: KeepsProcess())
        t = rt.spawn(double, 2, process=True)
        assert t.wait(timeout=30.0) == 4
        with pytest.raises(ValueError, match="closed"):
            started[0].is_alive()
        t._t.terminate()  # Private: the runtime's stop calls these
        t._t.kill()

    def test_its_end_is_sent_on_done(self, rt: Runtime) -> None:
        done: Chan[TaskDone] = Chan(1)
        t = rt.spawn(double, 4, name="d", done=done, process=True)
        end = done.recv(timeout=30.0)
        assert (end.task_id, end.name, end.result, end.error) == (t.id, "d", 8, None)


def reported(report: tuple[Any, ...]) -> tuple[Any, Any]:
    """A child that has exited, and a connection holding *report*, as a child
    sends it: for _outcome() to read."""
    ctx = mp.get_context("spawn")
    recv, send = ctx.Pipe(duplex=False)
    send.send_bytes(pickle.dumps(report))
    send.close()
    process = ctx.Process(target=os.getpid)
    process.start()
    return process, recv


def process_task() -> Any:
    """A process task not launched: _outcome() is called on it directly."""
    return process_module._ProcessTask(lambda _: None, 1, None, double, (), StopToken())


class TestReport:
    """The child's report decides the outcome; the parent's token only counts
    when no report arrives."""

    def test_a_reported_stop_is_a_stop_with_the_parents_token_running(self) -> None:
        """The child stopped its own token and ended on it."""
        task = process_task()
        task._outcome(*reported((None, None, True)))
        assert (task.stopped, task.exception) == (True, None)

    def test_a_reported_failure_stays_one_with_the_parents_token_stopped(
        self,
    ) -> None:
        """The child raised StoppedError on its running token, a failure; the
        parent was cancelled before it read the report."""
        task = process_task()
        task.token.stop()
        task._outcome(*reported((None, StoppedError("its own"), False)))
        assert task.stopped is False
        assert isinstance(task.exception, StoppedError)


async def returns_on_the_loop() -> int:
    return 1


def ignores_its_stop(started: Any) -> None:
    """Ignores its stop, not SIGTERM: a terminate() ends it."""
    started.set()
    threading.Event().wait()


class TestStopWithTimeout:
    """task.stop(timeout): the token stops at once; a process task still
    running *timeout* seconds on gets SIGTERM, then SIGKILL."""

    def test_a_child_ending_on_its_stop_is_not_signalled(self, rt: Runtime) -> None:
        started = rt.process_context.Event()
        task = rt.spawn(returns_on_stop, started, process=True)
        assert task.process is not None
        assert started.wait(30.0)

        task.stop(timeout=30.0)
        task.wait(timeout=30.0)  # returns: it ended on its stop
        assert task.process.detail().exitcode == 0

    def test_a_child_ignoring_its_stop_is_terminated(self, rt: Runtime) -> None:
        started = rt.process_context.Event()
        task = rt.spawn(ignores_its_stop, started, process=True)
        assert task.process is not None
        assert started.wait(30.0)

        task.stop(timeout=0.1)
        with pytest.raises(StoppedError):
            task.wait(timeout=30.0)
        assert task.process.detail().exitcode == -signal.SIGTERM

    def test_a_child_ignoring_sigterm_is_killed(
        self, rt: Runtime, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(process_module, "_GRACE", 0.1)
        started = rt.process_context.Event()
        task = rt.spawn(ignores_everything, started, process=True)
        assert task.process is not None
        assert started.wait(30.0)

        task.stop(timeout=0.1)
        with pytest.raises(StoppedError):
            task.wait(timeout=30.0)
        assert task.process.detail().exitcode == -signal.SIGKILL

    def test_a_thread_task_is_stopped_as_cancel_stops_it(self, rt: Runtime) -> None:
        """Stopped once its call runs: stopped before, the call is skipped."""
        started = threading.Event()

        def waits_on_its_stop() -> None:
            started.set()
            stopping().wait()

        task = rt.spawn(waits_on_its_stop)
        assert started.wait(30.0)
        task.stop(timeout=0.1)
        task.wait(timeout=30.0)
        assert task.process is None


class TestKindAndDetail:
    """What a task tells about how it runs: its kind, and for a process task
    the child's pid, exit code and liveness."""

    @pytest.mark.parametrize(
        ("fn", "process", "kind"),
        [
            (double, False, TaskKind.THREAD),
            (returns_on_the_loop, False, TaskKind.LOOP),
            (double, True, TaskKind.PROCESS),
        ],
        ids=["thread", "loop", "process"],
    )
    def test_a_task_tells_its_kind(
        self, rt: Runtime, fn: Any, process: bool, kind: TaskKind
    ) -> None:
        args = () if fn is returns_on_the_loop else (1,)
        task = rt.spawn(fn, *args, process=process)
        task.wait(timeout=30.0)
        assert task.kind is kind
        assert (task.process is not None) is (kind is TaskKind.PROCESS)

    def test_the_detail_follows_the_child(self, rt: Runtime) -> None:
        """While the child runs: its pid, alive, no exit code; once it has
        ended and been reaped: the same pid and its exit code."""
        started = rt.process_context.Event()
        task = rt.spawn(returns_on_stop, started, process=True)
        assert task.process is not None
        assert started.wait(30.0)

        running = task.process.detail()
        assert running.pid is not None and running.pid != os.getpid()
        assert running.alive
        assert running.exitcode is None

        task.cancel()
        task.wait(timeout=30.0)
        ended = task.process.detail()
        assert ended == ProcessDetail(pid=running.pid, exitcode=0, alive=False)

    @pytest.mark.parametrize(
        ("end", "signum"),
        [("terminate", signal.SIGTERM), ("kill", signal.SIGKILL)],
    )
    def test_the_handle_ends_the_child(
        self, rt: Runtime, end: str, signum: int
    ) -> None:
        """terminate() and kill() reach the child; its exit code names the
        signal."""
        started = rt.process_context.Event()
        task = rt.spawn(returns_on_stop, started, process=True)
        assert task.process is not None
        assert started.wait(30.0)

        getattr(task.process, end)()
        with pytest.raises(ProcessExitError):
            task.wait(timeout=30.0)
        assert task.process.detail().exitcode == -signum

    def test_children_start_in_the_runtimes_context(self, rt: Runtime) -> None:
        assert rt.process_context.get_start_method() == "spawn"


class TestStop:
    def test_cancel_stops_the_childs_token(self, rt: Runtime) -> None:
        """The child sees its stop and returns: the task's result, with the
        task's id as the child knows it."""
        started = mp.get_context("spawn").Event()
        t = rt.spawn(returns_on_stop, started, process=True)
        assert started.wait(30.0)  # the timeout is the failure path
        t.cancel()
        assert t.wait(timeout=30.0) == t.id

    def test_a_child_ending_on_its_stop_is_stopped(self, rt: Runtime) -> None:
        started = mp.get_context("spawn").Event()
        t = rt.spawn(raises_on_stop, started, process=True)
        assert started.wait(30.0)
        t.cancel()
        with pytest.raises(StoppedError):
            t.wait(timeout=30.0)

    def test_the_runtimes_stop_kills_a_child_that_ignores_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Past the stop's timeout the child is terminated, then killed: it
        ignores SIGTERM too. Without an outcome, the stopped task is stopped."""
        monkeypatch.setattr(process_module, "_GRACE", 0.2)
        rt = Runtime(MagicMock())
        rt.start()
        started = mp.get_context("spawn").Event()
        t = rt.spawn(ignores_everything, started, process=True)
        assert started.wait(30.0)  # the timeout is the failure path
        rt.stop(timeout=0.5)
        assert not t.alive()
        with pytest.raises(StoppedError):
            t.wait(timeout=0)

    def test_a_stop_forced_before_the_child_is_published_still_kills_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The child is running its call, ignoring its stop, but the parent
        thread has not published it yet when the runtime's stop forces the
        task: the force is recorded, and applied as the child is published."""
        monkeypatch.setattr(process_module, "_GRACE", 0.1)
        real = mp.get_context("spawn")
        held, release = HeldAfterStart.held, HeldAfterStart.release
        held.clear()
        release.clear()

        class SpawnsHeld:
            def __getattr__(self, name: str) -> Any:
                return getattr(real, name)

            def Process(self, *args: Any, **kwargs: Any) -> Any:  # noqa: N802
                return HeldAfterStart(*args, **kwargs)

        monkeypatch.setattr(process_module.mp, "get_context", lambda _: SpawnsHeld())
        started = real.Event()
        rt = Runtime(MagicMock())
        rt.start()
        try:
            t = rt.spawn(ignores_everything, started, process=True)
            assert held.wait(30.0)  # the timeouts are the failure path
            assert started.wait(30.0)  # in its call, ignoring stop and SIGTERM
            rt.stop(timeout=0.1)  # forces the task before it is published
            release.set()
            with pytest.raises(StoppedError):
                t.wait(timeout=10.0)
        finally:
            release.set()
            for child in mp.active_children():  # a failing run leaves it running
                child.kill()

    def test_a_child_still_starting_when_the_stop_gives_up_is_killed_once_started(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The runtime's stop forces a child whose start() is still pickling
        its arguments: once it starts, it is killed, not left running."""
        monkeypatch.setattr(process_module, "_GRACE", 0.1)
        slow = SlowToPickle()
        rt = Runtime(MagicMock())
        rt.start()
        try:
            t = rt.spawn(holds_its_argument, slow, process=True)
            assert slow.entered.wait(30.0)  # the timeout is the failure path
            rt.stop(timeout=0.1)  # gives up while start() still pickles
            slow.release.set()
            with pytest.raises(StoppedError):
                t.wait(timeout=30.0)
        finally:
            slow.release.set()
            for child in mp.active_children():  # a failing run leaves it running
                child.kill()

    def test_a_stop_sent_before_the_child_started_skips_the_call(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A stop signalled before the child starts is seen before the call,
        whatever its listener thread does: here the listener never reads it.
        Run in this process: _child() is the child's main."""
        monkeypatch.setattr(process_module, "_stop_on_signal", lambda *_: None)
        ctx = mp.get_context("spawn")
        stop_recv, stop_send = ctx.Pipe(duplex=False)
        outcome_recv, outcome_send = ctx.Pipe(duplex=False)
        stop_send.send_bytes(b"")  # as the task's token stopping does
        called = threading.Event()
        process_module._child(1, None, called.set, (), stop_recv, outcome_send)
        _, error, stopped = pickle.loads(outcome_recv.recv_bytes())
        assert (stopped, error) == (True, None)
        assert not called.is_set()

    def test_a_closed_stop_connection_stops_the_child(self) -> None:
        """EOF on the stop connection, as when the parent is gone, stops the
        child's token like a stop signal does."""
        recv, send = mp.get_context("spawn").Pipe(duplex=False)
        token = StopToken()
        send.close()
        _stop_on_signal(recv, token)
        assert token.is_set()
