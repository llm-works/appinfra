# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""YAML files with includes, shared by the unit and integration YAML loader tests."""

from pathlib import Path

import pytest


@pytest.fixture
def yaml_files_dir(temp_dir: Path):
    """Create a directory with test YAML files."""
    # Main config
    (temp_dir / "main.yaml").write_text(
        """
app:
  name: main_app
  version: 1.0.0
database: !include "./db.yaml"
"""
    )

    # Database config
    (temp_dir / "db.yaml").write_text(
        """
host: localhost
port: 5432
name: test_db
"""
    )

    # Nested include
    (temp_dir / "nested.yaml").write_text(
        """
level1: !include "./level2.yaml"
"""
    )

    (temp_dir / "level2.yaml").write_text(
        """
level2: !include "./level3.yaml"
"""
    )

    (temp_dir / "level3.yaml").write_text(
        """
value: "deep"
"""
    )

    # Circular includes
    (temp_dir / "circular_a.yaml").write_text(
        """
data: !include "./circular_b.yaml"
"""
    )

    (temp_dir / "circular_b.yaml").write_text(
        """
data: !include "./circular_a.yaml"
"""
    )

    return temp_dir
