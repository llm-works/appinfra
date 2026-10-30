# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for AppBuilder.build() integrations across blocks.

Covers the version flag the cli block exposes from the version block,
and the top-level surface that remains after the facets.
"""

import pytest

from appinfra.app.builder.app import AppBuilder
from appinfra.version.actions import VersionWithTrackerAction

# =============================================================================
# -v/--version from .cli(version=True) and .version
# =============================================================================


@pytest.mark.unit
class TestVersionFlag:
    """The cli flag exposes the argument; the version block supplies its text."""

    def test_flag_off_adds_nothing(self):
        """A version without the flag stays metadata only."""
        builder = AppBuilder("test").version(semver="1.0.0")

        builder.build()

        assert builder._custom_args == []

    def test_flag_on_adds_v_and_version(self):
        """Both spellings share one tracker-aware action."""
        builder = AppBuilder("test").version(semver="1.2.3").cli(version=True)

        builder.build()

        ((flags, kwargs),) = builder._custom_args
        assert flags == ("-v", "--version")
        assert kwargs["action"] is VersionWithTrackerAction
        assert kwargs["app_name"] == "test"
        assert kwargs["app_version"] == "1.2.3"

    def test_flag_on_without_semver_raises(self):
        """A flag with nothing to print is a build-time error."""
        with pytest.raises(ValueError, match=r"requires \.version\.with_semver"):
            AppBuilder("test").cli(version=True).build()

    def test_tracker_and_build_info_are_passed(self):
        """The action gets what the version block collected."""
        builder = AppBuilder("test").version(semver="1.0.0", package="appinfra")
        builder.cli(version=True)

        builder.build()

        kwargs = builder._custom_args[0][1]
        assert kwargs["tracker"] is builder._version_tracker
        assert kwargs["tracker"] is not None

    def test_presentation_override_applies(self):
        """with_flag('version', ...) reaches the argparse kwargs."""
        builder = (
            AppBuilder("test")
            .version(semver="1.0.0")
            .cli.with_flags(version=True)
            .with_flag("version", help="show version")
            .done()
        )

        builder.build()

        assert builder._custom_args[0][1]["help"] == "show version"

    def test_build_twice_raises(self):
        """A builder builds once; its managers are handed to the App."""
        builder = AppBuilder("test").version(semver="1.0.0").cli(version=True)
        builder.build()

        with pytest.raises(ValueError, match="already called"):
            builder.build()


@pytest.mark.integration
class TestVersionFlagReachesParser:
    """The argument is real once the App creates its parser."""

    def test_both_option_strings_present(self):
        """-v and --version are one action on the parser."""
        app = AppBuilder("test").version(semver="1.0.0").cli(version=True).build()
        app.create_args()

        actions = [
            a for a in app.parser.parser._actions if "--version" in a.option_strings
        ]
        assert len(actions) == 1
        assert "-v" in actions[0].option_strings
        assert isinstance(actions[0], VersionWithTrackerAction)


# =============================================================================
# Top-level surface
# =============================================================================


@pytest.mark.unit
class TestTopLevelSurface:
    """Identity stays on the builder; everything else is a block."""

    def test_name_and_description_reach_app(self):
        """Constructor name and with_description set app metadata."""
        app = AppBuilder("myapp").with_description("does things").build()

        assert app.name == "myapp"
        assert app.description == "does things"

    def test_removed_flat_methods_are_gone(self):
        """The flat spellings no longer exist on the builder."""
        builder = AppBuilder("test")

        for name in (
            "with_name",
            "with_version",
            "with_config",
            "with_standard_args",
            "with_standard_arg",
            "without_standard_args",
            "with_main_tool",
            "advanced",
        ):
            assert not hasattr(builder, name), name

    def test_blocks_are_exposed(self):
        """One block per axis."""
        builder = AppBuilder("test")

        for name in (
            "config",
            "cli",
            "logging",
            "tools",
            "lifecycle",
            "version",
        ):
            assert getattr(builder, name).done() is builder, name
