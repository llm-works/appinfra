"""
Tests for standard CLI argument control in AppBuilder.

Tests the with_standard_args() and without_standard_args() methods that give users
fine-grained control over which standard CLI arguments are automatically added.
"""

import pytest

from appinfra.app.builder.app import AppBuilder


@pytest.mark.unit
class TestWithStandardArgsMethod:
    """Test AppBuilder.with_standard_args() method behavior."""

    def test_no_args_enables_all(self):
        """Test calling with_standard_args() with no arguments enables all args."""
        builder = AppBuilder("test")

        # Disable all first
        builder.without_standard_args()
        assert all(not v for v in builder._standard_args.values())

        # Call with no args should re-enable all
        builder.with_standard_args()
        assert all(builder._standard_args.values())

    def test_specific_kwargs_enable_individual_args(self):
        """Test specific kwargs can enable individual args."""
        builder = AppBuilder("test")

        # Enable specific args (defaults are all False except help)
        builder.with_standard_args(log_location=True, log_micros=True)

        assert builder._standard_args["log_location"] is True
        assert builder._standard_args["log_micros"] is True
        # Others should still be disabled
        assert builder._standard_args["etc_dir"] is False
        assert builder._standard_args["log_level"] is False
        assert builder._standard_args["quiet"] is False

    def test_multiple_kwargs_work_together(self):
        """Test multiple keyword arguments work together."""
        builder = AppBuilder("test")

        builder.with_standard_args(etc_dir=True, log_level=True, log_location=True)

        assert builder._standard_args["etc_dir"] is True
        assert builder._standard_args["log_level"] is True
        assert builder._standard_args["log_location"] is True
        assert builder._standard_args["log_micros"] is False
        assert builder._standard_args["quiet"] is False

    def test_invalid_arg_name_raises_value_error(self):
        """Test invalid argument name raises ValueError."""
        builder = AppBuilder("test")

        with pytest.raises(
            ValueError, match="Invalid standard argument name: 'invalid_arg'"
        ):
            builder.with_standard_args(invalid_arg=False)

    def test_non_boolean_value_raises_value_error(self):
        """Test non-boolean value raises ValueError."""
        builder = AppBuilder("test")

        with pytest.raises(ValueError, match="Value for 'etc_dir' must be a boolean"):
            builder.with_standard_args(etc_dir="not_a_bool")

    def test_method_chaining_works(self):
        """Test method returns self for chaining."""
        builder = AppBuilder("test")

        result = builder.with_standard_args(log_location=False)

        assert result is builder

    def test_can_re_enable_after_disabling(self):
        """Test can re-enable args after disabling them."""
        builder = AppBuilder("test")

        # Disable
        builder.with_standard_args(etc_dir=False)
        assert builder._standard_args["etc_dir"] is False

        # Re-enable
        builder.with_standard_args(etc_dir=True)
        assert builder._standard_args["etc_dir"] is True

    def test_empty_call_after_partial_disable_re_enables_all(self):
        """Test calling with no args after partial disable re-enables all."""
        builder = AppBuilder("test")

        # Partially disable
        builder.with_standard_args(log_location=False, log_micros=False)
        assert builder._standard_args["log_location"] is False

        # Empty call should re-enable all
        builder.with_standard_args()
        assert builder._standard_args["log_location"] is True
        assert builder._standard_args["log_micros"] is True

    def test_log_alias_enables_all_log_args(self):
        """Test log=True enables all logging-related args."""
        builder = AppBuilder("test")

        builder.with_standard_args(log=True)

        # All log args should be enabled
        assert builder._standard_args["log_level"] is True
        assert builder._standard_args["log_location"] is True
        assert builder._standard_args["log_micros"] is True
        assert builder._standard_args["log_topic"] is True
        assert builder._standard_args["log_colors"] is True
        assert builder._standard_args["log_json"] is True
        assert builder._standard_args["quiet"] is True
        # Non-log args should still be disabled
        assert builder._standard_args["etc_dir"] is False
        assert builder._standard_args["config_file"] is False

    def test_log_alias_with_override(self):
        """Test log=True can be overridden by explicit settings."""
        builder = AppBuilder("test")

        # log=True but quiet=False should keep quiet disabled
        builder.with_standard_args(log=True, quiet=False)

        assert builder._standard_args["log_level"] is True
        assert builder._standard_args["quiet"] is False  # Override wins


@pytest.mark.unit
class TestWithoutStandardArgsMethod:
    """Test AppBuilder.without_standard_args() method behavior."""

    def test_disables_all_standard_args(self):
        """Test method disables all standard arguments."""
        builder = AppBuilder("test")

        # First enable all
        builder.with_standard_args()
        assert all(builder._standard_args.values())

        # Disable all
        builder.without_standard_args()

        assert all(not v for v in builder._standard_args.values())

    def test_method_chaining_works(self):
        """Test method returns self for chaining."""
        builder = AppBuilder("test")

        result = builder.without_standard_args()

        assert result is builder

    def test_multiple_calls_are_idempotent(self):
        """Test calling multiple times has same effect."""
        builder = AppBuilder("test")

        builder.without_standard_args()
        first_state = builder._standard_args.copy()

        builder.without_standard_args()
        second_state = builder._standard_args.copy()

        assert first_state == second_state
        assert all(not v for v in second_state.values())


