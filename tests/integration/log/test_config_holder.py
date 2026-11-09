# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for LogConfigHolder used from several threads at once."""

import threading
import time

from appinfra.log.config import LogConfig
from appinfra.log.config_holder import LogConfigHolder


class TestLogConfigHolder:
    """Unit tests for LogConfigHolder."""

    def test_thread_safety_read(self):
        """Test thread-safe reads."""
        config = LogConfig.from_params("info")
        holder = LogConfigHolder(config)
        results = []

        def reader():
            for _ in range(100):
                results.append(holder.level)
                time.sleep(0.001)

        threads = [threading.Thread(target=reader) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All reads should succeed
        assert len(results) == 500

    def test_thread_safety_write(self):
        """Test thread-safe writes."""
        config1 = LogConfig.from_params("info")
        holder = LogConfigHolder(config1)
        errors = []

        def writer(level):
            try:
                for _ in range(50):
                    config = LogConfig.from_params(level)
                    holder.update(config)
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=writer, args=("debug",)),
            threading.Thread(target=writer, args=("info",)),
            threading.Thread(target=writer, args=("warning",)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
