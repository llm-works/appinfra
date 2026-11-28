# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""A Runtime left running when the interpreter exits stops its tasks."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

# Starts a runtime and a task, then exits without stop(); the task prints a
# marker only once its token stops
SCRIPT = """
import threading
from unittest.mock import MagicMock

from appinfra.runtime import Runtime, this_task

entered = threading.Event()


def marks():
    entered.set()
    this_task().token.wait()
    print("stopped", flush=True)


rt = Runtime(MagicMock())
rt.start()
rt.spawn(marks)
entered.wait(5.0)
print("running", flush=True)
"""


def test_a_runtime_not_stopped_stops_its_tasks_at_exit():
    result = subprocess.run(
        [sys.executable, "-c", SCRIPT],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["running", "stopped"], result.stdout
