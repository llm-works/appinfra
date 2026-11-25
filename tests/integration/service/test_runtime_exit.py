# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""A Runtime left running when the interpreter exits stops its services."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

# Starts a runtime and a service, then exits without stop(); the service's
# teardown() prints a marker only a graceful stop gets to
SCRIPT = """
from unittest.mock import MagicMock

from appinfra.service import Runtime, Service


class Marks(Service):
    def __init__(self):
        self._lg = MagicMock()

    @property
    def name(self):
        return "marks"

    def run(self):
        self.stopping.wait()

    def teardown(self):
        print("torn down", flush=True)


rt = Runtime(MagicMock())
rt.start()
rt.ready(rt.spawn(Marks()))
print("running", flush=True)
"""


def test_a_runtime_not_stopped_stops_its_services_at_exit():
    result = subprocess.run(
        [sys.executable, "-c", SCRIPT],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["running", "torn", "down"], result.stdout
