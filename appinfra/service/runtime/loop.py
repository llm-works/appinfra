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
from .runner import Runner


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
        # Runners whose task is alive; loop thread only. The shutdown stops their
        # tokens before it cancels the tasks, as TaskRunner.stop() does
        self._runners: set[TaskRunner] = set()

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
        self._runners = set()
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

    def _serve(self, loop: asyncio.AbstractEventLoop) -> None:
        """Thread target: run *loop* until stop(), then end its tasks, as
        asyncio.run() does, and close it. The services' tokens stop before
        their tasks are cancelled: a run that waits for its own work while it
        is cancelled needs that work told to stop first."""
        asyncio.set_event_loop(loop)
        try:
            loop.run_forever()
            for runner in list(self._runners):
                runner.service.stopping.stop()
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
    run on. If the host is already stopping when start() schedules the task,
    teardown() runs on the thread that called start(), like setup(): the loop
    may run no more work.
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
        # Plain counts, not threading.Events, so that an idle service costs no
        # lock or condition: an Event exists only while a stop() waits.
        # Runs launched by start() and runs whose task has ended and torn the
        # service down; alive while they differ. Counts, each with one writer,
        # not a flag: a run ending after a start() on another thread launched
        # a newer one counts itself, not the newer run.
        self._launched = 0
        self._ended = 0
        # The task; held here because the loop keeps only a weak reference.
        # None from start() until the task is created, so a run ending tells
        # whether a start() on another thread has begun a newer one meanwhile
        self._task: asyncio.Task[None] | None = None
        # Events of stop() calls waiting for the task to end; loop thread only
        self._waiters: list[threading.Event] | None = None

    def start(self) -> None:
        """Run setup(), then start the service's task on the host's loop.

        Raises:
            RuntimeError: If the host is not running or is stopping (a service
                already set up is torn down and the runner FAILED), or if
                called from one of this runner's state hooks.
            InvalidTransitionError: If the runner is not CREATED, STOPPED or FAILED.
            SetupError: If setup fails.
        """
        self._host.loop  # fails before any state change if the host is not running
        super().start()

    def _launch(self) -> None:
        """Schedule the service's task on the host's loop; if the host is
        stopping, tear the service down and fail."""
        self._exception = None
        self._task = None
        self._launched += 1
        try:
            self._host._schedule(self._spawn)
        except RuntimeError:
            self._launched -= 1
            # As when a run ends: work setup() derived stops before teardown()
            self.service.stopping.stop()
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
        self._host._runners.add(self)

    def _finish(self, task: asyncio.Task[None]) -> None:
        """On the loop, once *task* has ended: stop the run's token, tear the
        service down, settle the state, and wake the stop() calls waiting for it.

        The token stops however the task ended, also when the host cancelled it
        without a stop(): work derived from it is told to stop before
        teardown(). The state settles before the run is counted ended, so
        is_alive() never reports a RUNNING service as gone. Once it has settled,
        a start() on another thread may begin a new run, which resets _task;
        the new run's task is then left alone."""
        self.service.stopping.stop()
        if self._task is task:
            self._host._runners.discard(self)
        self._teardown()
        waiters, self._waiters = self._waiters, None
        self._settle_exit_state(self._exception)
        if self._task is task:
            self._task = None
        self._ended += 1
        for waiter in waiters or ():
            waiter.set()

    async def _run_service(self) -> None:
        """run(), unless a stop() came first. A cancel, from stop() or the host
        shutting down, ends it cleanly; any other exception is recorded."""
        if self._service.stopping.is_set():
            return
        try:
            await self._service.run()
        except asyncio.CancelledError:
            pass
        except BaseException as e:
            self._exception = e

    def stop(self, timeout: float = 5.0) -> None:
        """Cancel the service's task and wait up to *timeout* seconds for it to
        end and the service to be torn down. A start() in progress on another
        thread is waited for first; both waits together take at most *timeout*.

        Raises:
            RuntimeError: If called from one of this runner's state hooks, or
                from the host's loop thread on a runner that is starting or
                running, which the wait would block.
        """
        self._refuse_from_hook("stop")
        on_loop = self._host.on_loop_thread()
        # On the loop thread, not even a start() in progress is waited for
        if not on_loop:
            left = self._start_ended(timeout)
            if left is None:
                return
            timeout = left
        if self._state in (State.CREATED, State.STOPPED, State.STOPPING, State.DONE):
            return
        if on_loop:
            raise RuntimeError("TaskRunner.stop() on the loop thread would block it")

        self._transition(State.STOPPING)
        # Before the cancel: a task not begun yet sees it and skips run()
        self.service.stopping.stop()
        if self.is_alive() and not self._wait_ended(timeout):
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
        if not self.is_alive():
            ended.set()
            return
        if self._waiters is None:
            self._waiters = []
        self._waiters.append(ended)
        if self._task is not None:
            self._task.cancel()

    def is_alive(self) -> bool:
        """True while the service's task has not ended."""
        return self._ended != self._launched

    def is_healthy(self) -> bool:
        """Check if service is healthy."""
        return self.service.is_healthy()

    @property
    def exception(self) -> BaseException | None:
        """Exception from run(), if any."""
        return self._exception
