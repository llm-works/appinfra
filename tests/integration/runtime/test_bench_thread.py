# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""The thread bench's memory runs, when their threads do not all start in time:
the threads already parked are released, not left on an event nothing sets."""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest

from appinfra.runtime import Runtime
from appinfra.runtime.bench import thread as bench_thread

COUNT = 8
# Seconds the released threads may take to end: the failure path, not a wait
DUE = 10.0


@pytest.fixture
def rt() -> Iterator[Runtime]:
    rt = Runtime(MagicMock())
    rt.start()
    yield rt
    rt.stop(timeout=DUE)


def _timed_out(*_: object) -> None:
    """In place of _arrived(): the threads did not all start in time."""
    raise TimeoutError("did not all start")


def _ended_to(threads: int) -> bool:
    """Whether the live threads are back to *threads* before DUE: an ended
    thread signals nothing to wait on. The deadline is the failure path."""
    deadline = time.monotonic() + DUE
    while threading.active_count() > threads:
        if time.monotonic() > deadline:
            return False
        time.sleep(0.01)
    return True


@pytest.fixture
def timing_out(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bench_thread, "_arrived", _timed_out)


@pytest.mark.usefixtures("timing_out")
class TestStartTimingOut:
    def test_plain_threads_are_released(self) -> None:
        before = threading.active_count()
        with pytest.raises(TimeoutError):
            bench_thread._start_plain(COUNT)
        assert _ended_to(before)

    def test_thread_tasks_are_released(self, rt: Runtime) -> None:
        """They park on the run's event, not on their token: a stop of the
        runtime would not release them."""
        before = threading.active_count()
        with pytest.raises(TimeoutError):
            bench_thread._start_tasks(rt, COUNT)
        assert _ended_to(before)
