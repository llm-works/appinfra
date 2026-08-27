# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Performance tests for database connection pooling."""

import time

import pytest

# Performance tests in this module run against a real PG instance; skip the
# whole module with the sentinel reason if PG is unreachable.
pytestmark = pytest.mark.require_pg


@pytest.mark.performance
@pytest.mark.integration  # Requires actual DB
class TestConnectionPoolPerformance:
    def test_connection_checkout_time(self, pg_connection):
        """Measure average connection checkout time from pool."""
        pg = pg_connection

        # Warm up pool
        with pg.session():
            pass

        # Measure: 100 connection checkouts
        iterations = 100
        checkout_times = []

        for _ in range(iterations):
            start = time.monotonic()
            with pg.session():
                pass
            checkout_times.append(time.monotonic() - start)

        # Calculate stats
        avg_time_ms = (sum(checkout_times) / iterations) * 1000
        max_time_ms = max(checkout_times) * 1000

        # Assert: Average checkout < 1ms, max < 10ms
        assert avg_time_ms < 1.0, (
            f"Connection checkout too slow: {avg_time_ms:.2f}ms > 1ms"
        )
        assert max_time_ms < 10.0, (
            f"Max checkout time too high: {max_time_ms:.2f}ms > 10ms"
        )

        print(f"\nDB pool checkout: avg={avg_time_ms:.2f}ms, max={max_time_ms:.2f}ms")
