# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Runtime: runs tasks on its event loop or on threads of their own."""

from __future__ import annotations

import asyncio
import atexit
import contextlib
import contextvars
import functools
import inspect
import multiprocessing as mp
import operator
import pickle
import threading
import time
from collections.abc import Callable
from multiprocessing.context import BaseContext
from types import TracebackType
from typing import Any, final

from ..log import Logger
from . import process as process_module
from .chan import Chan, ClosedError, Sender
from .errors import StoppedError
from .loop import LoopHost, _LoopTask
from .process import START_METHOD, _ProcessTask
from .stop import StopToken
from .task import Task, TaskDone, _current_task, _Task
from .thread import _ThreadTask


@final
class Runtime:
    """Runs tasks: spawn() takes a function, calls it once, from any thread,
    and returns its Task, whose id the runtime assigns and never reuses.

    - an async function: a task on the runtime's event loop (a LoopHost), shared
      by every async task, so one waiting on an await holds no thread
    - any other function: a thread of its own

    A task keeps its outcome: ``task.wait()`` in blocking code, ``await task``
    in a coroutine, as often as wanted. ``task.detach()`` gives up waiting:
    its failure is logged then, as nobody else sees it.

    Every task's token derives from the token of the task that spawned it, or
    from the runtime's; ``stopping()`` returns it inside the task, ``task_id()``
    its id. A task on a thread or the loop runs in a copy of the spawner's
    contextvars, as asyncio's create_task() and to_thread() do; a process
    task's child starts with a fresh context. stop() stops every task's token, cancels
    the tasks on the loop, and waits for the ones on threads.

    A task its stop ended has no result: wait() raises StoppedError for it,
    and a detached one is not logged as failed. A function that sees the stop
    and returns ends with its result.

    A task spawned with ``done`` is detached, and its TaskDone is sent on that
    channel (or pipe) as it ends, instead: one receiver learns of the ends of
    many tasks, as a Go supervisor reads them from one channel.

    Example:
        with Runtime(lg) as rt:
            server = rt.spawn(serve, port)   # async def serve(port): ...
            rt.spawn(consume, q).detach()    # def consume(q): ...
            server.cancel()
            with contextlib.suppress(StoppedError):
                server.wait(timeout=5.0)
    """

    def __init__(self, lg: Logger) -> None:
        """A runtime not yet started."""
        self._lg = lg
        self._host = LoopHost()
        self._root = StopToken()
        self._lock = threading.Lock()  # guards everything below
        # The tasks still running, for stop(); a task keeps its own outcome
        self._tasks: dict[int, _Task] = {}
        self._next_task_id = 1
        self._started_runtime = False
        self._closing = False
        # TaskDones awaiting room on a full done channel; loop thread only.
        # Held here: the loop keeps only a weak reference to a task
        self._sending: set[asyncio.Task[None]] = set()
        # One bound method every task reports its end to, not one per task
        self._end_hook = self._on_end

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

    @property
    def process_context(self) -> BaseContext:
        """The multiprocessing context a process task's child starts in. A
        queue, event or value shared with a child is made from it: one from
        another context fails in the child. The same as process_context()."""
        return process_context()

    # -- spawn --------------------------------------------------------------

    def spawn(
        self,
        fn: Callable[..., Any],
        *args: Any,
        name: str | None = None,
        token: StopToken | None = None,
        done: Chan[TaskDone] | Sender[TaskDone] | None = None,
        process: bool = False,
    ) -> Task:
        """Call *fn*(*args*) as a task: on the loop if it is an async function,
        else on a thread of its own, or in a process of its own if *process*.
        Returns the task.

        Args:
            fn: The function to call.
            *args: Its arguments.
            name: Who the task is: on its handle, its thread or asyncio task,
                its process, its log records and its TaskDone.
            token: The token the task's derives from, instead of the spawning
                task's or the runtime's. stop() stops the task all the same.
            done: A channel, or a pipe's sending end, the task's TaskDone is
                sent on as it ends; one channel can take the ends of many
                tasks. The task is detached: not waited for, its failure
                sent, not logged. The ending task does not
                wait for room: an end that finds the channel full waits on
                the loop, so ends come in end order only while there is room,
                and one still waiting when the runtime stops is lost. On a
                closed channel the end is dropped. Through a pipe, an end
                that cannot be pickled and unpickled again is sent with a
                RuntimeError naming why, in place of its result and error.
            process: Call *fn* in a child process, started with the ``spawn``
                method: *fn* and *args* are pickled, so *fn* is defined at
                module level, and process creation goes under ``if __name__ ==
                "__main__":``. Its result or exception comes back pickled; an
                exception carries the child's traceback as a note, which a
                done pipe keeps. The child is a fresh interpreter: it does not
                see the spawner's contextvars; stopping() and task_id() work
                there, as the child sets them up itself. The
                child's token stops with the task's, or once the parent is
                gone. A child that exits without an outcome fails the task
                with ProcessExitError. stop() kills one still running past its
                timeout.

        Raises:
            TypeError: If *name* is not a string, or *process* is asked for an
                async function: a child has no event loop.
            RuntimeError: If the runtime is not running.
        """
        name = _task_name(name)
        if process and _async_callable(fn):
            raise TypeError("an async function runs on the loop, not in a process")
        if token is None:
            parent = _current_task()
            token = self._root if parent is None else parent.token
        token = token.child()
        with self._lock:
            if not self._started_runtime or self._closing:
                token.detach()
                raise RuntimeError("runtime is not running")
            task_id = self._next_task_id
            self._next_task_id += 1
            t = self._task_for(task_id, name, fn, args, token, process)
            t.done_chan = done
            t.detached = done is not None
            self._tasks[task_id] = t
            # Under the lock, so stop() never finds a task here not launched
            self._launch(t)
        return Task._of(self, t)

    def _task_for(
        self,
        task_id: int,
        name: str | None,
        fn: Callable[..., Any],
        args: tuple[Any, ...],
        token: StopToken,
        process: bool,
    ) -> _Task:
        """The task that calls *fn*: in a process if asked, on the loop if it
        is an async function, else on a thread."""
        if process:
            return _ProcessTask(self._end_hook, task_id, name, fn, args, token)
        if inspect.iscoroutinefunction(fn):
            return _LoopTask(self._end_hook, self._host, task_id, name, fn, args, token)
        return _ThreadTask(self._end_hook, task_id, name, fn, args, token)

    def _launch(self, t: _Task) -> None:
        """Launch *t*; under the lock. A task the loop refuses leaves the
        runtime and its token the tree."""
        try:
            t.launch()
        except BaseException:
            del self._tasks[t.id]
            t.token.stop()
            t.token.detach()
            raise

    # -- a task's waits: Task.wait(), await task, Task.detach() --------------

    def _wait(self, t: _Task, timeout: float | None) -> Any:
        """Task.wait(): block until *t* has ended, then its outcome. Refused in
        *t*'s own context: its own thread, or a worker it handed its context
        to (asyncio.to_thread()), which *t* waits for in turn."""
        if _current_task() is t:
            raise RuntimeError(f"task {t.id} cannot wait for itself")
        with self._lock:
            if t.detached:
                raise RuntimeError(f"task {t.id} is detached")
            # Its outcome is settled once the end is recorded, though its
            # thread may not have run its last line yet: no wait for it then
            ended = t.ended
        # For both kinds: joining a thread blocks the loop as much as an
        # Event.wait() on it does. An ended task can still be collected
        if not ended and self._host.on_loop_thread():
            raise RuntimeError(f"waiting for task {t.id} on the loop would block it")
        if not ended and not t.join(timeout):
            raise TimeoutError(f"task {t.id} is still running")
        return _outcome(t)

    async def _await(self, t: _Task) -> Any:
        """``await task``: as _wait(), on the caller's loop, which a wake from
        _on_end() resumes. Cancelled, it leaves no wake behind."""
        if _current_task() is t:
            raise RuntimeError(f"task {t.id} cannot wait for itself")
        loop = asyncio.get_running_loop()
        ended: asyncio.Future[None] = loop.create_future()

        def wake() -> None:
            with contextlib.suppress(RuntimeError):  # the loop has closed
                loop.call_soon_threadsafe(_resolve, ended)

        with self._lock:
            if t.detached:
                raise RuntimeError(f"task {t.id} is detached")
            if t.ended:
                ended.set_result(None)
            else:
                if t.wakes is None:
                    t.wakes = []
                t.wakes.append(wake)
        try:
            await ended
        finally:
            with self._lock:
                if t.wakes is not None and wake in t.wakes:
                    t.wakes.remove(wake)
        return _outcome(t)

    def _detach(self, t: _Task) -> None:
        """Task.detach(): nobody waits for *t*; its failure is logged, now if
        it has ended, else by _on_end()."""
        with self._lock:
            if t.detached:
                return
            t.detached = True
            ended = t.ended
        if ended:
            self._log_failure(t)

    def _stop(self, t: _Task, timeout: float) -> None:
        """Task.stop(): cancel *t*; a killable one still running *timeout*
        seconds on is terminated, then killed _GRACE seconds later, on the
        loop's timers. Once the loop is stopping, stop() escalates instead."""
        t.cancel()
        if not t.killable or t.ended:
            return
        with contextlib.suppress(RuntimeError):  # the loop is stopping
            self._host._schedule(functools.partial(_force_later, t, timeout))

    def _on_end(self, t: _Task) -> None:
        """Once *t*'s call has ended: forget it, wake the awaits waiting for
        it, then, if it is detached, send its end on its *done*, or log its
        failure if it has none."""
        with self._lock:
            t.ended = True
            self._tasks.pop(t.id, None)
            wakes, t.wakes = t.wakes, None
            detached = t.detached
        for wake in wakes or ():
            wake()
        if not detached:
            return
        if t.done_chan is None:
            self._log_failure(t)
            return
        self._send_done(t.done_chan, TaskDone(t.id, t.name, t.result, _error(t)))

    def _send_done(
        self, done: Chan[TaskDone] | Sender[TaskDone], end: TaskDone
    ) -> None:
        """Send *end* without waiting, on the ending task's thread or the
        loop's: neither may block on a receiver. A full channel gets it from
        the loop, once it has room. A pipe gets the bytes its check pickled,
        on the Sender's own channel: pickled again, a result another thread
        is changing could fail where the check passed, and the end be lost."""
        chan: Chan[Any]
        value: Any  # a TaskDone, or a pipe's pickled bytes
        if isinstance(done, Sender):
            chan, value = done._chan, _portable(end)
        else:
            chan, value = done, end
        try:
            chan.send(value, timeout=0)
        except TimeoutError:
            # Through the host's gate: once it is stopping, the send would
            # start after the loop took the tasks to cancel, and outlive the
            # loop; the end is dropped instead. An empty context: the ending
            # task's has its stopped token, which would end the wait at once
            with contextlib.suppress(RuntimeError):  # the loop is stopping
                self._host._schedule(
                    functools.partial(
                        contextvars.Context().run, self._send_later, chan, value
                    )
                )
        except ClosedError:
            pass  # nobody receives any more

    def _send_later(self, chan: Chan[Any], value: Any) -> None:
        """On the loop: await room for *value* in an asyncio task of its own."""
        sending = asyncio.get_running_loop().create_task(_asend(chan, value))
        self._sending.add(sending)
        sending.add_done_callback(self._sending.discard)

    def _log_failure(self, t: _Task) -> None:
        """Log the failure of a task nobody waits for."""
        if t.exception is not None:
            self._lg.warning(
                "task failed",
                extra={"task_id": t.id, "task_name": t.name, "exception": t.exception},
            )

    # -- stop ---------------------------------------------------------------

    def stop(self, timeout: float = 5.0) -> None:
        """Stop every task's token, then the loop, which cancels the tasks on
        it; then wait for the tasks on threads and in processes. All of it
        takes at most *timeout* seconds: the loop, the thread and the process
        tasks share the one budget. A thread task still running then is logged
        and left, as a thread cannot be killed. Process tasks still running
        then are ended by force, on top of *timeout*: every child is sent
        SIGTERM and given _GRACE seconds, then every survivor SIGKILL and
        _GRACE seconds more; one still running after that is logged. The tasks
        keep their outcomes, to be waited for.

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
            running = list(self._tasks.values())
        atexit.unregister(self._atexit_stop)
        try:
            self._root.stop()
            # A task spawned by another runtime's task derives from that
            # task's token, outside this root's tree: its own token is stopped
            # as well
            for t in running:
                t.token.stop()
        finally:
            # Ctrl-C during the stops reaches the caller once the shutdown is
            # done: a second stop() returns at once
            self._host.stop(max(0.0, deadline - time.monotonic()))
            for t in self._still_running(running, deadline):
                self._lg.warning(
                    "task did not end in time",
                    extra={"task_id": t.id, "task_name": t.name, "timeout": timeout},
                )

    def _still_running(self, tasks: list[_Task], deadline: float) -> list[_Task]:
        """The *tasks* still running once the loop has stopped and the killable
        ones have been ended by force (_escalate())."""
        late = self._overdue(tasks, deadline)
        killable = _escalate([t for t in late if t.killable])
        return [t for t in late if not t.killable] + killable

    def _overdue(self, tasks: list[_Task], deadline: float) -> list[_Task]:
        """The *tasks* still running at *deadline*. A thread or process task is
        waited for until then; a loop task only checked, as the loop's stop had
        its time already. A task stopping the runtime does not wait for
        itself."""
        caller = _current_task()
        late = []
        for t in tasks:
            if t is caller:
                continue
            if isinstance(t, _LoopTask):
                ended = not t.is_running()
            else:
                ended = t.join(max(0.0, deadline - time.monotonic()))
            if not ended:
                late.append(t)
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


def _resolve(future: asyncio.Future[None]) -> None:
    """On its loop: resolve *future*, unless a cancel or timeout ended it."""
    if not future.done():
        future.set_result(None)


def _outcome(t: _Task) -> Any:
    """What *t*, ended, returned; or raise its error. What its call raised is
    raised from the task's own traceback each time, as asyncio.Future does:
    raised again as is, it would collect every wait's frames."""
    if t.exception is not None:
        raise t.exception.with_traceback(t.exception_tb)
    error = _error(t)
    if error is not None:
        raise error
    return t.result