@pytest.mark.integration
class TestStandardArgsIntegration:
    """Test standard args integration with App class."""

    def test_minimal_args_by_default(self):
        """Test only help is added to parser by default (minimal CLI)."""
        app = AppBuilder("test").build()
        app.create_args()

        # Get the parser's arguments
        parser_args = {action.dest for action in app.parser.parser._actions}

        # Only help should be present by default
        assert "help" in parser_args

        # These should NOT be present by default
        assert "etc_dir" not in parser_args
        assert "log_level" not in parser_args
        assert "log_location" not in parser_args
        assert "log_micros" not in parser_args
        assert "quiet" not in parser_args
        assert "config" not in parser_args

    def test_enabled_args_added_to_parser(self):
        """Test enabled args are added to parser."""
        app = (
            AppBuilder("test")
            .with_standard_args(etc_dir=True, log_level=True, quiet=True)
            .build()
        )
        app.create_args()

        parser_args = {action.dest for action in app.parser.parser._actions}

        # These should be present
        assert "etc_dir" in parser_args
        assert "log_level" in parser_args
        assert "quiet" in parser_args

        # These should NOT be present
        assert "log_location" not in parser_args
        assert "log_micros" not in parser_args

    def test_hybrid_usage_disable_all_enable_specific(self):
        """Test disabling all then enabling specific args."""
        app = (
            AppBuilder("test")
            .without_standard_args()
            .with_standard_args(etc_dir=True, log_level=True)
            .build()
        )
        app.create_args()

        parser_args = {action.dest for action in app.parser.parser._actions}

        # Only these should be present
        assert "etc_dir" in parser_args
        assert "log_level" in parser_args

        # These should NOT be present
        assert "log_location" not in parser_args
        assert "log_micros" not in parser_args
        assert "quiet" not in parser_args

    def test_partial_enable_works_correctly(self):
        """Test partial enable of args works correctly."""
        app = (
            AppBuilder("test")
            .with_standard_args(log_level=True, log_location=True, log_micros=True)
            .build()
        )
        app.create_args()

        parser_args = {action.dest for action in app.parser.parser._actions}

        # These should be present
        assert "log_level" in parser_args
        assert "log_location" in parser_args
        assert "log_micros" in parser_args

        # These should NOT be present
        assert "etc_dir" not in parser_args
        assert "quiet" not in parser_args

    def test_configuration_passed_from_builder_to_app(self):
        """Test standard args configuration is passed from builder to app."""
        builder = AppBuilder("test")
        builder.with_standard_args(log_location=True, etc_dir=True)

        app = builder.build()

        # App should have the same configuration
        assert app._standard_args["log_location"] is True
        assert app._standard_args["etc_dir"] is True
        # Others should still be disabled (default)
        assert app._standard_args["log_micros"] is False


@pytest.mark.integration
class TestMinimalDefaults:
    """Test minimal default behavior - only help by default."""

    def test_default_behavior_is_minimal(self):
        """Test default behavior only adds help (minimal CLI)."""
        app = AppBuilder("test").build()
        app.create_args()

        parser_args = {action.dest for action in app.parser.parser._actions}

        # Only help should be present by default
        assert "help" in parser_args
        assert "etc_dir" not in parser_args
        assert "log_level" not in parser_args
        assert "config" not in parser_args

    def test_opt_in_pattern_for_standard_args(self):
        """Test the recommended opt-in pattern for enabling standard args."""
        app = (
            AppBuilder("test")
            .with_name("MyApp")
            .with_description("Test app")
            .with_standard_args(
                etc_dir=True, config_file=True, log_level=True, quiet=True
            )
            .build()
        )
        app.create_args()

        parser_args = {action.dest for action in app.parser.parser._actions}

        # Opted-in args should be present
        assert "etc_dir" in parser_args
        assert "config" in parser_args
        assert "log_level" in parser_args
        assert "quiet" in parser_args
        # Not opted-in args should NOT be present
        assert "log_location" not in parser_args
        assert "log_micros" not in parser_args


