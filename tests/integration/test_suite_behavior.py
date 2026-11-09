# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""What a test does on threads other than its own (appinfra._suite_behavior)."""

from __future__ import annotations

import threading

from appinfra._suite_behavior import SOCKET, Recorder
from tests.helpers.suite_behavior import PROJECT


class TestRecorder:
    """The recorder here is not installed: events are handed to it directly."""

    def test_another_thread_is_not_charged(self) -> None:
        """A thread left running by an earlier test works on its own time: its events are
        not the running test's."""
        recorder = Recorder(PROJECT)

        def elsewhere() -> None:
            recorder.audit("os.chdir", ("/x",))
            recorder.note((SOCKET, "socket.bind"))

        with recorder.running("t.py::test_a"):
            thread = threading.Thread(target=elsewhere)
            thread.start()
            thread.join()
        assert recorder.evidence("t.py::test_a", []) == {}