def _error(t: _Task) -> BaseException | None:
    """How *t* ended, as an error: what its call raised, StoppedError if its
    stop ended it without a result, None if it returned."""
    if t.exception is not None:
        return t.exception
    if t.stopped:
        return StoppedError(f"task {t.id} was stopped")
    return None


def _escalate(late: list[_Task]) -> list[_Task]:
    """Terminate every one of *late*, killable tasks, then wait for them, all
    against one deadline _GRACE away; kill the survivors and wait for them the
    same way. No task's wait delays another's signal.

    Returns:
        The tasks still running after the kill's grace.
    """
    for end in (operator.methodcaller("terminate"), operator.methodcaller("kill")):
        if not late:
            break
        for t in late:
            end(t)
        grace = time.monotonic() + process_module._GRACE
        late = [t for t in late if not t.join(max(0.0, grace - time.monotonic()))]
    return late


def process_context() -> BaseContext:
    """The multiprocessing context every process task's child starts in, for
    what is shared with a child before any Runtime exists: a queue, event or
    value from another context fails in the child."""
    return mp.get_context(START_METHOD)


def _force_later(t: _Task, timeout: float) -> None:
    """On the loop: terminate *t* *timeout* seconds from now, if it still runs."""
    asyncio.get_running_loop().call_later(timeout, _terminate_late, t)


