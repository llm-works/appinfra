# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for the AppBuilder config block (ConfigConfigurer)."""

from pathlib import Path

import pytest

from appinfra.app.builder import AppBuilder
from appinfra.app.builder.configurer.config import ConfigConfigurer
from appinfra.config import ConfigSpec
from appinfra.dot_dict import DotDict


@pytest.fixture
def base(tmp_path) -> Path:
    path = tmp_path / "pkg" / "etc" / "myapp.yaml"
    path.parent.mkdir(parents=True)
    path.write_text("")
    return path


# =============================================================================
# with_spec
# =============================================================================


@pytest.mark.unit
class TestWithSpec:
    """`config.with_spec` declares the ConfigSpec the App resolves at setup."""

    def test_stores_spec_and_chains(self, base):
        builder = AppBuilder("test")
        block = builder.config.with_spec("myorg", "myapp", path=base)

        assert isinstance(block, ConfigConfigurer)
        assert block.done() is builder
        assert builder._config_spec == ConfigSpec("myorg", "myapp", path=base)
        assert builder._config_spec.name == "myapp"

    def test_forwards_layout_parts(self, tmp_path):
        builder = AppBuilder("test")
        builder.config.with_spec(
            "ns", "bday", origin=tmp_path, etc_dir="", filename="happy.yaml"
        )
        assert builder._config_spec.base_config == (tmp_path / "happy.yaml").resolve()

    def test_does_not_auto_register_etc_dir_flag(self, base):
        """Flag exposure is orthogonal; the spec alone must not force the flag on."""
        builder = (
            AppBuilder("test").config.with_spec("myorg", "myapp", path=base).done()
        )
        assert builder._standard_args["etc_dir"] is False


# =============================================================================
# with_overrides / with_value
# =============================================================================


@pytest.mark.unit
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
        builder.config.with_overrides({"logging": {"level": "info", "micros": True}})
        builder.config.with_overrides(
            {"logging": {"level": "debug"}, "server": {"port": 1}}
        )
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
        builder.config.with_overrides({"logging": {"micros": True}})
        builder.config.with_value("logging.level", "debug")
        assert builder._config.logging.micros is True
        assert builder._config.logging.level == "debug"

    def test_returns_self(self):
        block = AppBuilder("test").config
        assert block.with_overrides({"a": 1}) is block
        assert block.with_value("b", 2) is block


# =============================================================================
# with_hot_reload
# =============================================================================


@pytest.mark.unit
@pytest.mark.usefixtures("clean_env")
class TestWithHotReload:
    """Hot reload needs a declared source and writes logging.hot_reload."""

    def test_requires_a_config_source(self):
        with pytest.raises(ValueError, match="requires a config source"):
            AppBuilder("test").config.with_hot_reload()

    def test_writes_hot_reload_under_logging(self, base):
        builder = AppBuilder("test").config.with_spec("ns", "myapp", path=base).done()
        builder.config.with_hot_reload()
        assert builder._config.logging.hot_reload.enabled is True
        assert builder._config.logging.hot_reload.debounce_ms == 500

    def test_disable_and_custom_debounce(self, base):
        builder = AppBuilder("test").config.with_spec("ns", "myapp", path=base).done()
        builder.config.with_hot_reload(False, debounce_ms=1000)
        assert builder._config.logging.hot_reload.enabled is False
        assert builder._config.logging.hot_reload.debounce_ms == 1000

    def test_keeps_existing_overrides(self, base):
        builder = (
            AppBuilder("test")
            .config.with_spec("ns", "myapp", path=base)
            .with_overrides({"logging": {"level": "debug"}})
            .with_hot_reload()
            .done()
        )
        assert builder._config.logging.level == "debug"
        assert builder._config.logging.hot_reload.enabled is True

    def test_returns_self(self, base):
        block = AppBuilder("test").config.with_spec("ns", "myapp", path=base)
        assert block.with_hot_reload() is block


# =============================================================================
# keyword form
# =============================================================================


@pytest.mark.unit
class TestCall:
    """`builder.config(...)` sets the same state and returns the AppBuilder."""

    def test_spec_from_keywords(self, base):
        builder = AppBuilder("test")
        result = builder.config(namespace="myorg", name="myapp", path=base)
        assert result is builder
        assert builder._config_spec == ConfigSpec("myorg", "myapp", path=base)

    def test_layout_keywords_forwarded(self, tmp_path):
        builder = AppBuilder("test").config(
            namespace="ns",
            name="bday",
            origin=tmp_path,
            etc_dir="",
            filename="happy.yaml",
        )
        assert builder._config_spec.base_config == (tmp_path / "happy.yaml").resolve()

    def test_namespace_and_name_required_together(self):
        with pytest.raises(ValueError, match="required together"):
            AppBuilder("test").config(name="myapp")
        with pytest.raises(ValueError, match="required together"):
            AppBuilder("test").config(namespace="ns", filename="x.yaml")

    def test_everything_in_one_call(self, base):
        builder = AppBuilder("test").config(
            namespace="ns",
            name="myapp",
            path=base,
            overrides={"logging": {"level": "debug"}},
            hot_reload=True,
            debounce_ms=250,
        )
        assert builder._config_spec.name == "myapp"
        assert builder._config.logging.level == "debug"
        assert builder._config.logging.hot_reload.debounce_ms == 250

    def test_debounce_requires_hot_reload(self, base):
        with pytest.raises(ValueError, match="debounce_ms requires hot_reload"):
            AppBuilder("test").config(
                namespace="ns", name="myapp", path=base, debounce_ms=1
            )

    def test_overrides_alone(self):
        builder = AppBuilder("test").config(overrides={"a": 1})
        assert builder._config.a == 1
        assert builder._config_spec is None