@pytest.mark.unit
class TestEdgeCases:
    """Test edge cases and complex chaining scenarios."""

    def test_multiple_chained_calls_with_different_configs(self):
        """Test multiple chained calls with different configurations."""
        builder = (
            AppBuilder("test")
            .with_standard_args(log_location=False)
            .with_standard_args(log_micros=False)
            .with_standard_args(etc_dir=False)
        )

        # All three should be disabled
        assert builder._standard_args["log_location"] is False
        assert builder._standard_args["log_micros"] is False
        assert builder._standard_args["etc_dir"] is False

    def test_mix_of_enable_disable_in_single_call(self):
        """Test mix of True/False values in single call."""
        builder = AppBuilder("test")

        # Start with all enabled
        builder.with_standard_args()

        # Now disable some and explicitly enable others
        builder.with_standard_args(
            log_location=False,
            log_micros=True,  # Explicitly True (already True)
            etc_dir=False,
        )

        assert builder._standard_args["log_location"] is False
        assert builder._standard_args["log_micros"] is True
        assert builder._standard_args["etc_dir"] is False
        assert builder._standard_args["log_level"] is True  # Unchanged

    def test_complex_chaining_scenarios(self):
        """Test complex chaining scenarios."""
        builder = (
            AppBuilder("test")
            .without_standard_args()
            .with_standard_args(etc_dir=True)
            .with_standard_args(log_level=True)
            .with_standard_args(etc_dir=False)  # Disable again
            .with_standard_args()
        )  # Re-enable all

        # Final state should be all enabled (last call)
        assert all(builder._standard_args.values())


@pytest.mark.unit
class TestWithStandardArgMethod:
    """Test AppBuilder.with_standard_arg() per-arg override behavior."""

    def test_stores_overrides_under_arg_name(self):
        builder = AppBuilder("test").with_standard_arg(
            "etc_dir", default="./etc", help="config dir"
        )

        assert builder._standard_arg_overrides == {
            "etc_dir": {"default": "./etc", "help": "config dir"}
        }

    def test_multiple_calls_merge_keys(self):
        builder = AppBuilder("test")
        builder.with_standard_arg("etc_dir", default="./etc")
        builder.with_standard_arg("etc_dir", help="new help")

        assert builder._standard_arg_overrides["etc_dir"] == {
            "default": "./etc",
            "help": "new help",
        }

    def test_later_call_overwrites_same_key(self):
        builder = AppBuilder("test")
        builder.with_standard_arg("etc_dir", default="./etc")
        builder.with_standard_arg("etc_dir", default="/srv/etc")

        assert builder._standard_arg_overrides["etc_dir"]["default"] == "/srv/etc"

    def test_invalid_name_rejected(self):
        builder = AppBuilder("test")
        with pytest.raises(ValueError, match="Invalid standard argument name"):
            builder.with_standard_arg("not_a_real_arg", default="x")

    def test_log_alias_rejected(self):
        builder = AppBuilder("test")
        with pytest.raises(ValueError, match="'log' is an alias"):
            builder.with_standard_arg("log", default="warning")

    def test_dest_override_rejected(self):
        builder = AppBuilder("test")
        with pytest.raises(ValueError, match="Cannot override 'dest'"):
            builder.with_standard_arg("etc_dir", dest="my_etc_dir")

    def test_method_chains(self):
        builder = AppBuilder("test")
        result = builder.with_standard_arg("etc_dir", default="./etc")
        assert result is builder


@pytest.mark.integration
class TestStandardArgOverrideIntegration:
    """Verify with_standard_arg overrides reach the parser."""

    @staticmethod
    def _action_for(app, dest: str):
        return next(a for a in app.parser.parser._actions if a.dest == dest)

    def test_default_override_reaches_parser(self):
        app = (
            AppBuilder("test")
            .with_standard_args(etc_dir=True)
            .with_standard_arg("etc_dir", default="./etc")
            .build()
        )
        app.create_args()

        action = self._action_for(app, "etc_dir")
        assert action.default == "./etc"

    def test_help_override_reaches_parser(self):
        app = (
            AppBuilder("test")
            .with_standard_args(etc_dir=True)
            .with_standard_arg("etc_dir", help="custom etc help")
            .build()
        )
        app.create_args()

        action = self._action_for(app, "etc_dir")
        assert action.help == "custom etc help"

    def test_override_for_disabled_arg_is_silently_ignored(self):
        app = (
            AppBuilder("test")
            .without_standard_args()
            .with_standard_arg("etc_dir", default="./etc")
            .build()
        )
        app.create_args()

        parser_dests = {a.dest for a in app.parser.parser._actions}
        assert "etc_dir" not in parser_dests

    def test_override_only_changes_specified_keys(self):
        """Framework defaults survive for kwargs not in the override."""
        app = (
            AppBuilder("test")
            .with_standard_args(etc_dir=True)
            .with_standard_arg("etc_dir", default="./etc")
            .build()
        )
        app.create_args()

        action = self._action_for(app, "etc_dir")
        assert action.default == "./etc"
        # metavar and type came from the framework
        assert action.metavar == "DIR"
        assert action.type is str

    def test_log_level_override(self):
        app = (
            AppBuilder("test")
            .with_standard_args(log_level=True)
            .with_standard_arg("log_level", default="warning")
            .build()
        )
        app.create_args()

        assert self._action_for(app, "log_level").default == "warning"

    def test_config_file_override(self):
        app = (
            AppBuilder("test")
            .with_standard_args(config_file=True)
            .with_standard_arg("config_file", default="prod.yaml", help="prod config")
            .build()
        )
        app.create_args()

        action = self._action_for(app, "config")
        assert action.default == "prod.yaml"
        assert action.help == "prod config"
