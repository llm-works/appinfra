# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""runtime.Config: what a runtime is configured with, from code or from a config
section; runtime.Factory: runtimes by name from a config's runtime section."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from appinfra.dot_dict import DotDict
from appinfra.runtime import Config, Factory, ProcessConfig, Runtime


class TestConfig:
    def test_the_defaults(self) -> None:
        config = Config()
        assert config.process.method == "forkserver"
        assert config.process.grace == 2.0
        assert config.stop_timeout == 5.0

    def test_fork_is_refused_for_the_runtimes_threads(self) -> None:
        with pytest.raises(ValueError, match="threads"):
            ProcessConfig(method="fork")

    def test_an_unknown_method_is_refused(self) -> None:
        with pytest.raises(ValueError, match="'thread'"):
            ProcessConfig(method="thread")

    @pytest.mark.parametrize("bad", [0, -1.0, float("inf")])
    def test_seconds_must_be_positive_and_finite(self, bad: float) -> None:
        with pytest.raises(ValueError, match="grace"):
            ProcessConfig(grace=bad)
        with pytest.raises(ValueError, match="stop_timeout"):
            Config(stop_timeout=bad)


class TestFromConfig:
    def test_an_empty_section_is_the_defaults(self) -> None:
        assert Config.from_config({}) == Config()

    def test_durations_as_strings_or_seconds(self) -> None:
        config = Config.from_config(
            {"process": {"method": "spawn", "grace": "500ms"}, "stop_timeout": 12}
        )
        assert config == Config(
            process=ProcessConfig(method="spawn", grace=0.5), stop_timeout=12.0
        )

    def test_a_config_section_is_read_as_a_mapping(self) -> None:
        section = DotDict({"process": {"method": "spawn"}, "stop_timeout": "1m"})
        config = Config.from_config(section)
        assert (config.process.method, config.stop_timeout) == ("spawn", 60.0)

    @pytest.mark.parametrize(
        "section",
        [{"stop_timout": 1}, {"process": {"methd": "spawn"}}],
        ids=["top", "process"],
    )
    def test_an_unknown_key_is_refused(self, section: dict) -> None:
        with pytest.raises(ValueError, match="timout|methd"):
            Config.from_config(section)

    @pytest.mark.parametrize("bad", ["soon", True, None])
    def test_a_bad_duration_is_refused(self, bad: object) -> None:
        with pytest.raises(ValueError, match="stop_timeout"):
            Config.from_config({"stop_timeout": bad})


class TestFactory:
    CONFIG = DotDict(
        {
            "runtime": {
                "default": {"process": {"method": "forkserver"}},
                "compute": {"process": {"method": "spawn"}, "stop_timeout": "30s"},
            }
        }
    )

    def test_a_runtime_by_name_from_its_section(self) -> None:
        rt = Factory(MagicMock(), self.CONFIG).create("compute")
        assert isinstance(rt, Runtime)
        assert rt.config.process.method == "spawn"
        assert rt.config.stop_timeout == 30.0

    def test_the_name_defaults_to_default(self) -> None:
        factory = Factory(MagicMock(), self.CONFIG)
        assert factory.config() == Config()

    def test_an_unknown_name_is_refused_with_the_known_ones(self) -> None:
        with pytest.raises(KeyError, match="'compute', 'default'"):
            Factory(MagicMock(), self.CONFIG).config("comptue")

    def test_a_config_without_a_runtime_section_has_no_runtimes(self) -> None:
        with pytest.raises(KeyError, match="no runtime section"):
            Factory(MagicMock(), DotDict({})).create()
