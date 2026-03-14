"""
Ticker system for periodic task execution.

This module provides classes for implementing periodic task execution
with both scheduled and continuous modes. The system supports both
interval-based scheduling and continuous execution patterns.

The ticker system is designed for applications that need to perform
periodic tasks such as:
- Health checks and monitoring
- Data synchronization
- Periodic cleanup operations
- Status reporting
- Background processing

Key Features:
- Scheduled execution with precise intervals
- Continuous execution for high-frequency tasks
- Graceful stopping with cleanup
- Error handling and recovery
- Thread-safe operation
- Status monitoring and introspection

Example Usage:
    import logging

    lg = logging.getLogger(__name__)

    # Scheduled execution (every 5 seconds) with handler class
    class MyHandler(TickerHandler):
        def __init__(self):
            self.lg = logging.getLogger(__name__)

        def ticker_start(self, *args, **kwargs):
            self.lg.info("Ticker started")

        def ticker_tick(self):
            self.lg.info("Tick executed")

        def ticker_stop(self):
            self.lg.info("Ticker stopped")

    handler = MyHandler()
    ticker = Ticker(lg, handler, secs=5)
    ticker.run()

    # Simple callable (auto-wrapped)
    ticker = Ticker(lg, lambda: print("tick"), secs=5)
    ticker.run()

    # Continuous execution (no secs parameter)
    ticker = Ticker(lg, handler)
    ticker.run()

    # Non-blocking mode for mixed event sources
    ticker = Ticker(lg, secs=30, mode=TickerMode.FLEX)
    while running:
        msg = channel.recv(timeout=ticker.time_until_next_tick())
        if msg:
            handle_message(msg)
        ticker.try_tick()
"""

import sched
import signal
import threading
import time
from collections.abc import Callable, Iterator
from enum import Enum
from types import FrameType
from typing import Any, Self

from appinfra.errors import TickerAPIError, TickerConfigError, TickerStateError
from appinfra.log import Logger


class TickerMode(Enum):
    """
    Timing mode for ticker execution.

    Attributes:
        FLEX: Flexible timing - fixed-rate from tick start with no catch-up.
              Maintains interval timing but resets if tasks run late. Prevents
              multiple back-to-back ticks. Safe default that prevents runaway
              execution.

        STRICT: Strict timing - maintains average tick rate by catching up if
                tasks run slow. Use for synchronization to external clock.

        SPACED: Spaced timing - always waits full interval from task completion.
                Guarantees minimum spacing between tasks. Use for rate limiting
                API calls or ensuring recovery time between ops.

    Example:
        # Flex mode (default) - maintains interval, no catch-up
        ticker = Ticker(lg, secs=1, mode=TickerMode.FLEX)
        # If task takes 0.2s, next tick at t=1.0 (0.8s wait)
        # If task takes 1.2s, next tick at t=1.2 (0s wait), then resets from there

        # Strict mode - maintains rate, catches up
        ticker = Ticker(lg, secs=1, mode=TickerMode.STRICT)
        # If task takes 1.2s, ticks immediately to catch up, maintains average rate

        # Spaced mode - guarantees spacing
        ticker = Ticker(lg, secs=1, mode=TickerMode.SPACED)
        # If task takes 0.2s, next tick at t=1.2 (1.0s wait from completion)
        # If task takes 1.2s, next tick at t=2.2 (1.0s wait from completion)
    """

    FLEX = "flex"
    STRICT = "strict"
    SPACED = "spaced"


