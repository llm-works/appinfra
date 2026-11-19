# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Runs a service's work on the thread or process a runner gives it.

The loops here suit a runner that gives each service a thread or a process of
its own: an idle step service wakes every WAIT_SLICE seconds to recheck stop,
and a stop takes up to that long to end its loop.
"""

from __future__ import annotations

from typing import Any, Protocol

from ..base import ScheduledService, Service, StepService
from ..channel.sync import Channel
from ..errors import ChannelClosedError, ChannelFullError, ChannelTimeoutError

#: Longest a step service's loop waits on its inbox, to receive a message or to
#: find room for a reply, before rechecking stop.
WAIT_SLICE = 0.1

#: The services whose loop the runner runs; a service is at most one of them.
LOOPED_SERVICES = (StepService, ScheduledService)


class StopSignal(Protocol):
    """What drive() needs from the runner's stop signal: a threading.Event in a
    thread, the shutdown multiprocessing.Event in a subprocess."""

    def is_set(self) -> bool: ...

    def wait(self, timeout: float | None = None) -> bool: ...


def check_form(service: object, inbox: Channel | None) -> Service:
    """Check that a runner can host *service*, with *inbox* if it is a step service.

    Returns:
        *service*, typed as a Service.

    Raises:
        TypeError: If *service* is not a Service, or is both a StepService and
            a ScheduledService.
        ValueError: If a step service has no inbox, or another service is
            given one.
    """
    if not isinstance(service, Service):
        raise TypeError(f"service must be a Service, got {type(service)}")
    _check_one_loop(service)
    if isinstance(service, StepService):
        if inbox is None:
            raise ValueError(f"step service '{service.name}' needs an inbox channel")
    elif inbox is not None:
        raise ValueError(
            f"service '{service.name}' takes no inbox channel: only a step service does"
        )
    return service


def _check_one_loop(service: Service) -> None:
    """The runner runs one loop per service, so a service is at most one of the
    services it loops."""
    kinds = [kind.__name__ for kind in LOOPED_SERVICES if isinstance(service, kind)]
    if len(kinds) > 1:
        raise TypeError(
            f"service '{service.name}' is more than one of {', '.join(kinds)}"
        )


def drive(service: Service, stop: StopSignal, inbox: Channel | None) -> None:
    """Run *service*'s work until *stop* is set.

    - StepService: step() with each message from *inbox*, until stopped or the
      inbox closes. A reply step() returns goes back on *inbox*; while the inbox
      is full the loop waits for room, and a stop meanwhile drops the reply.
    - ScheduledService: tick(), then wait interval seconds, until stopped. The
      wait follows each tick, so ticks are interval plus tick() time apart.
    - Any other Service: run() once; it returns when the service is stopped.

    Exceptions from the service propagate to the runner.

    Raises:
        TypeError: If *service* is both a StepService and a ScheduledService,
            or a step service comes without an inbox.
    """
    _check_one_loop(service)  # a subprocess runs this without a runner's check
    if isinstance(service, StepService):
        if inbox is None:
            raise TypeError(f"step service '{service.name}' needs an inbox channel")
        _drive_steps(service, stop, inbox)
    elif isinstance(service, ScheduledService):
        _drive_scheduled(service, stop)
    else:
        service.run()


def _drive_scheduled(service: ScheduledService, stop: StopSignal) -> None:
    while not stop.is_set():
        service.tick()
        stop.wait(service.interval)


def _drive_steps(service: StepService, stop: StopSignal, inbox: Channel) -> None:
    while not stop.is_set():
        try:
            msg = inbox.recv(timeout=WAIT_SLICE)
        except ChannelTimeoutError:
            continue
        except ChannelClosedError:
            return
        reply = service.step(msg)
        if reply is not None and not _send_reply(inbox, reply, stop):
            return


def _send_reply(inbox: Channel, reply: Any, stop: StopSignal) -> bool:
    """Send *reply* on *inbox*, waiting for room in slices until *stop* is set.

    Returns:
        False if the inbox closed, True otherwise (sent, or dropped at stop).
    """
    while not stop.is_set():
        try:
            inbox.send(reply, timeout=WAIT_SLICE)
            return True
        except ChannelFullError:
            continue
        except ChannelClosedError:
            return False
    return True
