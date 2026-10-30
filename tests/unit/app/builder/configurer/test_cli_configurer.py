# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for app/builder/configurer/cli.py.

The cli block controls which standard CLI flags the app exposes, the
argparse presentation of each flag, and custom arguments.
"""

import pytest

from appinfra.app.builder.app import AppBuilder
from appinfra.app.builder.configurer.cli import CliFlags
from appinfra.app.core.app import DEFAULT_STANDARD_ARGS

# =============================================================================
# with_flags
# =============================================================================


class TestWithFlags:
    """Flags merge onto the current set; names and values are validated."""

    def test_specific_flags_enable_individual_args(self):
        """Named flags turn on; the rest keep their default."""
        builder = AppBuilder("test")

        builder.cli.with_flags(log_location=True, log_micros=True)

        assert builder._standard_args["log_location"] is True
        assert builder._standard_args["log_micros"] is True
        assert builder._standard_args["etc_dir"] is False
        assert builder._standard_args["log_level"] is False
        assert builder._standard_args["quiet"] is False

    def test_flags_merge_across_calls(self):
        """A later call adds to, and does not replace, an earlier one."""
        builder = AppBuilder("test")

        builder.cli.with_flags(etc_dir=True).with_flags(log_level=True)

        assert builder._standard_args["etc_dir"] is True
        assert builder._standard_args["log_level"] is True

    def test_can_disable_and_re_enable(self):
        """Explicit False and True both apply, last one wins."""
        builder = AppBuilder("test")

        builder.cli.with_flags(etc_dir=True).with_flags(etc_dir=False).done()
        assert builder._standard_args["etc_dir"] is False

        builder.cli.with_flags(etc_dir=True).done()
        assert builder._standard_args["etc_dir"] is True

    def test_no_flags_raises(self):
        """An empty call is a mistake, not enable-all."""
        with pytest.raises(ValueError, match="at least one flag"):
            AppBuilder("test").cli.with_flags()

    def test_invalid_flag_name_raises(self):
        """Unknown names are rejected with the valid set listed."""
        with pytest.raises(TypeError, match="Unknown CLI flag: 'invalid_arg'"):
            AppBuilder("test").cli.with_flags(invalid_arg=False)

    def test_non_boolean_value_raises(self):
        """Values must be booleans."""
        with pytest.raises(TypeError, match="Value for 'etc_dir' must be a boolean"):
            AppBuilder("test").cli.with_flags(etc_dir="not_a_bool")

    def test_returns_block_for_chaining(self):
        """with_flags returns the block, not the AppBuilder."""
        block = AppBuilder("test").cli

        assert block.with_flags(log_location=False) is block

    def test_log_alias_enables_all_log_flags(self):
        """log=True expands to every logging-related flag and nothing else."""
        builder = AppBuilder("test")

        builder.cli.with_flags(log=True)

        for name in (
            "log_level",
            "log_location",
            "log_micros",
            "log_topic",
            "log_colors",
            "log_json",
            "quiet",
        ):
            assert builder._standard_args[name] is True, name
        assert builder._standard_args["etc_dir"] is False
        assert builder._standard_args["config_file"] is False
        assert builder._standard_args["version"] is False

    def test_log_alias_with_override(self):
        """An explicit key wins over the alias."""
        builder = AppBuilder("test")

        builder.cli.with_flags(log=True, quiet=False)

        assert builder._standard_args["log_level"] is True
        assert builder._standard_args["quiet"] is False

    def test_log_alias_rejects_non_boolean(self):
        """The alias value is validated like any other."""
        with pytest.raises(TypeError, match="Value for 'log' must be a boolean"):
            AppBuilder("test").cli.with_flags(log=1)

    def test_version_is_a_flag(self):
        """version is a standard flag key like the others."""
        builder = AppBuilder("test")

        builder.cli.with_flags(version=True)

        assert builder._standard_args["version"] is True


# =============================================================================
# without_flags
# =============================================================================


class TestWithoutFlags:
    """without_flags clears every flag, help included."""

    def test_disables_all_flags(self):
        """Every key goes False."""
        builder = AppBuilder("test")
        builder.cli.with_flags(log=True, etc_dir=True).done()

        builder.cli.without_flags().done()

        assert all(not v for v in builder._standard_args.values())

    def test_returns_block_for_chaining(self):
        """without_flags returns the block."""
        block = AppBuilder("test").cli

        assert block.without_flags() is block

    def test_then_with_flags_enables_only_named(self):
        """The locked-down idiom: clear, then name what stays."""
        builder = AppBuilder("test")

        builder.cli.without_flags().with_flags(etc_dir=True)

        assert builder._standard_args["etc_dir"] is True
        assert builder._standard_args["help"] is False
        assert builder._standard_args["log_level"] is False


# =============================================================================
# with_all_flags
# =============================================================================


class TestWithAllFlags:
    """with_all_flags enables every standard flag, help included."""

    def test_enables_every_flag_except_version_without_config(self):
        """Every key except version goes True when no version configured."""
        builder = AppBuilder("test")

        builder.cli.with_all_flags().done()

        for name in DEFAULT_STANDARD_ARGS:
            if name == "version":
                assert builder._standard_args[name] is False, "version stays off"
            else:
                assert builder._standard_args[name] is True, name

    def test_enables_version_when_configured(self):
        """version flag enabled when version block is configured first."""
        builder = AppBuilder("test")

        builder.version.with_semver("1.0.0").done()
        builder.cli.with_all_flags().done()

        assert builder._standard_args["version"] is True

    def test_after_without_flags_restores_full_set_except_version(self):
        """without_flags then with_all_flags reinstates flags (version needs config)."""
        builder = AppBuilder("test")

        builder.cli.without_flags().with_all_flags().done()

        for name in DEFAULT_STANDARD_ARGS:
            if name == "version":
                assert builder._standard_args[name] is False
            else:
                assert builder._standard_args[name] is True

    def test_returns_block_for_chaining(self):
        """with_all_flags returns the block."""
        block = AppBuilder("test").cli

        assert block.with_all_flags() is block


# =============================================================================
# without_flag
# =============================================================================


class TestWithoutFlag:
    """without_flag disables one standard flag."""

    def test_disables_named_flag(self):
        """The named flag goes False; others keep their value."""
        builder = AppBuilder("test")
        builder.cli.with_all_flags().done()

        builder.cli.without_flag("log_json").done()

        assert builder._standard_args["log_json"] is False
        assert builder._standard_args["log_level"] is True
        assert builder._standard_args["etc_dir"] is True

    def test_accepts_help(self):
        """help is a standard flag key; without_flag can turn it off."""
        builder = AppBuilder("test")

        builder.cli.without_flag("help").done()

        assert builder._standard_args["help"] is False

    def test_log_alias_rejected(self):
        """log is a bulk alias; the message points at with_flags(log=False)."""
        with pytest.raises(ValueError, match="'log' is an alias"):
            AppBuilder("test").cli.without_flag("log")

    def test_unknown_name_raises(self):
        """Unknown names are rejected with the valid set listed."""
        with pytest.raises(TypeError, match="Unknown CLI flag: 'invalid_arg'"):
            AppBuilder("test").cli.without_flag("invalid_arg")

    def test_returns_block_for_chaining(self):
        """without_flag returns the block."""
        block = AppBuilder("test").cli

        assert block.without_flag("etc_dir") is block


# =============================================================================
# Keyword form
# =============================================================================


class TestKeywordForm:
    """Calling the block sets flags and returns the AppBuilder."""

    def test_call_sets_flags_and_returns_builder(self):
        """The keyword form is with_flags plus done."""
        builder = AppBuilder("test")

        result = builder.cli(etc_dir=True, log=True)

        assert result is builder
        assert builder._standard_args["etc_dir"] is True
        assert builder._standard_args["log_level"] is True

    def test_call_without_flags_raises(self):
        """An empty call is rejected like with_flags()."""
        with pytest.raises(ValueError, match="at least one flag"):
            AppBuilder("test").cli()

    def test_failed_call_leaves_no_block_open(self):
        """A rejected keyword form closes its block, so the builder stays usable."""
        builder = AppBuilder("test")
        with pytest.raises(ValueError, match="at least one flag"):
            builder.cli()

        assert builder.tools.done() is builder

    def test_call_unknown_keyword_raises(self):
        """The keyword form and with_flags fail the same way on an unknown name."""
        with pytest.raises(TypeError, match="unknown cli field\\(s\\): foo"):
            AppBuilder("test").cli(foo=True)

    def test_fields_match_default_standard_args(self):
        """CliFlags keys equal DEFAULT_STANDARD_ARGS plus the log alias."""
        assert set(CliFlags.__annotations__) == set(DEFAULT_STANDARD_ARGS) | {"log"}


# =============================================================================
# with_flag (presentation)
# =============================================================================


class TestWithFlag:
    """with_flag stores argparse presentation for one standard flag."""

    def test_stores_presentation_under_flag_name(self):
        """Keys land under the flag's name."""
        builder = (
            AppBuilder("test")
            .cli.with_flag("etc_dir", help="config dir", metavar="PATH")
            .done()
        )

        assert builder._standard_arg_overrides == {
            "etc_dir": {"help": "config dir", "metavar": "PATH"}
        }

    def test_multiple_calls_merge_keys(self):
        """Later calls add keys for the same flag."""
        builder = AppBuilder("test")

        builder.cli.with_flag("etc_dir", metavar="PATH").with_flag(
            "etc_dir", help="new help"
        )

        assert builder._standard_arg_overrides["etc_dir"] == {
            "metavar": "PATH",
            "help": "new help",
        }

    def test_later_call_overwrites_same_key(self):
        """The last value for a key wins."""
        builder = AppBuilder("test")

        builder.cli.with_flag("etc_dir", help="a").with_flag("etc_dir", help="b")

        assert builder._standard_arg_overrides["etc_dir"]["help"] == "b"

    def test_invalid_name_rejected(self):
        """Unknown flag names are rejected."""
        with pytest.raises(TypeError, match="Unknown CLI flag"):
            AppBuilder("test").cli.with_flag("not_a_real_arg", help="x")

    def test_log_alias_rejected(self):
        """The alias has no single argparse action to present."""
        with pytest.raises(ValueError, match="'log' is an alias"):
            AppBuilder("test").cli.with_flag("log", help="x")

    def test_help_rejected(self):
        """help is argparse's add_help, not a standard-arg action."""
        with pytest.raises(ValueError, match="'help' has no presentation"):
            AppBuilder("test").cli.with_flag("help", help="custom")

    def test_default_rejected(self):
        """A default is a value; values come from the subsystem block or file."""
        with pytest.raises(ValueError, match="does not accept 'default'"):
            AppBuilder("test").cli.with_flag("log_level", default="warning")

    def test_dest_rejected(self):
        """The framework reads parsed args by a fixed attribute name."""
        with pytest.raises(ValueError, match="does not accept 'dest'"):
            AppBuilder("test").cli.with_flag("etc_dir", dest="my_etc_dir")

    def test_returns_block_for_chaining(self):
        """with_flag returns the block."""
        block = AppBuilder("test").cli

        assert block.with_flag("etc_dir", help="x") is block


