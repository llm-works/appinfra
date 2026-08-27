# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Property-based tests for regex utilities."""

import re

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from appinfra.regex_utils import (
    RegexComplexityError,
    RegexTimeoutError,
    safe_compile,
    safe_match,
)


@pytest.mark.property
@pytest.mark.unit
class TestRegexProperties:
    """Property-based tests for regex_utils.py functions."""

    @given(pattern=st.text(max_size=30))
    @settings(max_examples=50)
    def test_safe_compile_never_crashes(self, pattern: str) -> None:
        """safe_compile should handle any input without crashing unexpectedly."""
        try:
            result = safe_compile(pattern, timeout=0.05)
            # If it compiled, it should be a valid pattern
            assert hasattr(result, "match")
        except RegexComplexityError:
            pass  # Expected for complex patterns
        except RegexTimeoutError:
            pass  # Expected for slow patterns (Unix only)
        except re.error:
            pass  # Expected for invalid regex syntax

    @given(
        pattern=st.from_regex(r"[a-z]+", fullmatch=True),
        text=st.text(alphabet="abcdefghijklmnopqrstuvwxyz", max_size=50),
    )
    @settings(max_examples=50)
    def test_valid_patterns_work(self, pattern: str, text: str) -> None:
        """Valid simple patterns should compile and match without issues."""
        compiled = safe_compile(pattern, timeout=0.1)
        # Should not raise - just test it completes
        safe_match(compiled, text, timeout=0.1)

    @given(length=st.integers(min_value=1001, max_value=2000))
    def test_long_patterns_rejected(self, length: int) -> None:
        """Patterns exceeding max length should be rejected."""
        pattern = "a" * length
        with pytest.raises(RegexComplexityError, match="too long"):
            safe_compile(pattern)

    @given(
        prefix=st.text(alphabet="abc", min_size=0, max_size=5),
        suffix=st.text(alphabet="abc", min_size=0, max_size=5),
    )
    def test_nested_quantifiers_rejected(self, prefix: str, suffix: str) -> None:
        """Nested quantifiers should be rejected as dangerous."""
        # These are known ReDoS patterns
        dangerous_patterns = [
            f"{prefix}(.+)+{suffix}",
            f"{prefix}(.*)*{suffix}",
            f"{prefix}(a+)+{suffix}",
        ]

        for pattern in dangerous_patterns:
            with pytest.raises(RegexComplexityError, match="nested quantifiers"):
                safe_compile(pattern)

    @given(char_class=st.sampled_from(["a-z", "0-9", "A-Z", "a-zA-Z0-9"]))
    def test_simple_character_classes_safe(self, char_class: str) -> None:
        """Simple character class patterns should be safe."""
        patterns = [
            f"[{char_class}]+",
            f"[{char_class}]*",
            f"[{char_class}]{{1,10}}",
            f"^[{char_class}]+$",
        ]

        for pattern in patterns:
            result = safe_compile(pattern)
            assert hasattr(result, "match")
