# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tasks, and the runtime that runs them: an async function as a task on the
runtime's event loop, any other function on a thread of its own. Imports
nothing from appinfra.service.

Built on, not extended: what is exported here is the whole API. Runtime and
Task are final, and the kinds of task are the runtime's own; layers above
compose spawn(), Chan, pipe() and StopToken."""

from .chan import Chan, aselect, select
from .chan import ClosedError as ChanClosedError
from .chan import Recv as ChanRecv
from .chan import Send as ChanSend
from .errors import StoppedError
from .runtime import Runtime, Task
from .stop import StopToken
from .task import TaskDone, stopping, task_id

__all__ = [
    "Chan",
    "ChanClosedError",
    "ChanRecv",
    "ChanSend",
    "Runtime",
    "StopToken",
    "StoppedError",
    "Task",
    "TaskDone",
    "aselect",
    "select",
    "stopping",
    "task_id",
]
