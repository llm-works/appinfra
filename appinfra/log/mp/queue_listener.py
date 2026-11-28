# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Queue listener for receiving log records from subprocesses.

This module provides a listener that runs in the parent process, receiving
log records from subprocess queue handlers and dispatching them to the
parent's logging handlers.
"""

from __future__ import annotations

import contextlib
import logging
import queue
import sys
import threading
import traceback
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from multiprocessing import Queue as QueueType

    from ..logger import Logger


def _report(doing: str) -> None:
    """Write the exception being handled to stderr, as the listener met it
    *doing* a record: no logger can be trusted with its own failure."""
    sys.stderr.write(f"LogQueueListener: error {doing} record:\n")
    traceback.print_exc(file=sys.stderr)


class LogQueueListener:
    """
    Receives log records from subprocesses and dispatches to handlers.

    Runs a background thread that reads from a multiprocessing.Queue and
    passes records to the specified logger's handlers.

    Usage:
        from multiprocessing import Queue
        from . import LogQueueListener

        queue = Queue()
        listener = LogQueueListener(queue, parent_logger)
        listener.start()

        # ... spawn subprocesses that use MPQueueHandler with this queue ...

        listener.stop()

    Thread Safety:
        The listener runs in its own daemon thread. It's safe to call
        start() and stop() from any thread.
    """

    def __init__(
        self,
        log_queue: QueueType[logging.LogRecord | None],
        logger: Logger,
        respect_handler_level: bool = True,
    ) -> None:
        """
        Initialize the queue listener.

        Args:
            log_queue: multiprocessing.Queue to receive records from
            logger: Logger whose handlers will process the records
            respect_handler_level: If True, only dispatch to handlers whose
                                   level is <= record level (default True)
        """
        self._queue = log_queue
        self._logger = logger
        self._respect_handler_level = respect_handler_level
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        # Set by stop(close_queue=True): the thread closes the queue as it ends
        self._close_queue = False

    def start(self) -> None:
        """
        Start the listener thread.

        The thread runs as a daemon, so it won't prevent process exit.
        Call stop() for graceful shutdown.
        """
        if self._thread is not None and self._thread.is_alive():
            return  # Already running

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._listen, daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0, close_queue: bool = False) -> None:
        """
        Stop the listener thread gracefully.

        Sends a sentinel value to unblock the queue.get() and waits for
        the thread to finish.

        Args:
            timeout: Maximum seconds to wait for thread to finish
            close_queue: Close the multiprocessing queue, and join its
                feeder, once the thread has handled every record before the
                sentinel. The thread does it as it ends, so a drain that
                outlasts *timeout* still loses no record, and the caller is
                not held past *timeout*.
        """
        self._close_queue = close_queue
        self._stop_event.set()

        # Send sentinel to unblock queue.get(); the queue might be full or closed
        with contextlib.suppress(Exception):
            self._queue.put_nowait(None)

        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None
        elif close_queue:  # never started: nothing to drain
            self._close()

    def _close(self) -> None:
        """Close the queue and join its feeder thread."""
        self._queue.close()
        self._queue.join_thread()

    def _listen(self) -> None:
        """Run the listener loop, then close the queue if stop() asked to."""
        try:
            self._drain()
        finally:
            if self._close_queue:
                self._close()

    def _drain(self) -> None:
        """
        Main listener loop - runs in background thread.

        Continuously reads from the queue and dispatches records to handlers.
        Exits on the sentinel stop() posts, once every record queued before it
        is handled; or, stopped with no sentinel queued (the queue was full or
        closed), once the queue is empty; or once the queue is closed under
        it. A record get() cannot decode is reported and skipped.
        """
        while True:
            try:
                record = self._queue.get(timeout=0.5)
            except queue.Empty:
                if self._stop_event.is_set():
                    break
                continue
            except Exception:
                # multiprocessing.Queue unpickles in get(), so a bad record
                # raises here too; a closed queue is told by the flag close()
                # sets (private, but what get() itself checks), not the error
                if getattr(self._queue, "_closed", False):
                    break
                _report("decoding")
                continue
            if record is None:  # the sentinel: shutdown
                break
            try:
                self._handle_record(record)
            except Exception:  # the listener thread outlives a bad record
                _report("handling")

    def _handle_record(self, record: logging.LogRecord) -> None:
        """
        Dispatch a record to the logger's handlers.

        Args:
            record: Log record to handle
        """
        # Use logger.handle() which respects the logger's level and calls handlers
        # But we want to use the logger's handlers directly to avoid level filtering
        # since the record was already filtered in the subprocess
        for handler in self._get_handlers():
            if self._respect_handler_level and record.levelno < handler.level:
                continue
            try:
                handler.handle(record)
            except Exception:
                handler.handleError(record)

    def _get_handlers(self) -> list[logging.Handler]:
        """
        Get handlers to dispatch to.

        For view loggers (those with _root_logger), uses the root's handlers.

        Returns:
            List of handlers to use
        """
        root = getattr(self._logger, "_root_logger", None)
        if root is not None:
            return list(root.handlers)
        return list(self._logger.handlers)

    @property
    def is_alive(self) -> bool:
        """Check if the listener thread is running."""
        return self._thread is not None and self._thread.is_alive()
