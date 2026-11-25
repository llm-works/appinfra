# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Runs a service's work on the thread or process a ThreadRunner or ProcessRunner
gives it."""

from __future__ import annotations

from typing import Protocol

from ..base import AsyncService, ScheduledService, Service


class StopSignal(Protocol):
    """What drive() needs from the runner's stop signal: a threading.Event in a
    thread, the shutdown multiprocessing.Event in a subprocess."""

    def is_set(self) -> bool: ...

    def wait(self, timeout: float | None = None) -> bool: ...


def check_service(service: object) -> Service:
    """Check that *service* is a Service, and not both scheduled and async.

    Returns:
        *service*, typed as a Service.

    Raises:
        TypeError: If it is not, or is both a ScheduledService and an AsyncService.
    """
    if not isinstance(service, Service):
        raise TypeError(f"service must be a Service, got {type(service)}")
    if isinstance(service, ScheduledService) and isinstance(service, AsyncService):
        raise TypeError(
            f"service '{service.name}' is both a ScheduledService and an AsyncService"
        )
    return service


def check_drivable(service: Service) -> None:
    """Refuse an AsyncService, which only a LoopHost runs.

    Raises:
        TypeError: If *service* is an AsyncService.
    """
    if isinstance(service, AsyncService):
        raise TypeError(
            f"async service '{service.name}' runs on a LoopHost: use "
            "host.runner(service), not ThreadRunner or ProcessRunner"
        )


def drive(service: Service, stop: StopSignal) -> None:
    """Run *service*'s work until *stop* is set.

    - ScheduledService: tick(), then wait interval seconds, until stopped. The
      wait follows each tick, so ticks are interval plus tick() time apart.
    - Any other Service: run() once; it returns when the service is stopped.

    Exceptions from the service propagate to the runner.

    Raises:
        TypeError: If *service* is an AsyncService (checked here too: a
            subprocess runs this without a runner's check).
    """
    check_drivable(service)
    if isinstance(service, ScheduledService):
        while not stop.is_set():
            service.tick()
            stop.wait(service.interval)
    else:
        service.run()
