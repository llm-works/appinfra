# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""The steps of a service the service Runtime runs as tasks: each function here
is a task's call, and its end reaches the Runtime as the task's TaskDone."""

from __future__ import annotations

import contextlib
import threading
from typing import Any

from ...log import Logger
from ...runtime import StoppedError, stopping
from ..base import Service
from ..errors import SetupError
from .drive import drive

# Seconds between two health checks of a service starting
HEALTH_INTERVAL = 0.1


def set_up(service: Service) -> None:
    """Setup step: the service's setup().

    Raises:
        SetupError: If it fails; another exception becomes one, caused by it.
    """
    try:
        service.setup()
    except SetupError:
        raise
    except Exception as e:
        raise SetupError(service.name, str(e)) from e


def check_health(service: Service) -> bool:
    """Health step: ask is_healthy() every HEALTH_INTERVAL seconds, waiting on
    this task's token, which the run's ends.

    Returns:
        True once healthy; False if the run ended first.
    """
    token = stopping()
    while not token.is_set():
        if service.is_healthy():
            return True
        token.wait(HEALTH_INTERVAL)
    return False


def check_child_health(healthy: Any) -> bool:
    """Health step of an isolated service: wait for its child to report it
    healthy (*healthy*, a multiprocessing Event the child sets), checking this
    task's token between waits.

    Returns:
        True once reported healthy; False if the run ended first.
    """
    token = stopping()
    while not token.is_set():
        if healthy.wait(HEALTH_INTERVAL):
            return True
    return False


def tear_down(service: Service) -> None:
    """Teardown step: the service's teardown()."""
    service.teardown()


def back_off(delay: float) -> None:
    """Backoff step: wait out *delay* seconds before a restart attempt, unless
    the runtime's stop ends the wait first.

    Raises:
        StoppedError: If stopped first, as a stopped task ends.
    """
    if stopping().wait(delay):
        raise StoppedError()


def isolated(service: Service, healthy: Any, log_config: dict[str, Any]) -> None:
    """The run of an isolated service, in its child process: set up, run, and
    tear down there, with a logger forwarding to the parent's (*log_config*).
    The service's stopping token is this task's, which the parent's stop
    stops. *healthy* is set once is_healthy() reports it.

    Raises:
        SetupError: If setup() fails; whatever the run raised otherwise.
    """
    token = stopping()
    lg = Logger.from_queue_config(log_config, name=f"svc/{service.name}")
    if hasattr(service, "_lg"):
        service._lg = lg
    service.stopping = token
    set_up(service)
    threading.Thread(
        target=_report_health, args=(service, healthy), name="health", daemon=True
    ).start()
    try:
        drive(service, token)
    finally:
        token.stop()
        try:
            service.teardown()
        except Exception as e:
            lg.warning("teardown failed", extra={"exception": e})


def _report_health(service: Service, healthy: Any) -> None:
    """In the child: set *healthy* once the service reports it, unless the
    run ends first."""
    token = service.stopping
    with contextlib.suppress(Exception):
        while not token.is_set():
            if service.is_healthy():
                healthy.set()
                return
            token.wait(HEALTH_INTERVAL)
