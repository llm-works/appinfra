# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""spawn(process=True) refusals, checked before any task or process exists, and
the errors a process task ends with."""

import pickle
import time
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import MagicMock

import pytest

from appinfra.runtime import ProcessExitError, Runtime


async def parked() -> None:
    """An async function: it runs on the loop, which a child does not have."""


async def ticks() -> AsyncIterator[int]:
    """An async generator function: what it returns needs a loop too."""
    yield 1


class AsyncCallable:
    """An object whose __call__ is a coroutine function."""

    async def __call__(self) -> None:
        """Nothing to do."""


@pytest.mark.parametrize("fn", [parked, ticks, AsyncCallable()])
def test_an_async_callable_is_refused_a_process(fn: Any) -> None:
    """Refused by spawn() itself: the runtime here is not even running."""
    with pytest.raises(TypeError, match="not in a process"):
        Runtime(MagicMock()).spawn(fn, process=True)


class Stubborn:
    """A task that never ends and can be ended by force, as a process task's;
    records what the runtime's stop does to it."""

    killable = True

    def __init__(self, name: str, log: list[tuple[str, str]]) -> None:
        self.name = name
        self._log = log

    def is_running(self) -> bool:
        return True

    def join(self, timeout: float | None = None) -> bool:
        self._log.append(("join", self.name))
        return False

    def terminate(self) -> None:
        self._log.append(("terminate", self.name))

    def kill(self) -> None:
        self._log.append(("kill", self.name))


def test_the_stop_escalates_every_late_task_before_waiting_on_one() -> None:
    """Every late task is terminated before the grace wait, and every survivor
    killed before the last wait: one shared budget, not one per task."""
    log: list[tuple[str, str]] = []
    tasks = [Stubborn("a", log), Stubborn("b", log)]
    rt = Runtime(MagicMock())
    late = rt._still_running(tasks, time.monotonic())  # type: ignore[arg-type]
    assert late == tasks
    assert log == [
        ("join", "a"), ("join", "b"),            # the cooperative wait
        ("terminate", "a"), ("terminate", "b"),
        ("join", "a"), ("join", "b"),            # the grace
        ("kill", "a"), ("kill", "b"),
        ("join", "a"), ("join", "b"),
    ]  # fmt: skip


def test_a_process_exit_error_survives_a_pickle_round_trip() -> None:
    """A done pipe pickles the end again: the error comes back whole."""
    error = pickle.loads(pickle.dumps(ProcessExitError(7, -9)))
    assert (error.task_id, error.exitcode) == (7, -9)
    assert str(error) == "task 7's process exited with code -9"
