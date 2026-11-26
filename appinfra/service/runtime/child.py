# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""An isolated service's process: its main, which the service Runtime runs as a
process task, and the parent's wait for the health the child reports."""

from __future__ import annotations

import threading
from typing import Any

from ...log import Logger
from ...runtime import stopping
from ..base import Service
from ..errors import SetupError

# Seconds between two checks of the child's health
HEALTH_INTERVAL = 0.1


def main(service: Service, healthy: Any, log_config: dict[str, Any]) -> None:
    """The run of an isolated service, in its child process: set up, run, and
    tear down there, with a logger forwarding to the parent's (*log_config*).
    The service's stopping token is this task's, which the parent's stop
    stops. *healthy* is set once is_healthy() reports it.

    Raises:
        SetupError: If setup() fails; what is_healthy() raised, which ends the
            run; whatever the run raised otherwise.
    """
    token = stopping()
    lg = Logger.from_queue_config(log_config, name=f"svc/{service.name}")
    if hasattr(service, "_lg"):
        service._lg = lg
    service.stopping = token
    try:
        service.setup()
    except Exception as e:
        raise SetupError.of(service.name, e)  # noqa: B904  # of() sets the cause
    failed: list[Exception] = []  # what is_healthy() raised, if it did
    threading.Thread(
        target=_report_health,
        args=(lg, service, healthy, failed),
        name="health",
        daemon=True,
    ).start()
    try:
        service.run()
    finally:
        token.stop()
        try:
            service.teardown()
        except Exception as e:
            lg.warning("teardown failed", extra={"exception": e})
    if failed:
        raise failed[0]


def wait_healthy(healthy: Any) -> bool:
    """In the parent: wait for the child to report its service healthy
    (*healthy*, a multiprocessing Event the child sets), checking this task's
    token between waits.

    Returns:
        True once reported healthy; False if the run ended first.
    """
    token = stopping()
    while not token.is_set():
        if healthy.wait(HEALTH_INTERVAL):
            return True
    return False


def _report_health(
    lg: Logger, service: Service, healthy: Any, failed: list[Exception]
) -> None:
    """In the child: set *healthy* once the service reports it, unless the
    run ends first. An is_healthy() that raises ends the run, as it does for a
    service in the parent's process: its error goes to *failed*, for main() to
    raise, and the service's token stops."""
    token = service.stopping
    try:
        while not token.is_set():
            if service.is_healthy():
                healthy.set()
                return
            token.wait(HEALTH_INTERVAL)
    except Exception as e:
        lg.warning("service health check failed", extra={"exception": e})
        failed.append(e)
        token.stop()
