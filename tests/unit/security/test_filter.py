# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for appinfra.security.filter module."""

import logging

import pytest

pytestmark = pytest.mark.unit

from appinfra.security.filter import SecretMaskingFilter, add_masking_filter_to_logger
from appinfra.security.masking import SecretMasker, reset_masker


@pytest.fixture(autouse=True)
def reset_global_masker():
    """Reset the global masker before each test."""
    reset_masker()
    yield
    reset_masker()


class TestSecretMaskingFilter:
    """Tests for SecretMaskingFilter class."""

    def test_filter_creation(self):
        """Test filter can be created."""
        filter_instance = SecretMaskingFilter()
        assert filter_instance.masker is not None

    def test_filter_with_custom_masker(self):
        """Test filter with custom masker."""
        masker = SecretMasker(mask="***")
        filter_instance = SecretMaskingFilter(masker=masker)
        assert filter_instance.masker is masker

    def test_filter_masks_message(self):
        """Test filter masks secrets in message."""
        masker = SecretMasker()
        filter_instance = SecretMaskingFilter(masker=masker)

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="password=secret123456789",
            args=(),
            exc_info=None,
        )

        result = filter_instance.filter(record)
        assert result is True
        assert "[MASKED]" in record.msg
        assert "secret123456789" not in record.msg

    def test_filter_masks_tuple_args(self):
        """Test filter masks secrets in tuple args."""
        masker = SecretMasker()
        filter_instance = SecretMaskingFilter(masker=masker)

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Connecting with %s",
            args=("password=secret123456789",),
            exc_info=None,
        )

        filter_instance.filter(record)
        assert "[MASKED]" in record.args[0]

    def test_filter_masks_dict_args(self):
        """Test filter masks secrets in dict args."""
        masker = SecretMasker()
        filter_instance = SecretMaskingFilter(masker=masker)

        # Create record with normal args first, then set dict args
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Config: %(config)s",
            args=(),
            exc_info=None,
        )
        # Set dict args manually to bypass LogRecord validation
        record.args = {"config": "api_key=sk-12345678901234567890"}

        filter_instance.filter(record)
        assert "[MASKED]" in record.args["config"]

    def test_filter_preserves_non_string_args(self):
        """Test filter preserves non-string args."""
        masker = SecretMasker()
        filter_instance = SecretMaskingFilter(masker=masker)

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Count: %d, Value: %s",
            args=(42, "password=secret123456789"),
            exc_info=None,
        )

        filter_instance.filter(record)
        assert record.args[0] == 42
        assert "[MASKED]" in record.args[1]

    def test_filter_always_returns_true(self):
        """Test filter always returns True (allows record through)."""
        filter_instance = SecretMaskingFilter()

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Normal message",
            args=(),
            exc_info=None,
        )

        assert filter_instance.filter(record) is True

    def test_filter_masks_exc_text(self):
        """Test filter masks secrets in exception text."""
        masker = SecretMasker()
        filter_instance = SecretMaskingFilter(masker=masker)

        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname="test.py",
            lineno=1,
            msg="Error occurred",
            args=(),
            exc_info=None,
        )
        # Set exc_text manually (normally set by formatter)
        record.exc_text = "Traceback: password=secret123456789"

        filter_instance.filter(record)
        assert "[MASKED]" in record.exc_text
        assert "secret123456789" not in record.exc_text


class TestAddMaskingFilterToLogger:
    """Tests for add_masking_filter_to_logger function."""

    def test_add_by_name(self):
        """Test adding filter by logger name."""
        filter_instance = add_masking_filter_to_logger("test.add_by_name")
        assert isinstance(filter_instance, SecretMaskingFilter)

    def test_add_by_instance(self):
        """Test adding filter by logger instance."""
        logger = logging.getLogger("test.add_by_instance")
        filter_instance = add_masking_filter_to_logger(logger)
        assert isinstance(filter_instance, SecretMaskingFilter)
        assert filter_instance in logger.filters

    def test_add_with_custom_masker(self):
        """Test adding filter with custom masker."""
        masker = SecretMasker(mask="***")
        logger = logging.getLogger("test.custom_masker")
        filter_instance = add_masking_filter_to_logger(logger, masker=masker)
        assert filter_instance.masker is masker
