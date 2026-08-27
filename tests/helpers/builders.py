# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Test data builders for creating complex test objects.

Provides builder classes that make it easy to create test data
with sensible defaults and easy customization.
"""

from typing import Any

from appinfra.config import Config
from appinfra.dot_dict import DotDict


class ConfigBuilder:
    """Builder for Config objects with sensible test defaults."""

    def __init__(self):
        self._data = {
            "app": {
                "name": "test_app",
                "version": "1.0.0",
                "debug": False,
            },
        }

    def with_app_name(self, name: str) -> "ConfigBuilder":
        """Set application name."""
        self._data["app"]["name"] = name
        return self

    def with_database(
        self, host: str = "localhost", port: int = 5432, database: str = "test_db"
    ) -> "ConfigBuilder":
        """Add database configuration."""
        self._data["database"] = {
            "host": host,
            "port": port,
            "database": database,
        }
        return self

    def with_logging(
        self, level: str = "info", format_string: str | None = None
    ) -> "ConfigBuilder":
        """Add logging configuration."""
        self._data["logging"] = {
            "level": level,
        }
        if format_string:
            self._data["logging"]["format"] = format_string
        return self

    def with_custom(self, key: str, value: Any) -> "ConfigBuilder":
        """Add custom configuration key-value."""
        self._data[key] = value
        return self

    def build(self) -> Config:
        """Build the Config object."""
        return Config(self._data)

    def build_dict(self) -> dict[str, Any]:
        """Build as plain dictionary."""
        return self._data.copy()


class DotDictBuilder:
    """Builder for DotDict objects."""

    def __init__(self):
        self._data = {}

    def with_nested(self, path: str, value: Any) -> "DotDictBuilder":
        """
        Set a nested value using dot notation.

        Args:
            path: Dot-separated path (e.g., "a.b.c")
            value: Value to set

        Returns:
            Self for chaining
        """
        keys = path.split(".")
        current = self._data

        for key in keys[:-1]:
            if key not in current:
                current[key] = {}
            current = current[key]

        current[keys[-1]] = value
        return self

    def with_list(self, key: str, items: list[Any]) -> "DotDictBuilder":
        """Add a list value."""
        self._data[key] = items
        return self

    def build(self) -> DotDict:
        """Build the DotDict object."""
        return DotDict(self._data)


class YAMLConfigBuilder:
    """Builder for YAML configuration strings."""

    def __init__(self):
        self._sections = []

    def with_app_section(
        self, name: str = "test_app", version: str = "1.0.0"
    ) -> "YAMLConfigBuilder":
        """Add app section."""
        self._sections.append(
            f"""
app:
  name: {name}
  version: {version}
"""
        )
        return self

    def with_database_section(
        self, host: str = "localhost", port: int = 5432
    ) -> "YAMLConfigBuilder":
        """Add database section."""
        self._sections.append(
            f"""
database:
  host: {host}
  port: {port}
"""
        )
        return self

    def with_custom_section(
        self, section_name: str, content: str
    ) -> "YAMLConfigBuilder":
        """Add custom YAML section."""
        self._sections.append(f"\n{section_name}:\n{content}\n")
        return self

    def build(self) -> str:
        """Build the YAML string."""
        return "\n".join(self._sections)
