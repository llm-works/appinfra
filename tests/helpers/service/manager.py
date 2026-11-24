# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""A service for the manager tests."""

import threading

from appinfra.service import Service, SetupError


class SimpleService(Service):
    """Simple test service that tracks lifecycle calls."""

    def __init__(
        self,
        name: str,
        depends_on: list[str] | None = None,
        setup_error: str | None = None,
        barrier: threading.Barrier | None = None,
    ) -> None:
        self._name = name
        self._depends_on = depends_on or []
        self._setup_error = setup_error
        # run() waits here before it reports healthy
        self._barrier = barrier

        self._setup_called = False
        self._run_called = False
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

    def run(self) -> None:
        self._run_called = True

        if self._barrier is not None:
            self._barrier.wait()

        self._healthy = True
        self._stop_event.wait()

    def teardown(self) -> None:
        self._teardown_called = True
        self._stop_event.set()

    def is_healthy(self) -> bool:
        return self._healthy
