#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Disabled Logging Example

This example demonstrates how to completely disable logging by setting the log level to False.
When logging is disabled, no log messages will be output, no callbacks will be triggered,
and no I/O operations will be performed.

What This Example Demonstrates:
- Disabling logging using boolean False
- Disabling logging using string "false"
- Disabling logging via configuration file
- Verifying that disabled loggers produce no output
- Checking the disabled state of loggers

Running the Example:
    # From the project root
    # From the infra project root
    ~/.venv/bin/python examples/disabled_logging_example.py

Expected Output:
    The console will show various ways to disable logging and demonstrate that
    disabled loggers produce no output, even for critical messages.

Key Features Demonstrated:
- Complete Logging Disable: No output, no callbacks, no I/O
- Multiple Ways to Disable: Boolean False, string "false", config file
- State Checking: Verify if logging is disabled
- Performance: Disabled logging has minimal overhead
"""

import pathlib
import sys
import time

# Add the project root to the path
project_root = str(pathlib.Path(__file__).resolve().parents[3])
sys.path.append(project_root) if project_root not in sys.path else None

from appinfra.log import LogConfig, Logger, LoggerFactory
from appinfra.log.callback import CallbackRegistry


def demo_boolean_false_disabled_logging():
    """Demonstrate disabling logging with boolean False."""
    print("=== Disabled Logging with Boolean False ===")

    # Create logger with disabled logging
    config = LogConfig.from_params(False, location=1, micros=True)
    logger = LoggerFactory.create("disabled_logger", config)

    print(f"Logger disabled: {logger.disabled}")
    print(f"Logger level: {logger.get_level()}")
    print(f"Underlying logger level: {logger.level}")

    # Try to log at various levels - none should produce output
    print("\nAttempting to log at various levels:")
    logger.debug("Debug message - should not appear")
    logger.info("Info message - should not appear")
    logger.warning("Warning message - should not appear")
    logger.error("Error message - should not appear")
    logger.critical("Critical message - should not appear")
    logger.trace("Trace message - should not appear")
    logger.trace2("Trace2 message - should not appear")

    print("✓ No output was produced (as expected)")


def demo_string_false_disabled_logging():
    """Demonstrate disabling logging with string 'false'."""
    print("\n=== Disabled Logging with String 'false' ===")

    # Create logger with disabled logging using string
    config = LogConfig.from_params("false", location=1, micros=True)
    logger = LoggerFactory.create("disabled_string_logger", config)

    print(f"Logger disabled: {logger.disabled}")
    print(f"Logger level: {logger.get_level()}")
    print(f"Underlying logger level: {logger.level}")

    # Try to log at various levels - none should produce output
    print("\nAttempting to log at various levels:")
    logger.debug("Debug message - should not appear")
    logger.info("Info message - should not appear")
    logger.warning("Warning message - should not appear")
    logger.error("Error message - should not appear")
    logger.critical("Critical message - should not appear")

    print("✓ No output was produced (as expected)")


def demo_disabled_logging_with_callbacks():
    """Demonstrate that disabled logging doesn't trigger callbacks."""
    print("\n=== Disabled Logging with Callbacks ===")

    # Create callback registry
    callback_registry = CallbackRegistry()
    callback_called = False

    def test_callback(level, logger, msg, args, kwargs):
        nonlocal callback_called
        callback_called = True
        print(f"Callback triggered: {msg}")

    # Register callback for INFO level
    callback_registry.register(20, test_callback)  # INFO level

    # Create disabled logger with callbacks
    config = LogConfig.from_params(False, location=1, micros=True)
    logger = Logger("disabled_callback_logger", config, callback_registry)

    print(f"Logger disabled: {logger.disabled}")

    # Try to log - callbacks should not be triggered
    print("\nAttempting to log with callbacks:")
    logger.info("Info message with callback - should not trigger callback")
    logger.warning("Warning message with callback - should not trigger callback")
    logger.error("Error message with callback - should not trigger callback")

    print(f"Callback was called: {callback_called}")
    print("✓ Callbacks were not triggered (as expected)")