# =============================================================================
# with_argument
# =============================================================================


class TestWithArgument:
    """with_argument stores add_argument arguments for build time."""

    def test_appends_custom_argument(self):
        """Positional and keyword arguments are kept as given."""
        builder = (
            AppBuilder("test").cli.with_argument("--flag", action="store_true").done()
        )

        assert builder._custom_args == [(("--flag",), {"action": "store_true"})]

    def test_returns_block_for_chaining(self):
        """with_argument returns the block."""
        block = AppBuilder("test").cli

        assert block.with_argument("--x") is block


# =============================================================================
# Integration with the App parser
# =============================================================================


def _dests(app) -> set[str]:
    return {action.dest for action in app.parser.parser._actions}


def _action_for(app, dest: str):
    return next(a for a in app.parser.parser._actions if a.dest == dest)


class TestFlagsIntegration:
    """Flags declared on the block decide what the App's parser gets."""

    def test_minimal_args_by_default(self):
        """Only help is present without any flag declaration."""
        app = AppBuilder("test").build()
        app.create_args()

        dests = _dests(app)
        assert "help" in dests
        for name in ("etc_dir", "log_level", "log_location", "quiet", "config"):
            assert name not in dests, name

    def test_enabled_flags_added_to_parser(self):
        """Enabled flags appear; the rest do not."""
        app = AppBuilder("test").cli(etc_dir=True, log_level=True, quiet=True).build()
        app.create_args()

        dests = _dests(app)
        assert {"etc_dir", "log_level", "quiet"} <= dests
        assert "log_location" not in dests
        assert "log_micros" not in dests

    def test_locked_down_then_specific(self):
        """without_flags then with_flags yields exactly the named flags."""
        app = (
            AppBuilder("test")
            .cli.without_flags()
            .with_flags(etc_dir=True, log_level=True)
            .done()
            .build()
        )
        app.create_args()

        dests = _dests(app)
        assert {"etc_dir", "log_level"} <= dests
        assert "quiet" not in dests
        assert "log_location" not in dests

    def test_configuration_passed_from_builder_to_app(self):
        """The App gets a copy of the builder's flag table."""
        builder = AppBuilder("test").cli(log_location=True, etc_dir=True)

        app = builder.build()

        assert app._standard_args["log_location"] is True
        assert app._standard_args["etc_dir"] is True
        assert app._standard_args["log_micros"] is False

    def test_custom_argument_reaches_parser(self):
        """with_argument adds a real argparse action."""
        app = AppBuilder("test").cli.with_argument("--flag", action="store_true").done()
        app = app.build()
        app.create_args()

        assert "flag" in _dests(app)