class TickerHandler:
    """
    Interface for objects that handle ticker events.

    Defines the methods that ticker-aware objects must implement
    to participate in the ticker system. All methods are optional
    and have default no-op implementations.

    This interface allows objects to participate in the ticker system
    by implementing the lifecycle methods they need. The ticker will
    call these methods at appropriate times during its execution.

    Example:
        import logging

        class DatabaseMonitor(TickerHandler):
            def __init__(self, db_connection):
                self.db = db_connection
                self.check_count = 0
                self.lg = logging.getLogger(__name__)

            def ticker_start(self, *args, **kwargs):
                self.lg.info("Starting database monitoring")
                self.check_count = 0

            def ticker_tick(self):
                self.check_count += 1
                if self.db.is_healthy():
                    self.lg.info(f"Database check #{self.check_count}: OK")
                else:
                    self.lg.warning(f"Database check #{self.check_count}: FAILED")

            def ticker_stop(self):
                self.lg.info(f"Database monitoring stopped after {self.check_count} checks")
    """

    def ticker_start(self, *args: Any, **kwargs: Any) -> None:
        """
        Called when the ticker starts.

        Args:
            *args: Positional arguments passed to ticker
            **kwargs: Keyword arguments passed to ticker
        """
        pass

    def ticker_before_first_tick(self, *args: Any, **kwargs: Any) -> None:
        """
        Called before the first tick execution.

        Args:
            *args: Positional arguments passed to ticker
            **kwargs: Keyword arguments passed to ticker
        """
        pass

    def ticker_tick(self) -> None:
        """
        Called on each tick execution.

        This method should contain the periodic work to be performed.
        """
        pass

    def ticker_stop(self) -> None:
        """
        Called when the ticker stops.

        This method is called when the ticker is stopped gracefully.
        """
        pass


class _CallableWrapper(TickerHandler):
    """
    Wrapper that adapts a plain callable to the TickerHandler interface.

    This allows users to pass simple functions or lambdas to Ticker
    without having to create a TickerHandler subclass.
    """

    def __init__(self, fn: Callable[[], None]) -> None:
        """
        Initialize the wrapper with a callable.

        Args:
            fn: Callable to execute on each tick
        """
        self._fn = fn

    def ticker_tick(self) -> None:
        """Execute the wrapped callable."""
        self._fn()


