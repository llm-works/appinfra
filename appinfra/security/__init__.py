# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Security module for appinfra.

Provides automatic secret detection and masking for logs and console output.
Security by default - secrets are masked without requiring explicit configuration.

Example:
    from . import SecretMasker, get_masker

    # Get the global masker
    masker = get_masker()

    # Mask secrets in text
    safe_text = masker.mask("api_key=sk-12345678901234567890")
    # Output: "api_key=[MASKED]"

    # Add known secrets (e.g., from environment)
    masker.add_known_secret(os.environ.get("DB_PASSWORD"))

    # Add custom patterns
    masker.add_pattern(r"MY_TOKEN_[A-Z0-9]+")
"""

from .filter import SecretMaskingFilter
from .masking import SecretMasker, get_masker, reset_masker
from .patterns import DEFAULT_PATTERNS, PATTERN_NAMES

__all__ = [
    "SecretMasker",
    "SecretMaskingFilter",
    "get_masker",
    "reset_masker",
    "DEFAULT_PATTERNS",
    "PATTERN_NAMES",
]
