# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for an isolated service's health reporting in its child process."""

import threading
from unittest.mock import MagicMock

from appinfra.runtime import StopToken
from appinfra.service import Service
from appinfra.service.runtime import child


class Checked(Service):
    """is_healthy() returns True; *ends_run* stops the token first, as the run
    ending while a check blocks does."""

    def __init__(self, ends_run: bool) -> None:
        self._lg = MagicMock()
        self._ends_run = ends_run
        self.stopping = StopToken()

    @property
    def name(self) -> str:
        return "checked"

    def run(self) -> None:
        raise AssertionError("never run by these tests")

    def is_healthy(self) -> bool:
        if self._ends_run:
            self.stopping.stop()
        return True


def _report(service: Checked) -> threading.Event:
    healthy = threading.Event()
    child._report_health(MagicMock(), service, healthy, [], threading.Lock())
    return healthy


def test_a_check_ending_after_the_run_publishes_nothing() -> None:
    assert not _report(Checked(ends_run=True)).is_set()


def test_a_check_during_the_run_publishes_health() -> None:
    assert _report(Checked(ends_run=False)).is_set()
