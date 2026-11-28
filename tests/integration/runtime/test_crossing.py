# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Crossing.close(): a child's log records are all handled, though their
handling outlasts the listener's join."""

from __future__ import annotations

import logging
import multiprocessing as mp
import threading
from typing import Any

from appinfra.runtime.chan.crossing import Crossing
from tests.helpers.lg import quiet_lg

# Seconds a wait expected to end now may take: the failure path, not a wait
DUE = 10.0


def test_records_handled_after_the_join_are_not_dropped() -> None:
    """The handler is still on the first record when close() runs, and the
    listener's join gives up at once: the queue stays open until the listener
    has handled the rest, then the listener closes it."""
    crossing = Crossing(quiet_lg(), mp.get_context("spawn"))
    crossing.carry()
    records, listener = crossing._queue, crossing._listener
    assert listener is not None
    handled: list[str] = []
    entered, release = threading.Event(), threading.Event()

    def slow_first(record: logging.LogRecord) -> None:
        if not handled:
            entered.set()
            release.wait(DUE)
        handled.append(record.getMessage())

    listener._handle_record = slow_first  # type: ignore[method-assign]
    stop = listener.stop

    def no_wait(**kwargs: Any) -> None:
        stop(timeout=0, **kwargs)  # the join outlasted at once

    listener.stop = no_wait  # type: ignore[method-assign]
    for i in range(3):
        records.put(logging.LogRecord("t", logging.INFO, "t.py", i, f"r{i}", (), None))
    assert entered.wait(DUE)
    thread = listener._thread
    assert thread is not None
    crossing.close()
    release.set()
    thread.join(DUE)
    assert handled == ["r0", "r1", "r2"]
    assert records._closed
