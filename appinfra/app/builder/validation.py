# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Validation framework for the AppBuilder.

This module provides a fluent API for creating validation rules
and validating application inputs.
"""

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Self


@dataclass
class ValidationResult:
    """Result of a validation operation."""

    is_valid: bool
    errors: list[str]
    warnings: list[str] = field(default_factory=list)

    def add_error(self, error: str) -> None:
        """Add an error message."""
        self.errors.append(error)
        self.is_valid = False

    def add_warning(self, warning: str) -> None:
        """Add a warning message."""
        self.warnings.append(warning)

    @property
    def has_errors(self) -> bool:
        """Check if there are any errors."""
        return len(self.errors) > 0

    @property
    def has_warnings(self) -> bool:
        """Check if there are any warnings."""
        return len(self.warnings) > 0


class ValidationRule(ABC):
    """Base class for validation rules."""

    def __init__(self, name: str, message: str | None = None):
        """
        Initialize the validation rule.

        Args:
            name: Rule name
            message: Custom error message
        """
        self.name = name
        self.message = message or f"Validation failed for {name}"

    @abstractmethod
    def validate(
        self, value: Any, context: dict[str, Any] | None = None
    ) -> ValidationResult:
        """
        Validate a value.

        Args:
            value: Value to validate
            context: Additional context for validation

        Returns:
            ValidationResult: Validation result
        """
        pass


class RequiredRule(ValidationRule):
    """Rule that requires a value to be present and not empty."""

    def __init__(self, field_name: str, message: str | None = None):
        super().__init__(
            f"required_{field_name}", message or f"{field_name} is required"
        )
        self.field_name = field_name

    def validate(
        self, value: Any, context: dict[str, Any] | None = None
    ) -> ValidationResult:
        """Validate that the field is required."""
        result = ValidationResult(is_valid=True, errors=[])

        if value is None or (isinstance(value, str) and not value.strip()):
            result.add_error(self.message)

        return result


class TypeRule(ValidationRule):
    """Rule that validates the type of a value."""

    def __init__(
        self, field_name: str, expected_type: type, message: str | None = None
    ):
        super().__init__(
            f"type_{field_name}",
            message or f"{field_name} must be of type {expected_type.__name__}",
        )
        self.field_name = field_name
        self.expected_type = expected_type

    def validate(
        self, value: Any, context: dict[str, Any] | None = None
    ) -> ValidationResult:
        """Validate the type of the value."""
        result = ValidationResult(is_valid=True, errors=[])

        if value and not isinstance(value, self.expected_type):
            result.add_error(self.message)

        return result


class RangeRule(ValidationRule):
    """Rule that validates a value is within a range."""

    def __init__(
        self,
        field_name: str,
        min_value: float | None = None,
        max_value: float | None = None,
        message: str | None = None,
    ):
        super().__init__(
            f"range_{field_name}",
            message or f"{field_name} must be between {min_value} and {max_value}",
        )
        self.field_name = field_name
        self.min_value = min_value
        self.max_value = max_value

    def validate(
        self, value: Any, context: dict[str, Any] | None = None
    ) -> ValidationResult:
        """Validate the value is within range."""
        result = ValidationResult(is_valid=True, errors=[])

        if value is None:
            return result

        try:
            num_value = float(value)
            # More concise range validation
            for limit, op, msg in [
                (self.min_value, "<", "at least"),
                (self.max_value, ">", "at most"),
            ]:
                if limit and (
                    (op == "<" and num_value < limit)
                    or (op == ">" and num_value > limit)
                ):
                    result.add_error(f"{self.field_name} must be {msg} {limit}")
        except (ValueError, TypeError):
            result.add_error(f"{self.field_name} must be a number")

        return result


class ChoiceRule(ValidationRule):
    """Rule that validates a value is one of the allowed choices."""

    def __init__(self, field_name: str, choices: list[Any], message: str | None = None):
        super().__init__(
            f"choice_{field_name}", message or f"{field_name} must be one of {choices}"
        )
        self.field_name = field_name
        self.choices = choices

    def validate(
        self, value: Any, context: dict[str, Any] | None = None
    ) -> ValidationResult:
        """Validate the value is in the allowed choices."""
        result = ValidationResult(is_valid=True, errors=[])

        if value and value not in self.choices:
            result.add_error(f"{self.field_name} must be one of {self.choices}")

        return result


class CustomRule(ValidationRule):
    """Rule that uses a custom validation function."""

    def __init__(
        self,
        field_name: str,
        validator: Callable[[Any], bool],
        message: str | None = None,
    ):
        super().__init__(
            f"custom_{field_name}", message or f"{field_name} failed custom validation"
        )
        self.field_name = field_name
        self.validator = validator

    def validate(
        self, value: Any, context: dict[str, Any] | None = None
    ) -> ValidationResult:
        """Validate using the custom validator function."""
        result = ValidationResult(is_valid=True, errors=[])

        try:
            if not self.validator(value):
                result.add_error(self.message)
        except Exception as e:
            result.add_error(f"{self.field_name} validation error: {str(e)}")

        return result


class ValidationBuilder:
    """Builder for creating validation rules."""

    def __init__(self) -> None:
        self._rules: list[ValidationRule] = []

    def require_argument(self, name: str, message: str | None = None) -> Self:
        """Add a required argument rule."""
        self._rules.append(RequiredRule(name, message))
        return self

    def require_one_of(self, *args: str) -> Self:
        """Require at least one of the specified arguments."""

        def validator(value: Any, context: dict[str, Any] | None = None) -> bool:
            if context is None:
                return False
            return any(context.get(arg) is not None for arg in args)

        self._rules.append(
            CustomRule(
                f"one_of_{'_'.join(args)}",
                validator,
                f"At least one of {args} must be provided",
            )
        )
        return self

    def require_all_of(self, *args: str) -> Self:
        """Require all of the specified arguments."""

        def validator(value: Any, context: dict[str, Any] | None = None) -> bool:
            if context is None:
                return False
            return all(context.get(arg) is not None for arg in args)

        self._rules.append(
            CustomRule(
                f"all_of_{'_'.join(args)}", validator, f"All of {args} must be provided"
            )
        )
        return self

    def with_type(
        self, name: str, expected_type: type, message: str | None = None
    ) -> Self:
        """Add a type validation rule."""
        self._rules.append(TypeRule(name, expected_type, message))
        return self

    def with_range(
        self,
        name: str,
        min_value: float | None = None,
        max_value: float | None = None,
        message: str | None = None,
    ) -> Self:
        """Add a range validation rule."""
        self._rules.append(RangeRule(name, min_value, max_value, message))
        return self

    def with_choice(
        self, name: str, choices: list[Any], message: str | None = None
    ) -> Self:
        """Add a choice validation rule."""
        self._rules.append(ChoiceRule(name, choices, message))
        return self

    def with_custom_rule(self, rule: ValidationRule) -> Self:
        """Add a custom validation rule."""
        self._rules.append(rule)
        return self

    def with_custom_validator(
        self, name: str, validator: Callable[[Any], bool], message: str | None = None
    ) -> Self:
        """Add a custom validator function."""
        self._rules.append(CustomRule(name, validator, message))
        return self

    def build(self) -> list[ValidationRule]:
        """Build the list of validation rules."""
        return self._rules.copy()


class Validator:
    """Main validator class that applies validation rules."""

    def __init__(self, rules: list[ValidationRule] | None = None):
        """
        Initialize the validator.

        Args:
            rules: List of validation rules
        """
        self.rules = rules or []

    def add_rule(self, rule: ValidationRule) -> None:
        """Add a validation rule."""
        self.rules.append(rule)

    def validate(self, data: dict[str, Any]) -> ValidationResult:
        """
        Validate data against all rules.

        Args:
            data: Data to validate

        Returns:
            ValidationResult: Combined validation result
        """
        result = ValidationResult(is_valid=True, errors=[], warnings=[])

        for rule in self.rules:
            # Get the value for this rule's field
            field_name = getattr(rule, "field_name", None)
            if field_name:
                value = data.get(field_name)
                rule_result = rule.validate(value, data)
            else:
                # For rules without specific field names, validate the entire data
                rule_result = rule.validate(data, data)

            # Merge results
            if not rule_result.is_valid:
                result.is_valid = False
                result.errors.extend(rule_result.errors)
            result.warnings.extend(rule_result.warnings)

        return result

    def validate_args(self, args: Any) -> ValidationResult:
        """
        Validate command-line arguments.

        Args:
            args: Parsed arguments object

        Returns:
            ValidationResult: Validation result
        """
        # Convert args to dictionary
        data = vars(args) if hasattr(args, "__dict__") else args
        return self.validate(data)


def create_validation_builder() -> ValidationBuilder:
    """
    Create a new validation builder.

    Returns:
        ValidationBuilder instance

    Example:
        validator = create_validation_builder().with_rule(custom_rule).build()
    """
    return ValidationBuilder()
