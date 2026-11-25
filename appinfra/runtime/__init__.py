# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tasks, and the runtime that runs them: an async function as a task on the
runtime's event loop, any other function on a thread of its own. Imports
nothing from appinfra.service."""

from .chan import Chan, aselect, select
from .chan import ClosedError as ChanClosedError
from .chan import Recv as ChanRecv
from .chan import Send as ChanSend
from .errors import StoppedError
from .runtime import Runtime
from .stop import StopToken
from .task import stopping, task_id

__all__ = [
    "Chan",
    "ChanClosedError",
    "ChanRecv",
    "ChanSend",
    "Runtime",
    "StopToken",
    "StoppedError",
    "aselect",
    "select",
    "stopping",
    "task_id",
]
