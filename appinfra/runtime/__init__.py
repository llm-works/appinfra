# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tasks, and the runtime that runs them: an async function as a task on the
runtime's event loop, any other function on a thread of its own. Imports
nothing from appinfra.service.

Built on, not extended: what is exported here is the whole API. Runtime and
Task are final, and the kinds of task are the runtime's own; layers above
compose spawn(), Chan and StopToken."""

from .chan import Chan, aselect, select
from .chan import ClosedError as ChanClosedError
from .chan import Recv as ChanRecv
from .chan import Send as ChanSend
from .errors import ProcessExitError, StoppedError
from .runtime import Runtime, process_context
from .stop import StopToken
from .task import (
    ProcessDetail,
    Task,
    TaskDone,
    TaskKind,
    TaskProcess,
    stopping,
    task_id,
)

__all__ = [
    "Chan",
    "ChanClosedError",
    "ChanRecv",
    "ChanSend",
    "ProcessDetail",
    "Runtime",
    "StopToken",
    "ProcessExitError",
    "StoppedError",
    "Task",
    "TaskDone",
    "TaskKind",
    "TaskProcess",
    "aselect",
    "process_context",
    "select",
    "stopping",
    "task_id",
]
