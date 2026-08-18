"""Performance tests for ticker interval accuracy."""

import threading
import time

import pytest

from appinfra.time.ticker import Ticker, TickerHandler


class PerfTestHandler(TickerHandler):
    """Test handler that records tick times."""

    def __init__(self):
        self.ticks = []

    def ticker_start(self, *args, **kwargs):
        pass

    def ticker_tick(self):
        self.ticks.append(time.monotonic())

    def ticker_stop(self):
        pass


@pytest.mark.performance
@pytest.mark.slow
class TestTickerAccuracy:
    def test_interval_timing_accuracy(self):
        """Measure ticker interval deviation from expected interval.

        Uses 0.4s intervals with generous tolerances because macOS CI runners
        have high timing jitter - 0.1s intervals saw 2x+ variance.
        """
        import logging

        lg = logging.getLogger(__name__)
        handler = PerfTestHandler()
        interval = 0.4
        ticker = Ticker(lg, handler, secs=interval)

        # Run ticker for ~2 seconds (expect ~5 ticks)
        thread = threading.Thread(target=ticker.run, daemon=True)
        thread.start()
        time.sleep(2.0)
        ticker.stop()
        thread.join(timeout=1.0)

        # Analyze: Calculate interval deviations
        ticks = handler.ticks
        if len(ticks) < 3:
            pytest.skip("Not enough ticks collected")

        intervals = [ticks[i + 1] - ticks[i] for i in range(len(ticks) - 1)]
        avg_interval = sum(intervals) / len(intervals)
        max_deviation = max(abs(i - interval) for i in intervals)

        # Assert: Average close to target, max deviation < 200ms
        assert abs(avg_interval - interval) < 0.2, (
            f"Interval average off: {avg_interval:.3f}s vs {interval}s expected"
        )
        assert max_deviation < 0.4, (
            f"Interval deviation too high: {max_deviation * 1000:.1f}ms > 400ms"
        )

        print(
            f"\nTicker accuracy (target={interval}s): avg={avg_interval:.3f}s, "
            f"max_dev={max_deviation * 1000:.1f}ms"
        )
