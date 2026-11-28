# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Request and reply over a stream of messages that cannot carry a Chan: each
reply found by a key it shares with its request (a Correlation Identifier)."""

from __future__ import annotations

import contextlib
import threading
import time
from collections.abc import Callable, Hashable, Iterator
from typing import Generic, TypeVar

from .chan import Chan
from .errors import ClosedError, ResponseError

M = TypeVar("M")


class Correlator(Generic[M]):
    """Routes one stream of messages to the calls waiting on them.

    The caller owns the transport: *send* puts a message on it, and whatever
    reads it hands each arrival to deliver(). A message whose key a submit()
    or stream() waits on goes to that call; any other goes to the inbox that
    recv() reads. The Correlator knows nothing of the messages' format: *key*,
    *failed* and *final* read it.

    Where both ends can hold Chans, a reply Chan in the request does the same
    with no keys at all.
    """

    def __init__(
        self,
        send: Callable[[M, float | None], None],
        *,
        key: Callable[[M], Hashable],
        failed: Callable[[M], bool],
        final: Callable[[M], bool],
    ) -> None:
        """*send(message, timeout)* puts a message on the transport. *key*
        gives a message's correlation key, *failed* tells a reply that reports
        a failure, *final* tells a stream's last chunk."""
        self._send = send
        self._key = key
        self._failed = failed
        self._final = final
        self._inbox: Chan[M] = Chan(None)
        self._routes: dict[Hashable, Chan[M]] = {}
        self._lock = threading.Lock()
        self._closed = False

    def deliver(self, message: M) -> None:
        """Route an arrived message; never waits. After close() it is dropped."""
        with self._lock:
            route = self._routes.get(self._key(message), self._inbox)
            with contextlib.suppress(ClosedError):
                route.send(message, timeout=0)

    def submit(self, request: M, timeout: float | None = None) -> M:
        """Send *request* and return the reply with its key; *timeout* bounds
        the send and the wait together.

        Raises:
            TimeoutError: No reply in time; one arriving later goes to recv().
            ResponseError: The reply is a failure.
            ClosedError: The Correlator is closed, before or during the wait.
            ValueError: A call already waits on the request's key.
        """
        deadline = None if timeout is None else time.monotonic() + timeout
        key, route = self._enter(request)
        try:
            self._send(request, timeout)
            return self._wait(key, route, _left(deadline))
        finally:
            self._leave(key)

    def stream(self, request: M, timeout: float | None = None) -> Iterator[M]:
        """Send *request* and yield the chunks with its key, up to the final
        one; *timeout* bounds the send and the wait for each chunk. Nothing is
        sent before the first chunk is asked for; leaving early ends the wait.

        Raises what submit() does, from the chunk it concerns.
        """
        key, route = self._enter(request)
        try:
            self._send(request, timeout)
            while True:
                chunk = self._wait(key, route, timeout)
                yield chunk
                if self._final(chunk):
                    return
        finally:
            self._leave(key)

    def recv(self, timeout: float | None = None) -> M:
        """The next message no call waits on.

        Raises:
            TimeoutError: None in time.
            ClosedError: Closed and drained.
        """
        return self._inbox.recv(timeout)

    def send(self, message: M, timeout: float | None = None) -> None:
        """Put *message* on the transport, a reply to the peer's request say."""
        self._send(message, timeout)

    def close(self) -> None:
        """Fail the waiting calls and any after; recv() drains the inbox, then
        fails. Idempotent; the transport stays the caller's to close."""
        with self._lock:
            self._closed = True
            self._inbox.close()
            for route in self._routes.values():
                route.close()

    def _enter(self, request: M) -> tuple[Hashable, Chan[M]]:
        """Register the request's route before it is sent, so that a reply
        arriving during the send finds it."""
        key = self._key(request)
        with self._lock:
            if self._closed:
                raise ClosedError("correlator is closed")
            if key in self._routes:
                raise ValueError(f"a call already waits on {key!r}")
            route: Chan[M] = Chan(None)
            self._routes[key] = route
            return key, route

    def _wait(self, key: Hashable, route: Chan[M], timeout: float | None) -> M:
        """The next message on *route*. On a timeout the route leaves first,
        so no delivery lands on it after the look at what is there."""
        try:
            return self._checked(route.recv(timeout))
        except TimeoutError:
            self._leave(key)
            if len(route) == 0:
                raise
            return self._checked(route.recv(timeout=0))  # came as the wait ended

    def _leave(self, key: Hashable) -> None:
        with self._lock:
            self._routes.pop(key, None)

    def _checked(self, reply: M) -> M:
        if self._failed(reply):
            raise ResponseError(reply)
        return reply


def _left(deadline: float | None) -> float | None:
    """What remains of the wait before *deadline*; None waits without one."""
    return None if deadline is None else max(0.0, deadline - time.monotonic())
