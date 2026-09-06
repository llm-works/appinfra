#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Location Color Configuration Example

This example demonstrates how to configure custom colors for code location
display in log messages. By default, code locations ([file.py:42]) are shown
in BLACK, but you can customize this to any ANSI color.

Running the Example:
    ~/.venv/bin/python examples/03_logging/location_color_example.py

Expected Output:
    The console will show log messages with code locations in different colors:
    - Default BLACK color
    - CYAN color
    - Custom gray level (medium gray)

Key Features Demonstrated:
- Default location color (BLACK)
- Custom location color using ColorManager.CYAN
- Custom location color using gray levels
- Using .with_location_color() builder method
- Configuration via LogConfig.from_params()
"""

import sys
from pathlib import Path

# Allow running from a source checkout without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from appinfra.log.builder import LoggingBuilder
from appinfra.log.colors import ColorManager
from appinfra.log.config import LogConfig
from appinfra.log.factory import LoggerFactory


def demo_default_location_color():
    """Demonstrate default location color (BLACK)."""
    print("=== Default Location Color (BLACK) ===\n")

    logger = (
        LoggingBuilder("demo.default")
        .with_level("info")
        .with_location(1)  # Show file location
        .with_console_handler()
        .build()
    )

    logger.info("This uses the default BLACK color for location")
    logger.warning("Location is shown in BLACK by default")
    print()


def demo_cyan_location_color():
    """Demonstrate CYAN location color."""
    print("=== CYAN Location Color ===\n")

    logger = (
        LoggingBuilder("demo.cyan")
        .with_level("info")
        .with_location(1)
        .with_location_color(ColorManager.CYAN)  # Set location color to CYAN
        .with_console_handler()
        .build()
    )

    logger.info("Location is now shown in CYAN", extra={"color": "cyan"})
    logger.warning("CYAN stands out better than black", extra={"color": "cyan"})
    print()


def demo_gray_location_color():
    """Demonstrate custom gray level for location color."""
    print("=== Gray Level Location Color ===\n")

    # Gray levels range from 0 (darkest) to 23 (lightest)
    # Level 12 is a medium gray that provides good contrast
    gray_color = ColorManager.create_gray_level(12)

    logger = (
        LoggingBuilder("demo.gray")
        .with_level("info")
        .with_location(1)
        .with_location_color(gray_color)  # Use medium gray
        .with_console_handler()
        .build()
    )

    logger.info("Location shown in medium gray (level 12)", extra={"color": "gray-12"})
    logger.warning("Gray provides subtle contrast", extra={"color": "gray-12"})
    print()


def demo_multiple_colors():
    """Demonstrate multiple loggers with different location colors."""
    print("=== Multiple Loggers with Different Location Colors ===\n")

    # Create loggers with different location colors
    colors = [
        ("BLACK", ColorManager.BLACK),
        ("CYAN", ColorManager.CYAN),
        ("YELLOW", ColorManager.YELLOW),
        ("MAGENTA", ColorManager.MAGENTA),
        ("GRAY-9", ColorManager.create_gray_level(9)),
        ("GRAY-15", ColorManager.create_gray_level(15)),
    ]

    for name, color in colors:
        logger = (
            LoggingBuilder(f"demo.{name.lower()}")
            .with_level("info")
            .with_location(1)
            .with_location_color(color)
            .with_console_handler()
            .build()
        )
        logger.info(f"Location color: {name}")

    print()


def demo_config_dict():
    """Demonstrate configuration via LogConfig.from_params()."""
    print("=== Configuration via LogConfig ===\n")

    # Create logger using LogConfig.from_params()
    config = LogConfig.from_params(
        level="info",
        location=1,
        micros=True,
        colors=True,
        location_color=ColorManager.CYAN,
    )

    logger = LoggerFactory.create("demo.config", config)

    logger.info("Configured via LogConfig.from_params()")
    logger.warning("Location color set to CYAN in config")
    print()


def _demo_production_logger():
    """Demo production logger with subtle gray."""
    print("1. Production Logger (subtle gray for locations):")
    prod_logger = (
        LoggingBuilder("app.production")
        .with_level("info")
        .with_location(2)
        .with_location_color(ColorManager.create_gray_level(9))
        .with_console_handler()
        .build()
    )
    prod_logger.info("Production log with subtle gray locations")


def _demo_dev_logger():
    """Demo development logger with bright cyan."""
    print("\n2. Development Logger (bright cyan for visibility):")
    dev_logger = (
        LoggingBuilder("app.development")
        .with_level("debug")
        .with_location(2)
        .with_location_color(ColorManager.CYAN)
        .with_console_handler()
        .build()
    )
    dev_logger.debug("Debug log with cyan locations for easy identification")


def _demo_error_logger():
    """Demo error logger with default black."""
    print("\n3. Error Logger (default black, focus on error message):")
    error_logger = (
        LoggingBuilder("app.errors")
        .with_level("warning")
        .with_location(1)
        .with_console_handler()
        .build()
    )
    error_logger.error("Error log with default black location")
    print()


def demo_practical_usage():
    """Demonstrate practical usage scenarios."""
    print("=== Practical Usage Scenarios ===\n")
    _demo_production_logger()
    _demo_dev_logger()
    _demo_error_logger()


def _run_all_location_color_demos():
    """Run all location color demos."""
    demo_default_location_color()
    demo_cyan_location_color()
    demo_gray_location_color()
    demo_multiple_colors()
    demo_config_dict()
    demo_practical_usage()


def _print_location_color_summary():
    """Print summary of location color features."""
    print("=" * 60)
    print("Demo Complete!")
    print("=" * 60)
    print("\nSummary:")
    print("- Default location color is BLACK")
    print("- Use .with_location_color(color) to customize")
    print("- ColorManager provides ANSI color constants")
    print("- ColorManager.create_gray_level(n) creates grayscale (0-23)")
    print("- ColorManager.from_name('cyan') converts color names to ANSI codes")
    print("- Location color stays consistent across all log levels")
    print("- YAML config supports color names: 'cyan', 'gray-12', etc.\n")


def main():
    """Main function to run location color demos."""
    print("=" * 60)
    print("Location Color Configuration Example")
    print("=" * 60)
    print()

    try:
        _run_all_location_color_demos()
        _print_location_color_summary()
    except Exception as e:
        print(f"\nDemo failed: {e}")
        import traceback

        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
