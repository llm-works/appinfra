"""
Shutdown manager for handling application shutdown signals.

This module provides signal handling for graceful application termination
on SIGTERM and SIGINT signals. The signal handler raises KeyboardInterrupt
to allow proper cleanup before shutdown.
"""

import signal
import time
from typing import Any


class ShutdownManager:
    """
    Manages shutdown signal handling.

    Registers handlers for SIGTERM and SIGINT that raise KeyboardInterrupt,
    allowing the call stack to unwind properly before shutdown. This ensures
    async cleanup (finally blocks, context managers) completes before the
    lifecycle logs "done".

    Usage:
        manager = ShutdownManager()
        manager.register_signal_handlers()

        # Later, check state or get return code:
        if manager.is_shutting_down():
            code = manager.get_signal_return_code()
    """

    def __init__(self) -> None:
        """Initialize shutdown manager."""
        self._shutting_down = False
        self._signal_return_code: int = 130  # Default to SIGINT
        self._original_handlers: dict[signal.Signals, Any] = {}

    def register_signal_handlers(self) -> None:
        """Register signal handlers for SIGTERM and SIGINT."""
        self._original_handlers[signal.SIGTERM] = signal.signal(
            signal.SIGTERM, self._handle_signal
        )
        self._original_handlers[signal.SIGINT] = signal.signal(
            signal.SIGINT, self._handle_signal
        )

    def _handle_signal(self, signum: int, frame: Any) -> None:
        """
        Handle shutdown signal by raising KeyboardInterrupt.

        This allows tool code to unwind properly (finally blocks, __aexit__, etc.)
        before App.main() catches the exception and calls lifecycle.shutdown().

        Args:
            signum: Signal number (SIGINT=2, SIGTERM=15)
            frame: Current stack frame (unused)
        """
        if self._shutting_down:
            return  # Ignore duplicate signals

        self._shutting_down = True
        self._signal_return_code = 130 if signum == signal.SIGINT else 143
        raise KeyboardInterrupt()

    def is_shutting_down(self) -> bool:
        """Check if shutdown is in progress."""
        return self._shutting_down

    def get_signal_return_code(self) -> int:
        """
        Get the return code for the signal that triggered shutdown.

        Returns:
            130 for SIGINT (Ctrl+C), 143 for SIGTERM, or 130 as default.
        """
        return self._signal_return_code

    def sleep(self, seconds: float) -> bool:
        """
        Sleep up to ``seconds``, waking early if a shutdown signal fires.

        Safe to call from any thread. Use in place of ``time.sleep`` inside
        worker code so SIGTERM does not stall shutdown for the full sleep
        duration (``KeyboardInterrupt`` only unwinds the main thread).

        Uses polling (5ms interval) rather than ``threading.Event`` to avoid
        deadlock risk: ``Event.set()`` acquires a lock, and calling it from a
        signal handler can deadlock if the main thread holds that lock.

        Args:
            seconds: Maximum time to sleep (must be non-negative).

        Returns:
            True if a shutdown signal fired during (or before) the sleep,
            False if the full time was slept.

        Raises:
            ValueError: If seconds is negative.
        """
        if seconds < 0:
            raise ValueError("sleep length must be non-negative")
        deadline = time.monotonic() + seconds
        while not self._shutting_down:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(remaining, 0.005))
        return True
