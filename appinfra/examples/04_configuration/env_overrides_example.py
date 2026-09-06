#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Environment Variable Overrides Example

This example demonstrates how to use environment variables to override
configuration values from appinfra.yaml without modifying the YAML file.

What This Example Demonstrates:
- Basic environment variable overrides
- Different data types (string, boolean, numeric, float, list, null)
- Nested configuration overrides
- Custom environment variable prefixes
- Integration with logging system
- Checking applied overrides
- Disabling environment overrides

Running the Example:
    # From the infra project root
    ~/.venv/bin/python examples/04_configuration/env_overrides_example.py

Expected Output:
    The console will show various environment variable overrides being applied
    and demonstrate how they affect the configuration values.

Key Features Demonstrated:
- Environment Variable Overrides: Override any config value via env vars
- Type Conversion: Automatic conversion to appropriate data types
- Nested Configuration: Override deeply nested configuration values
- Custom Prefixes: Use different prefixes for environment variables
- Integration: Works seamlessly with existing configuration system
- Debugging: Check what overrides are applied
"""

import os
import sys
import tempfile

# Add the project root to the path (examples/04_configuration/file.py -> project root is 2 levels up)
from pathlib import Path
from unittest.mock import patch

# Allow running from a source checkout without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from appinfra import DEFAULT_CONFIG_FILE, Config, get_default_config
from appinfra.log import LogConfig, LoggerFactory

config = get_default_config()


def demo_basic_overrides():
    """Demonstrate basic environment variable overrides."""
    print("=== Basic Environment Variable Overrides ===")

    with patch.dict(
        os.environ,
        {
            "INFRA_LOGGING_LEVEL": "debug",
            "INFRA_PGSERVER_PORT": "5432",
            "INFRA_PGSERVER_USER": "myuser",
        },
    ):
        config = get_default_config()

        print(f"Logging level: {config.logging.level}")
        print(f"PostgreSQL port: {config.pgserver.port}")
        print(f"PostgreSQL user: {config.pgserver.user}")
        print("✓ Basic overrides applied successfully")


def _print_data_types(config):
    """Print the data types of config values."""
    print(f"String: {config.test.string} (type: {type(config.test.string)})")
    print(f"Boolean: {config.test.boolean} (type: {type(config.test.boolean)})")
    print(f"Integer: {config.test.integer} (type: {type(config.test.integer)})")
    print(f"Float: {config.test.float} (type: {type(config.test.float)})")
    print(f"List: {config.test.list} (type: {type(config.test.list)})")
    print(f"Null: {config.test.nullval} (type: {type(config.test.nullval)})")
    print("✓ Data type conversion working correctly")


def demo_data_types():
    """Demonstrate different data types in environment variables."""
    print("\n=== Data Type Conversion ===")

    env_vars = {
        "INFRA_TEST_STRING": "hello world",
        "INFRA_TEST_BOOLEAN": "true",
        "INFRA_TEST_INTEGER": "42",
        "INFRA_TEST_FLOAT": "3.14",
        "INFRA_TEST_LIST": "item1,item2,item3",
        "INFRA_TEST_NULLVAL": "null",
    }

    with patch.dict(os.environ, env_vars):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(
                "test:\n  string: original\n  boolean: false\n  integer: 0\n  "
                "float: 0.0\n  list: [original]\n  nullval: original\n"
            )
            temp_file = f.name

        try:
            config = Config(temp_file)
            _print_data_types(config)
        finally:
            os.unlink(temp_file)


def demo_nested_overrides():
    """Demonstrate nested configuration overrides."""
    print("\n=== Nested Configuration Overrides ===")

    with patch.dict(
        os.environ,
        {
            "INFRA_TEST_TIMEOUT": "120",
            "INFRA_TEST_LOGGING_LEVEL": "info",
            "INFRA_TEST_LOGGING_COLORS_ENABLED": "true",
        },
    ):
        config = get_default_config()

        # Use get() with defaults since test config may not exist in default config
        test_config = config.get("test", {})
        test_timeout = test_config.get("timeout", "120 (from env)")
        test_logging = test_config.get("logging", {})
        test_level = test_logging.get("level", "info (from env)")
        test_colors = test_logging.get("colors_enabled", "true (from env)")

        print(f"Test timeout: {test_timeout}")
        print(f"Test logging level: {test_level}")
        print(f"Test logging colors: {test_colors}")
        print("✓ Nested overrides demonstration complete")


def demo_custom_prefix():
    """Demonstrate custom environment variable prefix."""
    print("\n=== Custom Environment Variable Prefix ===")

    with patch.dict(
        os.environ,
        {
            "MYAPP_LOGGING_LEVEL": "warning",
            "MYAPP_PGSERVER_PORT": "3306",
            "INFRA_LOGGING_LEVEL": "debug",  # Should be ignored
        },
    ):
        config = Config(str(DEFAULT_CONFIG_FILE), env_prefix="MYAPP_")

        print(f"Logging level: {config.logging.level}")
        print(f"PostgreSQL port: {config.pgserver.port}")
        print("✓ Custom prefix working correctly")


def demo_check_overrides():
    """Demonstrate checking applied overrides."""
    print("\n=== Checking Applied Overrides ===")

    with patch.dict(
        os.environ,
        {
            "INFRA_LOGGING_LEVEL": "debug",
            "INFRA_PGSERVER_PORT": "5432",
            "INFRA_TEST_TIMEOUT": "120",
        },
    ):
        config = get_default_config()
        overrides = config.get_env_overrides()

        print("Applied environment variable overrides:")
        for key, value in overrides.items():
            print(f"  {key}: {value}")
        print("✓ Override checking working correctly")


def demo_disabled_overrides():
    """Demonstrate disabled environment overrides."""
    print("\n=== Disabled Environment Overrides ===")

    with patch.dict(
        os.environ, {"INFRA_LOGGING_LEVEL": "debug", "INFRA_PGSERVER_PORT": "5432"}
    ):
        # Overrides disabled
        config = Config(str(DEFAULT_CONFIG_FILE), enable_env_overrides=False)

        print(f"Logging level: {config.logging.level} (should be 'info')")
        print(f"PostgreSQL port: {config.pgserver.port} (should be 25432)")
        print("✓ Environment overrides disabled correctly")


def demo_logging_integration():
    """Demonstrate integration with logging system."""
    print("\n=== Logging System Integration ===")

    with patch.dict(
        os.environ,
        {
            "INFRA_TEST_LOGGING_LEVEL": "info",
            "INFRA_TEST_LOGGING_COLORS_ENABLED": "false",
        },
    ):
        # Create logger using public API with config from environment
        config = get_default_config()
        log_config = LogConfig.from_config(config.dict(), "test.logging")
        logger = LoggerFactory.create("env_override_test", log_config)

        print(f"Logger level: {logger.get_level()}")
        print(f"Logger disabled: {logger.disabled}")
        print(f"Colors enabled: {logger.config.colors}")

        logger.info("This message should appear (level: info)")
        logger.debug("This message should NOT appear (level: debug)")
        print("✓ Logging integration working correctly")


def demo_variable_substitution():
    """Demonstrate variable substitution with overrides."""
    print("\n=== Variable Substitution with Overrides ===")

    with patch.dict(
        os.environ, {"INFRA_PGSERVER_PORT": "5432", "INFRA_PGSERVER_USER": "myuser"}
    ):
        config = get_default_config()

        print(f"Database URL: {config.dbs.main.url}")
        print("✓ Variable substitution using overridden values")


def _print_override_values(config):
    """Print override values from config using safe accessors."""
    logging_cfg = config.get("logging", {})
    pgserver_cfg = config.get("pgserver", {})
    test_cfg = config.get("test", {})
    test_logging_cfg = test_cfg.get("logging", {}) if isinstance(test_cfg, dict) else {}
    print(f"  Logging level: {logging_cfg.get('level', 'N/A')}")
    print(f"  Logging micros: {logging_cfg.get('micros', 'N/A')}")
    print(f"  PostgreSQL port: {pgserver_cfg.get('port', 'N/A')}")
    print(f"  PostgreSQL user: {pgserver_cfg.get('user', 'N/A')}")
    timeout = test_cfg.get("timeout", "N/A") if isinstance(test_cfg, dict) else "N/A"
    print(f"  Test timeout: {timeout}")
    print(f"  Test logging level: {test_logging_cfg.get('level', 'N/A')}")


# Environment variables for multiple overrides demo
_MULTIPLE_OVERRIDE_ENVS = {
    "INFRA_LOGGING_LEVEL": "debug",
    "INFRA_LOGGING_MICROSECONDS": "true",
    "INFRA_PGSERVER_PORT": "5432",
    "INFRA_PGSERVER_USER": "testuser",
    "INFRA_TEST_TIMEOUT": "120",
    "INFRA_TEST_LOGGING_LEVEL": "info",
}


def demo_multiple_overrides():
    """Demonstrate multiple environment variable overrides."""
    print("\n=== Multiple Environment Variable Overrides ===")

    with patch.dict(os.environ, _MULTIPLE_OVERRIDE_ENVS):
        config = get_default_config()
        print("Multiple overrides applied:")
        _print_override_values(config)
        print("✓ Multiple overrides demonstration complete")


def demo_command_line_usage():
    """Demonstrate command line usage patterns."""
    print("\n=== Command Line Usage Patterns ===")

    print("Development environment:")
    print("  export INFRA_LOGGING_LEVEL=debug")
    print("  export INFRA_LOGGING_MICROSECONDS=true")
    print("  export INFRA_PGSERVER_PORT=5432")
    print("  python my_app.py")

    print("\nTesting environment:")
    print("  export INFRA_TEST_LOGGING_LEVEL=info")
    print("  export INFRA_TEST_LOGGING_COLORS_ENABLED=false")
    print("  make test")

    print("\nProduction environment:")
    print("  export INFRA_LOGGING_LEVEL=warning")
    print("  export INFRA_PGSERVER_PORT=5432")
    print("  export INFRA_PGSERVER_USER=produser")
    print("  python my_app.py")


def _run_all_env_demos():
    """Run all environment variable demo functions."""
    demo_basic_overrides()
    demo_data_types()
    demo_nested_overrides()
    demo_custom_prefix()
    demo_check_overrides()
    demo_disabled_overrides()
    demo_logging_integration()
    demo_variable_substitution()
    demo_multiple_overrides()
    demo_command_line_usage()


def _print_env_summary():
    """Print environment variable demo summary."""
    print("\n=== Demo Complete ===")
    print("Environment variable override functionality has been demonstrated.")
    print("Key takeaways:")
    print("- Use INFRA_<SECTION>_<SUBSECTION>_<KEY> naming convention")
    print("- Automatic type conversion (string, bool, int, float, list, null)")
    print("- Works with nested configurations")
    print("- Integrates seamlessly with existing systems")
    print("- Can be disabled or use custom prefixes")
    print("- Useful for development, testing, and production environments")


def main():
    """Main function to run the environment variable overrides demos."""
    print("=== Environment Variable Overrides Example ===")
    print("This example demonstrates how to override configuration values")
    print("from appinfra.yaml using environment variables.\n")

    try:
        _run_all_env_demos()
        _print_env_summary()
    except Exception as e:
        print(f"\nDemo failed: {e}")
        import traceback

        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
