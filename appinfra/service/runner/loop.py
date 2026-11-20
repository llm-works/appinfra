# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""LoopHost and TaskRunner - many AsyncServices as tasks on one event loop."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from types import TracebackType

from ..base import AsyncService
from ..state import RestartPolicy, State
from .base import Runner


class LoopHost:
    """An event loop on a thread of its own, running AsyncServices as tasks.

    runner() gives each service a TaskRunner; the runners share the loop, so a
    service waiting on an await holds no thread. Once stop() begins, the host
    takes no new tasks; it cancels the tasks still running and lets them finish
    before the loop closes.

    Example:
        with LoopHost() as host:
            runner = host.runner(MyAsyncService(lg))
            runner.start()
            runner.wait_healthy()
            ...
            runner.stop()
    """

    def __init__(self, name: str = "loop-host") -> None:
        """Initialize host.

        Args:
            name: Name of the loop's thread.
        """
        self.name = name
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
            raise RuntimeError(f"loop host '{self.name}' is not running")
        return self._loop

    def on_loop_thread(self) -> bool:
        """True when called from the loop's own thread."""
        return self._thread is not None and threading.current_thread() is self._thread

    def _schedule(self, callback: Callable[[], object]) -> None:
        """Run *callback* on the loop soon; for TaskRunner.

        Raises:
            RuntimeError: If the host is not running, or stop() has begun.
        """
        with self._lock:
            if self._closing:
                raise RuntimeError(f"loop host '{self.name}' is stopping")
            self.loop.call_soon_threadsafe(callback)

    def runner(
        self, service: AsyncService, policy: RestartPolicy | None = None
    ) -> TaskRunner:
        """A TaskRunner for *service* on this host's loop."""
        return TaskRunner(self, service, policy)

    def start(self) -> None:
        """Start the loop on its own thread.

        Raises:
            RuntimeError: If the host is already started.
        """
        if self._thread is not None:
            raise RuntimeError(f"loop host '{self.name}' is already started")
        self._closing = False
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._serve, args=(self._loop,), name=self.name, daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the loop: cancel the tasks still running, let them finish, and
        wait up to *timeout* seconds for the thread to end. If it is still
        ending then, the host stays running, closed to new tasks, and a later
        stop() waits for it again.

        Raises:
            RuntimeError: If called from the loop's own thread.
        """
        if self._thread is None or self._loop is None:
            return
        if self.on_loop_thread():
            raise RuntimeError("LoopHost.stop() on the loop thread would block it")
        with self._lock:
            if not self._closing:
                self._closing = True
                self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout)
        if self._thread.is_alive():
            return
        self._thread = None
        self._loop = None

    @staticmethod
    def _serve(loop: asyncio.AbstractEventLoop) -> None:
        """Thread target: run *loop* until stop(), then end its tasks, as
        asyncio.run() does, and close it."""
        asyncio.set_event_loop(loop)
        try:
            loop.run_forever()
            tasks = asyncio.all_tasks(loop)
            for task in tasks:
                task.cancel()
            loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.run_until_complete(loop.shutdown_default_executor())
        finally:
            loop.close()

    def __enter__(self) -> LoopHost:
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.stop()


class TaskRunner(Runner):
    """Runs an AsyncService as a task on a LoopHost's event loop.

    Created by LoopHost.runner(). setup() runs on the thread that calls start();
    run(), then teardown(), run on the loop. stop() cancels the task, raising
    CancelledError at the await run() is parked on, and waits for teardown().
    A failure in run() fails this service only; the loop and its other services
    run on.
    """

    def __init__(
        self,
        host: LoopHost,
        service: AsyncService,
        policy: RestartPolicy | None = None,
    ) -> None:
        """Initialize task runner.

        Args:
            host: The LoopHost whose loop runs the service.
            service: The async service to run.
            policy: Restart policy.

        Raises:
            TypeError: If *service* is not an AsyncService.
        """
        super().__init__(service, policy)
        if not isinstance(service, AsyncService):
            raise TypeError(
                f"TaskRunner runs an AsyncService; '{self.name}' takes a "
                "ThreadRunner or ProcessRunner"
            )
        self._host = host
        self._service = service
        self._exception: BaseException | None = None
        # Plain flags, not threading.Events, so that an idle service costs no
        # lock or condition: an Event exists only while a stop() waits.
        # Set by stop(); read on the loop, where a task that has not begun yet
        # sees it and skips run()
        self._stop_requested = False
        # True from start() until the task has ended and torn the service down
        self._running = False
        # The task; held here because the loop keeps only a weak reference
        self._task: asyncio.Task[None] | None = None
        # Events of stop() calls waiting for the task to end; loop thread only
        self._waiters: list[threading.Event] | None = None

    def _reset_stop(self) -> None:
        self._stop_requested = False

    def start(self) -> None:
        """Run setup(), then start the service's task on the host's loop.

        Raises:
            RuntimeError: If the host is not running or is stopping; a service
                already set up is torn down and the runner FAILED.
            InvalidTransitionError: If the runner is not CREATED, STOPPED or FAILED.
            SetupError: If setup fails.
        """
        self._host.loop  # fails before any state change if the host is not running
        self._begin_start()
        self._exception = None
        self._running = True
        try:
            self._host._schedule(self._spawn)
        except RuntimeError:
            self._running = False
            self._teardown()
            self._transition(State.FAILED)
            raise

    def _spawn(self) -> None:
        """Create the service's task; called on the loop. _finish() runs when
        it ends, however it ends: also when cancelled before its first step,
        when the task's own code never runs."""
        task = asyncio.get_running_loop().create_task(
            self._run_service(), name=f"svc-{self.name}"
        )
        task.add_done_callback(self._finish)
        self._task = task

    def _finish(self, task: asyncio.Task[None]) -> None:
        """On the loop, once the task has ended: tear the service down, settle
        the state, and wake the stop() calls waiting for it."""
        self._teardown()
        self._settle_exit_state(self._exception)
        self._task = None
        self._running = False
        waiters, self._waiters = self._waiters, None
        for waiter in waiters or ():
            waiter.set()

    async def _run_service(self) -> None:
        """run(), unless a stop() came first. A cancel, from stop() or the host
        shutting down, ends it cleanly; any other exception is recorded."""
        if self._stop_requested:
            return
        try:
            await self._service.run()
        except asyncio.CancelledError:
            pass
        except BaseException as e:
            self._exception = e

    def stop(self, timeout: float = 5.0) -> None:
        """Cancel the service's task and wait up to *timeout* seconds for it to
        end and the service to be torn down.

        Raises:
            RuntimeError: If called from the host's loop thread, which the wait
                would block.
        """
        if self._state in (State.CREATED, State.STOPPED, State.STOPPING, State.DONE):
            return
        if self._host.on_loop_thread():
            raise RuntimeError("TaskRunner.stop() on the loop thread would block it")

        self._transition(State.STOPPING)
        self._stop_requested = True
        if self._running and not self._wait_ended(timeout):
            self.service.lg.warning(
                "service task did not end in time",
                extra={"service": self.name, "timeout": timeout},
            )
            return  # Stay STOPPING; the task moves the runner to STOPPED once it ends
        # The task, ending, has usually moved the runner to STOPPED already
        self._transition_from(State.STOPPING, State.STOPPED)

    def _wait_ended(self, timeout: float) -> bool:
        """Cancel the task and wait up to *timeout* seconds for it to end.

        Returns:
            False if it is still running after *timeout*.
        """
        ended = threading.Event()
        try:
            self._host.loop.call_soon_threadsafe(self._cancel, ended)
        except RuntimeError:
            return True  # Host stopped: its shutdown ended the task
        return ended.wait(timeout)

    def _cancel(self, ended: threading.Event) -> None:
        """On the loop: set *ended* once the task has ended, and cancel it. A
        task not created yet sees the stop request and skips run()."""
        if not self._running:
            ended.set()
            return
        if self._waiters is None:
            self._waiters = []
        self._waiters.append(ended)
        if self._task is not None:
            self._task.cancel()

    def is_alive(self) -> bool:
        """True while the service's task has not ended."""
        return self._running

    def is_healthy(self) -> bool:
        """Check if service is healthy."""
        return self.service.is_healthy()

    @property
    def exception(self) -> BaseException | None:
        """Exception from run(), if any."""
        return self._exception
