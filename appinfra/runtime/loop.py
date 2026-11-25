# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""LoopHost - the runtime's event loop, on a thread of its own."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable

THREAD_NAME = "runtime-loop"


class LoopHost:
    """The runtime's event loop, on a thread of its own, shared by every async
    task, so one waiting on an await holds no thread. Once stop() begins, the
    host takes no new tasks; it cancels the tasks still running and lets them
    finish before the loop closes. The runtime stops every task's token first.
    """

    def __init__(self) -> None:
        """A host not yet started."""
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        # Orders _schedule() against stop(): what is scheduled before stop()
        # begins runs before the loop stops, so its shutdown sees the task
        self._lock = threading.Lock()
        self._closing = False

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        """The running loop.

        Raises:
            RuntimeError: Before start() or after stop().
        """
        if self._loop is None or self._thread is None or not self._thread.is_alive():
            raise RuntimeError("runtime loop is not running")
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
                raise RuntimeError("runtime loop is stopping")
            self.loop.call_soon_threadsafe(callback)

    def start(self) -> None:
        """Start the loop on its own thread; once."""
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._serve, args=(self._loop,), name=THREAD_NAME, daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the loop: cancel the tasks still running, let them finish, and
        wait up to *timeout* seconds for the thread to end. If it is still
        ending then, the host stays closed to new tasks, and a later stop()
        waits for it again.

        Raises:
            RuntimeError: If called from the loop's own thread.
        """
        if self._thread is None or self._loop is None:
            return
        if self.on_loop_thread():
            raise RuntimeError(
                "stopping the runtime loop on its own thread would block it"
            )
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
        asyncio.run() does, and close it."""
        asyncio.set_event_loop(loop)
        try:
            loop.run_forever()
            tasks = asyncio.all_tasks(loop)
            for task in tasks:
                task.cancel()
            loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.run_until_complete(loop.shutdown_default_executor())
        finally:
            loop.close()
