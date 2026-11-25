# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Runtime: runs tasks on its event loop or on threads of their own."""

from __future__ import annotations

import atexit
import inspect
import threading
import time
from collections.abc import Callable
from types import TracebackType
from typing import Any

from ..log import Logger
from .errors import StoppedError
from .loop import LoopHost
from .stop import StopToken
from .task import LoopTask, Task, ThreadTask, current_task


class Runtime:
    """Runs tasks: spawn() takes a function, calls it once, from any thread,
    and returns the task's id, assigned by the runtime and never reused.

    - an async function: a task on the runtime's event loop (a LoopHost), shared
      by every async task, so one waiting on an await holds no thread
    - any other function: a thread of its own

    As with processes, a task that has ended stays known until wait() collects
    its outcome; detach() gives up waiting, and the task is dropped as soon as
    it ends. A detached task's failure is logged, as nobody else sees it.

    Every task's token derives from the token of the task that spawned it, or
    from the runtime's; ``stopping()`` returns it inside the task, ``task_id()``
    its id. stop() stops every task's token, cancels the tasks on the loop, and
    waits for the ones on threads; their outcomes stay to be waited for.

    A task its stop ended has no result: wait() raises StoppedError for it,
    and a detached one is not logged as failed. A function that sees the stop
    and returns ends with its result.

    Example:
        with Runtime(lg) as rt:
            server = rt.spawn(serve, port)   # async def serve(port): ...
            rt.detach(rt.spawn(consume, q))  # def consume(q): ...
            rt.cancel(server)
            with contextlib.suppress(StoppedError):
                rt.wait(server, timeout=5.0)
    """

    def __init__(self, lg: Logger) -> None:
        """A runtime not yet started."""
        self._lg = lg
        self._host = LoopHost()
        self._root = StopToken()
        self._lock = threading.Lock()  # guards everything below
        # Tasks not reaped: running, and ended ones not waited for yet
        self._tasks: dict[int, Task] = {}
        self._next_task_id = 1
        self._started_runtime = False
        self._closing = False

    def start(self) -> None:
        """Start the runtime's event loop.

        Raises:
            RuntimeError: If the runtime was started already.
        """
        if self._started_runtime:
            raise RuntimeError("runtime was started already")
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

    # -- spawn --------------------------------------------------------------

    def spawn(self, fn: Callable[..., Any], *args: Any) -> int:
        """Call *fn*(*args*) as a task: on the loop if it is an async function,
        else on a thread of its own. Returns the task's id.

        Raises:
            RuntimeError: If the runtime is not running.
        """
        parent = current_task()
        token = (self._root if parent is None else parent.token).child()
        with self._lock:
            if not self._started_runtime or self._closing:
                token.detach()
                raise RuntimeError("runtime is not running")
            task_id = self._next_task_id
            self._next_task_id += 1
            task = self._task_for(task_id, fn, args, token)
            self._tasks[task_id] = task
            # Under the lock, so stop() never finds a task here not launched
            self._launch(task)
        return task_id

    def _task_for(
        self,
        task_id: int,
        fn: Callable[..., Any],
        args: tuple[Any, ...],
        token: StopToken,
    ) -> Task:
        """The task that calls *fn*: on the loop if it is an async function."""
        if inspect.iscoroutinefunction(fn):
            return LoopTask(self._host, task_id, fn, args, token, self._on_end)
        return ThreadTask(task_id, fn, args, token, self._on_end)

    def _launch(self, task: Task) -> None:
        """Launch *task*; under the lock. A task the loop refuses leaves the
        runtime and its token the tree."""
        try:
            task._launch()
        except BaseException:
            del self._tasks[task.task_id]
            task.token.stop()
            task.token.detach()
            raise

    # -- tasks by id --------------------------------------------------------

    def _get(self, task_id: int) -> Task:
        """The task *task_id*; under the lock.

        Raises:
            LookupError: If no task has that id, or it was reaped.
        """
        task = self._tasks.get(task_id)
        if task is None:
            raise LookupError(f"no task {task_id}")
        return task

    def wait(self, task_id: int, timeout: float | None = None) -> Any:
        """Wait up to *timeout* seconds for task *task_id* to end, then reap it.

        Returns:
            What the task's function returned.

        Raises:
            LookupError: If no task has that id, or it was reaped.
            RuntimeError: If the task is detached, or the wait would block the
                loop or the task's own thread.
            TimeoutError: If the task is still running after *timeout*; it is
                not reaped.
            StoppedError: If the task was stopped before it returned: its call
                was skipped, cancelled, or ended by a wait the stop ended. A
                function that sees the stop and returns gives its result.
            BaseException: Whatever the task's function raised.
        """
        with self._lock:
            task = self._get(task_id)
            if task.detached:
                raise RuntimeError(f"task {task_id} is detached")
            # Its outcome is settled once the end is recorded, though its
            # thread may not have run its last line yet: no wait for it then
            ended = task.ended
            # For both kinds: joining a thread blocks the loop as much as an
            # Event.wait() on it does. An ended task can still be collected
            if not ended and self._host.on_loop_thread():
                raise RuntimeError(
                    f"waiting for task {task_id} on the loop would block it"
                )
        if not ended and not task.wait(timeout):
            raise TimeoutError(f"task {task_id} is still running")
        with self._lock:
            if self._tasks.get(task_id) is not task:
                raise LookupError(f"no task {task_id}")
            del self._tasks[task_id]
        if task.exception is not None:
            raise task.exception
        if task.stopped:
            raise StoppedError(f"task {task_id} was stopped")
        return task.result

    def cancel(self, task_id: int) -> None:
        """Stop task *task_id*'s token and, on the loop, cancel it; returns at once.
        A task on a thread sees its token and returns.

        Raises:
            LookupError: If no task has that id, or it was reaped.
        """
        with self._lock:
            task = self._get(task_id)
        task.cancel()

    def alive(self, task_id: int) -> bool:
        """True while task *task_id* has not ended.

        Raises:
            LookupError: If no task has that id, or it was reaped.
        """
        with self._lock:
            return not self._get(task_id).ended

    def detach(self, task_id: int) -> None:
        """Give up waiting for task *task_id*: it is reaped as soon as it ends, now
        if it has ended already.

        Raises:
            LookupError: If no task has that id, or it was reaped.
        """
        with self._lock:
            task = self._get(task_id)
            task.detached = True
            reap = task.ended
            if reap:
                del self._tasks[task_id]
        if reap:
            self._log_failure(task)

    def _on_end(self, task: Task) -> None:
        """Once *task*'s call has ended: reap it if it is detached."""
        with self._lock:
            task.ended = True
            reap = task.detached
            if reap:
                self._tasks.pop(task.task_id, None)
        if reap:
            self._log_failure(task)

    def _log_failure(self, task: Task) -> None:
        """Log the failure of a task nobody waits for."""
        if task.exception is not None:
            self._lg.warning(
                "task failed",
                extra={"task_id": task.task_id, "exception": task.exception},
            )

    # -- stop ---------------------------------------------------------------

    def stop(self, timeout: float = 5.0) -> None:
        """Stop every task's token, then the loop, which cancels the tasks on
        it; then wait for the tasks on threads. All of it takes at most
        *timeout* seconds: the loop and the thread tasks share the one budget.
        A task still running then is logged and left, as a thread cannot be
        killed. Ended tasks stay to be waited for.

        Raises:
            RuntimeError: If called on the runtime's loop thread.
        """
        if self._host.on_loop_thread():
            raise RuntimeError("Runtime.stop() on the loop thread would block it")
        deadline = time.monotonic() + timeout
        with self._lock:
            if not self._started_runtime or self._closing:
                return
            self._closing = True
            running = [t for t in self._tasks.values() if not t.ended]
        atexit.unregister(self._atexit_stop)
        try:
            self._root.stop()
            # A task spawned by another runtime's task derives from that
            # task's token, outside this root's tree: its own token is stopped
            # as well
            for task in running:
                task.token.stop()
        finally:
            # Ctrl-C during the stops reaches the caller once the shutdown is
            # done: a second stop() returns at once
            self._host.stop(max(0.0, deadline - time.monotonic()))
            for task in self._still_running(running, deadline):
                self._lg.warning(
                    "task did not end in time",
                    extra={"task_id": task.task_id, "timeout": timeout},
                )

    def _still_running(self, tasks: list[Task], deadline: float) -> list[Task]:
        """The *tasks* still running once the loop has stopped. A thread task
        is waited for until *deadline*; a loop task only checked, as the loop's
        stop had its time already. A task stopping the runtime does not wait
        for itself."""
        caller = current_task()
        late = []
        for task in tasks:
            if task is caller:
                continue
            if isinstance(task, LoopTask):
                ended = not task.is_alive()
            else:
                ended = task.wait(max(0.0, deadline - time.monotonic()))
            if not ended:
                late.append(task)
        return late

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
