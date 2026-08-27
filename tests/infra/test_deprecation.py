# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for deprecation utilities.

Tests the @deprecated decorator including:
- Warning emission
- Message formatting
- Function metadata preservation
- Stack level correctness
"""

import warnings

import pytest

from appinfra.deprecation import deprecated

# =============================================================================
# Test Deprecated Decorator - Basic Functionality
# =============================================================================


@pytest.mark.unit
class TestDeprecatedBasic:
    """Test basic @deprecated decorator functionality."""

    def test_emits_deprecation_warning(self):
        """Test that calling a deprecated function emits DeprecationWarning."""

        @deprecated(version="0.2.0")
        def old_function() -> str:
            return "result"

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = old_function()

            assert result == "result"
            assert len(w) == 1
            assert issubclass(w[0].category, DeprecationWarning)

    def test_warning_message_includes_version(self):
        """Test that warning message includes the deprecation version."""

        @deprecated(version="0.2.0")
        def old_function() -> str:
            return "result"

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            old_function()

            assert "0.2.0" in str(w[0].message)

    def test_warning_message_includes_function_name(self):
        """Test that warning message includes the function name."""

        @deprecated(version="0.2.0")
        def my_old_function() -> str:
            return "result"

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            my_old_function()

            assert "my_old_function" in str(w[0].message)

    def test_warning_message_includes_replacement_when_provided(self):
        """Test that warning message includes replacement when specified."""

        @deprecated(version="0.2.0", replacement="new_function")
        def old_function() -> str:
            return "result"

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            old_function()

            assert "new_function" in str(w[0].message)
            assert "instead" in str(w[0].message)

    def test_warning_message_without_replacement(self):
        """Test that warning message works without replacement."""

        @deprecated(version="0.2.0")
        def old_function() -> str:
            return "result"

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            old_function()

            assert "instead" not in str(w[0].message)


# =============================================================================
# Test Deprecated Decorator - Metadata Preservation
# =============================================================================


@pytest.mark.unit
class TestDeprecatedMetadata:
    """Test that @deprecated preserves function metadata."""

    def test_preserves_function_name(self):
        """Test that __name__ is preserved."""

        @deprecated(version="0.2.0")
        def my_function() -> str:
            return "result"

        assert my_function.__name__ == "my_function"

    def test_preserves_docstring(self):
        """Test that __doc__ is preserved."""

        @deprecated(version="0.2.0")
        def my_function() -> str:
            """This is the docstring."""
            return "result"

        assert my_function.__doc__ == "This is the docstring."

    def test_preserves_module(self):
        """Test that __module__ is preserved."""

        @deprecated(version="0.2.0")
        def my_function() -> str:
            return "result"

        assert my_function.__module__ == __name__


# =============================================================================
# Test Deprecated Decorator - Arguments and Return Values
# =============================================================================


@pytest.mark.unit
class TestDeprecatedArgsReturn:
    """Test that @deprecated correctly passes arguments and return values."""

    def test_passes_positional_args(self):
        """Test that positional arguments are passed correctly."""

        @deprecated(version="0.2.0")
        def add(a: int, b: int) -> int:
            return a + b

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            assert add(2, 3) == 5

    def test_passes_keyword_args(self):
        """Test that keyword arguments are passed correctly."""

        @deprecated(version="0.2.0")
        def greet(name: str, greeting: str = "Hello") -> str:
            return f"{greeting}, {name}!"

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            assert greet(name="World", greeting="Hi") == "Hi, World!"

    def test_passes_mixed_args(self):
        """Test that mixed positional and keyword arguments work."""

        @deprecated(version="0.2.0")
        def format_message(msg: str, *, prefix: str = "") -> str:
            return f"{prefix}{msg}"

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            assert format_message("test", prefix=">>") == ">>test"

    def test_returns_none(self):
        """Test that None return value works correctly."""

        @deprecated(version="0.2.0")
        def do_nothing() -> None:
            pass

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            assert do_nothing() is None


# =============================================================================
# Test Deprecated Decorator - Method Usage
# =============================================================================


@pytest.mark.unit
class TestDeprecatedMethods:
    """Test @deprecated on class methods."""

    def test_instance_method(self):
        """Test deprecated instance method."""

        class MyClass:
            @deprecated(version="0.2.0")
            def old_method(self) -> str:
                return "instance method"

        obj = MyClass()
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = obj.old_method()

            assert result == "instance method"
            assert len(w) == 1
            assert "old_method" in str(w[0].message)

    def test_class_method(self):
        """Test deprecated class method."""

        class MyClass:
            @classmethod
            @deprecated(version="0.2.0")
            def old_classmethod(cls) -> str:
                return "class method"

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = MyClass.old_classmethod()

            assert result == "class method"
            assert len(w) == 1

    def test_static_method(self):
        """Test deprecated static method."""

        class MyClass:
            @staticmethod
            @deprecated(version="0.2.0")
            def old_staticmethod() -> str:
                return "static method"

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = MyClass.old_staticmethod()

            assert result == "static method"
            assert len(w) == 1


# =============================================================================
# Test Deprecated Decorator - Stack Level
# =============================================================================


@pytest.mark.unit
class TestDeprecatedStackLevel:
    """Test that warning points to caller, not decorator."""

    def test_warning_points_to_caller(self):
        """Test that stacklevel=2 makes warning point to caller."""
        import os

        @deprecated(version="0.2.0")
        def old_function() -> str:
            return "result"

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            old_function()  # This line should be in the warning

            # The warning's filename should be this test file
            # Use samefile to handle symlinks and path normalization
            assert os.path.samefile(w[0].filename, __file__)


# =============================================================================
# Test Deprecated Decorator - Multiple Calls
# =============================================================================


@pytest.mark.unit
class TestDeprecatedMultipleCalls:
    """Test behavior with multiple calls to deprecated function."""

    def test_warns_on_each_call(self):
        """Test that each call emits a warning."""

        @deprecated(version="0.2.0")
        def old_function() -> str:
            return "result"

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            old_function()
            old_function()
            old_function()

            assert len(w) == 3
