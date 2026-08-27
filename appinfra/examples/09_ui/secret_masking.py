#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Secret Masking Example

Demonstrates automatic secret detection and masking using appinfra.security:
- Pattern-based secret detection
- Known secret registration
- Logging filter integration
- Console output integration

Run: python examples/09_ui/secret_masking.py
"""

import logging
import sys
from pathlib import Path

# Add parent to path for development
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from appinfra.security import (
    DEFAULT_PATTERNS,
    PATTERN_NAMES,
    SecretMasker,
    SecretMaskingFilter,
    get_masker,
)
from appinfra.ui import Table, console

MASKING_TEST_CASES = [
    ("API Key", "api_key=sk-12345678901234567890"),
    ("Password", "password: super-secret-pass-123"),
    ("Token", 'token="ghp_1234567890123456789012345678901234567890"'),
    (
        "Bearer",
        "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.payload.signature",
    ),
    ("AWS Key", "AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"),
    ("DB URL", "postgresql://admin:mypassword123@localhost:5432/mydb"),
    ("Normal", "This is a normal log message with no secrets"),
]


def _truncate(text: str, max_len: int = 40) -> str:
    """Truncate text for display."""
    return text[:max_len] + "..." if len(text) > max_len else text


def demo_basic_masking():
    """Demonstrate basic secret masking."""
    console.rule("Basic Secret Masking")
    masker = SecretMasker()

    table = Table(title="Secret Masking Results")
    table.add_column("Type", style="cyan")
    table.add_column("Original")
    table.add_column("Masked", style="green")

    for secret_type, original in MASKING_TEST_CASES:
        masked = masker.mask(original)
        table.add_row(secret_type, _truncate(original), _truncate(masked))

    console.print(table)
    console.print()


def demo_known_secrets():
    """Demonstrate known secret registration."""
    console.rule("Known Secrets")

    masker = SecretMasker()

    # Simulate loading secrets from environment
    db_password = "my-database-password-xyz"
    api_secret = "custom-api-secret-12345"

    # Register known secrets
    masker.add_known_secret(db_password)
    masker.add_known_secret(api_secret)

    # These will now be masked even if they don't match patterns
    test_messages = [
        f"Connecting to database with {db_password}",
        f"API initialized with secret {api_secret}",
        "Normal message without secrets",
    ]

    console.print("[bold]Messages with known secrets registered:[/bold]")
    for msg in test_messages:
        masked = masker.mask(msg)
        console.print(f"  Original: {msg}")
        console.print(f"  Masked:   [green]{masked}[/green]")
        console.print()


def demo_custom_patterns():
    """Demonstrate custom pattern registration."""
    console.rule("Custom Patterns")

    # Create masker with no default patterns
    masker = SecretMasker(patterns=[])

    # Add custom pattern for our internal tokens
    masker.add_pattern(r"MYAPP_TOKEN_([A-Za-z0-9]{20,})")

    test_cases = [
        "Using MYAPP_TOKEN_abc123def456ghi789jkl",
        "Normal text without tokens",
    ]

    console.print("[bold]Custom pattern (MYAPP_TOKEN_xxx):[/bold]")
    for msg in test_cases:
        masked = masker.mask(msg)
        console.print(f"  {msg}")
        console.print(f"  -> [green]{masked}[/green]")
        console.print()


def _setup_secure_logger() -> logging.Logger:
    """Set up a logger with masking filter."""
    logger = logging.getLogger("secure_app")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    masker = SecretMasker()
    masker.add_known_secret("secret-db-pass-123")
    handler.addFilter(SecretMaskingFilter(masker))
    logger.addHandler(handler)
    return logger


def demo_logging_integration():
    """Demonstrate logging filter integration."""
    console.rule("Logging Integration")
    logger = _setup_secure_logger()

    console.print("[bold]Logging with automatic masking:[/bold]")
    console.print()

    logger.info("Starting application...")
    logger.info("Connecting with password=secret-db-pass-123")
    logger.info("API key loaded: api_key=sk-12345678901234567890")
    logger.info("Database URL: postgresql://user:secret-db-pass-123@localhost/db")
    logger.info("Application ready")
    console.print()


def demo_supported_patterns():
    """Show all supported secret patterns."""
    console.rule("Supported Secret Patterns")

    table = Table(title="Default Detection Patterns")
    table.add_column("Pattern Name", style="cyan")
    table.add_column("Description")

    for name, description in PATTERN_NAMES.items():
        table.add_row(name, description)

    console.print(table)
    console.print()
    console.print(f"[dim]Total patterns: {len(DEFAULT_PATTERNS)}[/dim]")
    console.print()


def demo_is_secret():
    """Demonstrate secret detection without masking."""
    console.rule("Secret Detection")

    masker = get_masker()

    test_values = [
        "sk-12345678901234567890",
        "ghp_1234567890123456789012345678901234567890",
        "AKIAIOSFODNN7EXAMPLE",
        "normal_variable_name",
        "user@example.com",
    ]

    console.print("[bold]Checking if values appear to be secrets:[/bold]")
    for value in test_values:
        is_secret = masker.is_secret(value)
        status = "[red]SECRET[/red]" if is_secret else "[green]OK[/green]"
        console.print(f"  {value[:30]:30} {status}")

    console.print()


def main():
    """Run all demos."""
    console.print()
    console.print("[bold blue]Secret Masking Demo[/bold blue]")
    console.print()

    demo_basic_masking()
    demo_known_secrets()
    demo_custom_patterns()
    demo_logging_integration()
    demo_is_secret()
    demo_supported_patterns()

    console.rule("Demo Complete")


if __name__ == "__main__":
    main()
