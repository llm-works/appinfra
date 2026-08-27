# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for app/builder/configurer/advanced.py.

Tests key functionality including:
- AdvancedConfigurer initialization
- Hook registration
- Hook builder integration
- Validation rule registration
- Validation builder integration
- Custom argument registration
- Method chaining (fluent API)
"""

from unittest.mock import Mock

import pytest

from appinfra.app.builder.configurer.advanced import AdvancedConfigurer

# =============================================================================
# Test AdvancedConfigurer Initialization
# =============================================================================


@pytest.mark.unit
class TestAdvancedConfigurerInit:
    """Test AdvancedConfigurer initialization."""

    def test_stores_app_builder_reference(self):
        """Test stores reference to parent AppBuilder."""
        app_builder = Mock()

        configurer = AdvancedConfigurer(app_builder)

        assert configurer._app_builder is app_builder


# =============================================================================
# Test with_hook
# =============================================================================


@pytest.mark.unit
class TestWithHook:
    """Test AdvancedConfigurer.with_hook method."""

    def test_registers_hook_callback(self):
        """Test registers hook callback with hook manager."""
        app_builder = Mock()
        app_builder._hooks = Mock()
        configurer = AdvancedConfigurer(app_builder)

        def my_callback():
            pass

        result = configurer.with_hook("startup", my_callback)

        app_builder._hooks.register_hook.assert_called_once_with("startup", my_callback)
        assert result is configurer

    def test_multiple_hooks_same_event(self):
        """Test can register multiple hooks for same event."""
        app_builder = Mock()
        app_builder._hooks = Mock()
        configurer = AdvancedConfigurer(app_builder)

        def callback1():
            pass

        def callback2():
            pass

        configurer.with_hook("startup", callback1)
        configurer.with_hook("startup", callback2)

        assert app_builder._hooks.register_hook.call_count == 2

    def test_different_events(self):
        """Test can register hooks for different events."""
        app_builder = Mock()
        app_builder._hooks = Mock()
        configurer = AdvancedConfigurer(app_builder)

        startup_callback = lambda: None
        shutdown_callback = lambda: None

        configurer.with_hook("startup", startup_callback)
        configurer.with_hook("shutdown", shutdown_callback)

        assert app_builder._hooks.register_hook.call_count == 2
        # Verify both events were registered
        call_args = [
            call[0] for call in app_builder._hooks.register_hook.call_args_list
        ]
        events = [args[0] for args in call_args]
        assert "startup" in events
        assert "shutdown" in events


# =============================================================================
# Test with_hook_builder
# =============================================================================


@pytest.mark.unit
class TestWithHookBuilder:
    """Test AdvancedConfigurer.with_hook_builder method."""

    def test_builds_and_merges_hooks(self):
        """Test builds hook manager and merges hooks."""
        app_builder = Mock()
        app_builder._hooks = Mock()
        configurer = AdvancedConfigurer(app_builder)

        # Mock hook builder
        builder = Mock()
        hook_manager = Mock()
        hook_manager._hooks = {
            "startup": [Mock(name="cb1"), Mock(name="cb2")],
            "shutdown": [Mock(name="cb3")],
        }
        builder.build.return_value = hook_manager

        result = configurer.with_hook_builder(builder)

        builder.build.assert_called_once()
        # Should register all hooks from the builder
        assert app_builder._hooks.register_hook.call_count == 3
        assert result is configurer

    def test_empty_hook_builder(self):
        """Test handles empty hook builder."""
        app_builder = Mock()
        app_builder._hooks = Mock()
        configurer = AdvancedConfigurer(app_builder)

        builder = Mock()
        hook_manager = Mock()
        hook_manager._hooks = {}
        builder.build.return_value = hook_manager

        result = configurer.with_hook_builder(builder)

        builder.build.assert_called_once()
        app_builder._hooks.register_hook.assert_not_called()
        assert result is configurer


# =============================================================================
# Test with_validation_rule
# =============================================================================


@pytest.mark.unit
class TestWithValidationRule:
    """Test AdvancedConfigurer.with_validation_rule method."""

    def test_adds_validation_rule(self):
        """Test adds validation rule to list."""
        app_builder = Mock()
        app_builder._validation_rules = []
        configurer = AdvancedConfigurer(app_builder)
        rule = Mock(name="ValidationRule")

        result = configurer.with_validation_rule(rule)

        assert rule in app_builder._validation_rules
        assert result is configurer

    def test_multiple_rules(self):
        """Test can add multiple validation rules."""
        app_builder = Mock()
        app_builder._validation_rules = []
        configurer = AdvancedConfigurer(app_builder)
        rule1 = Mock(name="Rule1")
        rule2 = Mock(name="Rule2")

        configurer.with_validation_rule(rule1)
        configurer.with_validation_rule(rule2)

        assert rule1 in app_builder._validation_rules
        assert rule2 in app_builder._validation_rules
        assert len(app_builder._validation_rules) == 2


# =============================================================================
# Test with_validation_builder
# =============================================================================


@pytest.mark.unit
class TestWithValidationBuilder:
    """Test AdvancedConfigurer.with_validation_builder method."""

    def test_builds_and_extends_rules(self):
        """Test builds rules from builder and extends list."""
        app_builder = Mock()
        app_builder._validation_rules = []
        configurer = AdvancedConfigurer(app_builder)

        builder = Mock()
        built_rules = [Mock(name="Rule1"), Mock(name="Rule2")]
        builder.build.return_value = built_rules

        result = configurer.with_validation_builder(builder)

        builder.build.assert_called_once()
        assert len(app_builder._validation_rules) == 2
        assert result is configurer

    def test_appends_to_existing_rules(self):
        """Test appends builder rules to existing rules."""
        app_builder = Mock()
        existing_rule = Mock(name="ExistingRule")
        app_builder._validation_rules = [existing_rule]
        configurer = AdvancedConfigurer(app_builder)

        builder = Mock()
        builder.build.return_value = [Mock(name="NewRule")]

        configurer.with_validation_builder(builder)

        assert existing_rule in app_builder._validation_rules
        assert len(app_builder._validation_rules) == 2


# =============================================================================
# Test with_argument
# =============================================================================


@pytest.mark.unit
class TestWithArgument:
    """Test AdvancedConfigurer.with_argument method."""

    def test_adds_positional_argument(self):
        """Test adds positional argument spec."""
        app_builder = Mock()
        app_builder._custom_args = []
        configurer = AdvancedConfigurer(app_builder)

        result = configurer.with_argument("filename", help="Input file")

        assert len(app_builder._custom_args) == 1
        args, kwargs = app_builder._custom_args[0]
        assert args == ("filename",)
        assert kwargs == {"help": "Input file"}
        assert result is configurer

    def test_adds_optional_argument(self):
        """Test adds optional argument spec."""
        app_builder = Mock()
        app_builder._custom_args = []
        configurer = AdvancedConfigurer(app_builder)

        result = configurer.with_argument(
            "--verbose", "-v", action="store_true", help="Enable verbose output"
        )

        args, kwargs = app_builder._custom_args[0]
        assert args == ("--verbose", "-v")
        assert kwargs == {"action": "store_true", "help": "Enable verbose output"}
        assert result is configurer

    def test_multiple_arguments(self):
        """Test can add multiple custom arguments."""
        app_builder = Mock()
        app_builder._custom_args = []
        configurer = AdvancedConfigurer(app_builder)

        configurer.with_argument("input")
        configurer.with_argument("output")
        configurer.with_argument("--force", action="store_true")

        assert len(app_builder._custom_args) == 3

    def test_complex_argument_options(self):
        """Test handles complex argument options."""
        app_builder = Mock()
        app_builder._custom_args = []
        configurer = AdvancedConfigurer(app_builder)

        configurer.with_argument(
            "--count",
            type=int,
            default=10,
            choices=[1, 5, 10, 50, 100],
            help="Number of items",
        )

        args, kwargs = app_builder._custom_args[0]
        assert kwargs["type"] is int
        assert kwargs["default"] == 10
        assert kwargs["choices"] == [1, 5, 10, 50, 100]


# =============================================================================
# Test done
# =============================================================================


@pytest.mark.unit
class TestDone:
    """Test AdvancedConfigurer.done method."""

    def test_returns_app_builder(self):
        """Test returns parent AppBuilder for continued chaining."""
        app_builder = Mock()
        configurer = AdvancedConfigurer(app_builder)

        result = configurer.done()

        assert result is app_builder


# =============================================================================
# Integration Tests
# =============================================================================


@pytest.mark.integration
class TestAdvancedConfigurerIntegration:
    """Integration tests for AdvancedConfigurer."""

    def test_full_configuration_chain(self):
        """Test complete fluent configuration chain."""
        app_builder = Mock()
        app_builder._hooks = Mock()
        app_builder._validation_rules = []
        app_builder._custom_args = []

        configurer = AdvancedConfigurer(app_builder)
        rule = Mock(name="ValidationRule")

        result = (
            configurer.with_hook("startup", lambda: None)
            .with_hook("shutdown", lambda: None)
            .with_validation_rule(rule)
            .with_argument("--debug", action="store_true")
            .done()
        )

        assert result is app_builder
        assert app_builder._hooks.register_hook.call_count == 2
        assert rule in app_builder._validation_rules
        assert len(app_builder._custom_args) == 1

    def test_builder_pattern_integration(self):
        """Test using builders with configurer."""
        app_builder = Mock()
        app_builder._hooks = Mock()
        app_builder._validation_rules = []
        app_builder._custom_args = []

        # Mock hook builder
        hook_builder = Mock()
        hook_manager = Mock()
        hook_manager._hooks = {"startup": [Mock()]}
        hook_builder.build.return_value = hook_manager

        # Mock validation builder
        validation_builder = Mock()
        validation_builder.build.return_value = [Mock(), Mock()]

        configurer = AdvancedConfigurer(app_builder)

        result = (
            configurer.with_hook_builder(hook_builder)
            .with_validation_builder(validation_builder)
            .done()
        )

        assert result is app_builder
        hook_builder.build.assert_called_once()
        validation_builder.build.assert_called_once()
        assert len(app_builder._validation_rules) == 2

    def test_combining_direct_and_builder_configuration(self):
        """Test mixing direct configuration with builders."""
        app_builder = Mock()
        app_builder._hooks = Mock()
        app_builder._validation_rules = []
        app_builder._custom_args = []

        direct_rule = Mock(name="DirectRule")

        validation_builder = Mock()
        builder_rules = [Mock(name="BuilderRule1"), Mock(name="BuilderRule2")]
        validation_builder.build.return_value = builder_rules

        configurer = AdvancedConfigurer(app_builder)

        (
            configurer.with_validation_rule(direct_rule)
            .with_validation_builder(validation_builder)
            .with_hook("startup", lambda: None)
        )

        assert direct_rule in app_builder._validation_rules
        assert len(app_builder._validation_rules) == 3
        app_builder._hooks.register_hook.assert_called_once()
