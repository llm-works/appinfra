# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Configuration fixtures for testing.

Provides fixtures for config objects, YAML files, and configuration utilities.
"""

from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest

from appinfra.config import Config
from appinfra.dot_dict import DotDict


@pytest.fixture
def sample_config() -> Config:
    """
    Provide a sample Config object for testing.

    Returns:
        Config: Sample configuration
    """
    return Config(
        {
            "app": {
                "name": "test_app",
                "version": "1.0.0",
                "debug": True,
            },
            "database": {
                "host": "localhost",
                "port": 5432,
            },
            "logging": {
                "level": "info",
            },
        }
    )


@pytest.fixture
def sample_dot_dict() -> DotDict:
    """
    Provide a sample DotDict object for testing.

    Returns:
        DotDict: Sample dot-accessible dictionary
    """
    return DotDict(
        {
            "nested": {
                "value": 42,
                "deep": {
                    "key": "value",
                },
            },
            "list": [1, 2, 3],
            "string": "test",
        }
    )


@pytest.fixture
def temp_yaml_file(temp_dir: Path) -> Generator[Path, None, None]:
    """
    Create a temporary YAML config file for testing.

    Args:
        temp_dir: Temporary directory fixture

    Yields:
        Path: Path to temporary YAML file
    """
    yaml_content = """
app:
  name: test_app
  version: 1.0.0
  debug: true

database:
  host: localhost
  port: 5432
  name: test_db

logging:
  level: info
  format: "%(message)s"
"""
    yaml_file = temp_dir / "config.yaml"
    yaml_file.write_text(yaml_content)
    yield yaml_file


@pytest.fixture
def malformed_yaml_file(temp_dir: Path) -> Generator[Path, None, None]:
    """
    Create a malformed YAML file for testing error handling.

    Args:
        temp_dir: Temporary directory fixture

    Yields:
        Path: Path to malformed YAML file
    """
    yaml_content = """
app:
  name: test_app
  invalid: [unclosed list
"""
    yaml_file = temp_dir / "malformed.yaml"
    yaml_file.write_text(yaml_content)
    yield yaml_file


@pytest.fixture
def config_with_env_vars() -> dict[str, Any]:
    """
    Provide a config dict with environment variable references.

    Returns:
        dict: Configuration with ${ENV_VAR} placeholders
    """
    return {
        "database": {
            "host": "${DB_HOST}",
            "port": "${DB_PORT}",
            "password": "${DB_PASSWORD}",
        },
        "api": {
            "key": "${API_KEY}",
        },
    }