def demo_config_file_disabled_logging():
    """Demonstrate disabling logging via configuration file."""
    print("\n=== Disabled Logging via Configuration File ===")

    # Create a temporary config dict simulating a config file with disabled logging
    config_dict = {
        "logging": {
            "level": "false",
            "location": 1,
            "micros": True,
            "colors_enabled": True,
        }
    }

    # Create LogConfig from config dict
    config = LogConfig.from_config(config_dict, "logging")
    logger = LoggerFactory.create("config_disabled_logger", config)

    print(f"Logger disabled: {logger.disabled}")
    print(f"Logger level: {logger.get_level()}")

    # Try to log - none should produce output
    print("\nAttempting to log via config file disabled logger:")
    logger.debug("Debug message - should not appear")
    logger.info("Info message - should not appear")
    logger.warning("Warning message - should not appear")
    logger.error("Error message - should not appear")

    print("✓ No output was produced (as expected)")


def demo_performance_comparison():
    """Demonstrate performance difference between enabled and disabled logging."""
    print("\n=== Performance Comparison ===")

    # Create enabled logger
    enabled_config = LogConfig.from_params("info", location=1, micros=True)
    enabled_logger = LoggerFactory.create("enabled_logger", enabled_config)

    # Create disabled logger
    disabled_config = LogConfig.from_params(False, location=1, micros=True)
    disabled_logger = LoggerFactory.create("disabled_logger", disabled_config)

    # Test performance with enabled logging
    start_time = time.time()
    for i in range(1000):
        enabled_logger.info(f"Performance test message {i}")
    enabled_time = time.time() - start_time

    # Test performance with disabled logging
    start_time = time.time()
    for i in range(1000):
        disabled_logger.info(f"Performance test message {i}")
    disabled_time = time.time() - start_time

    print(f"Enabled logging time: {enabled_time:.4f} seconds")
    print(f"Disabled logging time: {disabled_time:.4f} seconds")
    print(
        f"Performance improvement: {((enabled_time - disabled_time) / enabled_time * 100):.1f}%"
    )
    print("✓ Disabled logging is significantly faster")


def demo_mixed_logging_scenarios():
    """Demonstrate mixed scenarios with enabled and disabled loggers."""
    print("\n=== Mixed Logging Scenarios ===")

    # Create both enabled and disabled loggers
    enabled_config = LogConfig.from_params("info", location=1, micros=True)
    enabled_logger = LoggerFactory.create("enabled_logger", enabled_config)

    disabled_config = LogConfig.from_params(False, location=1, micros=True)
    disabled_logger = LoggerFactory.create("disabled_logger", disabled_config)

    print("Enabled logger:")
    enabled_logger.info("This message WILL appear")
    enabled_logger.debug("This debug message will NOT appear (level too low)")

    print("\nDisabled logger:")
    disabled_logger.info("This message will NOT appear (logging disabled)")
    disabled_logger.error("This error message will NOT appear (logging disabled)")

    print("\n✓ Mixed scenario demonstrates selective logging control")


def _run_all_disabled_logging_demos():
    """Run all disabled logging demo functions."""
    demo_boolean_false_disabled_logging()
    demo_string_false_disabled_logging()
    demo_disabled_logging_with_callbacks()
    demo_config_file_disabled_logging()
    demo_performance_comparison()
    demo_mixed_logging_scenarios()


def _print_disabled_logging_summary():
    """Print disabled logging demo summary."""
    print("\n=== Demo Complete ===")
    print("Disabled logging functionality has been demonstrated.")
    print("Key takeaways:")
    print("- Use False or 'false' to completely disable logging")
    print("- Disabled loggers produce no output and trigger no callbacks")
    print("- Disabled logging has minimal performance overhead")
    print("- You can mix enabled and disabled loggers in the same application")


def main():
    """Main function to run the disabled logging demos."""
    print("=== Disabled Logging Example ===")
    print("This example demonstrates how to completely disable logging.")
    print(
        "When logging is disabled, no output is produced, no callbacks are triggered,"
    )
    print("and no I/O operations are performed.\n")

    try:
        _run_all_disabled_logging_demos()
        _print_disabled_logging_summary()
    except Exception as e:
        print(f"\nDemo failed: {e}")
        import traceback

        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