def _terminate_late(t: _Task) -> None:
    """On the loop: terminate *t*, which outlived its stop's timeout, and kill
    it _GRACE seconds later if it outlives that too."""
    if not t.ended:
        t.terminate()
        asyncio.get_running_loop().call_later(process_module._GRACE, _kill_late, t)


def _kill_late(t: _Task) -> None:
    """On the loop: kill *t*, which outlived its SIGTERM's grace."""
    if not t.ended:
        t.kill()


def _async_callable(fn: Callable[..., Any]) -> bool:
    """True if calling *fn* makes something only a loop can run: a coroutine
    function or an async generator function, or an object whose __call__ is
    one."""

    def is_async(f: object) -> bool:
        return inspect.iscoroutinefunction(f) or inspect.isasyncgenfunction(f)

    if is_async(fn):
        return True
    call = getattr(type(fn), "__call__", None)
    return not inspect.isfunction(fn) and is_async(call)


def _task_name(name: object) -> str | None:
    """spawn()'s *name* as a plain str: bypassing a subclass's own __str__,
    whose formatting or pickling could fail on the loop, a pipe or in a child,
    where the caller never sees it. A StrEnum becomes its value.

    Raises:
        TypeError: If *name* is not a string or None.
    """
    if name is None:
        return None
    if not isinstance(name, str):
        raise TypeError(f"task name must be a string, not {type(name).__name__}")
    return str.__str__(name)


def _portable(end: TaskDone) -> bytes:
    """*end* pickled, once the bytes unpickle here; else a TaskDone with a
    RuntimeError naming why, in place of its result and error, pickled. The
    receiving side skips a value it cannot unpickle, and an end skipped
    there would never arrive. Costs an unpickle, once per task."""
    try:
        payload = pickle.dumps(end)
        pickle.loads(payload)
    except Exception as e:
        error = RuntimeError(f"task {end.task_id} ended unpicklable: {e!r}")
        return pickle.dumps(TaskDone(end.task_id, end.name, None, error))
    return payload


async def _asend(chan: Chan[Any], value: Any) -> None:
    """Send *value* once *chan* has room; dropped if it is closed meanwhile."""
    with contextlib.suppress(ClosedError):
        await chan.asend(value)
