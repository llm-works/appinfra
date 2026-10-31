# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for app/builder/app.py that build apps from config files on disk.
"""

from unittest.mock import patch

from appinfra.app.builder.app import AppBuilder
from appinfra.app.tools.base import Tool, ToolConfig

# =============================================================================
# Test AppBuilder.config block reaches the App
# =============================================================================


class TestAppBuilderConfigBlock:
    """The config block's spec is handed to the built App."""

    def test_built_app_carries_the_spec(self, tmp_path):
        base = tmp_path / "pkg" / "etc" / "myapp.yaml"
        base.parent.mkdir(parents=True)
        base.write_text("")

        app = (
            AppBuilder("test")
            .config.with_spec("myorg", "myapp", path=base)
            .done()
            .build()
        )

        assert app.config_spec is not None
        assert app.config_spec.name == "myapp"
        assert app.config_spec.base_config == base.resolve()
        assert app.config_path is None  # resolved at setup, not at build


# =============================================================================
# Test AppBuilder Build
# =============================================================================


class TestBuildIsDeclarationOnly:
    """Declaring every block and building runs nothing from the run phase.

    The app logger is created by the lifecycle in ``App.setup()``; until then
    no component may create a logger or a long-running object. A block that
    does so would receive a logger the app's config and flags never reach.
    """

    def test_no_logger_and_no_runtime_object_before_setup(self, tmp_path):
        base = tmp_path / "etc" / "probe.yaml"
        base.parent.mkdir()
        base.write_text("logging:\n  level: info\n")

        class Hello(Tool):
            def __init__(self):
                super().__init__(config=ToolConfig(name="hello", help_text="hi"))

            def run(self, **kwargs):
                return 0

        with (
            patch("appinfra.log.logger.Logger.__init__", side_effect=AssertionError),
            patch(
                "appinfra.log.factory.LoggerFactory.create_root",
                side_effect=AssertionError,
            ),
            patch(
                "appinfra.log.factory.LoggerFactory.derive", side_effect=AssertionError
            ),
            patch("threading.Thread.start", side_effect=AssertionError),
        ):
            app = (
                AppBuilder("probe")
                .config.with_spec("probe-org", "probe", path=base)
                .with_hot_reload(debounce_ms=100)
                .done()
                .cli(log_level=True, quiet=True, etc_dir=True, config_file=True)
                .logging.with_level("info")
                .with_topic_level("/db", "debug")
                .done()
                .tools.with_tool(Hello())
                .with_main("hello")
                .done()
                .lifecycle.with_hook("startup", lambda ctx: None)
                .done()
                .version.with_semver("0.0.1")
                .with_package("pytest")
                .done()
                .build()
            )

        assert app.lifecycle.logger is None
