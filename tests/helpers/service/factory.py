# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""A service for the factory tests."""

import threading

from appinfra.log import Logger
from appinfra.service import Service


class SimpleService(Service):
    """Simple test service."""

    def __init__(self, lg: Logger) -> None:
        self._lg = lg
        self._stop = threading.Event()

    @property
    def name(self) -> str:
        return "simple"

    def execute(self) -> None:
        self._stop.wait()

    def teardown(self) -> None:
        self._stop.set()

    def is_healthy(self) -> bool:
        return True
