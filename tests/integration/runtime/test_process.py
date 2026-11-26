# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for tasks spawned with process=True: a call in a child process."""

from __future__ import annotations

import multiprocessing as mp
import os
import signal
import threading
from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock

import pytest

from appinfra.runtime import (
    Chan,
    ProcessExitError,
    Runtime,
    StoppedError,
    StopToken,
    TaskDone,
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


def ignores_everything() -> None:
    """Ignores its stop and SIGTERM: only a kill ends it."""
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    threading.Event().wait()


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
        assert "in fails" in str(caught.value.__cause__)

    def test_an_unpicklable_result_is_named(self, rt: Runtime) -> None:
        t = rt.spawn(returns_unpicklable, process=True)
        with pytest.raises(RuntimeError, match="unpicklable"):
            t.wait(timeout=30.0)

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

    def test_its_end_is_sent_on_done(self, rt: Runtime) -> None:
        done: Chan[TaskDone] = Chan(1)
        t = rt.spawn(double, 4, name="d", done=done, process=True)
        end = done.recv(timeout=30.0)
        assert (end.task_id, end.name, end.result, end.error) == (t.id, "d", 8, None)


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
        t = rt.spawn(ignores_everything, process=True)
        rt.stop(timeout=0.5)
        assert not t.alive()
        with pytest.raises(StoppedError):
            t.wait(timeout=0)

    def test_a_closed_stop_connection_stops_the_child(self) -> None:
        """EOF on the stop connection, as when the parent is gone, stops the
        child's token like a stop signal does."""
        recv, send = mp.get_context("spawn").Pipe(duplex=False)
        token = StopToken()
        send.close()
        _stop_on_signal(recv, token)
        assert token.is_set()
