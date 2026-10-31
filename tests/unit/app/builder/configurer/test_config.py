# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for the AppBuilder config block's programmatic layer (ConfigConfigurer)."""

from appinfra.app.builder import AppBuilder
from appinfra.dot_dict import DotDict

# =============================================================================
# with_overrides / with_value
# =============================================================================


class TestOverrides:
    """The programmatic layer accepts any mapping and deep-merges."""

    def test_plain_dict_becomes_dotdict(self):
        builder = AppBuilder("test")
        builder.config.with_overrides({"logging": {"level": "debug"}})
        assert isinstance(builder._config, DotDict)
        assert builder._config.logging.level == "debug"

    def test_dotdict_kept_as_given(self):
        builder = AppBuilder("test")
        config = DotDict(a=1)
        builder.config.with_overrides(config)
        assert builder._config is config

    def test_repeated_calls_deep_merge(self):
        builder = AppBuilder("test")
        builder.config.with_overrides(
            {"logging": {"level": "info", "micros": True}}
        ).done()
        builder.config.with_overrides(
            {"logging": {"level": "debug"}, "server": {"port": 1}}
        ).done()
        assert builder._config.logging.level == "debug"
        assert builder._config.logging.micros is True
        assert builder._config.server.port == 1

    def test_with_value_sets_a_dotted_path(self):
        builder = AppBuilder("test")
        builder.config.with_value("logging.level", "debug").with_value(
            "server.port", 8080
        )
        assert builder._config.logging.level == "debug"
        assert builder._config.server.port == 8080

    def test_with_value_merges_into_existing_layer(self):
        builder = AppBuilder("test")
        builder.config.with_overrides({"logging": {"micros": True}}).done()
        builder.config.with_value("logging.level", "debug").done()
        assert builder._config.logging.micros is True
        assert builder._config.logging.level == "debug"

    def test_returns_self(self):
        block = AppBuilder("test").config
        assert block.with_overrides({"a": 1}) is block
        assert block.with_value("b", 2) is block
