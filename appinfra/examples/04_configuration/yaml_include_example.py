#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
YAML File Inclusion Example

This example demonstrates how to use the !include tag to organize configuration
across multiple YAML files, making large configurations more maintainable.

What This Example Demonstrates:
- Basic file inclusion with !include tag
- Relative and absolute path resolution
- Nested/recursive includes
- Include with variable substitution
- Multiple includes in one file
- Circular dependency detection
- Real-world organization patterns
- Environment-specific configuration

Running the Example:
    # From the infra project root
    ~/.venv/bin/python examples/04_configuration/yaml_include_example.py

    # Or from examples/04_configuration/
    ../../.venv/bin/python yaml_include_example.py

Expected Output:
    The console will show various YAML include scenarios being demonstrated
    with clear explanations of what's happening at each step.

Key Features Demonstrated:
- File Inclusion: Split large configs into modular files
- Path Resolution: Relative paths resolved from including file's directory
- Recursive Includes: Files can include other files (A → B → C)
- Circular Detection: Automatic detection of circular includes
- Variable Substitution: Works seamlessly across included files
- Organization: Best practices for structuring configuration files

Example Files:
    All example YAML files are located in examples/04_configuration/etc/
    You can inspect these files to see the actual !include syntax and structure.
"""

# Add the project root to the path (examples/04_configuration/file.py -> project root is 2 levels up)
import pathlib
import sys
from pathlib import Path

import yaml

project_root = str(pathlib.Path(__file__).resolve().parents[3])
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from appinfra import Config

# Get the etc directory path
ETC_DIR = pathlib.Path(__file__).parent / "etc"


def print_file_content(file_path: Path, max_lines: int | None = None):
    """Print file content with line numbers for demonstration."""
    with open(file_path) as f:
        lines = f.readlines()
        if max_lines:
            lines = lines[:max_lines]
        for i, line in enumerate(lines, 1):
            print(f"    {i:2d} | {line}", end="")
        if max_lines and len(lines) == max_lines:
            print("    ...")


def demo_basic_include():
    """Demonstrate basic file inclusion."""
    print("=== Basic File Inclusion ===")
    print(f"\nFiles used: {ETC_DIR}/01_basic_main.yaml and 01_basic_database.yaml")
    print("\nMain file (01_basic_main.yaml):")
    print_file_content(ETC_DIR / "01_basic_main.yaml")

    print("\nIncluded file (01_basic_database.yaml):")
    print_file_content(ETC_DIR / "01_basic_database.yaml")

    # Load and display
    config = Config(str(ETC_DIR / "01_basic_main.yaml"))

    print("\nResolved configuration:")
    print(f"  app_name: {config.get('app_name')}")
    print(f"  database.host: {config.get('database.host')}")
    print(f"  database.port: {config.get('database.port')}")
    print(f"  database.user: {config.get('database.user')}")
    print(f"  database.pool_size: {config.get('database.pool_size')}")
    print(f"  debug: {config.get('debug')}")
    print("\n✓ Basic inclusion working correctly")


def demo_nested_includes():
    """Demonstrate nested/recursive includes."""
    print("\n=== Nested/Recursive Includes ===")
    print("\nFiles used: 02_nested_*.yaml (4 files)")
    print("\nInclude chain: main → level1 → level2 → level3")

    print("\nMain file (02_nested_main.yaml):")
    print_file_content(ETC_DIR / "02_nested_main.yaml")

    # Load and display
    config = Config(str(ETC_DIR / "02_nested_main.yaml"))

    print("\nResolved configuration:")
    print(f"  config.value: {config.get('config.value')}")
    print(f"  config.level2.value: {config.get('config.level2.value')}")
    print(f"  config.level2.level3.value: {config.get('config.level2.level3.value')}")
    print("\n✓ Nested includes work correctly (4 levels deep)")


def demo_variable_substitution():
    """Demonstrate include with variable substitution."""
    print("\n=== Include with Variable Substitution ===")
    print("\nFiles used: 03_variables_*.yaml")

    print("\nMain file defines variables (03_variables_main.yaml):")
    print_file_content(ETC_DIR / "03_variables_main.yaml")

    print("\nIncluded file uses variables (03_variables_databases.yaml):")
    print_file_content(ETC_DIR / "03_variables_databases.yaml")

    # Load and display
    config = Config(str(ETC_DIR / "03_variables_main.yaml"))

    print("\nResolved configuration:")
    print(f"  dbs.main.url: {config.get('dbs.main.url')}")
    print(f"  dbs.test.url: {config.get('dbs.test.url')}")
    print("\n✓ Variable substitution works across file boundaries")


def demo_multiple_includes():
    """Demonstrate multiple includes in one file."""
    print("\n=== Multiple Includes in One File ===")
    print("\nFiles used: 04_multiple_*.yaml (4 files)")

    print("\nMain file includes 3 separate files (04_multiple_main.yaml):")
    print_file_content(ETC_DIR / "04_multiple_main.yaml")

    # Load and display
    config = Config(str(ETC_DIR / "04_multiple_main.yaml"))

    print("\nResolved configuration:")
    print(f"  app_name: {config.get('app_name')}")
    print(f"  database.host: {config.get('database.host')}")
    print(f"  database.port: {config.get('database.port')}")
    print(f"  cache.host: {config.get('cache.host')}")
    print(f"  cache.port: {config.get('cache.port')}")
    print(f"  logging.level: {config.get('logging.level')}")
    print("\n✓ Multiple includes in one file work correctly")


def _print_organized_structure():
    """Print the directory structure for organized config demo."""
    print("\nDirectory structure:")
    print("  etc/")
    print("  ├── 05_organized_main.yaml")
    print("  ├── database/")
    print("  │   ├── config.yaml")
    print("  │   ├── connection.yaml")
    print("  │   └── pool.yaml")
    print("  └── logging/")
    print("      ├── config.yaml")
    print("      └── handlers.yaml")


def demo_organized_config():
    """Demonstrate real-world organized configuration."""
    print("\n=== Real-World Organized Configuration ===")
    print(
        "\nFiles used: 05_organized_main.yaml + database/ and logging/ subdirectories"
    )

    _print_organized_structure()

    print("\nMain file (05_organized_main.yaml):")
    print_file_content(ETC_DIR / "05_organized_main.yaml")

    config = Config(str(ETC_DIR / "05_organized_main.yaml"))

    print("\nResolved configuration:")
    print(f"  app_name: {config.get('app_name')}")
    print(f"  database.connection.host: {config.get('database.connection.host')}")
    print(f"  database.connection.port: {config.get('database.connection.port')}")
    print(f"  database.pool.pool_size: {config.get('database.pool.pool_size')}")
    print(f"  database.pool.max_overflow: {config.get('database.pool.max_overflow')}")
    print(f"  logging.level: {config.get('logging.level')}")
    print(
        f"  logging.handlers.console.enabled: {config.get('logging.handlers.console.enabled')}"
    )
    print("\n✓ Organized configuration structure works well")


def _print_env_structure():
    """Print the directory structure for environment-specific config demo."""
    print("\nDirectory structure:")
    print("  etc/")
    print("  ├── common.yaml (shared settings)")
    print("  ├── 06_env_dev.yaml")
    print("  ├── 06_env_prod.yaml")
    print("  └── env/")
    print("      ├── dev/database.yaml")
    print("      └── prod/database.yaml")


def _show_dev_config():
    """Load and display development configuration."""
    print("\nDevelopment config (06_env_dev.yaml):")
    print_file_content(ETC_DIR / "06_env_dev.yaml")

    dev_config = Config(str(ETC_DIR / "06_env_dev.yaml"))
    print("\nResolved development configuration:")
    print(f"  common.app_name: {dev_config.get('common.app_name')}")
    print(f"  environment: {dev_config.get('environment')}")
    print(f"  database.host: {dev_config.get('database.host')}")
    print(f"  database.user: {dev_config.get('database.user')}")
    print(f"  database.debug: {dev_config.get('database.debug')}")


def _show_prod_config():
    """Load and display production configuration."""
    print("\nProduction config (06_env_prod.yaml):")
    print_file_content(ETC_DIR / "06_env_prod.yaml")

    prod_config = Config(str(ETC_DIR / "06_env_prod.yaml"))
    print("\nResolved production configuration:")
    print(f"  common.app_name: {prod_config.get('common.app_name')}")
    print(f"  environment: {prod_config.get('environment')}")
    print(f"  database.host: {prod_config.get('database.host')}")
    print(f"  database.user: {prod_config.get('database.user')}")
    print(f"  database.debug: {prod_config.get('database.debug')}")


def demo_environment_specific():
    """Demonstrate environment-specific configuration."""
    print("\n=== Environment-Specific Configuration ===")
    print("\nFiles used: 06_env_*.yaml + env/dev/ and env/prod/")

    _print_env_structure()
    _show_dev_config()
    _show_prod_config()

    print("\n✓ Environment-specific configuration pattern demonstrated")


def demo_circular_detection():
    """Demonstrate circular dependency detection."""
    print("\n=== Circular Dependency Detection ===")
    print("\nFiles used: 07_circular_a.yaml and 07_circular_b.yaml")

    print("\nFile A includes File B (07_circular_a.yaml):")
    print_file_content(ETC_DIR / "07_circular_a.yaml")

    print("\nFile B includes File A (07_circular_b.yaml):")
    print_file_content(ETC_DIR / "07_circular_b.yaml")

    print("\nAttempting to load (this will fail with circular dependency error)...")

    try:
        config = Config(str(ETC_DIR / "07_circular_a.yaml"))
        print("ERROR: Should have detected circular dependency!")
    except yaml.YAMLError as e:
        print("\n✓ Circular dependency detected correctly:")
        print(f"  {str(e)}")


def _print_path_practices():
    """Print practices 1-3."""
    print("\n1. Use relative paths for portability:")
    print("   database: !include './database.yaml'  # Good")
    print("   database: !include '/absolute/path.yaml'  # Avoid")

    print("\n2. Organize by purpose (see etc/ directory):")
    print("   etc/")
    print("     database/")
    print("       connection.yaml")
    print("       pool.yaml")
    print("     logging/")
    print("       handlers.yaml")

    print("\n3. Keep includes shallow (2-3 levels max):")
    print("   main.yaml → module.yaml → settings.yaml  # Good")
    print("   Too deep nesting makes debugging harder")


def _print_naming_practices():
    """Print practices 4-7."""
    print("\n4. Use descriptive filenames:")
    print("   database_connection.yaml  # Clear")
    print("   db.yaml                   # Unclear")

    print("\n5. Document includes with comments:")
    print("   # Database configuration (see config/database/)")
    print("   database: !include './config/database.yaml'")

    print("\n6. Combine with variable substitution:")
    print("   Define variables in main file, use in includes")
    print("   (See 03_variables_*.yaml for example)")

    print("\n7. Separate by environment:")
    print("   env/dev/database.yaml")
    print("   env/prod/database.yaml")
    print("   (See 06_env_*.yaml for example)")


def demo_best_practices():
    """Demonstrate best practices for using includes."""
    print("\n=== Best Practices for YAML Includes ===")
    _print_path_practices()
    _print_naming_practices()


def _print_summary():
    """Print the demo completion summary."""
    print("\n=== Demo Complete ===")
    print("YAML file inclusion functionality has been demonstrated.")
    print("\nKey takeaways:")
    print("✓ Use !include tag to split configuration into modular files")
    print("✓ Relative paths resolved from including file's directory")
    print("✓ Supports nested includes (files can include other files)")
    print("✓ Circular dependencies automatically detected")
    print("✓ Variable substitution works across file boundaries")
    print("✓ Organize config by purpose (database/, logging/, etc.)")
    print("✓ Great for environment-specific configuration (dev/prod)")
    print(f"\nInspect the example files in {ETC_DIR}/ to learn more!")
    print("For detailed documentation, see etc/README.md")


def _run_all_demos():
    """Run all demonstration functions."""
    demo_basic_include()
    demo_nested_includes()
    demo_variable_substitution()
    demo_multiple_includes()
    demo_organized_config()
    demo_environment_specific()
    demo_circular_detection()
    demo_best_practices()


def main():
    """Main function to run the YAML include demos."""
    print("=== YAML File Inclusion Example ===")
    print("This example demonstrates how to use !include tags to organize")
    print("configuration across multiple YAML files.")
    print(f"\nAll example files are in: {ETC_DIR}/")
    print("You can inspect these files to see the actual YAML structure.\n")

    try:
        _run_all_demos()
        _print_summary()
    except Exception as e:
        print(f"\nDemo failed: {e}")
        import traceback

        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
