# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for the configuration module's helper functions.
"""

from pathlib import Path
from unittest.mock import Mock

from appinfra.config.config import (
    _preserve_config_attributes,
    _restore_config_attributes,
)

# =============================================================================
# Test Helper Functions
# =============================================================================


class TestHelperFunctions:
    """Test module-level helper functions."""

    def test_preserve_config_attributes(self):
        """Test preserving config attributes."""
        mock_config = Mock()
        mock_config._enable_env_overrides = False
        mock_config._env_prefix = "TEST_"
        mock_config._merge_strategy = "merge"
        mock_config._allowed_paths = ["~/.myapp.yaml"]
        mock_config._origin_override = Path("/pkg")

        attrs = _preserve_config_attributes(mock_config)

        assert attrs["enable_env_overrides"] is False
        assert attrs["env_prefix"] == "TEST_"
        assert attrs["merge_strategy"] == "merge"
        assert attrs["allowed_paths"] == ["~/.myapp.yaml"]
        assert attrs["origin_override"] == Path("/pkg")

    def test_preserve_config_attributes_with_defaults(self):
        """Test preserving config attributes with missing attributes."""
        mock_config = Mock(spec=[])  # Empty spec - no attributes

        attrs = _preserve_config_attributes(mock_config)

        # Should return defaults
        assert attrs["enable_env_overrides"] is True
        assert attrs["env_prefix"] == "INFRA_"
        assert attrs["merge_strategy"] == "replace"
        assert attrs["allowed_paths"] is None
        assert attrs["origin_override"] is None

    def test_restore_config_attributes(self):
        """Test restoring config attributes."""
        mock_config = Mock()
        attrs = {
            "enable_env_overrides": False,
            "env_prefix": "CUSTOM_",
            "merge_strategy": "deep",
            "allowed_paths": ["~/.myapp.yaml"],
            "origin_override": Path("/pkg"),
        }

        _restore_config_attributes(mock_config, attrs)

        assert mock_config._enable_env_overrides is False
        assert mock_config._env_prefix == "CUSTOM_"
        assert mock_config._merge_strategy == "deep"
        assert mock_config._allowed_paths == ["~/.myapp.yaml"]
        assert mock_config._origin_override == Path("/pkg")
