# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""A service for the runner tests."""

import threading
import time
from unittest.mock import MagicMock

from appinfra.service import Service


class SimpleService(Service):
    """Simple test service."""

    def __init__(self, name: str = "test", health_delay: float = 0) -> None:
        self._name = name
        self._lg = MagicMock()
        self._health_delay = health_delay
        self._stop_event = threading.Event()
        self._running = False
        self._healthy = False

    @property
    def name(self) -> str:
        return self._name

    def execute(self) -> None:
        self._running = True
        if self._health_delay:
            time.sleep(self._health_delay)
        self._healthy = True
        self._stop_event.wait()
        self._running = False
        self._healthy = False

    def teardown(self) -> None:
        self._stop_event.set()

    def is_healthy(self) -> bool:
        return self._healthy
