# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""StopToken: the stop signal of one run of a service, and of the runs derived from it."""

from __future__ import annotations

import functools
import os
import sys
import threading
from collections.abc import Callable, Iterable

# Guards every token's children and wait event. One lock for all tokens, not one
# each: a lock costs more than a token, and these sections are short and rare
# (deriving, stopping, the first wait).
_lock = threading.Lock()

# Raised in each forked child. Callbacks carry the generation they were
# registered in; a child drops those it copied from its parent without running
# them.
_generation = 0


def _after_fork_in_child() -> None:
    """A fork copies the parent's state as it is.

    _lock, held by another thread at that moment, would stay held in the child,
    where that thread does not exist. Callbacks registered on tokens belong to
    the parent's waiters, which do not exist in the child either: running them
    there could block for good on a lock the fork copied held."""
    global _lock, _generation
    _lock = threading.Lock()
    _generation += 1


if hasattr(os, "register_at_fork"):  # POSIX only; nothing forks elsewhere
    os.register_at_fork(after_in_child=_after_fork_in_child)


class StopToken:
    """A one-way stop signal: once stopped, it stays stopped.

    A runner gives each run of a service its own token; the service checks it
    (``is_set()``), blocks on it (``wait()``) or has it call back (``on_stop()``)
    to learn when to return. Tokens
    form a tree, like Go's context: ``child()`` derives a token that is stopped
    when its parent is, so stopping one token stops everything derived from it.
    A derived token that is no longer needed leaves the tree with ``detach()``.

    An async service needs no token to learn of a stop: stopping it cancels its
    task. It uses the token to derive tokens for what it starts.
    """

    __slots__ = ("_stopped", "_event", "_children", "_callbacks", "_parent")

    def __init__(self) -> None:
        """A token not yet stopped, with no parent."""
        self._stopped = False
        # Created by the first wait(): most tokens are only checked or never read
        self._event: threading.Event | None = None
        self._children: set[StopToken] | None = None
        # The generation they were registered in, and the callbacks keyed by
        # registration, so removal is O(1) and one function can be registered
        # twice
        self._callbacks: tuple[int, dict[object, Callable[[], None]]] | None = None
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
        partway: the part already stopped would ignore a second stop(). For the
        same reason the whole tree is stopped before any callback runs: nothing
        a callback does can leave a token running. A callback that raises does
        not reach the caller either, who cannot act on one listener's failure:
        the error goes to threading.excepthook, as one nothing can catch, and
        the other callbacks still run. KeyboardInterrupt and other
        non-Exception errors propagate."""
        callbacks: list[Callable[[], None]] = []
        pending = [self]
        while pending:
            token = pending.pop()
            with _lock:
                if token._stopped:
                    continue
                token._stopped = True
                event, children = token._event, token._children
                callbacks.extend(token._take_callbacks())
                token._children = None
            if event is not None:
                event.set()
            if children:
                pending.extend(children)
        _run(callbacks)

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

    def on_stop(self, fn: Callable[[], None]) -> Callable[[], None]:
        """Call *fn* once when the token is stopped; at once if it is already.

        *fn* runs on the thread that calls stop(), and it must be short and
        not block: stop() calls each token's callbacks in turn. An Exception
        it raises there goes to threading.excepthook, and the stop goes on; on
        a token already stopped, *fn* runs at once and its error reaches the
        caller of on_stop().

        Returns:
            A function that unregisters *fn*. A caller done waiting calls it,
            so a long-lived token does not collect callbacks. It does nothing
            once *fn* has run, and calling it twice is harmless.
        """
        key = object()
        with _lock:
            if not self._stopped:
                if self._callbacks is None or self._callbacks[0] != _generation:
                    self._callbacks = (_generation, {})
                self._callbacks[1][key] = fn
                return functools.partial(self._remove_callback, key)
        fn()
        return _noop

    def _remove_callback(self, key: object) -> None:
        """Unregister the callback registered as *key*, if it is still there."""
        with _lock:
            if self._callbacks is not None:
                self._callbacks[1].pop(key, None)

    def _take_callbacks(self) -> list[Callable[[], None]]:
        """Clear the callbacks; returns those registered in this process.
        Called under _lock."""
        callbacks, self._callbacks = self._callbacks, None
        if callbacks is None or callbacks[0] != _generation:
            return []
        return list(callbacks[1].values())

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


def _run(callbacks: Iterable[Callable[[], None]]) -> None:
    """Call each of *callbacks*. One that raises an Exception is reported
    through threading.excepthook, as an error no caller can catch; the rest
    still run."""
    for fn in callbacks:
        try:
            fn()
        except Exception as e:
            _report(e)


def _report(error: Exception) -> None:
    """Report a callback's *error* through threading.excepthook. A hook that
    raises falls back to sys.excepthook with its own error, as threading does
    for a failing hook, so the stop's other callbacks still run."""
    try:
        threading.excepthook(
            threading.ExceptHookArgs(
                [type(error), error, error.__traceback__, threading.current_thread()]
            )
        )
    except Exception as hook_error:
        sys.excepthook(type(hook_error), hook_error, hook_error.__traceback__)


def _noop() -> None:
    """The unregister function of a callback that has run already."""


def _unpickle(parent: StopToken | None) -> StopToken:
    """A token unpickled: a new root, or a new child of its unpickled parent."""
    return StopToken() if parent is None else parent.child()
