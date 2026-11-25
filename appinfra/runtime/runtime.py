# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Runtime: runs tasks on its event loop or on threads of their own."""

from __future__ import annotations

import atexit
import inspect
import threading
from collections.abc import Callable
from types import TracebackType
from typing import Any

from ..log import Logger
from .loop import LoopHost
from .stop import StopToken
from .task import LoopTask, Task, ThreadTask, current_token


class Runtime:
    """Runs tasks: spawn() takes a function and calls it once, from any thread.

    - an async function: a task on the runtime's event loop (a LoopHost), shared
      by every async task, so one waiting on an await holds no thread
    - any other function: a thread of its own

    Every task's token derives from the token of the task that spawned it, or
    from the runtime's; ``stopping()`` returns it inside the task. A task that
    ends leaves the runtime. stop() stops every task's token, cancels the tasks
    on the loop, and waits for the ones on threads.

    Example:
        with Runtime(lg) as rt:
            rt.spawn(serve, port)        # async def serve(port): ...
            rt.spawn(consume, queue)     # def consume(queue): ...
    """

    def __init__(self, lg: Logger, name: str = "runtime") -> None:
        """A runtime not yet started; *name* names its event loop's thread."""
        self._lg = lg
        self.name = name
        self._host = LoopHost(name=name)
        self._root = StopToken()
        self._lock = threading.Lock()  # guards everything below
        self._tasks: set[Task] = set()  # tasks launched and not ended
        self._started_runtime = False
        self._closing = False

    @property
    def tasks(self) -> set[Task]:
        """The tasks launched and not ended yet."""
        with self._lock:
            return set(self._tasks)

    def start(self) -> None:
        """Start the runtime's event loop.

        Raises:
            RuntimeError: If the runtime was started already.
        """
        if self._started_runtime:
            raise RuntimeError(f"runtime '{self.name}' was started already")
        self._host.start()
        self._started_runtime = True
        # Its threads are daemons, ended unwound at exit: a runtime left running
        # is stopped first, so its tasks see their tokens stop
        atexit.register(self._atexit_stop)

    def _atexit_stop(self) -> None:
        """At interpreter exit: stop a runtime nothing stopped."""
        try:
            self.stop()
        except Exception as e:
            self._lg.warning("runtime stop at exit failed", extra={"exception": e})

    def spawn(self, fn: Callable[..., Any], *args: Any) -> Task:
        """Call *fn*(*args*) as a task: on the loop if it is an async function,
        else on a thread of its own. Returns the task.

        Raises:
            RuntimeError: If the runtime is not running.
        """
        parent = current_token()
        token = (self._root if parent is None else parent).child()
        task: Task
        if inspect.iscoroutinefunction(fn):
            task = LoopTask(self._host, fn, args, token, self._forget)
        else:
            task = ThreadTask(fn, args, token, self._forget)
        with self._lock:
            if not self._started_runtime or self._closing:
                token.detach()
                raise RuntimeError(f"runtime '{self.name}' is not running")
            self._tasks.add(task)
            # Under the lock, so stop() never finds a task here not launched
            self._launch(task)
        return task

    def _launch(self, task: Task) -> None:
        """Launch *task*; under the lock. A task the loop refuses leaves the
        runtime and its token the tree."""
        try:
            task._launch()
        except BaseException:
            self._tasks.discard(task)
            task.token.stop()
            task.token.detach()
            raise

    def _forget(self, task: Task) -> None:
        """Once *task* has ended: take it out of the runtime; log its failure."""
        with self._lock:
            self._tasks.discard(task)
        if task.exception is not None:
            self._lg.warning(
                "task failed", extra={"task": task.name, "exception": task.exception}
            )

    def stop(self, timeout: float = 5.0) -> None:
        """Stop every task's token, then the loop, which cancels the tasks on
        it; then wait for the tasks on threads. The loop and each thread task
        get up to *timeout* seconds; a task still running then is logged and
        left, as a thread cannot be killed.

        Raises:
            RuntimeError: If called on the runtime's loop thread.
        """
        if self._host.on_loop_thread():
            raise RuntimeError("Runtime.stop() on the loop thread would block it")
        with self._lock:
            if not self._started_runtime or self._closing:
                return
            self._closing = True
            tasks = list(self._tasks)
        atexit.unregister(self._atexit_stop)
        self._root.stop()
        self._host.stop(timeout)
        for task in tasks:
            if not task.stop(timeout):
                self._lg.warning(
                    "task did not end in time",
                    extra={"task": task.name, "timeout": timeout},
                )

    def __enter__(self) -> Runtime:
        """Start the runtime."""
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Stop the runtime."""
        self.stop()
