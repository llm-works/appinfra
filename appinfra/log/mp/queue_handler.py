"""
Multiprocessing-safe queue handler for appinfra logging.

This module provides a QueueHandler that properly serializes log records
for cross-process communication, handling exceptions and custom attributes
that are not picklable.
"""

from __future__ import annotations

import logging
import sys
import traceback
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from multiprocessing import Queue as QueueType


class MPQueueHandler(logging.Handler):
    """
    Multiprocessing-safe queue handler for appinfra.

    Unlike Python's standard QueueHandler, this handler properly handles:
    - Exception tracebacks (formatted to string before pickling)
    - appinfra's __infra__extra with exception objects
    - Format arguments that may not be picklable

    Usage:
        # In subprocess
        from multiprocessing import Queue
        from . import MPQueueHandler

        queue = Queue()
        handler = MPQueueHandler(queue)
        logger.addHandler(handler)
    """

    def __init__(self, queue: QueueType[logging.LogRecord | None]) -> None:
        """
        Initialize the queue handler.

        Args:
            queue: multiprocessing.Queue to send records to
        """
        super().__init__()
        self.queue = queue

    def emit(self, record: logging.LogRecord) -> None:
        """
        Emit a record by preparing it and putting it on the queue.

        Args:
            record: Log record to emit
        """
        try:
            prepared = self._prepare(record)
            self.queue.put_nowait(prepared)
        except Exception:
            self.handleError(record)

    def _prepare(self, record: logging.LogRecord) -> logging.LogRecord:
        """
        Prepare a record for cross-process pickling.

        This method:
        1. Formats exception tracebacks to strings (tracebacks aren't picklable)
        2. Handles exception objects in __infra__extra
        3. Formats message arguments into the message string

        Args:
            record: Log record to prepare

        Returns:
            Prepared log record safe for pickling
        """
        # Format exception to string while we have the traceback context
        if record.exc_info:
            record.exc_text = self._format_exc_info(record.exc_info)
            record.exc_info = None

        # Handle exception in __infra__extra (appinfra's extra={"exception": e} pattern)
        self._prepare_infra_extra(record)

        # Format args into message (args might contain unpicklable objects)
        try:
            record.msg = record.getMessage()
            record.args = None
        except Exception:
            # If getMessage() fails, keep original msg and clear args
            record.args = None

        return record

    def _prepare_infra_extra(self, record: logging.LogRecord) -> None:
        """
        Prepare __infra__extra dict for pickling.

        Converts exception objects to formatted strings. Handles:
        - The standard "exception" key (renamed to "exception_formatted")
        - Any other keys containing exceptions (converted in-place)
        - Nested dicts and lists containing exceptions

        Args:
            record: Log record to modify in place
        """
        extra = getattr(record, "__infra__extra", None)
        if extra is None:
            return

        # Recursively sanitize to handle exceptions anywhere in the structure
        extra = self._sanitize_for_pickle(extra, set())
        setattr(record, "__infra__extra", extra)

    def _sanitize_for_pickle(self, obj: Any, seen: set[int]) -> Any:
        """
        Recursively sanitize an object for pickling.

        Converts BaseException instances to formatted strings.
        Handles dicts, lists, tuples, and sets. Detects cycles to prevent
        infinite recursion on self-referential structures.

        Args:
            obj: Object to sanitize
            seen: Set of object ids already visited (for cycle detection)

        Returns:
            Sanitized object safe for pickling
        """
        if isinstance(obj, BaseException):
            return self._format_exception_in_context(obj)

        # Cycle detection for mutable container types
        if isinstance(obj, (dict, list, set)):
            if id(obj) in seen:
                return "<cyclic reference>"
            seen = seen | {id(obj)}

        if isinstance(obj, dict):
            return self._sanitize_dict(obj, seen)
        if isinstance(obj, list):
            return [self._sanitize_for_pickle(item, seen) for item in obj]
        if isinstance(obj, tuple):
            return tuple(self._sanitize_for_pickle(item, seen) for item in obj)
        if isinstance(obj, set):
            return {self._sanitize_for_pickle(item, seen) for item in obj}
        return obj

    def _sanitize_dict(self, obj: dict, seen: set[int]) -> dict:
        """Sanitize a dict, handling the special 'exception' key rename."""
        result = {}
        for key, value in obj.items():
            sanitized = self._sanitize_for_pickle(value, seen)
            if key == "exception" and isinstance(value, BaseException):
                result["exception_formatted"] = sanitized
            else:
                result[key] = sanitized
        return result

    def _format_exc_info(
        self, exc_info: tuple[type, BaseException, Any] | tuple[None, None, None]
    ) -> str:
        """
        Format exc_info tuple to string.

        Args:
            exc_info: Exception info tuple from sys.exc_info()

        Returns:
            Formatted traceback string
        """
        if exc_info[0] is None:
            return ""
        return "".join(traceback.format_exception(*exc_info))

    def _format_exception_in_context(self, exc: BaseException) -> str:
        """
        Format an exception with traceback if we're in the exception context.

        If the exception is the current exception being handled, we can get
        its full traceback. Otherwise, we just format the exception itself.

        Args:
            exc: Exception to format

        Returns:
            Formatted exception string, with traceback if available
        """
        # Check if this exception is the one currently being handled
        current_exc_info = sys.exc_info()
        if current_exc_info[1] is exc:
            return "".join(traceback.format_exception(*current_exc_info))

        # Not the current exception - format without traceback
        return f"{exc.__class__.__name__}: {exc}"

    def close(self) -> None:
        """Close the handler."""
        self.acquire()
        try:
            super().close()
        finally:
            self.release()
