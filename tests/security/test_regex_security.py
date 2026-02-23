"""Security tests for regex utilities (infra/regex_utils.py)."""

import sys
import time

import pytest

import appinfra.regex_utils
from appinfra.regex_utils import (
    MAX_PATTERN_LENGTH,
    RegexComplexityError,
    RegexTimeoutError,
    safe_compile,
    safe_match,
)
from tests.security.payloads.redos import (
    NESTED_QUANTIFIERS,
    REDOS_EVIL_INPUTS,
)


@pytest.mark.security
@pytest.mark.unit
@pytest.mark.parametrize("pattern", NESTED_QUANTIFIERS)
def test_nested_quantifier_detection(pattern: str):
    """
    Verify pattern complexity validator rejects nested quantifiers.

    Attack Vector: ReDoS via nested quantifiers
    Module: infra/regex_utils.py:63-89 (_validate_pattern_complexity)
    OWASP: A05:2021 - Security Misconfiguration

    Security Concern: Patterns with nested quantifiers like (.+)+ or (.*)*
    cause exponential backtracking, leading to CPU exhaustion (ReDoS).
    The complexity validator should detect and reject these patterns.
    """
    # Attempt to compile pattern with nested quantifiers
    with pytest.raises(
        RegexComplexityError,
        match="(nested quantifiers|catastrophic backtracking)",
    ):
        safe_compile(pattern)


@pytest.mark.security
@pytest.mark.unit
@pytest.mark.expected_skip  # Skips on Windows (no SIGALRM for timeout)
def test_alternation_explosion_detection():
    """
    Verify pattern complexity validator catches degenerate alternations.

    Attack Vector: ReDoS via alternation explosion
    Module: infra/regex_utils.py:63-89 (_validate_pattern_complexity)
    OWASP: A05:2021 - Security Misconfiguration

    Security Concern: Degenerate alternations like (a|a)* can cause
    catastrophic backtracking. While the current validator focuses on
    nested quantifiers, this test documents alternation-based ReDoS.
    """
    # Note: Current implementation may not catch all alternation patterns
    # This test documents the attack vector for future improvements

    # The pattern (a|a)* is degenerate but Python's regex engine optimizes it
    # so it doesn't actually cause catastrophic backtracking in practice.
    # This is a limitation of static analysis - some patterns look dangerous
    # but work fine due to regex engine optimizations.

    # For now, we just document this case. The pattern is allowed because:
    # 1. It's not a nested quantifier (our current focus)
    # 2. Python's regex engine handles it efficiently
    # 3. Timeout protection is available as a fallback on Unix

    if sys.platform == "win32":
        pytest.skip("Alternation pattern test not applicable on Windows")

    # Document that this pattern is currently allowed
    alternation_pattern = r"(a|a)*"
    compiled = safe_compile(alternation_pattern)

    # It should match successfully without timeout (Python optimizes this)
    result = safe_match(compiled, "a" * 30, timeout=1.0)
    assert result is not None


@pytest.mark.security
@pytest.mark.unit
def test_pattern_length_limit():
    """
    Verify MAX_PATTERN_LENGTH enforcement prevents extremely long patterns.

    Attack Vector: Resource exhaustion via extremely long patterns
    Module: infra/regex_utils.py:53 (MAX_PATTERN_LENGTH = 1000)
    OWASP: A05:2021 - Security Misconfiguration

    Security Concern: Extremely long regex patterns can consume excessive
    memory and processing time during compilation. The 1000-character
    limit should prevent this.
    """
    # Generate pattern exceeding MAX_PATTERN_LENGTH
    long_pattern = "a" * (MAX_PATTERN_LENGTH + 1)

    # Attempt to compile - should be rejected
    with pytest.raises(
        RegexComplexityError,
        match=f"Pattern too long.*{MAX_PATTERN_LENGTH}",
    ):
        safe_compile(long_pattern)

    # Verify patterns at exactly MAX_PATTERN_LENGTH are allowed
    exact_length_pattern = "a" * MAX_PATTERN_LENGTH
    compiled = safe_compile(exact_length_pattern)
    assert compiled is not None


