# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Performance tests for regex timeout enforcement."""

import time

import pytest

from appinfra.regex_utils import safe_compile


@pytest.mark.performance
class TestRegexTimeoutPerformance:
    def test_timeout_enforcement_overhead(self):
        """Measure overhead of timeout enforcement on safe patterns."""
        # Simple safe pattern
        pattern_str = r"^[a-zA-Z0-9_-]+$"

        # Measure: Compile with timeout enforcement
        iterations = 100
        start = time.monotonic()
        for _ in range(iterations):
            pattern = safe_compile(pattern_str, timeout=1.0)
            pattern.match("test_string_123")
        elapsed = time.monotonic() - start

        # Assert: Overhead < 10ms per operation
        avg_time_ms = (elapsed / iterations) * 1000
        assert avg_time_ms < 10, (
            f"Timeout enforcement overhead too high: {avg_time_ms:.2f}ms > 10ms"
        )

        print(f"\nRegex timeout overhead: {avg_time_ms:.2f}ms per operation")

    def test_complexity_validation_is_fast(self):
        """Verify complexity validation catches malicious patterns instantly."""
        from appinfra.regex_utils import RegexComplexityError

        # Catastrophic backtracking pattern
        malicious_pattern = r"(a+)+"

        start = time.monotonic()
        with pytest.raises(RegexComplexityError):
            safe_compile(malicious_pattern, timeout=0.1)
        elapsed = time.monotonic() - start

        # Assert: Complexity check should be instant (< 10ms)
        assert elapsed < 0.01, (
            f"Complexity validation too slow: {elapsed * 1000:.2f}ms > 10ms"
        )

        print(f"\nComplexity validation time: {elapsed * 1000:.3f}ms")
