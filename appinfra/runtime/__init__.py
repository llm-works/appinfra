# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tasks, and the runtime that runs them: an async function as a task on the
runtime's event loop, any other function on a thread of its own. Imports
nothing from appinfra.service."""

from .loop import LoopHost
from .runtime import Runtime
from .stop import StopToken
from .task import LoopTask, Task, ThreadTask, stopping

__all__ = [
    "Runtime",
    "Task",
    "LoopTask",
    "ThreadTask",
    "LoopHost",
    "StopToken",
    "stopping",
]
