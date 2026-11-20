# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""LoopHost and TaskRunner - many AsyncServices as tasks on one event loop."""

from __future__ import annotations

import asyncio
import contextlib
import threading
from types import TracebackType

from ..base import AsyncService
from ..state import RestartPolicy, State
from .base import Runner


class LoopHost:
    """An event loop on a thread of its own, running AsyncServices as tasks.

    runner() gives each service a TaskRunner; the runners share the loop, so a
    service waiting on an await holds no thread. stop() cancels the tasks still
    running and lets them finish before the loop closes.

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
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._serve, args=(self._loop,), name=self.name, daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the loop: cancel the tasks still running, let them finish, and
        wait up to *timeout* seconds for the thread to end.

        Raises:
            RuntimeError: If called from the loop's own thread.
        """
        if self._thread is None or self._loop is None:
            return
        if self.on_loop_thread():
            raise RuntimeError("LoopHost.stop() on the loop thread would block it")
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout)
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
        # Set by stop(); a task that has not started yet sees it and skips run()
        self._stop = threading.Event()
        # Set once the task has ended and the service is torn down
        self._done: threading.Event | None = None
        # The running task; set and cleared on the loop
        self._task: asyncio.Task[object] | None = None

    def start(self) -> None:
        """Run setup(), then start the service's task on the host's loop.

        Raises:
            RuntimeError: If the host is not running.
            InvalidTransitionError: If the runner is not CREATED, STOPPED or FAILED.
            SetupError: If setup fails.
        """
        loop = self._host.loop
        self._claim_start(self._stop)
        self._run_setup()
        self._transition(State.INITD)
        self._transition(State.STARTING)
        self._exception = None
        self._done = threading.Event()
        asyncio.run_coroutine_threadsafe(self._main(self._done), loop)

    async def _main(self, done: threading.Event) -> None:
        """The task: run the service, tear it down, settle the state."""
        self._task = asyncio.current_task()
        try:
            await self._run_service()
            self._teardown()
            self._settle_exit_state(self._exception)
        finally:
            self._task = None
            done.set()

    async def _run_service(self) -> None:
        """run(), unless a stop() came first. A cancel, from stop() or the host
        shutting down, ends it cleanly; any other exception is recorded."""
        if self._stop.is_set():
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
        self._stop.set()
        if self._done is not None:
            with contextlib.suppress(RuntimeError):  # host stopped: no task left
                self._host.loop.call_soon_threadsafe(self._cancel)
            if not self._done.wait(timeout):
                self.service.lg.warning(
                    "service task did not end in time",
                    extra={"service": self.name, "timeout": timeout},
                )
                return  # Stay STOPPING while the task still runs
        self._transition(State.STOPPED)

    def _cancel(self) -> None:
        """Cancel the running task, if any; called on the loop."""
        if self._task is not None:
            self._task.cancel()

    def is_alive(self) -> bool:
        """True while the service's task has not ended."""
        return self._done is not None and not self._done.is_set()

    def is_healthy(self) -> bool:
        """Check if service is healthy."""
        return self.service.is_healthy()

    @property
    def exception(self) -> BaseException | None:
        """Exception from run(), if any."""
        return self._exception
