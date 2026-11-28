# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tasks, and the runtime that runs them: an async function as a task on the
runtime's event loop, any other function on a thread of its own. Imports
nothing from appinfra.service.

Built on, not extended: what is exported here is the whole API. Runtime and
Task are final, and the kinds of task are the runtime's own; layers above
compose spawn(), Chan and StopToken."""

from .chan import Chan, Correlator, aselect, select
from .chan import ClosedError as ChanClosedError
from .chan import Recv as ChanRecv
from .chan import ResponseError as ChanResponseError
from .chan import Send as ChanSend
from .config import Config, ProcessConfig
from .errors import ProcessExitError, StoppedError
from .factory import Factory
from .runtime import Runtime, process_context
from .stop import StopToken
from .task import (
    ProcessDetail,
    Task,
    TaskContext,
    TaskDone,
    TaskKind,
    TaskProcess,
    this_task,
)

__all__ = [
    "Chan",
    "ChanClosedError",
    "ChanRecv",
    "ChanResponseError",
    "ChanSend",
    "Config",
    "Correlator",
    "Factory",
    "ProcessConfig",
    "ProcessDetail",
    "Runtime",
    "StopToken",
    "ProcessExitError",
    "StoppedError",
    "Task",
    "TaskContext",
    "TaskDone",
    "TaskKind",
    "TaskProcess",
    "aselect",
    "process_context",
    "select",
    "this_task",
]
