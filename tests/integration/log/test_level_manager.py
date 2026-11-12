# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for LogLevelManager used from several threads at once."""

import threading

import pytest

from appinfra.log.level_manager import LogLevelManager


@pytest.fixture(autouse=True)
def reset_manager():
    """Reset LogLevelManager singleton before each test."""
    LogLevelManager.reset_instance()
    yield
    LogLevelManager.reset_instance()


@pytest.fixture
def manager():
    """Get fresh LogLevelManager instance."""
    return LogLevelManager.get_instance()


class TestThreadSafety:
    """Test thread-safe operations."""

    def test_concurrent_rule_additions(self, manager):
        """Test that concurrent rule additions are thread-safe."""

        def add_rules(source, start):
            for i in range(10):
                pattern = f"/test/{source}/{i}"
                manager.add_rule(pattern, "debug", source=source, priority=1)

        threads = []
        for i in range(5):
            t = threading.Thread(target=add_rules, args=(f"source{i}", i * 10))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # Should have 50 rules total (5 threads * 10 rules each)
        rules = manager.get_rules()
        assert len(rules) == 50

    def test_concurrent_reads_and_writes(self, manager):
        """Test concurrent reads and writes."""
        manager.add_rule("/infra/**", "info", source="yaml", priority=1)

        results = []

        def read_level():
            for _ in range(100):
                level = manager.get_effective_level("/infra/db/queries")
                results.append(level)

        def write_rule():
            for i in range(10):
                manager.add_rule(f"/test/{i}", "debug", source="api", priority=10)

        threads = [threading.Thread(target=read_level) for _ in range(3)]
        threads.extend(threading.Thread(target=write_rule) for _ in range(2))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All reads should have succeeded
        assert len(results) == 300  # 3 threads * 100 reads each
