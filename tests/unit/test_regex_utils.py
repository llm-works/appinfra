# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for regex utilities with ReDoS protection.

These tests verify that the regex utility functions properly protect
against ReDoS (Regular Expression Denial of Service) attacks.
"""

import re
import unittest

import pytest

pytestmark = pytest.mark.unit

from appinfra.regex_utils import (
    MAX_PATTERN_LENGTH,
    RegexComplexityError,
    safe_compile,
    safe_findall,
    safe_match,
    safe_search,
)


class TestPatternComplexityValidation(unittest.TestCase):
    """Test pattern complexity validation."""

    def test_simple_pattern_accepted(self):
        """Simple patterns should be accepted."""
        pattern = safe_compile(r"^[a-z]+$")
        self.assertIsNotNone(pattern)
        self.assertEqual(pattern.match("hello").group(), "hello")

    def test_bounded_quantifiers_accepted(self):
        """Patterns with bounded quantifiers should be accepted."""
        pattern = safe_compile(r"^\d{1,5}$")
        self.assertIsNotNone(pattern)
        self.assertEqual(pattern.match("12345").group(), "12345")

    def test_character_classes_accepted(self):
        """Character classes should be accepted."""
        pattern = safe_compile(r"^[A-Za-z0-9_-]+$")
        self.assertIsNotNone(pattern)
        self.assertTrue(pattern.match("Test_123"))

    def test_pattern_too_long_rejected(self):
        """Patterns exceeding max length should be rejected."""
        long_pattern = "a" * (MAX_PATTERN_LENGTH + 1)
        with self.assertRaises(RegexComplexityError) as ctx:
            safe_compile(long_pattern)
        self.assertIn("too long", str(ctx.exception))

    def test_nested_quantifiers_rejected(self):
        """Patterns with nested quantifiers should be rejected."""
        dangerous_patterns = [
            r"(.+)+",  # Catastrophic backtracking
            r"(a+)+",  # Nested quantifiers
            r"(.*)*",  # Nested star quantifiers
        ]
        for pattern in dangerous_patterns:
            with self.assertRaises(RegexComplexityError):
                safe_compile(pattern)


class TestSafeCompile(unittest.TestCase):
    """Test safe_compile function."""

    def test_compile_simple_pattern(self):
        """Should compile simple patterns successfully."""
        pattern = safe_compile(r"^\w+$")
        self.assertIsInstance(pattern, re.Pattern)

    def test_compile_with_flags(self):
        """Should support regex flags."""
        pattern = safe_compile(r"^hello$", flags=re.IGNORECASE)
        self.assertTrue(pattern.match("HELLO"))
        self.assertTrue(pattern.match("hello"))

    def test_invalid_pattern_raises_error(self):
        """Should raise error for invalid regex syntax."""
        with self.assertRaises(re.error):
            safe_compile(r"[invalid")

    def test_timeout_disabled_with_none(self):
        """Should work when timeout is None."""
        pattern = safe_compile(r"^test$", timeout=None)
        self.assertEqual(pattern.match("test").group(), "test")


class TestSafeMatch(unittest.TestCase):
    """Test safe_match function."""

    def test_match_with_string_pattern(self):
        """Should match using string pattern."""
        match = safe_match(r"^hello", "hello world")
        self.assertIsNotNone(match)
        self.assertEqual(match.group(), "hello")

    def test_match_with_compiled_pattern(self):
        """Should match using compiled pattern."""
        pattern = safe_compile(r"^test")
        match = safe_match(pattern, "test string")
        self.assertIsNotNone(match)
        self.assertEqual(match.group(), "test")

    def test_no_match_returns_none(self):
        """Should return None when no match."""
        match = safe_match(r"^hello", "goodbye")
        self.assertIsNone(match)

    def test_match_with_flags(self):
        """Should support flags with string pattern."""
        match = safe_match(r"^HELLO", "hello", flags=re.IGNORECASE)
        self.assertIsNotNone(match)

    def test_match_with_timeout_none(self):
        """Should work when timeout is None (no timeout protection)."""
        match = safe_match(r"^hello", "hello world", timeout=None)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(), "hello")


class TestSafeSearch(unittest.TestCase):
    """Test safe_search function."""

    def test_search_finds_pattern(self):
        """Should find pattern anywhere in string."""
        match = safe_search(r"world", "hello world")
        self.assertIsNotNone(match)
        self.assertEqual(match.group(), "world")

    def test_search_with_compiled_pattern(self):
        """Should work with compiled pattern."""
        pattern = safe_compile(r"\d+")
        match = safe_search(pattern, "test 123 end")
        self.assertEqual(match.group(), "123")

    def test_search_no_match_returns_none(self):
        """Should return None when pattern not found."""
        match = safe_search(r"xyz", "hello world")
        self.assertIsNone(match)

    def test_search_with_timeout_none(self):
        """Should work when timeout is None (no timeout protection)."""
        match = safe_search(r"world", "hello world", timeout=None)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(), "world")


class TestSafeFindall(unittest.TestCase):
    """Test safe_findall function."""

    def test_findall_returns_all_matches(self):
        """Should return list of all matches."""
        matches = safe_findall(r"\d+", "a1b2c3")
        self.assertEqual(matches, ["1", "2", "3"])

    def test_findall_with_compiled_pattern(self):
        """Should work with compiled pattern."""
        pattern = safe_compile(r"[a-z]+")
        matches = safe_findall(pattern, "test123hello456world")
        self.assertEqual(matches, ["test", "hello", "world"])

    def test_findall_no_matches_returns_empty_list(self):
        """Should return empty list when no matches."""
        matches = safe_findall(r"\d+", "no numbers here")
        self.assertEqual(matches, [])

    def test_findall_with_groups(self):
        """Should handle capturing groups."""
        matches = safe_findall(r"(\d+)([a-z]+)", "1test2hello3world")
        self.assertEqual(matches, [("1", "test"), ("2", "hello"), ("3", "world")])

    def test_findall_with_timeout_none(self):
        """Should work when timeout is None (no timeout protection)."""
        matches = safe_findall(r"\d+", "a1b2c3", timeout=None)
        self.assertEqual(matches, ["1", "2", "3"])


class TestReDoSProtectionIntegration(unittest.TestCase):
    """Integration tests for ReDoS protection."""

    def test_safe_patterns_work_normally(self):
        """Safe patterns should work without any issues."""
        # Time format pattern (from sched.py)
        pattern = safe_compile(r"^\d{1,2}:\d{2}$")
        self.assertTrue(pattern.match("12:30"))
        self.assertTrue(pattern.match("9:45"))
        self.assertFalse(pattern.match("123:45"))

        # Duration pattern (from delta.py)
        pattern = safe_compile(r"(\d+(?:\.\d+)?(?:,\d+)?)(ms|μs|d|h|m|s)")
        matches = safe_findall(pattern, "1d2h30m45.500s")
        self.assertEqual(len(matches), 4)

        # Tool name pattern (from registry.py)
        pattern = safe_compile(r"^[a-z][a-z0-9_-]*$")
        self.assertTrue(pattern.match("my-tool"))
        self.assertTrue(pattern.match("tool_name"))
        self.assertFalse(pattern.match("Tool"))  # uppercase

    def test_config_variable_substitution_safe(self):
        """Config variable substitution pattern is safe."""
        pattern = safe_compile(r"\$\{([a-zA-Z0-9_.]+)\}")
        match = pattern.search("value is ${config.key}")
        self.assertEqual(match.group(1), "config.key")

    def test_whitespace_patterns_safe(self):
        """Whitespace normalization patterns are safe."""
        # From pg.py
        pattern = safe_compile(r"\n\s+")
        result = pattern.sub(" ", "line1\n  line2\n   line3")
        self.assertEqual(result, "line1 line2 line3")

        pattern = safe_compile(r"\s+")
        result = pattern.sub(" ", "multiple   spaces")
        self.assertEqual(result, "multiple spaces")


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and error conditions."""

    def test_empty_pattern(self):
        """Empty pattern should compile successfully."""
        pattern = safe_compile(r"")
        self.assertTrue(pattern.match(""))

    def test_pattern_with_unicode(self):
        """Should handle Unicode patterns."""
        pattern = safe_compile(r"μs|ms")
        self.assertTrue(pattern.match("μs"))
        self.assertTrue(pattern.match("ms"))

    def test_multiline_pattern(self):
        """Should support multiline patterns."""
        pattern = safe_compile(r"^test$", flags=re.MULTILINE)
        self.assertTrue(pattern.search("line1\ntest\nline3"))

    def test_dotall_pattern(self):
        """Should support DOTALL flag."""
        pattern = safe_compile(r"a.b", flags=re.DOTALL)
        self.assertTrue(pattern.match("a\nb"))


if __name__ == "__main__":
    unittest.main()
