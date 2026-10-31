# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for regex utilities whose default timeout arms SIGALRM.
"""

import re
import unittest

from appinfra.regex_utils import safe_compile, safe_findall


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
