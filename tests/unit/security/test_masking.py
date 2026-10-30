# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for appinfra.security.masking module."""

import pytest

pytestmark = pytest.mark.unit

from appinfra.security.masking import SecretMasker, get_masker, reset_masker


@pytest.fixture(autouse=True)
def reset_global_masker():
    """Reset the global masker before each test."""
    reset_masker()
    yield
    reset_masker()


class TestSecretMasker:
    """Tests for SecretMasker class."""

    def test_masker_creation(self):
        """Test masker can be created."""
        masker = SecretMasker()
        assert masker.enabled is True
        assert masker.mask_string == "[MASKED]"

    def test_masker_disabled(self):
        """Test disabled masker returns original text."""
        masker = SecretMasker(enabled=False)
        text = "api_key=sk-12345678901234567890"
        assert masker.mask(text) == text

    def test_masker_custom_mask(self):
        """Test masker with custom mask string."""
        masker = SecretMasker(mask="***REDACTED***")
        text = "password=secret123456"
        result = masker.mask(text)
        assert "***REDACTED***" in result
        assert "secret123456" not in result

    def test_mask_api_key(self):
        """Test masking API keys."""
        masker = SecretMasker()

        cases = [
            "api_key=sk-12345678901234567890",
            "apikey: sk-12345678901234567890",
            'API_KEY="sk-12345678901234567890"',
        ]

        for text in cases:
            result = masker.mask(text)
            assert "[MASKED]" in result
            assert "sk-12345678901234567890" not in result

    def test_mask_password(self):
        """Test masking passwords."""
        masker = SecretMasker()

        cases = [
            "password=super-secret-123",
            "passwd: super-secret-123",
            'pwd="super-secret-123"',
        ]

        for text in cases:
            result = masker.mask(text)
            assert "[MASKED]" in result
            assert "super-secret-123" not in result

    def test_mask_bearer_token(self):
        """Test masking bearer tokens."""
        masker = SecretMasker()

        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.payload"
        result = masker.mask(text)
        assert "[MASKED]" in result

    def test_mask_aws_access_key(self):
        """Test masking AWS access key IDs."""
        masker = SecretMasker()

        text = "AWS key: AKIAIOSFODNN7EXAMPLE"
        result = masker.mask(text)
        assert "[MASKED]" in result
        assert "AKIAIOSFODNN7EXAMPLE" not in result

    def test_mask_github_token(self):
        """Test masking GitHub tokens."""
        masker = SecretMasker()

        text = "token: ghp_1234567890123456789012345678901234567890"
        result = masker.mask(text)
        assert "[MASKED]" in result

    def test_mask_database_url(self):
        """Test masking database URL passwords."""
        masker = SecretMasker()

        text = "postgresql://user:mypassword123@localhost/db"
        result = masker.mask(text)
        assert "[MASKED]" in result
        assert "mypassword123" not in result

    def test_no_mask_normal_text(self):
        """Test normal text is not masked."""
        masker = SecretMasker()

        text = "This is a normal log message with no secrets"
        result = masker.mask(text)
        assert result == text
        assert "[MASKED]" not in result

    def test_known_secret(self):
        """Test masking known secrets."""
        masker = SecretMasker()
        masker.add_known_secret("my-custom-secret")

        text = "Connecting with my-custom-secret"
        result = masker.mask(text)
        assert "[MASKED]" in result
        assert "my-custom-secret" not in result

    def test_known_secret_none_ignored(self):
        """Test None known secret is ignored."""
        masker = SecretMasker()
        masker.add_known_secret(None)
        assert len(masker._known_secrets) == 0

    def test_known_secret_short_ignored(self):
        """Test short secrets are ignored."""
        masker = SecretMasker()
        masker.add_known_secret("abc")  # Too short
        assert len(masker._known_secrets) == 0

    def test_remove_known_secret(self):
        """Test removing known secrets."""
        masker = SecretMasker()
        masker.add_known_secret("secret-value")
        masker.remove_known_secret("secret-value")

        text = "Connecting with secret-value"
        result = masker.mask(text)
        assert "secret-value" in result

    def test_clear_known_secrets(self):
        """Test clearing all known secrets."""
        masker = SecretMasker()
        masker.add_known_secret("secret1")
        masker.add_known_secret("secret2")
        masker.clear_known_secrets()

        assert len(masker._known_secrets) == 0

    def test_add_custom_pattern(self):
        """Test adding custom patterns."""
        masker = SecretMasker(patterns=[])  # Start with no patterns
        masker.add_pattern(r"MY_TOKEN_([A-Z0-9]+)")

        text = "Using MY_TOKEN_ABC123DEF456"
        result = masker.mask(text)
        assert "[MASKED]" in result

    def test_is_secret(self):
        """Test is_secret detection."""
        masker = SecretMasker()

        assert masker.is_secret("api_key=sk-12345678901234567890")
        assert not masker.is_secret("normal text")
        assert not masker.is_secret("")

    def test_is_secret_known(self):
        """Test is_secret with known secrets."""
        masker = SecretMasker()
        masker.add_known_secret("my-known-secret")

        assert masker.is_secret("my-known-secret")

    def test_enable_disable(self):
        """Test enabling and disabling masker."""
        masker = SecretMasker()

        masker.enabled = False
        text = "password=secretpassword123"  # Must be 8+ chars to match pattern
        assert masker.mask(text) == text

        masker.enabled = True
        assert "[MASKED]" in masker.mask(text)


class TestGetMasker:
    """Tests for get_masker function."""

    def test_get_masker_returns_masker(self):
        """Test get_masker returns a SecretMasker instance."""
        masker = get_masker()
        assert isinstance(masker, SecretMasker)

    def test_get_masker_returns_same_instance(self):
        """Test get_masker returns the same instance."""
        masker1 = get_masker()
        masker2 = get_masker()
        assert masker1 is masker2

    def test_reset_masker(self):
        """Test reset_masker creates new instance."""
        masker1 = get_masker()
        reset_masker()
        masker2 = get_masker()
        assert masker1 is not masker2
