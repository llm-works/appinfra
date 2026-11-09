# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for LogConfigHolder - thread-safe configuration wrapper."""

from appinfra.log.config import LogConfig
from appinfra.log.config_holder import LogConfigHolder


class TestLogConfigHolder:
    """Unit tests for LogConfigHolder."""

    def test_init_stores_config(self):
        """Test that holder stores initial config."""
        config = LogConfig.from_params("info")
        holder = LogConfigHolder(config)

        assert holder.config is config

    def test_property_delegates_to_config(self):
        """Test that properties delegate to underlying config."""
        config = LogConfig.from_params("debug", location=2, micros=True, colors=False)
        holder = LogConfigHolder(config)

        assert holder.level == config.level
        assert holder.location == config.location
        assert holder.micros == config.micros
        assert holder.colors == config.colors

    def test_location_color_property(self):
        """Test location_color property delegation."""
        config = LogConfig.from_params("info", location_color="\x1b[36")
        holder = LogConfigHolder(config)

        assert holder.location_color == "\x1b[36"

    def test_update_replaces_config(self):
        """Test that update replaces the config atomically."""
        config1 = LogConfig.from_params("info")
        config2 = LogConfig.from_params("debug")
        holder = LogConfigHolder(config1)

        holder.update(config2)

        assert holder.config is config2
        assert holder.level == config2.level

    def test_update_notifies_callbacks(self):
        """Test that update notifies registered callbacks."""
        config1 = LogConfig.from_params("info")
        config2 = LogConfig.from_params("debug")
        holder = LogConfigHolder(config1)

        callback_received = []

        def callback(new_config):
            callback_received.append(new_config)

        holder.add_update_callback(callback)
        holder.update(config2)

        assert len(callback_received) == 1
        assert callback_received[0] is config2

    def test_multiple_callbacks(self):
        """Test multiple callbacks are all notified."""
        config1 = LogConfig.from_params("info")
        config2 = LogConfig.from_params("debug")
        holder = LogConfigHolder(config1)

        results = []

        holder.add_update_callback(lambda c: results.append("a"))
        holder.add_update_callback(lambda c: results.append("b"))
        holder.update(config2)

        assert results == ["a", "b"]

    def test_callback_error_does_not_break_update(self):
        """Test that callback errors don't prevent other callbacks."""
        config1 = LogConfig.from_params("info")
        config2 = LogConfig.from_params("debug")
        holder = LogConfigHolder(config1)

        results = []

        holder.add_update_callback(lambda c: results.append("first"))
        holder.add_update_callback(lambda c: 1 / 0)  # Raises ZeroDivisionError
        holder.add_update_callback(lambda c: results.append("third"))

        # Should not raise
        holder.update(config2)

        assert results == ["first", "third"]

    def test_remove_callback(self):
        """Test callback removal."""
        config1 = LogConfig.from_params("info")
        config2 = LogConfig.from_params("debug")
        holder = LogConfigHolder(config1)

        results = []

        def callback(c):
            results.append("called")

        holder.add_update_callback(callback)
        holder.remove_update_callback(callback)
        holder.update(config2)

        assert results == []

    def test_remove_nonexistent_callback_does_not_error(self):
        """Test removing non-existent callback doesn't raise."""
        holder = LogConfigHolder(LogConfig.from_params("info"))

        def callback(c):
            pass

        # Should not raise
        holder.remove_update_callback(callback)
