# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for app/builder/validation.py.

Tests key functionality including:
- ValidationResult dataclass
- Various ValidationRule implementations
- ValidationBuilder fluent API
- Validator class
"""

from unittest.mock import Mock

import pytest

from appinfra.app.builder.validation import (
    ChoiceRule,
    CustomRule,
    RangeRule,
    RequiredRule,
    TypeRule,
    ValidationBuilder,
    ValidationResult,
    Validator,
)

# =============================================================================
# Test ValidationResult
# =============================================================================


@pytest.mark.unit
class TestValidationResult:
    """Test ValidationResult dataclass (lines 13-42)."""

    def test_initialization(self):
        """Test basic initialization (lines 17-23)."""
        result = ValidationResult(is_valid=True, errors=[])

        assert result.is_valid is True
        assert result.errors == []
        assert result.warnings == []

    def test_initialization_with_warnings(self):
        """Test initialization with warnings."""
        result = ValidationResult(is_valid=True, errors=[], warnings=["warn1"])

        assert result.warnings == ["warn1"]

    def test_add_error(self):
        """Test add_error method (lines 25-28)."""
        result = ValidationResult(is_valid=True, errors=[])

        result.add_error("Error message")

        assert result.is_valid is False
        assert "Error message" in result.errors

    def test_add_warning(self):
        """Test add_warning method (lines 30-32)."""
        result = ValidationResult(is_valid=True, errors=[])

        result.add_warning("Warning message")

        assert result.is_valid is True  # Warnings don't affect validity
        assert "Warning message" in result.warnings

    def test_has_errors(self):
        """Test has_errors property (lines 34-37)."""
        result = ValidationResult(is_valid=True, errors=[])
        assert result.has_errors is False

        result.add_error("error")
        assert result.has_errors is True

    def test_has_warnings(self):
        """Test has_warnings property (lines 39-42)."""
        result = ValidationResult(is_valid=True, errors=[])
        assert result.has_warnings is False

        result.add_warning("warning")
        assert result.has_warnings is True


# =============================================================================
# Test RequiredRule
# =============================================================================


@pytest.mark.unit
class TestRequiredRule:
    """Test RequiredRule class (lines 74-90)."""

    def test_initialization(self):
        """Test initialization (lines 77-81)."""
        rule = RequiredRule("username")

        assert rule.name == "required_username"
        assert "username is required" in rule.message

    def test_initialization_custom_message(self):
        """Test initialization with custom message."""
        rule = RequiredRule("username", "Please provide a username")

        assert rule.message == "Please provide a username"

    def test_validate_passes_with_value(self):
        """Test validation passes with value (line 85)."""
        rule = RequiredRule("username")

        result = rule.validate("john_doe")

        assert result.is_valid is True
        assert result.errors == []

    def test_validate_fails_with_none(self):
        """Test validation fails with None (line 87)."""
        rule = RequiredRule("username")

        result = rule.validate(None)

        assert result.is_valid is False
        assert len(result.errors) == 1

    def test_validate_fails_with_empty_string(self):
        """Test validation fails with empty string (line 87)."""
        rule = RequiredRule("username")

        result = rule.validate("")

        assert result.is_valid is False

    def test_validate_fails_with_whitespace(self):
        """Test validation fails with whitespace only (line 87)."""
        rule = RequiredRule("username")

        result = rule.validate("   ")

        assert result.is_valid is False


# =============================================================================
# Test TypeRule
# =============================================================================


@pytest.mark.unit
class TestTypeRule:
    """Test TypeRule class (lines 93-111)."""

    def test_initialization(self):
        """Test initialization (lines 96-102)."""
        rule = TypeRule("count", int)

        assert rule.name == "type_count"
        assert "int" in rule.message
        assert rule.expected_type is int

    def test_validate_passes_with_correct_type(self):
        """Test validation passes with correct type (line 106)."""
        rule = TypeRule("count", int)

        result = rule.validate(42)

        assert result.is_valid is True

    def test_validate_fails_with_wrong_type(self):
        """Test validation fails with wrong type (lines 108-109)."""
        rule = TypeRule("count", int)

        result = rule.validate("not an int")

        assert result.is_valid is False

    def test_validate_passes_with_none(self):
        """Test validation passes with None (skips validation)."""
        rule = TypeRule("count", int)

        result = rule.validate(None)

        assert result.is_valid is True

    def test_validate_passes_with_subclass(self):
        """Test validation passes with subclass."""
        rule = TypeRule("data", dict)

        class MyDict(dict):
            pass

        result = rule.validate(MyDict())

        assert result.is_valid is True


# =============================================================================
# Test RangeRule
# =============================================================================


@pytest.mark.unit
class TestRangeRule:
    """Test RangeRule class (lines 114-154)."""

    def test_initialization(self):
        """Test initialization (lines 117-130)."""
        rule = RangeRule("age", min_value=0, max_value=120)

        assert rule.name == "range_age"
        assert rule.min_value == 0
        assert rule.max_value == 120

    def test_validate_passes_in_range(self):
        """Test validation passes when in range (line 134)."""
        rule = RangeRule("age", min_value=0, max_value=120)

        result = rule.validate(50)

        assert result.is_valid is True

    def test_validate_fails_below_min(self):
        """Test validation fails below min (lines 142-150)."""
        rule = RangeRule("age", min_value=1, max_value=120)

        result = rule.validate(-5)

        assert result.is_valid is False
        assert "at least" in result.errors[0]

    def test_validate_fails_above_max(self):
        """Test validation fails above max (lines 142-150)."""
        rule = RangeRule("age", min_value=0, max_value=120)

        result = rule.validate(150)

        assert result.is_valid is False
        assert "at most" in result.errors[0]

    def test_validate_passes_at_boundaries(self):
        """Test validation passes at boundaries."""
        rule = RangeRule("age", min_value=0, max_value=120)

        assert rule.validate(0).is_valid is True
        assert rule.validate(120).is_valid is True

    def test_validate_passes_with_none(self):
        """Test validation passes with None (lines 136-137)."""
        rule = RangeRule("age", min_value=0, max_value=120)

        result = rule.validate(None)

        assert result.is_valid is True

    def test_validate_fails_with_non_number(self):
        """Test validation fails with non-number (lines 151-152)."""
        rule = RangeRule("age", min_value=0, max_value=120)

        result = rule.validate("not a number")

        assert result.is_valid is False
        assert "must be a number" in result.errors[0]

    def test_validate_min_only(self):
        """Test validation with only min specified."""
        rule = RangeRule("value", min_value=10)

        assert rule.validate(5).is_valid is False
        assert rule.validate(15).is_valid is True

    def test_validate_max_only(self):
        """Test validation with only max specified."""
        rule = RangeRule("value", max_value=100)

        assert rule.validate(50).is_valid is True
        assert rule.validate(150).is_valid is False


# =============================================================================
# Test ChoiceRule
# =============================================================================


@pytest.mark.unit
class TestChoiceRule:
    """Test ChoiceRule class (lines 157-174)."""

    def test_initialization(self):
        """Test initialization (lines 160-165)."""
        rule = ChoiceRule("color", ["red", "green", "blue"])

        assert rule.name == "choice_color"
        assert rule.choices == ["red", "green", "blue"]

    def test_validate_passes_with_valid_choice(self):
        """Test validation passes with valid choice (line 169)."""
        rule = ChoiceRule("color", ["red", "green", "blue"])

        result = rule.validate("red")

        assert result.is_valid is True

    def test_validate_fails_with_invalid_choice(self):
        """Test validation fails with invalid choice (lines 171-172)."""
        rule = ChoiceRule("color", ["red", "green", "blue"])

        result = rule.validate("yellow")

        assert result.is_valid is False

    def test_validate_passes_with_none(self):
        """Test validation passes with None."""
        rule = ChoiceRule("color", ["red", "green", "blue"])

        result = rule.validate(None)

        assert result.is_valid is True


# =============================================================================
# Test CustomRule
# =============================================================================


@pytest.mark.unit
class TestCustomRule:
    """Test CustomRule class (lines 177-199)."""

    def test_initialization(self):
        """Test initialization (lines 180-187)."""
        validator = Mock(return_value=True)
        rule = CustomRule("email", validator)

        assert rule.name == "custom_email"
        assert rule.validator is validator

    def test_validate_passes_when_validator_returns_true(self):
        """Test validation passes when validator returns True (line 194)."""
        validator = Mock(return_value=True)
        rule = CustomRule("email", validator)

        result = rule.validate("test@example.com")

        assert result.is_valid is True
        validator.assert_called_once_with("test@example.com")

    def test_validate_fails_when_validator_returns_false(self):
        """Test validation fails when validator returns False (lines 194-195)."""
        validator = Mock(return_value=False)
        rule = CustomRule("email", validator)

        result = rule.validate("invalid")

        assert result.is_valid is False

    def test_validate_handles_exception(self):
        """Test validation handles validator exception (lines 196-197)."""
        validator = Mock(side_effect=ValueError("Invalid format"))
        rule = CustomRule("email", validator)

        result = rule.validate("test")

        assert result.is_valid is False
        assert "validation error" in result.errors[0]


# =============================================================================
# Test ValidationBuilder
# =============================================================================


@pytest.mark.unit
class TestValidationBuilder:
    """Test ValidationBuilder class (lines 202-284)."""

    def test_initialization(self):
        """Test initialization (lines 205-206)."""
        builder = ValidationBuilder()

        assert builder._rules == []

    def test_require_argument(self):
        """Test require_argument method (lines 208-211)."""
        builder = ValidationBuilder()

        result = builder.require_argument("name")

        assert len(builder._rules) == 1
        assert isinstance(builder._rules[0], RequiredRule)
        assert result is builder

    def test_require_one_of(self):
        """Test require_one_of method (lines 213-228)."""
        builder = ValidationBuilder()

        result = builder.require_one_of("arg1", "arg2", "arg3")

        assert len(builder._rules) == 1
        assert isinstance(builder._rules[0], CustomRule)
        assert result is builder

    def test_require_all_of(self):
        """Test require_all_of method (lines 230-243)."""
        builder = ValidationBuilder()

        result = builder.require_all_of("arg1", "arg2")

        assert len(builder._rules) == 1
        assert isinstance(builder._rules[0], CustomRule)
        assert result is builder

    def test_with_type(self):
        """Test with_type method (lines 245-250)."""
        builder = ValidationBuilder()

        result = builder.with_type("count", int)

        assert len(builder._rules) == 1
        assert isinstance(builder._rules[0], TypeRule)
        assert result is builder

    def test_with_range(self):
        """Test with_range method (lines 252-261)."""
        builder = ValidationBuilder()

        result = builder.with_range("age", min_value=0, max_value=100)

        assert len(builder._rules) == 1
        assert isinstance(builder._rules[0], RangeRule)
        assert result is builder

    def test_with_choice(self):
        """Test with_choice method (lines 263-268)."""
        builder = ValidationBuilder()

        result = builder.with_choice("color", ["red", "green", "blue"])

        assert len(builder._rules) == 1
        assert isinstance(builder._rules[0], ChoiceRule)
        assert result is builder

    def test_with_custom_rule(self):
        """Test with_custom_rule method (lines 270-273)."""
        builder = ValidationBuilder()
        rule = RequiredRule("test")

        result = builder.with_custom_rule(rule)

        assert builder._rules[0] is rule
        assert result is builder

    def test_with_custom_validator(self):
        """Test with_custom_validator method (lines 275-280)."""
        builder = ValidationBuilder()
        validator = Mock(return_value=True)

        result = builder.with_custom_validator("email", validator)

        assert len(builder._rules) == 1
        assert isinstance(builder._rules[0], CustomRule)
        assert result is builder

    def test_build(self):
        """Test build method (lines 282-284)."""
        builder = ValidationBuilder()
        builder.require_argument("name")
        builder.with_type("age", int)

        rules = builder.build()

        assert len(rules) == 2
        # Should be a copy
        builder._rules.clear()
        assert len(rules) == 2


# =============================================================================
# Test Validator
# =============================================================================


@pytest.mark.unit
class TestValidator:
    """Test Validator class (lines 287-345)."""

    def test_initialization(self):
        """Test initialization (lines 290-297)."""
        rules = [RequiredRule("name")]
        validator = Validator(rules)

        assert validator.rules == rules

    def test_initialization_default(self):
        """Test initialization with default."""
        validator = Validator()

        assert validator.rules == []

    def test_add_rule(self):
        """Test add_rule method (lines 299-301)."""
        validator = Validator()
        rule = RequiredRule("name")

        validator.add_rule(rule)

        assert rule in validator.rules

    def test_validate_passes(self):
        """Test validate passes (lines 303-331)."""
        rules = [RequiredRule("name"), TypeRule("age", int)]
        validator = Validator(rules)

        result = validator.validate({"name": "John", "age": 30})

        assert result.is_valid is True

    def test_validate_fails(self):
        """Test validate fails (lines 326-328)."""
        rules = [RequiredRule("name")]
        validator = Validator(rules)

        result = validator.validate({"name": None})

        assert result.is_valid is False

    def test_validate_merges_errors(self):
        """Test validate merges errors from multiple rules."""
        rules = [RequiredRule("name"), RequiredRule("email")]
        validator = Validator(rules)

        result = validator.validate({"name": None, "email": None})

        assert result.is_valid is False
        assert len(result.errors) == 2

    def test_validate_args(self):
        """Test validate_args method (lines 333-345)."""
        rules = [RequiredRule("name")]
        validator = Validator(rules)

        class Args:
            def __init__(self):
                self.name = "John"

        result = validator.validate_args(Args())

        assert result.is_valid is True

    def test_validate_args_with_dict(self):
        """Test validate_args with dict input."""
        rules = [RequiredRule("name")]
        validator = Validator(rules)

        result = validator.validate_args({"name": "John"})

        assert result.is_valid is True


# =============================================================================
# Integration Tests
# =============================================================================


@pytest.mark.integration
class TestValidationIntegration:
    """Test validation system integration."""

    def test_full_validation_workflow(self):
        """Test complete validation workflow."""
        # Build validation rules
        rules = (
            ValidationBuilder()
            .require_argument("username")
            .require_argument("email")
            .with_type("age", int)
            .with_range("age", min_value=18, max_value=120)
            .with_choice("role", ["admin", "user", "guest"])
            .build()
        )

        validator = Validator(rules)

        # Valid data
        valid_data = {
            "username": "john_doe",
            "email": "john@example.com",
            "age": 30,
            "role": "user",
        }
        result = validator.validate(valid_data)
        assert result.is_valid is True
        assert result.errors == []

        # Invalid data - missing required
        invalid_data = {
            "username": "",
            "email": None,
            "age": 30,
            "role": "user",
        }
        result = validator.validate(invalid_data)
        assert result.is_valid is False
        assert len(result.errors) == 2

        # Invalid data - out of range
        invalid_data = {
            "username": "john",
            "email": "john@example.com",
            "age": 150,  # Too old
            "role": "user",
        }
        result = validator.validate(invalid_data)
        assert result.is_valid is False

        # Invalid data - invalid choice
        invalid_data = {
            "username": "john",
            "email": "john@example.com",
            "age": 30,
            "role": "superadmin",  # Not in choices
        }
        result = validator.validate(invalid_data)
        assert result.is_valid is False

    def test_require_one_of_validation(self):
        """Test require_one_of creates appropriate rules.

        Note: The require_one_of validator requires context to be passed,
        but CustomRule.validate() only passes value. This test verifies
        the rule is created correctly.
        """
        rules = ValidationBuilder().require_one_of("input_file", "input_url").build()

        # Verify rule was created
        assert len(rules) == 1
        assert isinstance(rules[0], CustomRule)
        assert "one_of" in rules[0].name

    def test_require_all_of_validation(self):
        """Test require_all_of creates appropriate rules.

        Note: Similar to require_one_of, this validator requires context.
        """
        rules = ValidationBuilder().require_all_of("host", "port").build()

        # Verify rule was created
        assert len(rules) == 1
        assert isinstance(rules[0], CustomRule)
        assert "all_of" in rules[0].name

    def test_custom_validator_integration(self):
        """Test custom validator integration."""

        def is_valid_email(value):
            return value and "@" in value

        rules = (
            ValidationBuilder()
            .with_custom_validator("email", is_valid_email, "Invalid email format")
            .build()
        )
        validator = Validator(rules)

        # Valid
        result = validator.validate({"email": "test@example.com"})
        assert result.is_valid is True

        # Invalid
        result = validator.validate({"email": "not-an-email"})
        assert result.is_valid is False
