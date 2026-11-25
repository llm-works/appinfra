# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""StopToken: the stop signal of one run of a service, and of the runs derived from it."""

from __future__ import annotations

import os
import threading
from collections.abc import Callable

# Guards every token's children and wait event. One lock for all tokens, not one
# each: a lock costs more than a token, and these sections are short and rare
# (deriving, stopping, the first wait).
_lock = threading.Lock()


def _reset_lock_after_fork() -> None:
    """A fork copies _lock as it is: held by another thread at that moment, it
    would stay held in the child, where that thread does not exist."""
    global _lock
    _lock = threading.Lock()


if hasattr(os, "register_at_fork"):  # POSIX only; nothing forks elsewhere
    os.register_at_fork(after_in_child=_reset_lock_after_fork)


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

    def __reduce__(
        self,
    ) -> tuple[Callable[[StopToken | None], StopToken], tuple[StopToken | None]]:
        """Pickle as a new token, not stopped: a token signals within one
        process, so a service sent to a subprocess arrives with fresh ones that
        the subprocess stops. A derived token arrives derived from a new copy of
        its parent, the one pickled with it if any, so the tokens a service's
        setup() derives stay tied to its own. Only the chain to the root comes
        along, not the rest of the tree."""
        return (_unpickle, (self._parent,))

    def is_set(self) -> bool:
        """True once the token, or one it derives from, is stopped."""
        return self._stopped

    def stop(self) -> None:
        """Stop the token and every token derived from it. Idempotent.

        Walks the tree with a worklist, not recursion, so no depth stops it
        partway: the part already stopped would ignore a second stop()."""
        pending = [self]
        while pending:
            token = pending.pop()
            with _lock:
                if token._stopped:
                    continue
                token._stopped = True
                event, children = token._event, token._children
                token._children = None
            if event is not None:
                event.set()
            if children:
                pending.extend(children)

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


def _unpickle(parent: StopToken | None) -> StopToken:
    """A token unpickled: a new root, or a new child of its unpickled parent."""
    return StopToken() if parent is None else parent.child()
