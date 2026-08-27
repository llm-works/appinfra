# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Secret masking implementation.

Provides the SecretMasker class for detecting and masking secrets
in strings using regex patterns.
"""

import re
from re import Pattern

from .patterns import DEFAULT_PATTERNS


class SecretMasker:
    """
    Detect and mask secrets in strings.

    Uses regex patterns to find and replace secrets with a masked value.
    Supports both pattern-based detection and explicit known secrets.

    Example:
        masker = SecretMasker()

        # Pattern-based masking
        text = "api_key=sk-12345678901234567890"
        safe = masker.mask(text)
        # "api_key=[MASKED]"

        # Known secret masking
        masker.add_known_secret("my-secret-password")
        text = "connecting with my-secret-password"
        safe = masker.mask(text)
        # "connecting with [MASKED]"
    """

    DEFAULT_MASK = "[MASKED]"

    def __init__(
        self,
        *,
        patterns: list[str] | None = None,
        mask: str = DEFAULT_MASK,
        enabled: bool = True,
    ):
        """
        Initialize the masker.

        Args:
            patterns: List of regex patterns for detection (default: DEFAULT_PATTERNS)
            mask: Replacement string for secrets
            enabled: Whether masking is enabled
        """
        self._mask = mask
        self._enabled = enabled
        self._patterns: list[Pattern[str]] = []
        self._known_secrets: set[str] = set()

        # Compile default patterns
        pattern_list = patterns if patterns is not None else DEFAULT_PATTERNS
        for pattern in pattern_list:
            self.add_pattern(pattern)

    @property
    def enabled(self) -> bool:
        """Check if masking is enabled."""
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        """Enable or disable masking."""
        self._enabled = value

    @property
    def mask_string(self) -> str:
        """Get the mask replacement string."""
        return self._mask

    def add_pattern(self, pattern: str) -> None:
        """
        Add a regex pattern for secret detection.

        The pattern should capture the secret value as a group.
        If the pattern has multiple groups, the last non-empty group
        will be masked.

        Args:
            pattern: Regex pattern string

        Raises:
            re.error: If the pattern is invalid
        """
        compiled = re.compile(pattern)
        self._patterns.append(compiled)

    def add_known_secret(self, secret: str | None) -> None:
        """
        Add a known secret value to be masked.

        Useful for masking specific values like environment variables
        that might not match generic patterns.

        Args:
            secret: The secret value to mask (None values are ignored)
        """
        if secret and len(secret) >= 4:  # Avoid masking very short strings
            self._known_secrets.add(secret)

    def remove_known_secret(self, secret: str) -> None:
        """
        Remove a known secret from the mask list.

        Args:
            secret: The secret value to remove
        """
        self._known_secrets.discard(secret)

    def clear_known_secrets(self) -> None:
        """Clear all known secrets."""
        self._known_secrets.clear()

    def mask(self, text: str) -> str:
        """
        Mask secrets in the given text.

        Applies both pattern-based detection and known secret replacement.

        Args:
            text: Input text that may contain secrets

        Returns:
            Text with secrets replaced by mask string
        """
        if not self._enabled or not text:
            return text

        result = text

        # Apply pattern-based masking
        for pattern in self._patterns:
            result = self._mask_pattern(result, pattern)

        # Apply known secret masking
        for secret in self._known_secrets:
            if secret in result:
                result = result.replace(secret, self._mask)

        return result

    def _mask_pattern(self, text: str, pattern: Pattern[str]) -> str:
        """
        Apply a single pattern to mask secrets.

        Args:
            text: Input text
            pattern: Compiled regex pattern

        Returns:
            Text with matched secrets masked
        """

        def replacer(match: re.Match[str]) -> str:
            # Get all groups
            groups = match.groups()
            if not groups:
                return match.group(0)

            # Find the secret value (last non-empty group)
            secret_value = None
            for group in reversed(groups):
                if group:
                    secret_value = group
                    break

            if not secret_value:
                return match.group(0)

            # Replace the secret in the matched text
            full_match = match.group(0)
            return full_match.replace(secret_value, self._mask)

        return pattern.sub(replacer, text)

    def is_secret(self, text: str) -> bool:
        """
        Check if the text appears to be a secret.

        Args:
            text: Text to check

        Returns:
            True if the text matches any secret pattern
        """
        if not text:
            return False

        # Check known secrets
        if text in self._known_secrets:
            return True

        # Check patterns
        for pattern in self._patterns:
            if pattern.search(text):
                return True

        return False


# Global masker instance
_global_masker: SecretMasker | None = None


def get_masker() -> SecretMasker:
    """
    Get or create the global masker instance.

    Returns:
        SecretMasker instance
    """
    global _global_masker

    if _global_masker is None:
        _global_masker = SecretMasker()

    return _global_masker


def reset_masker() -> None:
    """Reset the global masker instance."""
    global _global_masker
    _global_masker = None