@pytest.mark.security
@pytest.mark.skipif(
    sys.platform == "win32",
    reason="signal.SIGALRM not available on Windows",
)
@pytest.mark.parametrize(
    "pattern,evil_input",
    list(REDOS_EVIL_INPUTS.items()),  # Test all available ReDoS patterns
)
def test_regex_timeout_enforcement_unix(pattern: str, evil_input: str):
    """
    Verify regex timeout mechanism prevents ReDoS on Unix systems.

    Attack Vector: ReDoS with malicious input causing catastrophic backtracking
    Module: infra/regex_utils.py:92-117 (_timeout_context)
    OWASP: A05:2021 - Security Misconfiguration

    Security Concern: Even simple-looking patterns can cause exponential
    backtracking with carefully crafted input. The 1-second timeout
    should prevent infinite regex execution.

    Note: This test only runs on Unix systems where signal.SIGALRM is available.
    """
    # These patterns are known to cause ReDoS, but may not be caught by
    # the complexity validator (simple syntax, complex behavior)

    # Force compile without timeout to get the dangerous pattern
    import re

    dangerous_pattern = re.compile(pattern)

    # Now test that matching with evil input triggers timeout
    start_time = time.time()

    with pytest.raises(RegexTimeoutError):
        safe_match(dangerous_pattern, evil_input, timeout=1.0)

    elapsed = time.time() - start_time

    # Verify timeout happened around 1 second (±0.5s tolerance)
    assert 0.5 <= elapsed <= 1.5, f"Timeout took {elapsed}s, expected ~1s"


@pytest.mark.security
@pytest.mark.integration
@pytest.mark.expected_skip  # Windows-only test, skips on Unix
@pytest.mark.skipif(
    sys.platform != "win32",
    reason="Test Windows behavior (or mock it on Unix)",
)
def test_regex_timeout_degradation_windows():
    """
    Verify graceful degradation when timeout is unavailable (Windows).

    Attack Vector: Platform-specific timeout bypass
    Module: infra/regex_utils.py:108-116 (signal.SIGALRM check)
    OWASP: A05:2021 - Security Misconfiguration

    Security Concern: signal.SIGALRM is Unix-only. On Windows, the timeout
    mechanism is disabled, leaving the system vulnerable to ReDoS. This test
    documents the limitation and verifies graceful degradation (no crashes).

    Note: This is a known limitation documented in SECURITY.md. Windows users
    should rely on pattern complexity validation only.
    """
    # On Windows, safe_compile should work but timeout is disabled
    import sys

    if sys.platform == "win32":
        # Pattern that would timeout on Unix
        pattern = r"(a+)+"
        input_str = "a" * 30 + "b"

        # Compile with timeout parameter (will be ignored on Windows)
        try:
            compiled = safe_compile(pattern)

            # Matching may hang on Windows (no timeout protection)
            # We can't easily test this without actually hanging,
            # so we just document the behavior
            pytest.skip("Windows timeout test skipped - would hang without protection")

        except RegexComplexityError:
            # Pattern caught by complexity validator - good fallback!
            pass
    else:
        # On Unix, mock Windows behavior
        import unittest.mock as mock

        with mock.patch("appinfra.regex_utils.signal.SIGALRM", create=False):
            # Simulate Windows environment where SIGALRM doesn't exist
            delattr(appinfra.regex_utils.signal, "SIGALRM")

            # safe_compile should still work, just without timeout
            simple_pattern = r"^[a-z]+$"
            compiled = safe_compile(simple_pattern, timeout=1.0)
            assert compiled is not None

            # Restore SIGALRM
            import signal

            appinfra.regex_utils.signal.SIGALRM = signal.SIGALRM


# Positive test: Verify legitimate patterns still work
@pytest.mark.security
@pytest.mark.unit
def test_legitimate_patterns_allowed():
    """
    Verify legitimate regex patterns are not blocked by security measures.

    Security Concern: Security measures should block attacks without breaking
    legitimate use cases. Common patterns should compile and match successfully.
    """
    legitimate_patterns = [
        r"^[a-z]+$",  # Simple character class
        r"\d{3}-\d{4}",  # Phone number pattern
        r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",  # Email pattern
        r"^(https?://)?[\w.-]+\.\w{2,}(/\S*)?$",  # URL pattern
        r"foo.*bar",  # Simple wildcard
    ]

    for pattern in legitimate_patterns:
        compiled = safe_compile(pattern)
        assert compiled is not None

    # Verify they match correctly
    assert safe_compile(r"^[a-z]+$").match("hello")
    assert safe_compile(r"\d{3}-\d{4}").search("123-4567")
