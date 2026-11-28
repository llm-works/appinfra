# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""this_task(): who the task the code runs in is, on a thread, on the loop and
in a process task's child; and spawn(derive_lg=...), a logger of a task's
own."""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterator
from typing import Any

import pytest

from appinfra.log import Logger
from appinfra.runtime import Chan, Runtime, TaskContext, this_task
from tests.helpers.lg import quiet_lg

# Seconds a call expected to end now may take: the failure path, not a wait
DUE = 30.0


class Captured(logging.Handler):
    """Keeps the records it handles; *arrived* is set on each."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []
        self.arrived = threading.Event()

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)
        self.arrived.set()


@pytest.fixture
def lg() -> Iterator[Logger]:
    """The runtime's logger, with a handler that keeps what reaches it."""
    lg = quiet_lg()
    lg.addHandler(Captured())
    yield lg


@pytest.fixture
def rt(lg: Logger) -> Iterator[Runtime]:
    runtime = Runtime(lg)
    runtime.start()
    yield runtime
    runtime.stop()


def captured(lg: Logger) -> Captured:
    """The handler the lg fixture added."""
    return next(h for h in lg.handlers if isinstance(h, Captured))


# The children run these by name: module level, as they find them by name


def who_am_i() -> tuple[int, str | None, str, bool]:
    """This task as it sees itself: id, name, its logger's name, and whether
    its token still runs."""
    me = this_task()
    return me.id, me.name, me.lg.name, not me.token.is_set()


async def who_am_i_async() -> tuple[int, str | None, str, bool]:
    return who_am_i()


def logs(message: str) -> str:
    """Logs *message* as a warning through this task's logger; returns the
    logger's name."""
    me = this_task()
    me.lg.warning(message)
    return me.lg.name


def logs_and_sends(message: str, out: Chan[str]) -> None:
    """Logs *message*, then sends it: the logger and a Chan both cross."""
    this_task().lg.warning(message)
    out.send(message, timeout=DUE)


def echoes(*args: Any) -> tuple[Any, ...]:
    return args


def spawns_a_logging_child(message: str) -> str:
    """In a child: a runtime of its own on this task's logger, and a process
    task on it that logs *message* under a derived name; returns that name."""
    with Runtime(this_task().lg) as rt:
        task = rt.spawn(logs, message, derive_lg="grand", process=True)
        name: str = task.wait(timeout=DUE)
        return name


class TestThisTask:
    def test_a_thread_task_knows_itself(self, rt: Runtime, lg: Logger) -> None:
        task = rt.spawn(who_am_i, name="thread")
        assert task.wait(timeout=DUE) == (task.id, "thread", lg.name, True)

    def test_a_loop_task_knows_itself(self, rt: Runtime, lg: Logger) -> None:
        task = rt.spawn(who_am_i_async, name="loop")
        assert task.wait(timeout=DUE) == (task.id, "loop", lg.name, True)

    def test_a_process_task_knows_itself(self, rt: Runtime, lg: Logger) -> None:
        task = rt.spawn(who_am_i, name="process", process=True)
        assert task.wait(timeout=DUE) == (task.id, "process", lg.name, True)

    def test_thread_tasks_share_the_runtimes_logger(
        self, rt: Runtime, lg: Logger
    ) -> None:
        """No logger is made per task: each gets the runtime's own."""
        seen: list[Logger] = []
        tasks = [rt.spawn(lambda: seen.append(this_task().lg)) for _ in range(3)]
        for t in tasks:
            t.wait(timeout=DUE)
        assert all(s is lg for s in seen)

    def test_it_is_a_frozen_context(self, rt: Runtime) -> None:
        me = rt.spawn(this_task).wait(timeout=DUE)
        assert isinstance(me, TaskContext)
        with pytest.raises(AttributeError):
            me.id = 0  # type: ignore[misc]


class TestDeriveLg:
    def test_a_thread_task_gets_a_derived_logger(self, rt: Runtime, lg: Logger) -> None:
        name = rt.spawn(logs, "derived", derive_lg="worker").wait(timeout=DUE)
        assert name == f"{lg.name.rstrip('/')}/worker"

    def test_a_loop_task_gets_a_derived_logger(self, rt: Runtime, lg: Logger) -> None:
        async def name_of_its_logger() -> str:
            return this_task().lg.name

        name = rt.spawn(name_of_its_logger, derive_lg="loop").wait(timeout=DUE)
        assert name == f"{lg.name.rstrip('/')}/loop"

    def test_tasks_sharing_a_suffix_share_its_logger(self, rt: Runtime) -> None:
        """The factory keeps one logger per name, however many tasks use it."""
        first = rt.spawn(lambda: this_task().lg, derive_lg="shared")
        second = rt.spawn(lambda: this_task().lg, derive_lg="shared")
        assert first.wait(timeout=DUE) is second.wait(timeout=DUE)

    def test_a_process_tasks_records_reach_the_parents_handlers(
        self, rt: Runtime, lg: Logger
    ) -> None:
        """Derived in the child; emitted here, under the derived name."""
        name = rt.spawn(logs, "from the child", derive_lg="proc", process=True)
        assert name.wait(timeout=DUE) == f"{lg.name.rstrip('/')}/proc"
        assert captured(lg).arrived.wait(DUE)
        record = captured(lg).records[0]
        assert (record.name, record.getMessage()) == (
            f"{lg.name.rstrip('/')}/proc",
            "from the child",
        )

    def test_without_one_a_process_task_logs_under_the_runtimes_name(
        self, rt: Runtime, lg: Logger
    ) -> None:
        rt.spawn(logs, "plain", process=True).wait(timeout=DUE)
        assert captured(lg).arrived.wait(DUE)
        assert captured(lg).records[0].name == lg.name

    def test_a_process_task_with_a_chan_logs_and_sends(
        self, rt: Runtime, lg: Logger
    ) -> None:
        """The logger the Chan's link carries and the task's are one in the
        child: both its records and its sends arrive."""
        out: Chan[str] = Chan(1, process=True)
        rt.spawn(logs_and_sends, "both", out, derive_lg="chan", process=True)
        assert out.recv(timeout=DUE) == "both"
        assert captured(lg).arrived.wait(DUE)
        assert captured(lg).records[0].name == f"{lg.name.rstrip('/')}/chan"

    def test_a_grandchilds_records_reach_the_first_parents_handlers(
        self, rt: Runtime, lg: Logger
    ) -> None:
        """A process task's runtime, built on its task's logger, carries that
        logger on: the grandchild's records cross both processes."""
        task = rt.spawn(spawns_a_logging_child, "two hops", process=True)
        name = task.wait(timeout=DUE)
        assert name == f"{lg.name.rstrip('/')}/grand"
        assert captured(lg).arrived.wait(DUE)
        record = captured(lg).records[0]
        assert (record.name, record.getMessage()) == (name, "two hops")

    def test_without_it_the_arguments_are_unchanged(self, rt: Runtime) -> None:
        assert rt.spawn(echoes, 1, "two").wait(timeout=DUE) == (1, "two")
        assert rt.spawn(echoes, 1, process=True).wait(timeout=DUE) == (1,)
