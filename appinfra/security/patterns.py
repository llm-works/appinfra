# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Secret detection patterns.

Contains regex patterns for detecting common secret formats in text.
Patterns are designed to minimize false positives while catching
real secrets.
"""

# Pattern names for documentation and configuration
PATTERN_NAMES = {
    "api_key": "API keys (generic)",
    "password_assignment": "Password assignments",
    "secret_assignment": "Secret/token assignments",
    "bearer_token": "Bearer tokens",
    "basic_auth": "Basic authentication",
    "aws_access_key": "AWS access key ID",
    "aws_secret_key": "AWS secret access key",
    "github_token": "GitHub tokens",
    "slack_token": "Slack tokens",
    "stripe_key": "Stripe API keys",
    "private_key": "Private key headers",
    "jwt_token": "JWT tokens",
    "database_url": "Database connection URLs with credentials",
}

# Default patterns for secret detection
# Each pattern captures the secret value as group 1 or 2
DEFAULT_PATTERNS: list[str] = [
    # Generic API key patterns
    # Matches: api_key=xxx, apikey: xxx, API-KEY="xxx"
    r'(?i)(?:api[_-]?key|apikey)["\s:=]+["\']?([a-zA-Z0-9_-]{16,})["\']?',
    # Password assignments
    # Matches: password=xxx, passwd: xxx, pwd="xxx"
    r'(?i)(?:password|passwd|pwd)["\s:=]+["\']?([^\s"\']{8,})["\']?',
    # Secret/token assignments
    # Matches: secret=xxx, token: xxx, SECRET_KEY="xxx"
    r'(?i)(?:secret|token|secret[_-]?key)["\s:=]+["\']?([a-zA-Z0-9_-]{16,})["\']?',
    # Bearer tokens
    # Matches: Bearer eyJhbGc..., Authorization: Bearer xxx
    r"(?i)bearer\s+([a-zA-Z0-9_-]{20,}\.?[a-zA-Z0-9_=-]*\.?[a-zA-Z0-9_=-]*)",
    # Basic auth
    # Matches: Basic dXNlcjpwYXNz
    r"(?i)basic\s+([a-zA-Z0-9+/]{20,}={0,2})",
    # AWS Access Key ID
    # Matches: AKIA... (20 chars)
    r"\b(AKIA[0-9A-Z]{16})\b",
    # AWS Secret Access Key
    # Matches: 40 character base64-ish string after aws_secret
    r'(?i)(?:aws[_-]?secret[_-]?access[_-]?key)["\s:=]+["\']?([a-zA-Z0-9/+=]{40})["\']?',
    # GitHub tokens
    # Matches: ghp_xxx, gho_xxx, ghu_xxx, ghs_xxx, ghr_xxx
    r"\b(gh[pousr]_[a-zA-Z0-9]{36,})\b",
    # Slack tokens
    # Matches: xoxb-xxx, xoxp-xxx, xoxa-xxx
    r"\b(xox[bpaosr]-[a-zA-Z0-9-]{24,})\b",
    # Stripe keys
    # Matches: sk_live_xxx, sk_test_xxx, pk_live_xxx, pk_test_xxx
    r"\b([sr]k_(?:live|test)_[a-zA-Z0-9]{24,})\b",
    # Private key headers
    # Matches: -----BEGIN RSA PRIVATE KEY-----, etc.
    r"(-----BEGIN\s+(?:RSA\s+)?PRIVATE\s+KEY-----)",
    # JWT tokens (basic detection)
    # Matches: eyJ... patterns with two dots
    r"\b(eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,})\b",
    # Database URLs with credentials
    # Matches: postgresql://user:pass@host, mysql://user:pass@host
    r"(?i)(?:postgresql|mysql|mongodb|redis)://[^:]+:([^@\s]{8,})@",
]

# Patterns that are more aggressive (higher false positive rate)
# These can be enabled via configuration
AGGRESSIVE_PATTERNS: list[str] = [
    # Any hex string that looks like a key (32+ chars)
    r"\b([a-fA-F0-9]{32,})\b",
    # Any base64-encoded string (40+ chars)
    r"\b([a-zA-Z0-9+/]{40,}={0,2})\b",
]

# Patterns for specific services (can be enabled selectively)
SERVICE_PATTERNS: dict[str, list[str]] = {
    "google": [
        r"\b(AIza[a-zA-Z0-9_-]{35})\b",  # Google API key
        r"([0-9]+-[a-zA-Z0-9_]{32}\.apps\.googleusercontent\.com)",  # OAuth client ID
    ],
    "azure": [
        r'(?i)(?:azure[_-]?(?:storage|account)[_-]?key)["\s:=]+["\']?([a-zA-Z0-9+/]{88}={0,2})["\']?',
    ],
    "sendgrid": [
        r"\b(SG\.[a-zA-Z0-9_-]{22}\.[a-zA-Z0-9_-]{43})\b",
    ],
    "twilio": [
        r"\b(SK[a-f0-9]{32})\b",  # Twilio API key
    ],
}
