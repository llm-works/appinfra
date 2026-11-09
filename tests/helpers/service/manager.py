# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""A service for the manager tests."""

import threading
import time

from appinfra.service import Service, SetupError


class SimpleService(Service):
    """Simple test service that tracks lifecycle calls."""

    def __init__(
        self,
        name: str,
        depends_on: list[str] | None = None,
        setup_error: str | None = None,
        health_delay: float = 0,
    ) -> None:
        self._name = name
        self._depends_on = depends_on or []
        self._setup_error = setup_error
        self._health_delay = health_delay

        self._setup_called = False
        self._execute_called = False
        self._teardown_called = False
        self._healthy = False
        self._stop_event = threading.Event()

    @property
    def name(self) -> str:
        return self._name

    @property
    def depends_on(self) -> list[str]:
        return self._depends_on

    def setup(self) -> None:
        self._setup_called = True
        if self._setup_error:
            raise SetupError(self._name, self._setup_error)

    def execute(self) -> None:
        self._execute_called = True

        if self._health_delay:
            time.sleep(self._health_delay)

        self._healthy = True
        self._stop_event.wait()

    def teardown(self) -> None:
        self._teardown_called = True
        self._stop_event.set()

    def is_healthy(self) -> bool:
        return self._healthy
