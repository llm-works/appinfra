# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""A task whose call runs on a thread of its own."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from .stop import StopToken
from .task import _label, _Task


class _ThreadTask(_Task):
    """Calls a function on a daemon thread of its own. A thread cannot be
    interrupted: the function sees its token (``stopping()``) and returns."""

    __slots__ = ("_thread", "_finished")

    def __init__(
        self,
        on_end: Callable[[_Task], None],
        task_id: int,
        name: str | None,
        fn: Callable[..., Any],
        args: tuple[Any, ...],
        token: StopToken,
    ) -> None:
        """Initialize task; see _Task."""
        super().__init__(on_end, task_id, name, fn, args, token)
        self._thread: threading.Thread | None = None
        # Set by _run() as its last step. Thread.is_alive() on Python 3.13+
        # stays True until the OS thread handle is marked done, after the GIL
        # is released, so it alone can report an ended call as running
        self._finished = False

    def launch(self) -> None:
        """Start the task's thread."""
        self._thread = threading.Thread(
            target=self._context.run,
            args=(self._run,),
            name=_label(self.id, self.name),
            daemon=True,
        )
        self._thread.start()

    def _run(self) -> None:
        """Thread target, in the task's context: call the function, unless
        its token was stopped before the thread got here, as on the loop."""
        try:
            if self.token.is_set():
                self.stopped = True
            else:
                try:
                    fn, args = self._take_call()
                    self.result = self._call(fn, args)
                except BaseException as e:
                    self._raised(e)
            self._end()
        finally:
            # Last, so the outcome is settled before is_running() reports the
            # end
            self._finished = True

    def _call(self, fn: Callable[..., Any], args: tuple[Any, ...]) -> Any:
        """The call itself: *fn*(*args*) on this thread."""
        return fn(*args)

    def cancel(self) -> None:
        """Stop the task's token; the function sees it and returns."""
        self.token.stop()

    def join(self, timeout: float | None = None) -> bool:
        """Join the task's thread for up to *timeout* seconds.

        Raises:
            RuntimeError: If called on the task's own thread, which would wait
                for itself.
        """
        thread = self._thread
        if thread is threading.current_thread():
            raise RuntimeError(f"task {self.id} cannot wait for itself")
        if thread is not None:
            thread.join(timeout)
        return not self.is_running()

    def is_running(self) -> bool:
        """True while the task's thread has not finished the call."""
        thread = self._thread
        return thread is not None and not self._finished and thread.is_alive()
