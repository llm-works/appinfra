# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Performance tests for logging throughput."""

import io
import logging
import time

import pytest

from appinfra.log import LoggingBuilder
from appinfra.time import delta_str


@pytest.mark.performance
@pytest.mark.slow
class TestLoggingThroughput:
    def test_logging_overhead_with_varied_messages(self):
        """Measure pure logging overhead without I/O, with varied messages."""
        # Setup: Logger with NullHandler (no I/O overhead)
        logger = LoggingBuilder("perf_test").with_level("info").build()
        logger.addHandler(logging.NullHandler())

        # Varied messages (realistic scenario)
        messages = [
            "User login successful",
            "Database query executed",
            "Cache hit for key",
            "Request processed",
            "Task completed",
        ]

        # Measure: 1000 log messages with varied content
        iterations = 1000
        start = time.monotonic()
        for i in range(iterations):
            msg_idx = i % len(messages)
            # Varied extra fields per iteration
            extra_fields = {
                "iteration": i,
                "user_id": i % 100,
                "duration_ms": (i % 500) + 10,
                "status": "success" if i % 3 == 0 else "pending",
                "endpoint": f"/api/v1/resource/{i % 10}",
            }
            logger.info(messages[msg_idx], extra=extra_fields)
        elapsed = time.monotonic() - start

        # Assert: Should log at least 25,000 messages/sec (no I/O overhead)
        # Lowered from 50,000 for CI environments with constrained resources
        throughput = iterations / elapsed
        time_per_msg = elapsed / iterations
        assert throughput > 25_000, (
            f"Logging overhead too high: {throughput:,.0f} msg/sec < 25,000"
        )

        print(
            f"\nLogging overhead (no I/O): {throughput:,.0f} messages/sec "
            f"({delta_str(time_per_msg)} per message)"
        )

    def test_structured_logging_to_string(self):
        """Measure structured logging rendering to string (not console I/O)."""
        # Setup: Logger with StringIO handler (measures formatting, not I/O)
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(
            logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        )

        logger = LoggingBuilder("perf_test").with_level("info").build()
        logger.addHandler(handler)

        # Varied messages with different extra fields
        iterations = 1000
        start = time.monotonic()
        for i in range(iterations):
            logger.info(
                f"Processing request {i} for user {i % 100}",
                extra={
                    "request_id": f"req-{i}",
                    "user_id": i % 100,
                    "endpoint": f"/api/resource/{i % 10}",
                    "duration_ms": (i % 500) + 10,
                },
            )
        elapsed = time.monotonic() - start

        # Assert: Should format at least 20,000 messages/sec
        throughput = iterations / elapsed
        time_per_msg = elapsed / iterations
        assert throughput > 20_000, (
            f"Formatting throughput too low: {throughput:,.0f} msg/sec < 20,000"
        )

        print(
            f"\nStructured logging (to string): {throughput:,.0f} messages/sec "
            f"({delta_str(time_per_msg)} per message)"
        )

    def test_json_logging_to_string(self):
        """Measure JSON logging throughput (production pattern)."""
        from appinfra.log.builder.json import JSONFormatter

        # Setup: Logger with JSON formatter to StringIO (no I/O, just serialization)
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(JSONFormatter(pretty_print=False))

        logger = LoggingBuilder("perf_test").with_level("info").build()
        logger.addHandler(handler)

        # Varied messages with realistic complex nested data
        iterations = 1000
        start = time.monotonic()
        for i in range(iterations):
            logger.info(
                f"API request processed for user {i % 100}",
                extra={
                    "request_id": f"req-{i}",
                    "user_id": i % 100,
                    "method": "POST" if i % 3 == 0 else "GET",
                    "endpoint": f"/api/v1/users/{i % 50}/orders",
                    "duration_ms": (i % 500) + 10,
                    "status_code": 200 if i % 10 != 0 else 404,
                    "metadata": {
                        "ip": f"192.168.1.{i % 255}",
                        "user_agent": "Mozilla/5.0",
                        "tags": ["api", "orders", f"tenant-{i % 5}"],
                        "session_id": f"sess-{i % 20}",
                    },
                },
            )
        elapsed = time.monotonic() - start

        # Assert: Should format at least 10,000 JSON messages/sec
        throughput = iterations / elapsed
        time_per_msg = elapsed / iterations
        assert throughput > 10_000, (
            f"JSON logging too slow: {throughput:,.0f} msg/sec < 10,000"
        )

        print(
            f"\nJSON logging (to string): {throughput:,.0f} messages/sec "
            f"({delta_str(time_per_msg)} per message)"
        )
