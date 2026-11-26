# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Errors of the runtime."""


class StoppedError(Exception):
    """A wait ended because the token of the task it runs in was stopped: a
    channel's send or receive, or Task.wait() or ``await task`` for a task its
    stop ended before it returned. A task that ends with it while its token is stopped is
    stopped, not failed."""


class ProcessExitError(Exception):
    """A task's process exited without reporting how its call ended: killed,
    crashed, or ended by os._exit(). *exitcode* is the process's: negative for
    the signal that ended it."""

    def __init__(self, task_id: int, exitcode: int | None) -> None:
        self.task_id = task_id
        self.exitcode = exitcode
        super().__init__(f"task {task_id}'s process exited with code {exitcode}")
