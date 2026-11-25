# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""TaskRunner - runs a service as a task on an appinfra.runtime Runtime."""

from __future__ import annotations

import asyncio
import contextlib

from ...runtime import Runtime as Tasks
from ...runtime import StoppedError, StopToken, Task
from ..base import AsyncService, ScheduledService
from ..state import RestartPolicy, State
from .drive import drive
from .runner import Runner


class TaskRunner(Runner):
    """Runs a service as a task on *tasks*, an appinfra.runtime Runtime: an
    AsyncService's run() on its event loop, shared by every async service, any
    other service's work (see drive()) on a thread of its own.

    setup() runs on the thread that calls start(). Once the work has ended,
    however it ended, the run's stopping token stops, so work derived from it
    is told to stop, and the service is torn down on the task. A synchronous
    service with a run() of its own is also torn down by stop(), which can
    release a run() blocked on something other than its token; a scheduled
    service is torn down only on its thread, so teardown never overlaps tick().

    Example:
        with Runtime(lg) as tasks:          # appinfra.runtime
            runner = TaskRunner(tasks, my_service)
            runner.start()
            runner.wait_healthy(timeout=30.0)
            ...
            runner.stop()
    """

    def __init__(
        self,
        tasks: Tasks,
        service: object,
        policy: RestartPolicy | None = None,
        *,
        parent: StopToken | None = None,
    ) -> None:
        """Initialize task runner.

        Args:
            tasks: The runtime the service's work runs on, as a task.
            service: The service to run.
            policy: Restart policy.
            parent: The token the service's stopping token derives from.

        Raises:
            TypeError: If *service* is not a Service (see check_service()).
        """
        super().__init__(service, policy, parent=parent)
        self._tasks = tasks
        self._task: Task | None = None
        self._exception: BaseException | None = None
        # Runs launched, and the last one torn down: once per run, by whichever
        # comes first of the run's end and a stop(). A number, not the task: a
        # run may end before spawn() has returned its task
        self._run = 0
        self._torn_down = 0

    @property
    def _tears_down_on_stop(self) -> bool:
        """True if stop() tears the service down too: a synchronous service with
        a run() of its own, which teardown can release."""
        return not isinstance(self.service, (ScheduledService, AsyncService))

    def _launch(self) -> None:
        """Spawn the service's work as a task, its token derived from the
        service's; if the runtime is not running, tear the service down and
        fail."""
        self._exception = None
        self._run += 1
        work = self._awork if isinstance(self.service, AsyncService) else self._work
        try:
            self._task = self._tasks.spawn(
                work, self._run, name=f"svc-{self.name}", token=self.service.stopping
            )
        except RuntimeError:
            self._end_run(self._run, None)
            self._transition(State.FAILED)
            raise

    def _work(self, run: int) -> None:
        """Thread task: the service's work, then the run's end."""
        error: BaseException | None = None
        try:
            drive(self.service, self.service.stopping)
        except BaseException as e:
            error = e
        self._end_run(run, error)

    async def _awork(self, run: int) -> None:
        """Loop task: run(), then the run's end. A cancel, from stop() or the
        runtime stopping, ends it cleanly."""
        error: BaseException | None = None
        try:
            await self.service.run()  # type: ignore[misc]
        except asyncio.CancelledError:
            pass
        except BaseException as e:
            error = e
        self._end_run(run, error)

    def _end_run(self, run: int, error: BaseException | None) -> None:
        """Once *run*'s work has ended: record *error*, stop the run's token,
        tear the service down unless stop() did, and settle the state."""
        self._exception = error
        self.service.stopping.stop()
        self._teardown_once(run)
        self._settle_exit_state(error)

    def _teardown_once(self, run: int) -> None:
        """Tear the service down for *run*, unless that run was torn down
        already."""
        with self._lock:
            if self._torn_down >= run:
                return
            self._torn_down = run
        self._teardown()

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the service: stop its token, cancel its task, and wait up to
        *timeout* seconds for the work to end and the service to be torn down.
        A start() in progress on another thread is waited for first; both waits
        together take at most *timeout*.

        Raises:
            RuntimeError: If called from one of this runner's state hooks, or,
                with the stop under way, from the runtime's loop or the
                service's own thread, which the wait would block.
        """
        self._refuse_from_hook("stop")
        left = self._start_ended(timeout)
        if left is None:
            return
        if self._state in (State.CREATED, State.STOPPED, State.STOPPING, State.DONE):
            return
        self._transition(State.STOPPING)
        self.service.stopping.stop()
        task, run = self._task, self._run
        if task is not None:
            if self._tears_down_on_stop:
                self._teardown_once(run)
            task.cancel()
            if not self._ended(task, left):
                return  # Stay STOPPING; the task moves the runner to STOPPED once it ends
        # A run its stop skipped never reached its own teardown
        self._teardown_once(run)
        self._transition_from(State.STOPPING, State.STOPPED)

    def _ended(self, task: Task, timeout: float) -> bool:
        """Wait up to *timeout* seconds for *task* to end; False, logged, if it
        is still running then."""
        try:
            with contextlib.suppress(StoppedError):  # Its stop skipped the call
                task.wait(timeout)
        except TimeoutError:
            self.service.lg.warning(
                "service task did not end in time",
                extra={"service": self.name, "timeout": timeout},
            )
            return False
        return True

    def is_alive(self) -> bool:
        """True while the service's task has not ended."""
        task = self._task
        return task is not None and task.alive()

    def is_healthy(self) -> bool:
        """Check if service is healthy."""
        return self.service.is_healthy()

    @property
    def exception(self) -> BaseException | None:
        """Exception from the service's work, if any."""
        return self._exception
