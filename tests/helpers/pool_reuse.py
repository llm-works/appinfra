# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""A fork pool whose one worker runs two tasks, each in the app's subprocess
context: run in an interpreter of its own, by a test.

fork() copies only the thread that calls it; a lock another thread holds at
that instant stays held in the child, where no thread releases it. An xdist
worker has threads of its own, so a pool forked there can hang for good.
Here the fork happens with this one thread alive, which run() checks."""

from __future__ import annotations

import logging
import multiprocessing
import threading

from appinfra.app.core.app import App
from appinfra.dot_dict import DotDict
from appinfra.log import LogConfig, LoggerFactory

# Set before the pool forks; the worker inherits it
_APP: App | None = None


def _task(i: int) -> int:
    """One task in the reused pool worker: enter the app's subprocess context."""
    assert _APP is not None
    with _APP.subprocess_context(handle_signals=False) as ctx:
        ctx.lg.info("task", extra={"i": i})
    return i


def run() -> None:
    """Run both tasks in one forked worker; each gets its own root logger,
    and this process's root is left as it was.

    Raises:
        AssertionError: If a thread besides this one is alive at the fork,
            or the tasks or the roots are not as expected.
    """
    global _APP
    _APP = App()
    _APP.config = DotDict(logging=DotDict(level="info", location=0))
    parent_root = LoggerFactory.create_root(LogConfig.from_params("info"))
    threads = [t.name for t in threading.enumerate()]
    assert threads == [threading.current_thread().name], f"threads at fork: {threads}"
    with multiprocessing.get_context("fork").Pool(1) as pool:
        results = pool.map_async(_task, [1, 2]).get(timeout=30)
        # The worker ends on its own, its exit (and the coverage data saved
        # there) complete: the context's terminate() would send SIGTERM to a
        # worker still on its way out
        pool.close()
        pool.join()
    assert results == [1, 2]
    assert logging.root.manager.loggerDict["/"] is parent_root
