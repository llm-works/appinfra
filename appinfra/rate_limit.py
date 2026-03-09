"""
Rate limiting functionality for controlling request frequency.

This module provides a RateLimiter class for implementing rate limiting
to control the frequency of operations or API calls, and a Backoff class
for implementing exponential backoff retry logic.
"""

import random
import threading
import time

from . import time as t
from .log import Logger


class RateLimiter:
    """
    Thread-safe rate limiter for controlling operation frequency.

    Provides functionality to limit the rate of operations to a specified
    number per minute, with automatic waiting when the rate limit is exceeded.
    All methods are safe to call concurrently from multiple threads.
    """

    def __init__(self, lg: Logger, per_minute: float) -> None:
        """
        Initialize the rate limiter.

        Args:
            lg: Logger instance for rate limiting operations
            per_minute: Maximum number of operations per minute (e.g., 1/60 for once per hour)

        Raises:
            ValueError: If per_minute is not positive.
        """
        if per_minute <= 0:
            raise ValueError("per_minute must be positive")
        self._lg = lg
        self.per_minute = per_minute
        self._lock = threading.Lock()
        # Initialize to future time so first request also respects rate limit
        self.last_t: float = time.monotonic() + 60.0 / per_minute

    def next(self, respect_max_ticks: bool = True) -> float:
        """
        Wait for the next allowed operation time.

        Calculates the required delay based on the rate limit and sleeps
        if necessary to maintain the specified rate. Thread-safe.

        Args:
            respect_max_ticks (bool): Whether to respect the rate limit

        Returns:
            float: Time waited in seconds
        """
        delay = 60.0 / self.per_minute
        with self._lock:
            now = time.monotonic()
            if now >= self.last_t:
                # Slot available now, claim next slot
                wait = 0.0
                self.last_t = now + delay
            else:
                # Need to wait for current slot
                wait = self.last_t - now
                self.last_t = self.last_t + delay
        # Sleep outside lock to avoid blocking other threads
        if wait > 0 and respect_max_ticks:
            self._lg.trace(
                "rate limiter wait",
                extra={"wait": t.delta.delta_str(wait, precise=False)},
            )
            time.sleep(wait)
        return wait

    def try_next(self) -> bool:
        """
        Non-blocking rate limit check.

        Checks if the rate limit allows an operation without blocking.
        If allowed, claims the slot and returns True.
        If rate limited, returns False without modifying state. Thread-safe.

        This method is useful for event loops that cannot block, such as
        message-processing loops that need to handle signals while rate-limiting
        operations.

        Returns:
            bool: True if operation is allowed (claims slot), False if rate limited.

        Example:
            if limiter.try_next():
                do_operation()
            else:
                # Skip this cycle, will retry on next loop iteration
                pass
        """
        delay = 60.0 / self.per_minute
        with self._lock:
            now = time.monotonic()
            if now >= self.last_t:
                # Slot available, claim next slot
                self.last_t = now + delay
                return True
            return False

    def can_proceed(self) -> bool:
        """
        Check if rate limit allows an operation (non-consuming).

        Unlike try_next(), this does NOT claim a slot.
        Use this for informational checks in event loops where you need to
        know availability without committing to an operation. Thread-safe.

        Returns:
            bool: True if a call would be allowed, False if rate limited.

        Example:
            while True:
                if limiter.can_proceed():
                    limiter.try_next()  # Actually claim the slot
                    do_operation()
                else:
                    handle_other_work()
        """
        with self._lock:
            return time.monotonic() >= self.last_t


class Backoff:
    """
    Exponential backoff for retry logic.

    Provides functionality to implement exponential backoff when retrying
    failed operations, with configurable base delay, maximum delay, growth
    factor, and optional jitter to avoid thundering herd problems.
    """

    def __init__(
        self,
        lg: Logger,
        base: float = 1.0,
        max_delay: float = 60.0,
        factor: float = 2.0,
        jitter: bool = True,
    ) -> None:
        """
        Initialize the backoff controller.

        Args:
            lg: Logger instance for backoff operations
            base: Initial delay in seconds (default: 1.0)
            max_delay: Maximum delay cap in seconds (default: 60.0)
            factor: Multiplier applied per attempt (default: 2.0)
            jitter: Whether to randomize delays to avoid thundering herd (default: True)

        Raises:
            ValueError: If base, max_delay, or factor have invalid values.
        """
        if base <= 0:
            raise ValueError("base must be positive")
        if max_delay <= 0:
            raise ValueError("max_delay must be positive")
        if factor < 1:
            raise ValueError("factor must be >= 1")
        self._lg = lg
        self.base = base
        self.max_delay = max_delay
        self.factor = factor
        self.jitter = jitter
        self._attempts = 0

    @property
    def attempts(self) -> int:
        """Return the current attempt count."""
        return self._attempts

    def next_delay(self) -> float:
        """
        Calculate the next backoff delay and increment attempt count.

        The delay is calculated as: min(base * (factor ** attempts), max_delay)
        If jitter is enabled, the delay is multiplied by a random factor
        between 0.0 and 1.0 (full jitter pattern).

        Returns:
            float: The calculated delay in seconds.
        """
        delay = min(self.base * (self.factor**self._attempts), self.max_delay)
        if self.jitter:
            delay = delay * random.uniform(0.0, 1.0)
        self._attempts += 1
        return delay

    def wait(self) -> float:
        """
        Wait for the calculated backoff delay.

        Calculates the next delay using next_delay(), sleeps for that duration,
        and returns the actual delay.

        Returns:
            float: The actual delay waited in seconds.
        """
        delay = self.next_delay()
        self._lg.trace(
            "backoff wait",
            extra={
                "delay": t.delta.delta_str(delay, precise=False),
                "attempt": self._attempts,
            },
        )
        time.sleep(delay)
        return delay

    def reset(self) -> None:
        """Reset the attempt counter after a successful operation."""
        self._attempts = 0
