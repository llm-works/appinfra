# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""LoopHost - an event loop on a thread of its own, shared by many tasks."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from types import TracebackType

from .stop import StopToken


class LoopHost:
    """An event loop on a thread of its own, shared by many tasks.

    The tasks share the loop, so one waiting on an await holds no thread. Once
    stop() begins, the host takes no new tasks; it stops the tokens of the tasks
    still running, then cancels them and lets them finish before the loop
    closes.
    """

    def __init__(self, name: str = "loop-host") -> None:
        """Initialize host.

        Args:
            name: Name of the loop's thread.
        """
        self.name = name
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        # Orders _schedule() against stop(): what is scheduled before stop()
        # begins runs before the loop stops, so its shutdown sees the task
        self._lock = threading.Lock()
        self._closing = False
        # Tokens of the tasks alive on the loop; loop thread only. The shutdown
        # stops them before it cancels the tasks, as a task's stop() does
        self._tokens: set[StopToken] = set()

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        """The running loop.

        Raises:
            RuntimeError: Before start() or after stop().
        """
        if self._loop is None or self._thread is None or not self._thread.is_alive():
            raise RuntimeError(f"loop host '{self.name}' is not running")
        return self._loop

    def on_loop_thread(self) -> bool:
        """True when called from the loop's own thread."""
        return self._thread is not None and threading.current_thread() is self._thread

    def _schedule(self, callback: Callable[[], object]) -> None:
        """Run *callback* on the loop soon.

        Raises:
            RuntimeError: If the host is not running, or stop() has begun.
        """
        with self._lock:
            if self._closing:
                raise RuntimeError(f"loop host '{self.name}' is stopping")
            self.loop.call_soon_threadsafe(callback)

    def start(self) -> None:
        """Start the loop on its own thread.

        Raises:
            RuntimeError: If the host is already started.
        """
        if self._thread is not None:
            raise RuntimeError(f"loop host '{self.name}' is already started")
        self._closing = False
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._serve, args=(self._loop,), name=self.name, daemon=True
        )
        self._tokens = set()
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the loop: cancel the tasks still running, let them finish, and
        wait up to *timeout* seconds for the thread to end. If it is still
        ending then, the host stays running, closed to new tasks, and a later
        stop() waits for it again.

        Raises:
            RuntimeError: If called from the loop's own thread.
        """
        if self._thread is None or self._loop is None:
            return
        if self.on_loop_thread():
            raise RuntimeError("LoopHost.stop() on the loop thread would block it")
        with self._lock:
            if not self._closing:
                self._closing = True
                self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout)
        if self._thread.is_alive():
            return
        self._thread = None
        self._loop = None

    def _serve(self, loop: asyncio.AbstractEventLoop) -> None:
        """Thread target: run *loop* until stop(), then end its tasks, as
        asyncio.run() does, and close it. The tasks' tokens stop before the
        tasks are cancelled: a task that waits for its own work while it is
        cancelled needs that work told to stop first."""
        asyncio.set_event_loop(loop)
        try:
            loop.run_forever()
            for token in list(self._tokens):
                token.stop()
            tasks = asyncio.all_tasks(loop)
            for task in tasks:
                task.cancel()
            loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.run_until_complete(loop.shutdown_default_executor())
        finally:
            loop.close()

    def __enter__(self) -> LoopHost:
        """Start the host."""
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Stop the host."""
        self.stop()
