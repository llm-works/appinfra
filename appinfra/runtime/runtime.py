# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Runtime: runs tasks on its event loop or on threads of their own."""

from __future__ import annotations

import asyncio
import atexit
import contextlib
import contextvars
import inspect
import pickle
import threading
import time
from collections.abc import Callable
from types import TracebackType
from typing import Any

from ..log import Logger
from .chan import Chan, ClosedError, Sender
from .errors import StoppedError
from .loop import LoopHost
from .stop import StopToken
from .task import LoopTask, Task, TaskEnd, ThreadTask, current_task


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

    A task spawned with ``ends`` is detached, and its TaskEnd is sent on that
    channel (or pipe) as it ends, instead: one receiver learns of the ends of
    many tasks, as a Go supervisor reads them from one channel.

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
        # Ends awaiting room on a full channel; loop thread only. Held here:
        # the loop keeps only a weak reference to a task
        self._sending: set[asyncio.Task[None]] = set()

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

    def spawn(
        self,
        fn: Callable[..., Any],
        *args: Any,
        token: StopToken | None = None,
        ends: Chan[TaskEnd] | Sender[TaskEnd] | None = None,
    ) -> int:
        """Call *fn*(*args*) as a task: on the loop if it is an async function,
        else on a thread of its own. Returns the task's id.

        Args:
            fn: The function to call.
            *args: Its arguments.
            token: The token the task's derives from, instead of the spawning
                task's or the runtime's. stop() stops the task all the same.
            ends: A channel, or a pipe's sending end, the task's TaskEnd is
                sent on as it ends; one channel can take the ends of many
                tasks. The task is detached: reaped as it ends, not waited
                for, its failure sent, not logged. The ending task does not
                wait for room: an end that finds the channel full waits on
                the loop, so ends come in end order only while there is room,
                and one still waiting when the runtime stops is lost. On a
                closed channel the end is dropped. Through a pipe, an end
                that cannot be pickled and unpickled again is sent with a
                RuntimeError naming why, in place of its result and
                exception.

        Raises:
            RuntimeError: If the runtime is not running.
        """
        if token is None:
            parent = current_task()
            token = self._root if parent is None else parent.token
        token = token.child()
        with self._lock:
            if not self._started_runtime or self._closing:
                token.detach()
                raise RuntimeError("runtime is not running")
            task_id = self._next_task_id
            self._next_task_id += 1
            task = self._task_for(task_id, fn, args, token)
            task.ends = ends
            task.detached = ends is not None
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
        """Once *task*'s call has ended: reap it if it is detached, then send
        its end on its *ends*, or log its failure if it has none."""
        with self._lock:
            task.ended = True
            reap = task.detached
            if reap:
                self._tasks.pop(task.task_id, None)
        if not reap:
            return
        if task.ends is None:
            self._log_failure(task)
            return
        end = TaskEnd(task.task_id, task.result, task.exception, task.stopped)
        self._send_end(task.ends, end)

    def _send_end(self, ends: Chan[TaskEnd] | Sender[TaskEnd], end: TaskEnd) -> None:
        """Send *end* without waiting, on the ending task's thread or the
        loop's: neither may block on a receiver. A full channel gets it from
        the loop, once it has room."""
        if isinstance(ends, Sender):
            end = _portable(end)
        try:
            ends.send(end, timeout=0)
        except TimeoutError:
            # An empty context: the ending task's, copied by default, has its
            # stopped token, which would end the wait at once
            with contextlib.suppress(RuntimeError):  # the loop has stopped
                self._host.loop.call_soon_threadsafe(
                    self._send_later, ends, end, context=contextvars.Context()
                )
        except ClosedError:
            pass  # nobody receives any more

    def _send_later(self, ends: Chan[TaskEnd] | Sender[TaskEnd], end: TaskEnd) -> None:
        """On the loop: await room for *end* in an asyncio task of its own."""
        sending = asyncio.get_running_loop().create_task(_asend(ends, end))
        self._sending.add(sending)
        sending.add_done_callback(self._sending.discard)

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


def _portable(end: TaskEnd) -> TaskEnd:
    """*end*, if it survives a pickle round trip here; else one with a
    RuntimeError naming why, in place of its result and exception. The
    receiving side skips a value it cannot unpickle, and an end skipped
    there would never arrive. Costs a second pickle, once per task end."""
    try:
        pickle.loads(pickle.dumps(end))
    except Exception as e:
        error = RuntimeError(f"task {end.task_id} ended unpicklable: {e!r}")
        return TaskEnd(end.task_id, None, error, end.stopped)
    return end


async def _asend(ends: Chan[TaskEnd] | Sender[TaskEnd], end: TaskEnd) -> None:
    """Send *end* once *ends* has room; dropped if it is closed meanwhile."""
    with contextlib.suppress(ClosedError):
        await ends.asend(end)
