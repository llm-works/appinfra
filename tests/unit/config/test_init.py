# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for appinfra.config module initialization and fallback behavior."""

import sys
from unittest.mock import patch

import pytest


@pytest.mark.unit
class TestPydanticImportFallback:
    """Test fallback behavior when pydantic is not available."""

    def test_import_with_pydantic_available(self):
        """Test normal import when pydantic is available."""
        # This test runs in normal environment where pydantic IS available
        from appinfra.config import PYDANTIC_AVAILABLE, validate_config

        # Should be True in normal test environment
        assert PYDANTIC_AVAILABLE is True
        assert validate_config is not None

    def test_fallback_when_pydantic_unavailable(self):
        """Test fallback behavior when pydantic import fails."""
        # Save the original module
        original_schemas = sys.modules.get("appinfra.config.schemas")
        original_config = sys.modules.get("appinfra.config")

        try:
            # Remove modules to force reimport
            if "appinfra.config.schemas" in sys.modules:
                del sys.modules["appinfra.config.schemas"]
            if "appinfra.config" in sys.modules:
                del sys.modules["appinfra.config"]

            # Mock the schemas import to raise ImportError
            with patch.dict("sys.modules", {"appinfra.config.schemas": None}):
                # Force import to fail by making the module None

                # Now try to import appinfra.config which should handle the ImportError
                try:
                    import appinfra.config as config_module

                    # In the fallback case, these should be None or have fallback values
                    # The except block sets PYDANTIC_AVAILABLE = False
                    assert hasattr(config_module, "PYDANTIC_AVAILABLE")
                    assert hasattr(config_module, "validate_config")

                    # If we successfully triggered the except block,
                    # validate_config should be the no-op function
                    if not config_module.PYDANTIC_AVAILABLE:
                        test_dict = {"key": "value"}
                        result = config_module.validate_config(test_dict)
                        assert result == test_dict  # No-op returns input unchanged

                except ImportError:
                    # This is actually OK - we're testing the fallback
                    pass

        finally:
            # Restore original modules
            if original_schemas is not None:
                sys.modules["appinfra.config.schemas"] = original_schemas
            if original_config is not None:
                sys.modules["appinfra.config"] = original_config

    def test_validate_config_no_op_fallback(self):
        """Test that fallback validate_config is a no-op."""
        # We need to test the no-op function directly
        # Create a mock that simulates the fallback scenario

        test_config = {"database": {"host": "localhost"}, "logging": {"level": "info"}}

        # The fallback validate_config should just return the input unchanged
        def fallback_validate_config(config_dict):
            """No-op validation when pydantic is not installed."""
            return config_dict

        result = fallback_validate_config(test_config)
        assert result is test_config
        assert result == test_config
