# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for appinfra.config's optional schema exports.

The behavior without pydantic is tested in a clean interpreter:
tests/integration/config/test_schemas_optional.py.
"""

import pytest


class TestPydanticExports:
    """The schema models are exported when pydantic is installed."""

    def test_import_with_pydantic_available(self):
        """With pydantic, appinfra.config exports the validator and the models."""
        pytest.importorskip("pydantic")
        import appinfra.config as config

        assert config.PYDANTIC_AVAILABLE is True
        assert config.validate_config is not None
        assert {
            "InfraConfig",
            "LoggingConfig",
            "DatabaseConfig",
            "validate_config",
        } <= set(config.__all__)
