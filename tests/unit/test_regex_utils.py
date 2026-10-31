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

    @pytest.mark.integration
    def test_simple_pattern_accepted(self):
        """Simple patterns should be accepted."""
        pattern = safe_compile(r"^[a-z]+$")
        self.assertIsNotNone(pattern)
        self.assertEqual(pattern.match("hello").group(), "hello")

    @pytest.mark.integration
    def test_bounded_quantifiers_accepted(self):
        """Patterns with bounded quantifiers should be accepted."""
        pattern = safe_compile(r"^\d{1,5}$")
        self.assertIsNotNone(pattern)
        self.assertEqual(pattern.match("12345").group(), "12345")

    @pytest.mark.integration
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

    @pytest.mark.integration
    def test_compile_simple_pattern(self):
        """Should compile simple patterns successfully."""
        pattern = safe_compile(r"^\w+$")
        self.assertIsInstance(pattern, re.Pattern)

    @pytest.mark.integration
    def test_compile_with_flags(self):
        """Should support regex flags."""
        pattern = safe_compile(r"^hello$", flags=re.IGNORECASE)
        self.assertTrue(pattern.match("HELLO"))
        self.assertTrue(pattern.match("hello"))

    @pytest.mark.integration
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

    @pytest.mark.integration
    def test_match_with_string_pattern(self):
        """Should match using string pattern."""
        match = safe_match(r"^hello", "hello world")
        self.assertIsNotNone(match)
        self.assertEqual(match.group(), "hello")

    @pytest.mark.integration
    def test_match_with_compiled_pattern(self):
        """Should match using compiled pattern."""
        pattern = safe_compile(r"^test")
        match = safe_match(pattern, "test string")
        self.assertIsNotNone(match)
        self.assertEqual(match.group(), "test")

    @pytest.mark.integration
    def test_no_match_returns_none(self):
        """Should return None when no match."""
        match = safe_match(r"^hello", "goodbye")
        self.assertIsNone(match)

    @pytest.mark.integration
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

    @pytest.mark.integration
    def test_search_finds_pattern(self):
        """Should find pattern anywhere in string."""
        match = safe_search(r"world", "hello world")
        self.assertIsNotNone(match)
        self.assertEqual(match.group(), "world")

    @pytest.mark.integration
    def test_search_with_compiled_pattern(self):
        """Should work with compiled pattern."""
        pattern = safe_compile(r"\d+")
        match = safe_search(pattern, "test 123 end")
        self.assertEqual(match.group(), "123")

    @pytest.mark.integration
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

    @pytest.mark.integration
    def test_findall_returns_all_matches(self):
        """Should return list of all matches."""
        matches = safe_findall(r"\d+", "a1b2c3")
        self.assertEqual(matches, ["1", "2", "3"])

    @pytest.mark.integration
    def test_findall_with_compiled_pattern(self):
        """Should work with compiled pattern."""
        pattern = safe_compile(r"[a-z]+")
        matches = safe_findall(pattern, "test123hello456world")
        self.assertEqual(matches, ["test", "hello", "world"])

    @pytest.mark.integration
    def test_findall_no_matches_returns_empty_list(self):
        """Should return empty list when no matches."""
        matches = safe_findall(r"\d+", "no numbers here")
        self.assertEqual(matches, [])

    @pytest.mark.integration
    def test_findall_with_groups(self):
        """Should handle capturing groups."""
        matches = safe_findall(r"(\d+)([a-z]+)", "1test2hello3world")
        self.assertEqual(matches, [("1", "test"), ("2", "hello"), ("3", "world")])

    def test_findall_with_timeout_none(self):
        """Should work when timeout is None (no timeout protection)."""
        matches = safe_findall(r"\d+", "a1b2c3", timeout=None)
        self.assertEqual(matches, ["1", "2", "3"])


if __name__ == "__main__":
    unittest.main()
