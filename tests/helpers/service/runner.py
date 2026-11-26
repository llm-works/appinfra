# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""A service for the runner tests, and a wait for what no event signals."""

import time
from collections.abc import Callable
from unittest.mock import MagicMock

from appinfra.service import Service


def wait_until(condition: Callable[[], bool], timeout: float = 5.0) -> bool:
    """Poll *condition* until it holds; False once *timeout* passes. For changes
    no event signals, such as a service leaving the runtime."""
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.01)
    return True


class SimpleService(Service):
    """Simple test service."""

    def __init__(self, name: str = "test", health_delay: float = 0) -> None:
        self._name = name
        self._lg = MagicMock()
        self._health_delay = health_delay
        self._running = False
        self._healthy = False

    @property
    def name(self) -> str:
        return self._name

    def run(self) -> None:
        self._running = True
        if self._health_delay:
            time.sleep(self._health_delay)
        self._healthy = True
        self.stopping.wait()  # each run has its own token; teardown() ends none
        self._running = False
        self._healthy = False

    def is_healthy(self) -> bool:
        return self._healthy
