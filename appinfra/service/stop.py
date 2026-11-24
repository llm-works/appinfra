# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""StopToken: the stop signal of one run of a service, and of the runs derived from it."""

from __future__ import annotations

import threading

# Guards every token's children and wait event. One lock for all tokens, not one
# each: a lock costs more than a token, and these sections are short and rare
# (deriving, stopping, the first wait).
_lock = threading.Lock()


class StopToken:
    """A one-way stop signal: once stopped, it stays stopped.

    A runner gives each run of a service its own token; the service checks it
    (``is_set()``) or blocks on it (``wait()``) to learn when to return. Tokens
    form a tree, like Go's context: ``child()`` derives a token that is stopped
    when its parent is, so stopping one token stops everything derived from it.
    A derived token that is no longer needed leaves the tree with ``detach()``.

    An async service needs no token to learn of a stop: stopping it cancels its
    task. It uses the token to derive tokens for what it starts.
    """

    __slots__ = ("_stopped", "_event", "_children", "_parent")

    def __init__(self) -> None:
        """A token not yet stopped, with no parent."""
        self._stopped = False
        # Created by the first wait(): most tokens are only checked or never read
        self._event: threading.Event | None = None
        self._children: set[StopToken] | None = None
        self._parent: StopToken | None = None

    def __reduce__(self) -> tuple[type[StopToken], tuple[()]]:
        """Pickle as a new token: a token signals within one process, so a
        service sent to a subprocess arrives with a fresh one (the subprocess
        gives it its own), not a copy of this one and the tree it belongs to."""
        return (StopToken, ())

    def is_set(self) -> bool:
        """True once the token, or one it derives from, is stopped."""
        return self._stopped

    def stop(self) -> None:
        """Stop the token and every token derived from it. Idempotent."""
        with _lock:
            if self._stopped:
                return
            self._stopped = True
            event, children = self._event, self._children
            self._children = None
        if event is not None:
            event.set()
        for child in children or ():
            child.stop()

    def wait(self, timeout: float | None = None) -> bool:
        """Block until the token is stopped or *timeout* seconds pass.

        Returns:
            True if the token is stopped.
        """
        if self._stopped:
            return True
        with _lock:
            if self._event is None:
                self._event = threading.Event()
                if self._stopped:
                    self._event.set()
            event = self._event
        return event.wait(timeout)

    def child(self) -> StopToken:
        """A token stopped when this one is; stopped already if this one is."""
        token = StopToken()
        with _lock:
            if self._stopped:
                token._stopped = True
                return token
            token._parent = self
            if self._children is None:
                self._children = set()
            self._children.add(token)
        return token

    def detach(self) -> None:
        """Leave the parent's tree, so a run that has ended is not kept alive by
        it; the token keeps its own state."""
        with _lock:
            parent, self._parent = self._parent, None
            if parent is not None and parent._children is not None:
                parent._children.discard(self)