class Ticker:
    """
    Periodic task execution system.

    Provides both scheduled (with intervals) and continuous execution modes
    for periodic tasks. Can work with TickerHandler objects to execute
    periodic operations.

    The ticker supports four usage patterns:

    1. Callback-based (using run()):
        ticker = Ticker(lg, lambda: do_work(), secs=5)
        ticker.run()

    2. Iterator (for-loop):
        for tick in Ticker(lg, secs=5):
            do_work()

    3. Iterator with context manager (recommended for signal handling):
        with Ticker(lg, secs=5) as t:
            for tick in t:
                do_work()
                # Stops gracefully on SIGTERM/SIGINT

    4. Non-blocking manual control (for mixed event sources):
        ticker = Ticker(lg, secs=30)
        while running:
            msg = channel.recv(timeout=ticker.time_until_next_tick())
            if msg:
                handle_message(msg)
            ticker.try_tick()  # Only ticks if interval elapsed

    Thread safety: The ticker is NOT thread-safe. Internal state (_first flag,
    _last_tick_time, _api_mode) is not protected by locks. Do not call ticker
    methods concurrently from multiple threads. Do not mix API modes (run/try_tick/
    iterator) even from the same thread - each Ticker instance must use exactly
    one API pattern throughout its lifetime.

    Example:
        import logging
        import threading

        lg = logging.getLogger(__name__)

        # Scheduled execution every 10 seconds with handler
        class HealthChecker(TickerHandler):
            def __init__(self):
                self.lg = logging.getLogger(__name__)

            def ticker_tick(self):
                self.lg.info("Checking system health...")

        handler = HealthChecker()
        ticker = Ticker(lg, handler, secs=10)

        # Run in a separate thread
        thread = threading.Thread(target=ticker.run, daemon=True)
        thread.start()

        # Stop gracefully
        ticker.stop()

        # Or use iterator pattern with subprocess context
        with app.subprocess_context() as ctx:
            with Ticker(ctx.lg, secs=30) as ticker:
                for tick in ticker:
                    sync_data()
    """

    @staticmethod
    def _validate_init_params(mode: TickerMode, secs: float | None) -> None:
        """Validate ticker initialization parameters."""
        if not isinstance(mode, TickerMode):
            raise TickerConfigError(
                f"mode must be TickerMode enum, got {type(mode).__name__}"
            )
        if secs is not None and secs <= 0:
            raise TickerConfigError(f"secs must be positive, got {secs}")

    def __init__(
        self,
        lg: Logger,
        handler: TickerHandler | Callable[[], None] | None = None,
        secs: float | None = None,
        initial: bool = True,
        mode: TickerMode = TickerMode.FLEX,
    ) -> None:
        """
        Initialize the ticker.

        Args:
            lg: Logger instance for error logging
            handler: TickerHandler instance or callable to execute on each tick.
                     Plain callables are automatically wrapped in a TickerHandler.
                     Optional when using iterator pattern (required for run()).
            secs: Interval between ticks in seconds (None for continuous mode)
            initial: Whether to run tick immediately on start (default True).
                     If False, waits for first interval before firing.
            mode: Timing mode (FLEX, STRICT, or SPACED). FLEX (default) maintains
                  interval from tick start without catch-up. STRICT maintains average
                  rate by catching up. SPACED waits full interval from completion.
        """
        self._validate_init_params(mode, secs)

        # Auto-wrap plain callables in a TickerHandler
        if (
            handler is not None
            and callable(handler)
            and not isinstance(handler, TickerHandler)
        ):
            handler = _CallableWrapper(handler)

        self._lg = lg
        self._handler: TickerHandler | None = handler
        self._secs = secs
        self._initial = initial
        self._mode = mode
        self._first = True
        self._running = False
        self._stop_event = threading.Event()
        self._sched = (
            sched.scheduler(time.monotonic, time.sleep) if secs is not None else None
        )
        # For context manager signal handling (stores previous handlers)
        self._prev_sigterm: Any = None
        self._prev_sigint: Any = None
        # For non-blocking API (try_tick/time_until_next_tick)
        self._last_tick_time: float | None = None
        # API mode tracking (prevents mixing run() with try_tick())
        self._api_mode: str | None = (
            None  # "blocking" for run(), "nonblocking" for try_tick()
        )

    def run(self, *args: Any, **kwargs: Any) -> None:
        """
        Start the ticker execution (callback-based mode).

        Requires a handler to be set. For iterator-based usage, use the
        for-loop pattern instead.

        Args:
            *args: Positional arguments to pass to handler
            **kwargs: Keyword arguments to pass to handler

        Raises:
            TickerStateError: If ticker is already running
            TickerAPIError: If try_tick() or iterator was already used (API mode conflict)
            TickerConfigError: If no handler was provided

        Example:
            >>> import threading
            >>> from appinfra.time.ticker import Ticker, TickerHandler
            >>>
            >>> class MetricsCollector(TickerHandler):
            ...     def ticker_tick(self):
            ...         collect_and_report_metrics()
            >>>
            >>> ticker = Ticker(logger, MetricsCollector(), secs=30)
            >>>
            >>> # Run in background thread
            >>> thread = threading.Thread(target=ticker.run, daemon=True)
            >>> thread.start()
            >>>
            >>> # Later, stop gracefully
            >>> ticker.stop()
        """
        if self._handler is None:
            raise TickerConfigError(
                "Handler required for run() mode. Use iterator pattern instead."
            )
        if self._running:
            raise TickerStateError("Ticker is already running")
        if self._api_mode == "nonblocking":
            raise TickerAPIError(
                "Cannot call run() after using try_tick(). "
                "Choose one API mode per Ticker instance."
            )
        if self._api_mode == "iterator":
            raise TickerAPIError(
                "Cannot call run() after using iterator. "
                "Choose one API mode per Ticker instance."
            )

        self._api_mode = "blocking"
        self._running = True
        self._stop_event.clear()

        try:
            self._handler.ticker_start(*args, **kwargs)
            self.run_started(*args, **kwargs)
        except Exception as e:
            self._running = False
            raise TickerStateError(f"Ticker execution failed: {e}") from e

    def run_started(self, *args: Any, **kwargs: Any) -> None:
        """
        Execute the ticker after startup.

        Chooses between scheduled and continuous execution based on configuration.

        Args:
            *args: Positional arguments to pass to handler
            **kwargs: Keyword arguments to pass to handler
        """
        kwargs = self._update_params_from_kwargs(kwargs)

        # Handler is guaranteed to be set - run() validates this
        assert self._handler is not None

        try:
            if self._sched is not None:
                # Scheduled execution mode
                self._tick_sched(*args, **kwargs)
                self._sched.run()
            else:
                # Continuous execution mode
                self._handler.ticker_before_first_tick(*args, **kwargs)
                while not self._stop_event.is_set():
                    try:
                        self._handler.ticker_tick()
                    except Exception as e:
                        # Log error but continue running unless it's a critical error
                        self._lg.exception(
                            "Error in ticker_tick", extra={"exception": e}
                        )
        finally:
            self._running = False
            # Note: ticker_stop() is now called immediately in stop() method
            # to ensure cleanup logging happens during shutdown phase, not here

    def _tick_sched(self, *args: Any, **kwargs: Any) -> None:
        """
        Schedule the next tick in scheduled mode with mode-aware timing.

        Args:
            *args: Positional arguments to pass to handler
            **kwargs: Keyword arguments to pass to handler
        """
        if self._secs is None:
            raise TickerConfigError("Cannot schedule tick without secs parameter")

        assert self._handler is not None
        assert self._sched is not None

        if not self._stop_event.is_set():
            tick_start_time = time.monotonic()

            # Handle first tick initialization
            if self._first and self._handle_first_tick_sched(
                tick_start_time, args, kwargs
            ):
                return  # Delayed first tick - return early

            # Execute handler
            try:
                self._handler.ticker_tick()
            except Exception as e:
                self._lg.exception("Error in ticker_tick", extra={"exception": e})

            # Calculate and schedule next tick
            tick_end_time = time.monotonic()
            delay = self._calculate_next_tick_delay(tick_start_time, tick_end_time)
            self._sched.enter(delay, 1, self._tick_sched, args, kwargs)

    def _handle_first_tick_sched(
        self, tick_start_time: float, args: tuple[Any, ...], kwargs: dict[str, Any]
    ) -> bool:
        """
        Handle first tick initialization for scheduled mode.

        Returns:
            bool: True if should return early (delayed first tick), False otherwise
        """
        self._first = False
        try:
            self._handler.ticker_before_first_tick(*args, **kwargs)  # type: ignore
        except Exception as e:
            self._lg.exception(
                "Error in ticker_before_first_tick", extra={"exception": e}
            )

        if not self._initial:
            # Initialize timing for delayed first tick
            self._last_tick_time = tick_start_time
            self._sched.enter(self._secs, 1, self._tick_sched, args, kwargs)  # type: ignore
            return True
        return False

    def _calculate_next_tick_delay(
        self, tick_start_time: float, tick_end_time: float
    ) -> float:
        """
        Calculate delay until next tick based on timing mode.

        Args:
            tick_start_time: Time when tick started (before handler)
            tick_end_time: Time when tick completed (after handler)

        Returns:
            float: Delay in seconds until next tick (>= 0)
        """
        if self._secs is None:  # pragma: no cover
            raise TickerConfigError(
                "Cannot calculate delay without secs parameter (continuous mode not supported)"
            )

        # Initialize timing reference if needed
        if self._last_tick_time is None:
            self._last_tick_time = tick_start_time

        if self._mode == TickerMode.FLEX:
            return self._delay_flex_mode(tick_start_time, tick_end_time)
        elif self._mode == TickerMode.STRICT:
            return self._delay_strict_mode(tick_end_time)
        else:  # TickerMode.SPACED
            return self._delay_spaced_mode(tick_end_time)

    def _delay_flex_mode(self, tick_start_time: float, tick_end_time: float) -> float:
        """
        Calculate delay for FLEX mode (no catch-up, resets if late).

        IMPORTANT: This method calculates the next tick time using the CURRENT value
        of _last_tick_time, then updates it for the next iteration. The order matters:
        - First: Calculate next_tick_time from OLD _last_tick_time
        - Then: Update _last_tick_time based on whether we're late or on-time
        This ensures the calculation uses the previous tick's reference time.
        """
        # Invariant: both secs and _last_tick_time must be set when calling this method
        if self._secs is None:  # pragma: no cover
            raise TickerConfigError("secs must be set for FLEX mode")
        if self._last_tick_time is None:  # pragma: no cover
            raise TickerConfigError(
                "_last_tick_time must be initialized before FLEX mode"
            )

        # Calculate when next tick SHOULD happen based on previous tick
        next_tick_time = self._last_tick_time + self._secs

        if tick_end_time >= next_tick_time:
            # Late - reset timing from now to prevent catch-up
            self._last_tick_time = tick_end_time
            return self._secs
        else:
            # On time - maintain interval from last tick start
            self._last_tick_time = tick_start_time
            return next_tick_time - tick_end_time

    def _delay_strict_mode(self, tick_end_time: float) -> float:
        """Calculate delay for STRICT mode (maintains average rate)."""
        # Invariant: both secs and _last_tick_time must be set when calling this method
        if self._secs is None:  # pragma: no cover
            raise TickerConfigError("secs must be set for STRICT mode")
        if self._last_tick_time is None:  # pragma: no cover
            raise TickerConfigError(
                "_last_tick_time must be initialized before STRICT mode"
            )

        self._last_tick_time += self._secs
        next_tick_time = self._last_tick_time
        delay = next_tick_time - tick_end_time

        # Warn if we're falling far behind (catch-up will cause back-to-back ticks)
        if delay < 0:
            intervals_behind = abs(delay) / self._secs
            if intervals_behind > 5:
                self._lg.warning(
                    "STRICT mode: falling behind schedule, catch-up will cause rapid ticking",
                    extra={
                        "intervals_behind": intervals_behind,
                        "delay_seconds": delay,
                        "interval_seconds": self._secs,
                    },
                )

        return max(0.0, delay)

    def _delay_spaced_mode(self, tick_end_time: float) -> float:
        """Calculate delay for SPACED mode (guaranteed spacing from completion)."""
        # Invariant: secs must be set when calling this method
        if self._secs is None:  # pragma: no cover
            raise TickerConfigError("secs must be set for SPACED mode")

        self._last_tick_time = tick_end_time
        return self._secs

    def _update_params_from_kwargs(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        """
        Update ticker parameters from keyword arguments.

        Args:
            kwargs: Keyword arguments dictionary

        Returns:
            dict: Updated keyword arguments
        """
        # Fix: Check for the correct key names
        if "ticker_secs" in kwargs:
            self._secs = kwargs["ticker_secs"]
            del kwargs["ticker_secs"]
        if "ticker_initial" in kwargs:
            self._initial = kwargs["ticker_initial"]
            del kwargs["ticker_initial"]
        return kwargs

    def stop(self) -> None:
        """
        Stop the ticker gracefully.

        This method signals the ticker to stop. If a handler is set, calls the
        handler's ticker_stop method immediately. The ticker will stop after
        the current tick completes.
        """
        self._stop_event.set()

        if self._running:
            # For scheduled mode, we need to cancel pending events
            if self._sched is not None:
                # Cancel all pending events
                for event in self._sched.queue:
                    self._sched.cancel(event)

            # Call ticker_stop handler immediately so cleanup logging
            # happens during the shutdown phase, not in finally block
            if self._handler is not None:
                try:
                    self._handler.ticker_stop()
                except Exception:
                    # Log error but continue with stop
                    self._lg.exception("Error in ticker_stop callback")

    def is_running(self) -> bool:
        """
        Check if the ticker is currently running.

        Returns:
            bool: True if the ticker is running, False otherwise
        """
        return self._running

    def get_status(self) -> dict:
        """
        Get the current status of the ticker.

        Returns:
            dict: Status information including running state, mode, and interval
        """
        return {
            "running": self._running,
            "mode": "scheduled" if self._sched is not None else "continuous",
            "interval": self._secs,
            "first_tick": self._first,
            "stop_requested": self._stop_event.is_set(),
        }

    # Non-blocking API for manual control

    def _validate_now_parameter(self, now: float, caller: str) -> None:
        """Validate user-provided 'now' parameter to catch common timing mistakes."""
        if now < 0:
            self._lg.warning(
                "Invalid 'now' parameter: negative value",
                extra={"now": now, "caller": caller},
            )
        elif self._last_tick_time is not None and now < self._last_tick_time - 10.0:
            # Allow small backwards jumps (clock adjustments), but warn on large ones
            self._lg.warning(
                "Suspicious 'now' parameter: far in past relative to last tick",
                extra={
                    "now": now,
                    "last_tick_time": self._last_tick_time,
                    "delta": now - self._last_tick_time,
                },
            )

    def _initialize_timing_state(self, now: float) -> None:
        """Initialize timing reference on first use with initial=False."""
        if (
            self._last_tick_time is None
            and not self._initial
            and self._secs is not None
        ):
            self._last_tick_time = now

    def time_until_next_tick(self, now: float | None = None) -> float:
        """
        Get seconds until next tick is due.

        This method provides timing information for event loops that need to
        multiplex multiple event sources. Use the return value as a timeout
        for blocking operations like channel.recv() or select().

        Args:
            now: Optional current time from time.monotonic(). If not provided,
                 time.monotonic() will be called. Pass this to avoid multiple
                 time.monotonic() calls and ensure timing accuracy.
                 **IMPORTANT**: Must be from time.monotonic(), not time.time()
                 or any other time source.

        Returns:
            float: Seconds until next tick is due.
                   Returns 0.0 if tick is ready now or in continuous mode.

        Example:
            >>> ticker = Ticker(lg, secs=30)
            >>> while running:
            ...     timeout = ticker.time_until_next_tick()
            ...     msg = channel.recv(timeout=timeout)
            ...     if msg:
            ...         handle_message(msg)
            ...     ticker.try_tick()

        Note:
            - Uses time.monotonic() for monotonic, drift-free timing
            - Continuous mode (secs=None) always returns 0.0
            - First tick with initial=True returns 0.0 (ready immediately)
            - FLEX mode: Interval from tick start, no catch-up (resets if late)
            - STRICT mode: Maintains rate, can return 0.0 for catch-up
            - SPACED mode: Interval from tick completion (guaranteed spacing)

        Warning:
            If passing 'now', it MUST be from time.monotonic(). Using time.time()
            or other time sources will cause incorrect behavior due to clock
            adjustments (NTP, DST, manual changes).
        """
        if now is None:
            now = time.monotonic()

        self._validate_now_parameter(now, "time_until_next_tick")

        # Continuous mode - always ready to tick
        if self._secs is None:
            return 0.0

        # First tick with initial=True - ready immediately
        if self._first and self._initial:
            return 0.0

        # If timing not initialized yet, first tick needs full interval
        # (Initialization happens in try_tick() to avoid side effects in query method)
        if self._last_tick_time is None:
            # Return full interval - first tick will happen after secs elapse
            return self._secs

        # Calculate next tick time
        next_tick_time = self._last_tick_time + self._secs
        remaining = next_tick_time - now
        return max(0.0, remaining)

    def try_tick(self, now: float | None = None) -> bool:
        """
        Execute tick if interval has elapsed. Returns True if tick was executed.

        This method is non-blocking and safe to call repeatedly. It only
        executes a tick when the configured interval has elapsed. Use this
        for event loops that need manual control over tick execution.

        Timing behavior depends on mode:
        - FLEX (default): Interval from tick start, no catch-up (resets if late)
        - STRICT: Maintains average rate, catches up if tasks run slow
        - SPACED: Interval from tick completion (guaranteed minimum spacing)

        Args:
            now: Optional current time from time.monotonic(). If not provided,
                 time.monotonic() will be called. Pass this to avoid multiple
                 time.monotonic() calls and ensure timing accuracy.
                 **IMPORTANT**: Must be from time.monotonic(), not time.time()
                 or any other time source.

        Returns:
            bool: True if tick was executed, False if not ready yet.

        Example with handler:
            >>> ticker = Ticker(lg, lambda: sync_data(), secs=30)
            >>> while running:
            ...     msg = channel.recv(timeout=ticker.time_until_next_tick())
            ...     if msg:
            ...         handle_message(msg)
            ...     ticker.try_tick()  # Calls handler if ready

        Example without handler (timing oracle):
            >>> ticker = Ticker(lg, secs=30)
            >>> while running:
            ...     if ticker.try_tick():
            ...         do_scheduled_work()

        Example with shared timestamp:
            >>> now = time.monotonic()
            >>> timeout = ticker.time_until_next_tick(now=now)
            >>> if ticker.try_tick(now=now):
            ...     do_work()

        Raises:
            TickerAPIError: If run() or iterator was already used on this Ticker instance.
                            Cannot mix different API modes (blocking/non-blocking/iterator).

        Note:
            - Safe to call repeatedly - only ticks when ready
            - Drift-free: Uses single time.monotonic() call for accuracy
            - Updates timing state even without a handler
            - Calls ticker_before_first_tick on first execution
            - Logs exceptions from handler but continues

        Warning:
            If passing 'now', it MUST be from time.monotonic(). Using time.time()
            or other time sources will cause incorrect behavior due to clock
            adjustments (NTP, DST, manual changes).
        """
        self._check_api_mode_nonblocking()

        # Capture time ONCE for drift-free accuracy
        now_provided = now is not None
        if now is None:
            now = time.monotonic()

        if now_provided:
            self._validate_now_parameter(now, "try_tick")

        self._initialize_timing_state(now)

        # Check if it's time to tick (using captured time)
        if self.time_until_next_tick(now=now) > 0:
            return False

        # Execute tick and update timing
        self._execute_tick_handler()

        # For SPACED mode, ALWAYS capture time AFTER handler completes
        # to guarantee spacing from completion (regardless of user-provided timestamp)
        if self._mode == TickerMode.SPACED:
            now = time.monotonic()

        self._update_tick_timing(now)
        return True

    def _check_api_mode_nonblocking(self) -> None:
        """Verify no API mode conflicts before using non-blocking API."""
        if self._api_mode == "blocking":
            raise TickerAPIError(
                "Cannot call try_tick() after using run(). "
                "Choose one API mode per Ticker instance."
            )
        if self._api_mode == "iterator":
            raise TickerAPIError(
                "Cannot call try_tick() after using iterator. "
                "Choose one API mode per Ticker instance."
            )
        self._api_mode = "nonblocking"

    def _execute_tick_handler(self) -> None:
        """Execute tick handler with first-tick initialization."""
        # Handle first tick initialization
        if self._first:
            self._first = False
            if self._handler is not None:
                try:
                    self._handler.ticker_before_first_tick()
                except Exception as e:
                    self._lg.exception(
                        "Error in ticker_before_first_tick", extra={"exception": e}
                    )

        # Execute tick via handler if present
        if self._handler is not None:
            try:
                self._handler.ticker_tick()
            except Exception as e:
                self._lg.exception("Error in ticker_tick", extra={"exception": e})

    def _update_tick_timing(self, now: float) -> None:
        """Update timing state based on mode after tick execution."""
        # Note: In continuous mode (secs=None), timing state is not used
        if self._secs is not None:
            if self._mode in (TickerMode.FLEX, TickerMode.SPACED):
                # FLEX/SPACED: Next tick after full interval from this moment
                # For FLEX: 'now' is pre-handler time (interval from tick start)
                # For SPACED: 'now' is post-handler time (interval from completion)
                self._last_tick_time = now
            else:
                # STRICT: Advance scheduled time to maintain rate
                if self._last_tick_time is None:
                    # First tick - initialize reference time for subsequent scheduling
                    self._last_tick_time = now
                else:
                    # Advance by interval (may be behind actual time, allows catch-up)
                    self._last_tick_time += self._secs

                    # Warn if we're falling far behind (catch-up will cause back-to-back ticks)
                    lag = now - self._last_tick_time
                    if lag > 0:
                        intervals_behind = lag / self._secs
                        if intervals_behind > 5:
                            self._lg.warning(
                                "STRICT mode: falling behind schedule, catch-up will cause rapid ticking",
                                extra={
                                    "intervals_behind": intervals_behind,
                                    "lag_seconds": lag,
                                    "interval_seconds": self._secs,
                                },
                            )

    # Context manager and iterator support

    def __enter__(self) -> Self:
        """
        Install signal handlers for graceful shutdown.

        When used as a context manager, SIGTERM and SIGINT will stop the ticker.

        Returns:
            Self for use in with statement.
        """
        self._prev_sigterm = signal.signal(signal.SIGTERM, self._handle_iter_signal)
        self._prev_sigint = signal.signal(signal.SIGINT, self._handle_iter_signal)
        return self

    def __exit__(self, *args: object) -> None:
        """Restore previous signal handlers."""
        if self._prev_sigterm is not None:
            signal.signal(signal.SIGTERM, self._prev_sigterm)
            self._prev_sigterm = None
        if self._prev_sigint is not None:
            signal.signal(signal.SIGINT, self._prev_sigint)
            self._prev_sigint = None

    def __iter__(self) -> Iterator[int]:
        """
        Yield tick count on each interval until stopped.

        Can be used with or without context manager:

            # Without context manager (no signal handling)
            for tick in Ticker(lg, secs=5):
                do_work()

            # With context manager (signal handling enabled)
            with Ticker(lg, secs=5) as t:
                for tick in t:
                    do_work()

        Yields:
            int: Tick count starting from 0.

        Raises:
            TickerConfigError: If secs parameter was not provided
            TickerAPIError: If run() or try_tick() was already used (API mode conflict)
        """
        if self._secs is None:
            raise TickerConfigError("secs parameter required for iterator mode")

        # Check for API mode mixing
        if self._api_mode in ("blocking", "nonblocking"):
            raise TickerAPIError(
                "Cannot use iterator after run() or try_tick(). "
                "Choose one API mode per Ticker instance."
            )
        self._api_mode = "iterator"

        tick = 0

        # Check stop before initial tick
        if self._stop_event.is_set():
            return

        if self._initial:
            yield tick
            tick += 1

        while not self._stop_event.wait(timeout=self._secs):
            yield tick
            tick += 1

    def _handle_iter_signal(self, signum: int, frame: FrameType | None) -> None:
        """Handle signal by stopping iteration."""
        sig_name = signal.Signals(signum).name
        self._lg.debug(f"received {sig_name}, stopping ticker")
        self._stop_event.set()
