# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""The benches' rate runs, when their tasks do not all start in time: the tasks
already spawned are cancelled and ended before the error leaves, for each kind
of task, not left parked until the runtime stops."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from typing import Any
from unittest.mock import MagicMock

import pytest

from appinfra.log import LogConfig, LoggerFactory
from appinfra.runtime import Chan, Runtime, Task
from appinfra.runtime.bench import loop as bench_loop
from appinfra.runtime.bench import process as bench_process
from appinfra.runtime.bench import thread as bench_thread
from appinfra.runtime.bench.measure import Arrivals

COUNT = 4
DUE = 30.0


class _NeverAll(threading.Event):
    """An event whose wait gives up at once: the arrivals never all came."""

    def wait(self, timeout: float | None = None) -> bool:
        return False


class _Late(Arrivals):
    """Arrivals that never report all of them in."""

    def __init__(self, expected: int) -> None:
        super().__init__(expected)
        self.all = _NeverAll()


def _timed_out(*_: object, **__: object) -> None:
    """In place of an arrival wait: not all started in time."""
    raise TimeoutError("did not all start")


class _NoArrivals(Chan[Any]):
    """The parent's arrivals Chan, its receive failing whatever the children
    send; they get the Chan itself, by reference, as any process Chan."""

    def recv(self, timeout: float | None = None) -> Any:
        raise TimeoutError("did not all start")


def _recording(rt: Runtime, monkeypatch: pytest.MonkeyPatch) -> list[Task]:
    """The tasks *rt* spawns from here on, as they are spawned."""
    spawned: list[Task] = []
    spawn: Callable[..., Task] = rt.spawn

    def record(*args: Any, **kwargs: Any) -> Task:
        task = spawn(*args, **kwargs)
        spawned.append(task)
        return task

    monkeypatch.setattr(rt, "spawn", record)
    return spawned


@pytest.fixture
def rt() -> Iterator[Runtime]:
    rt = Runtime(MagicMock())
    rt.start()
    yield rt
    rt.stop(timeout=DUE)


@pytest.fixture
def prt() -> Iterator[Runtime]:
    """A runtime with a real logger: it is carried into each child, which a
    mock cannot be."""
    rt = Runtime(LoggerFactory.create_root(LogConfig.from_params(level="warning")))
    rt.start()
    yield rt
    rt.stop(timeout=DUE)


class TestStartTimingOut:
    def test_loop_tasks_are_ended(
        self, rt: Runtime, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(bench_loop, "Arrivals", _Late)
        spawned = _recording(rt, monkeypatch)
        with pytest.raises(TimeoutError):
            bench_loop._spawn_parked(rt, COUNT)
        assert len(spawned) == COUNT
        assert not any(t.alive() for t in spawned)

    def test_thread_tasks_are_ended(
        self, rt: Runtime, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(bench_thread, "_arrived", _timed_out)
        spawned = _recording(rt, monkeypatch)
        with pytest.raises(TimeoutError):
            bench_thread._spawn_parked(rt, COUNT)
        assert len(spawned) == COUNT
        assert not any(t.alive() for t in spawned)

    def test_process_tasks_are_ended(
        self, prt: Runtime, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The parent's receive of the arrivals fails whatever the children
        do: no timing decides it."""
        monkeypatch.setattr(bench_process, "Chan", _NoArrivals)
        spawned = _recording(prt, monkeypatch)
        with pytest.raises(TimeoutError):
            bench_process._spawn_parked(prt, COUNT)
        assert len(spawned) == COUNT
        assert not any(t.alive() for t in spawned)
