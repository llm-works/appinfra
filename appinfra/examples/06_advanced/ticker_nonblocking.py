#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Non-blocking Ticker API example for mixed event sources.

Demonstrates using try_tick() and time_until_next_tick() for event loops
that need to multiplex between message handling and scheduled tasks.
"""

import pathlib
import queue
import sys
import time

# Add the project root to the path
project_root = str(pathlib.Path(__file__).resolve().parents[3])
if project_root not in sys.path:
    sys.path.append(project_root)

from appinfra.log import LogConfig, LoggerFactory
from appinfra.time import Ticker, TickerMode


def example_with_handler():
    """Example: Non-blocking ticker with handler."""
    print("\n=== Example 1: With Handler ===")

    config = LogConfig.from_params(level="info", location=1)
    lg = LoggerFactory.create_root(config)

    # Ticker calls handler when ready
    ticker = Ticker(lg, lambda: lg.info("scheduled task executed"), secs=2.0)

    # Simulate message queue
    messages = queue.Queue()
    messages.put("msg1")
    messages.put("msg2")

    print("Running event loop for 5 seconds...")
    start = time.monotonic()

    while time.monotonic() - start < 5.0:
        # Calculate timeout for next tick
        timeout = ticker.time_until_next_tick()

        try:
            # Wait for message OR timeout
            msg = messages.get(timeout=timeout)
            lg.info(f"received message: {msg}")
        except queue.Empty:
            pass  # Timeout is expected

        # Always try to tick (whether we got a message or not)
        ticker.try_tick()


def example_without_handler():
    """Example: Timing oracle mode without handler."""
    print("\n=== Example 2: Without Handler (Timing Oracle) ===")

    config = LogConfig.from_params(level="info", location=1)
    lg = LoggerFactory.create_root(config)

    # No handler - we control what happens on tick
    ticker = Ticker(lg, secs=1.5, mode=TickerMode.FLEX)

    print("Running for 5 seconds...")
    start = time.monotonic()

    while time.monotonic() - start < 5.0:
        # Check if it's time to tick
        if ticker.try_tick():
            lg.info("time to run scheduled work!")

        # Simulate other work
        time.sleep(0.1)


def example_strict_mode():
    """Example: STRICT mode catches up if tasks run slow."""
    print("\n=== Example 3: STRICT Mode (Catch-up) ===")

    config = LogConfig.from_params(level="info", location=1)
    lg = LoggerFactory.create_root(config)

    ticker = Ticker(lg, secs=0.5, mode=TickerMode.STRICT)

    print("Ticking every 0.5s, with one slow task (2s)...")
    tick_count = 0
    start = time.monotonic()

    while time.monotonic() - start < 4.0:
        if ticker.try_tick():
            tick_count += 1
            elapsed = time.monotonic() - start
            lg.info(f"tick {tick_count} at t={elapsed:.2f}s")

            # Simulate slow task on tick 2
            if tick_count == 2:
                lg.warning("task running slow (2 seconds)...")
                time.sleep(2.0)
            else:
                time.sleep(0.05)  # Fast task
        else:
            time.sleep(0.01)  # Check frequently

    print(f"→ STRICT mode: {tick_count} ticks in 4 seconds (caught up after slow task)")


def example_flex_mode():
    """Example: FLEX mode never catches up."""
    print("\n=== Example 4: FLEX Mode (No Catch-up) ===")

    config = LogConfig.from_params(level="info", location=1)
    lg = LoggerFactory.create_root(config)

    ticker = Ticker(lg, secs=0.5, mode=TickerMode.FLEX)

    print("Ticking every 0.5s, with one slow task (2s)...")
    tick_count = 0
    start = time.monotonic()

    while time.monotonic() - start < 4.0:
        if ticker.try_tick():
            tick_count += 1
            elapsed = time.monotonic() - start
            lg.info(f"tick {tick_count} at t={elapsed:.2f}s")

            # Simulate slow task on tick 2
            if tick_count == 2:
                lg.warning("task running slow (2 seconds)...")
                time.sleep(2.0)
            else:
                time.sleep(0.05)  # Fast task
        else:
            time.sleep(0.01)  # Check frequently

    print(
        f"→ FLEX mode: {tick_count} ticks in 4 seconds (waited after slow task, no catch-up)"
    )


def example_shared_timestamp():
    """Example: Sharing timestamp for drift-free operation."""
    print("\n=== Example 5: Shared Timestamp (Drift-Free) ===")

    config = LogConfig.from_params(level="info", location=1)
    lg = LoggerFactory.create_root(config)

    ticker = Ticker(lg, secs=1.0)

    print("Running with shared timestamps...")

    for i in range(3):
        # Capture time once
        now = time.monotonic()

        # Use same timestamp for both calls (drift-free)
        timeout = ticker.time_until_next_tick(now=now)
        lg.info(f"iteration {i}, timeout={timeout:.3f}s")

        if ticker.try_tick(now=now):
            lg.info("tick executed")

        time.sleep(1.1)


def example_spaced_mode():
    """Example: SPACED mode guarantees spacing from completion."""
    print("\n=== Example 6: SPACED Mode (Guaranteed Spacing) ===")

    config = LogConfig.from_params(level="info", location=1)
    lg = LoggerFactory.create_root(config)

    ticker = Ticker(lg, secs=0.5, mode=TickerMode.SPACED)

    print("Ticking every 0.5s FROM COMPLETION, with one slow task (1.5s)...")
    tick_count = 0
    start = time.monotonic()

    while time.monotonic() - start < 4.0:
        if ticker.try_tick():
            tick_count += 1
            elapsed = time.monotonic() - start
            lg.info(f"tick {tick_count} at t={elapsed:.2f}s")

            # Simulate slow task on tick 2
            if tick_count == 2:
                lg.warning("task running slow (1.5 seconds)...")
                time.sleep(1.5)
            else:
                time.sleep(0.05)  # Fast task
        else:
            time.sleep(0.01)  # Check frequently

    print(
        f"→ SPACED mode: {tick_count} ticks in 4 seconds (waited 0.5s after each completion)"
    )


def main():
    """Run all examples."""
    example_with_handler()
    example_without_handler()
    example_strict_mode()
    example_flex_mode()
    example_shared_timestamp()
    example_spaced_mode()
    return 0


if __name__ == "__main__":
    sys.exit(main())
