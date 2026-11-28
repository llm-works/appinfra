# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""What crosses to a process task's child as the runtime starts it: the
runtime's logger, and process Chans in its arguments. The function and its
arguments go to the child as always, pickled by multiprocessing; a process
Chan among them pickles, during that start only, as a reference registered
at the home of a link made for the run, and is rebuilt in the child as a
proxy over it. The logger crosses to every child, as the config of one whose
records the runtime's logger emits here; a start that meets no Chan makes no
link.

Multiprocessing rebuilds the arguments before the child's main runs: the
first reference rebuilt there opens the child's end of the link, which it
carries with the logger's config (pickled once, the others refer to it). The
child makes one logger from the config, whichever needs it first: its link
or its task.

Internal: the process task uses it."""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from multiprocessing.context import BaseContext
from typing import Any

from ...log import Logger
from ...log.mp import LogQueueListener
from .chan import Chan, _starting
from .endpoint import Endpoint
from .link import LinkEnd, link
from .proxy import _ChanProxy

_RELAYED = (
    "a proxy crosses to a process task only from its Chan's home, not on to "
    "a third process"
)

# The config of the logger carried over to a child, and that logger's name
Carried = tuple[dict[str, Any], str]

# The child's end of the run's link, with the logger carried over to it
_Linked = tuple[LinkEnd, dict[str, Any], str]


class Crossing:
    """The parent's side of one run: the listener of the child's log
    records, made once the logger is carried, and the link with its
    endpoint, made once the start meets a process Chan. Closed when the run
    ends."""

    def __init__(self, lg: Logger, ctx: BaseContext) -> None:
        """A crossing for the runtime's *lg*, into a child of *ctx*."""
        self._lg = lg
        self._ctx = ctx
        # The link once opened: its endpoint here, and what a reference
        # carries to the child
        self._opened: tuple[Endpoint, _Linked] | None = None
        self._far: LinkEnd | None = None  # the child's end, until it has it
        self._queue: Any = None  # the child's log records, with their listener
        self._listener: LogQueueListener | None = None
        self._carried: Carried | None = None

    @contextlib.contextmanager
    def starting(self) -> Iterator[None]:
        """While the child starts on this thread: a process Chan pickled in
        its arguments is referenced through this crossing."""
        _starting.reference = self._reference
        try:
            yield
        finally:
            del _starting.reference

    def carry(self) -> Carried:
        """The runtime's logger, as the child rebuilds it: the config of a
        logger whose records the runtime's logger emits here, and its name.
        The queue of those records and its listener open on the first call;
        before the child starts, as the queue reaches it only then."""
        if self._carried is None:
            self._queue = self._ctx.Queue()
            self._listener = LogQueueListener(self._queue, self._lg)
            self._listener.start()
            self._carried = (self._lg.queue_config(self._queue), self._lg.name)
        return self._carried

    def handed(self) -> None:
        """The child started: it has its end, so this process's copy goes,
        and the child's end closing is seen here as the link ending."""
        if self._far is not None:
            far, self._far = self._far, None
            far.release()

    def close(self) -> None:
        """End the run's link and the forwarding of the child's records,
        once the child has ended: every frame it sent (a close or a Release
        it posted last) is handled first. The queue is closed and let go
        here: the crossing can outlive the run (a task's error keeps the
        frame that holds it), and a queue left to the cyclic collector frees
        its semaphores wherever that runs, inside the resource tracker too,
        which refuses the reentrant call."""
        try:
            self.handed()  # a child that never started: its end goes too
            if self._opened is not None:
                self._opened[0].finish()
        finally:
            if self._listener is not None:
                self._listener.stop()
                self._queue.close()
                self._queue.join_thread()
            elif self._queue is not None:  # its listener never made: nothing fed it
                self._queue.close()
            self._opened = self._listener = self._queue = self._carried = None

    def _reference(self, chan: Chan[Any]) -> tuple[Any, ...]:
        """The reduction of *chan*: its id at the run's home, with the
        child's end of the link, made on the first.

        Raises:
            TypeError: For a proxy, which would need relaying through here.
        """
        if isinstance(chan, _ChanProxy):
            raise TypeError(_RELAYED)
        endpoint, linked = self._opened or self._open()
        return (_arrived, (endpoint.home.register(chan), linked))

    def _open(self) -> tuple[Endpoint, _Linked]:
        """Make the link, open here, with the logger the child gets."""
        log_config, lg_name = self.carry()
        near, self._far = link()
        linked = (self._far, log_config, lg_name)
        self._opened = (Endpoint(self._lg, near), linked)
        return self._opened


class _Child:
    """The child's side: the logger carried to it, once made, and its end of
    the run's link, once its first Chan arrives. One of each per child, as a
    child runs one call."""

    lg: Logger | None = None
    endpoint: Endpoint | None = None


def child_lg(log_config: dict[str, Any], lg_name: str) -> Logger:
    """In the child: the runtime's logger as carried over, made from
    *log_config* on the first call, and named *lg_name*."""
    if _Child.lg is None:
        _Child.lg = Logger.from_queue_config(log_config, name=lg_name)
    return _Child.lg


def _arrived(object_id: int, linked: _Linked) -> _ChanProxy[Any]:
    """In the child: the proxy of the Chan *object_id* homed at the parent,
    the link opened on the first, its logger carried over."""
    if _Child.endpoint is None:
        end, log_config, lg_name = linked
        _Child.endpoint = Endpoint(child_lg(log_config, lg_name), end)
    proxy: _ChanProxy[Any] = _Child.endpoint.proxy(object_id)
    return proxy


def close_child() -> None:
    """In the child: close its end of the link, if a Chan opened one; the
    frames its proxies posted reach the parent first."""
    if _Child.endpoint is not None:
        _Child.endpoint.close()