class TestPresentationIntegration:
    """with_flag overrides reach the parser's actions."""

    def test_help_override_reaches_parser(self):
        """help text is replaced."""
        app = (
            AppBuilder("test")
            .cli.with_flags(etc_dir=True)
            .with_flag("etc_dir", help="custom etc help")
            .done()
            .build()
        )
        app.create_args()

        assert _action_for(app, "etc_dir").help == "custom etc help"

    def test_with_flag_enables_the_flag(self):
        """with_flag is the singular of with_flags: it turns the flag on."""
        app = (
            AppBuilder("test")
            .cli.without_flags()
            .with_flag("etc_dir", help="config dir")
            .done()
            .build()
        )
        app.create_args()

        assert _action_for(app, "etc_dir").help == "config dir"

    def test_override_only_changes_specified_keys(self):
        """Framework values survive for keys not in the override."""
        app = (
            AppBuilder("test")
            .cli.with_flags(etc_dir=True)
            .with_flag("etc_dir", metavar="PATH")
            .done()
            .build()
        )
        app.create_args()

        action = _action_for(app, "etc_dir")
        assert action.metavar == "PATH"
        assert action.type is str
        assert action.default is None

    def test_config_file_override(self):
        """The config flag's dest is config; the override still finds it."""
        app = (
            AppBuilder("test")
            .cli.with_flags(config_file=True)
            .with_flag("config_file", help="prod config", metavar="CFG")
            .done()
            .build()
        )
        app.create_args()

        action = _action_for(app, "config")
        assert action.help == "prod config"
        assert action.metavar == "CFG"

    def test_log_topic_override(self):
        """log_topic's dest is log_topics; the override applies by flag name."""
        app = (
            AppBuilder("test")
            .cli.with_flags(log_topic=True)
            .with_flag("log_topic", help="custom topic help")
            .done()
            .build()
        )
        app.create_args()

        assert _action_for(app, "log_topics").help == "custom topic help"

    def test_quiet_override(self):
        """quiet is store_true; overriding help leaves the action intact."""
        app = (
            AppBuilder("test")
            .cli.with_flags(quiet=True)
            .with_flag("quiet", help="silence the build")
            .done()
            .build()
        )
        app.create_args()

        action = _action_for(app, "quiet")
        assert action.help == "silence the build"
        assert action.const is True
