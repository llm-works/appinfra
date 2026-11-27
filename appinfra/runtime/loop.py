# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""The runtime's event loop, on a thread of its own (LoopHost), and the tasks
whose calls run on it."""

from __future__ import annotations

import asyncio
import contextlib
import threading
from collections.abc import Callable
from typing import Any

from .errors import StoppedError
from .stop import StopToken
from .task import TaskKind, _label, _Task

# Prefixed, as the stdlib names the threads it creates: a thread dump shows whose it is
THREAD_NAME = "appinfra-loop"


class LoopHost:
    """The runtime's event loop, on a thread of its own, shared by every async
    task, so one waiting on an await holds no thread. Once stop() begins, the
    host takes no new tasks; it cancels the tasks still running and lets them
    finish before the loop closes. The runtime stops every task's token first.
    """

    def __init__(self) -> None:
        """A host not yet started."""
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        # Orders _schedule() against stop(): what is scheduled before stop()
        # begins runs before the loop stops, so its shutdown sees the task
        self._lock = threading.Lock()
        self._closing = False

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        """The running loop.

        Raises:
            RuntimeError: Before start() or after stop().
        """
        if self._loop is None or self._thread is None or not self._thread.is_alive():
            raise RuntimeError("runtime loop is not running")
        return self._loop

    def on_loop_thread(self) -> bool:
        """True when called from the loop's own thread."""
        return self._thread is not None and threading.current_thread() is self._thread

    def _schedule(self, callback: Callable[[], object]) -> None:
        """Run *callback* on the loop soon.

        Raises:
            RuntimeError: If the host is not running, or stop() has begun.
        """
        with self._lock:
            if self._closing:
                raise RuntimeError("runtime loop is stopping")
            self.loop.call_soon_threadsafe(callback)

    def start(self) -> None:
        """Start the loop on its own thread; once."""
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._serve, args=(self._loop,), name=THREAD_NAME, daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the loop: cancel the tasks still running, let them finish, and
        wait up to *timeout* seconds for the thread to end. If it is still
        ending then, the host stays closed to new tasks, and a later stop()
        waits for it again.

        Raises:
            RuntimeError: If called from the loop's own thread.
        """
        if self._thread is None or self._loop is None:
            return
        if self.on_loop_thread():
            raise RuntimeError(
                "stopping the runtime loop on its own thread would block it"
            )
        with self._lock:
            if not self._closing:
                self._closing = True
                self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout)
        if self._thread.is_alive():
            return
        self._thread = None
        self._loop = None

    def _serve(self, loop: asyncio.AbstractEventLoop) -> None:
        """Thread target: run *loop* until stop(), then end its tasks, as
        asyncio.run() does, and close it."""
        asyncio.set_event_loop(loop)
        try:
            _resumed(loop.run_forever, lambda: self._after_exit(loop))
            tasks = asyncio.all_tasks(loop)
            for task in tasks:
                task.cancel()
            gathered = asyncio.gather(*tasks, return_exceptions=True)
            # Ends once everything gathered has: resumed until then
            _resumed(lambda: loop.run_until_complete(gathered), lambda: None)
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.run_until_complete(loop.shutdown_default_executor())
        finally:
            loop.close()

    def _after_exit(self, loop: asyncio.AbstractEventLoop) -> None:
        """Before the run of *loop* until stop() resumes after an exit. An exit
        leaves an iteration partway: run_forever() forgets a stop run in it,
        and a stop queued behind it has not run. Once stop() has begun, the
        loop is stopped again, so the resumed run ends after one iteration,
        which runs a stop still queued: one left for the run that waits for
        the cancelled tasks would end it before they finish. Read under the
        lock, which stop() queues its stop under."""
        with self._lock:
            closing = self._closing
        if closing:
            loop.stop()


def _resumed(run: Callable[[], object], before_resume: Callable[[], None]) -> None:
    """*run*, a run of the loop, resumed when a task's SystemExit or
    KeyboardInterrupt comes out of it, after *before_resume*(). asyncio
    records the exit as that task's outcome, then re-raises it from the
    loop, which would end every other task with it; the task's own end is
    already scheduled on the loop."""
    while True:
        try:
            run()
            return
        except (SystemExit, KeyboardInterrupt):
            before_resume()


class _LoopTask(_Task):
    """Runs an async function as a task on a LoopHost's loop, so one waiting on
    an await holds no thread. cancel() raises CancelledError at the await it is
    parked on; a cancel is a stop."""

    __slots__ = ("_host", "_aio", "_finished", "_waiters")

    stop_signals = (asyncio.CancelledError, StoppedError)

    kind = TaskKind.LOOP

    def __init__(
        self,
        on_end: Callable[[_Task], None],
        host: LoopHost,
        task_id: int,
        name: str | None,
        fn: Callable[..., Any],
        args: tuple[Any, ...],
        token: StopToken,
    ) -> None:
        """Initialize task on *host*'s loop; see _Task for the rest."""
        super().__init__(on_end, task_id, name, fn, args, token)
        self._host = host
        # Held here: the loop keeps only a weak reference to a task
        self._aio: asyncio.Task[None] | None = None
        self._finished = False
        # Events of join() calls waiting for the task to end; loop thread only
        self._waiters: list[threading.Event] | None = None

    def launch(self) -> None:
        """Schedule the task's creation on the loop.

        Raises:
            RuntimeError: If the host is not running, or is stopping.
        """
        self._host._schedule(self._spawn)

    def _spawn(self) -> None:
        """Make the call's coroutine the asyncio task, in the task's context;
        called on the loop. A task whose token is stopped by then skips the
        call. _finish() runs when the asyncio task ends, however it ends: also
        when cancelled before its first step, when the call never runs. No
        coroutine of the runtime's wraps the call: a parked task holds the
        call's frame alone."""
        if self.token.is_set():
            self.stopped = True
            self._ended_on_loop()
            return
        try:
            coro = self._coroutine()
        except BaseException as e:  # Calling the function made no coroutine
            self._raised(e)
            self._ended_on_loop()
            return
        loop = asyncio.get_running_loop()
        # Queued before the task's first step, so it runs right before it
        loop.call_soon(self._check_start, context=self._context)
        aio = loop.create_task(
            coro, name=_label(self.id, self.name), context=self._context
        )
        # In the task's context: without one, asyncio copies the loop's for it
        aio.add_done_callback(self._finish, context=self._context)
        self._aio = aio

    def _check_start(self) -> None:
        """On the loop, right before the task's first step: cancel the task if
        its token was stopped since _spawn(), as a parent that returns right
        after spawning stops it. A task cancelled before its first step never
        calls its function, and is recorded as a stop."""
        if self.token.is_set() and self._aio is not None:
            self._aio.cancel()

    def _coroutine(self) -> Any:
        """The call's coroutine; its frame holds the function's arguments,
        and this one's frame, gone once it returns, the function and them."""
        fn, args = self._take_call()
        return fn(*args)

    def _finish(self, aio: asyncio.Task[Any]) -> None:
        """On the loop, once the asyncio task has ended: record how the call
        ended, end the task and wake the join() calls waiting for it."""
        self._aio = None
        self._record(aio)
        self._ended_on_loop()

    def _record(self, aio: asyncio.Task[Any]) -> None:
        """Record the outcome of *aio*, as _raised() does for a call that
        raised. It runs after the call ended, behind what was scheduled
        before, which may stop the token: a cancelled task is told apart by
        asyncio's record of it instead. One cancelled by cancel() or the
        host's shutdown, asked to cancel once its token was stopped, is a
        stop; one whose call raised CancelledError on its own, never asked
        to, is a failure. A StoppedError the call raises is still read
        against the token here, not when it was raised: no frame of the
        runtime's wraps the call. The runtime raises it only on a stopped
        token; a call raising it on a running one, with a stop landing before
        this runs, is recorded as a stop."""
        if aio.cancelled():
            if aio.cancelling() and self.token.is_set():
                self.stopped = True
                return
            try:
                aio.result()
            except asyncio.CancelledError as e:
                self.exception, self.exception_tb = e, e.__traceback__
            return
        error = aio.exception()
        if error is None:
            self.result = aio.result()
        else:
            self._raised(error)

    def _ended_on_loop(self) -> None:
        """On the loop, once the call has ended or was skipped: end the task
        and wake the join() calls waiting for it."""
        waiters, self._waiters = self._waiters, None
        self._end()
        # Last, so the outcome is settled before is_running() reports the end
        self._finished = True
        for waiter in waiters or ():
            waiter.set()

    def cancel(self) -> None:
        """Stop the task's token and cancel it on the loop. A task not begun
        yet sees the token and skips the call. Ctrl-C during the stop reaches
        the caller once the cancel is scheduled."""
        try:
            self.token.stop()
        finally:
            # RuntimeError: the host stopped, and its shutdown ended the task
            with contextlib.suppress(RuntimeError):
                self._host.loop.call_soon_threadsafe(self._cancel)

    def _cancel(self) -> None:
        """On the loop: cancel the asyncio task, if it is still running."""
        if self._aio is not None:
            self._aio.cancel()

    def join(self, timeout: float | None = None) -> bool:
        """Block up to *timeout* seconds for the task to end.

        Raises:
            RuntimeError: If called on the loop thread while the task runs,
                which the wait would block.
        """
        if not self.is_running():
            return True
        if self._host.on_loop_thread():
            raise RuntimeError(f"waiting for task {self.id} on the loop would block it")
        ended = threading.Event()
        try:
            self._host.loop.call_soon_threadsafe(self._watch, ended)
        except RuntimeError:
            return True  # Host stopped: its shutdown ended the task
        if ended.wait(timeout):
            return True
        # Timed out: drop the registration, or every poll would leave one
        with contextlib.suppress(RuntimeError):  # Host stopped: nothing to drop
            self._host.loop.call_soon_threadsafe(self._unwatch, ended)
        return False

    def _watch(self, ended: threading.Event) -> None:
        """On the loop: set *ended* once the task has ended."""
        if not self.is_running():
            ended.set()
            return
        if self._waiters is None:
            self._waiters = []
        self._waiters.append(ended)

    def _unwatch(self, ended: threading.Event) -> None:
        """On the loop: forget *ended*, whose wait timed out; once the task has
        ended, _finish() has cleared the list already."""
        if self._waiters is not None and ended in self._waiters:
            self._waiters.remove(ended)

    def is_running(self) -> bool:
        """True until the asyncio task has ended."""
        return not self._finished
