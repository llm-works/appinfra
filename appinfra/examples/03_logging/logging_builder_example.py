#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
LoggingBuilder Example

This example demonstrates the LoggingBuilder concept for configuring loggers
with a fluent, chainable API. It shows various builder patterns and configurations.

What This Example Demonstrates:
- Base LoggingBuilder for general logging configuration
- ConsoleLoggingBuilder for console-specific configurations
- FileLoggingBuilder for file-specific configurations
- JSONLoggingBuilder for structured JSON output
- Fluent API patterns and method chaining
- Quick setup functions for common configurations

Running the Example:
    # From the infra project root
    ~/.venv/bin/python examples/03_logging/logging_builder_example.py

Expected Output:
    The console will show various logging configurations being set up and used.
    Log files will be created in the .logs/ directory with different configurations.
    JSON output will demonstrate structured logging capabilities.

Key Features Demonstrated:
- Builder Pattern: Fluent API for complex logging configurations
- Specialized Builders: Different builders for different output types
- Method Chaining: Clean, readable configuration code
- Multiple Outputs: Easy configuration of multiple destinations
- Quick Setup: Convenience functions for common scenarios
- Extensibility: Easy to extend with new builder types

This example shows how the LoggingBuilder concept makes logging configuration
simple, readable, and maintainable.
"""

import json
import os
import pathlib
import sys
import time

# Log directory for examples (hidden to keep project root clean)
LOG_DIR = ".logs"

# Add the project root to the path (examples/03_logging/file.py -> project root is 2 levels up)
project_root = str(pathlib.Path(__file__).resolve().parents[3])
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from appinfra.log.builder import (
    ConsoleLoggingBuilder,
    FileLoggingBuilder,
    JSONLoggingBuilder,
    LoggingBuilder,
    quick_both_logger,
    quick_both_outputs,
    quick_console_and_file,
    quick_console_logger,
    quick_console_with_colors,
    quick_daily_file_logger,
    quick_file_logger,
    quick_json_console,
    quick_json_file,
)


def _demo_basic_configuration():
    """Demonstrate basic logging configuration."""
    print("\n1. Basic Configuration:")
    logger1 = (
        LoggingBuilder("demo.basic")
        .with_level("info")
        .with_location(1)
        .with_micros(True)
        .with_console_handler()
        .build()
    )
    logger1.info("Basic logging configuration", extra={"example": "basic_builder"})
    print("   -> Created logger with basic console output")


def _demo_multiple_handler_types():
    """Demonstrate multiple handler types on a single logger."""
    print("\n2. Multiple Handlers:")
    logger2 = (
        LoggingBuilder("demo.multiple")
        .with_level("debug")
        .with_console_handler()
        .with_file_handler(f"{LOG_DIR}/multiple_demo.log")
        .with_rotating_file_handler(
            f"{LOG_DIR}/rotating_demo.log", max_bytes=1024 * 1024, backup_count=3
        )
        .build()
    )
    logger2.debug(
        "Multiple handlers configured", extra={"example": "multiple_handlers"}
    )
    print("   -> Created logger with console, file, and rotating file handlers")


def _demo_custom_configuration():
    """Demonstrate custom logger configuration with separator."""
    print("\n3. Custom Configuration:")
    logger3 = (
        LoggingBuilder("demo.custom")
        .with_level("warning")
        .with_colors(False)
        .with_separator()
        .with_file_handler(f"{LOG_DIR}/custom_demo.log")
        .with_extra(service="demo", version="1.0.0")
        .build()
    )
    logger3.warning("Custom configuration applied", extra={"example": "custom_config"})
    print("   -> Created logger with custom configuration and separator support")


def demo_base_logging_builder():
    """Demonstrate the base LoggingBuilder."""
    print("=== Base LoggingBuilder Demo ===")
    _demo_basic_configuration()
    _demo_multiple_handler_types()
    _demo_custom_configuration()


def demo_console_logging_builder():
    """Demonstrate ConsoleLoggingBuilder."""
    print("\n=== ConsoleLoggingBuilder Demo ===")

    # 1. Basic console logging
    print("\n1. Basic Console Logging:")
    logger1 = (
        ConsoleLoggingBuilder("demo.console")
        .with_level("info")
        .with_colors(True)
        .build()
    )

    logger1.info("Console logging with colors", extra={"example": "console_builder"})
    print("   -> Created console logger with colors")

    # 2. Different output streams
    print("\n2. Different Output Streams:")
    logger2 = ConsoleLoggingBuilder("demo.stdout").with_level("info").stdout().build()

    logger2.info("Output to stdout", extra={"example": "stdout_output"})
    print("   -> Created console logger outputting to stdout")

    # 3. Console with colors
    print("\n3. Console with Colors:")
    logger3 = quick_console_with_colors("demo.colors", {"level": "debug"})
    logger3.debug("Text debug message", extra={"example": "colored_output"})
    print("   -> Created console logger with colored output")


def _demo_basic_file_logging():
    """Demonstrate basic file logging."""
    print("\n1. Basic File Logging:")
    logger1 = (
        FileLoggingBuilder("demo.file", f"{LOG_DIR}/file_demo.log")
        .with_level("info")
        .build()
    )
    logger1.info("File logging configured", extra={"example": "file_builder"})
    print("   -> Created file logger")


def _demo_file_rotation():
    """Demonstrate file rotation with size-based rollover."""
    print("\n2. File Rotation:")
    logger2 = (
        FileLoggingBuilder("demo.rotation", f"{LOG_DIR}/rotation_demo.log")
        .with_level("debug")
        .with_rotation(max_bytes=1024 * 1024, backup_count=3)  # 1MB rotation
        .build()
    )
    logger2.debug("File rotation configured", extra={"example": "file_rotation"})
    print("   -> Created file logger with rotation")


def _demo_time_based_rotation():
    """Demonstrate time-based file rotation (daily and hourly)."""
    print("\n3. Daily Rotation:")
    logger3 = quick_daily_file_logger(
        "demo.daily", f"{LOG_DIR}/daily_demo.log", "info", 7
    )
    logger3.info("Daily rotation configured", extra={"example": "daily_rotation"})
    print("   -> Created file logger with daily rotation")

    print("\n4. Hourly Rotation:")
    logger4 = (
        FileLoggingBuilder("demo.hourly", f"{LOG_DIR}/hourly_demo.log")
        .with_level("info")
        .hourly_rotation(backup_count=24)
        .build()
    )
    logger4.info("Hourly rotation configured", extra={"example": "hourly_rotation"})
    print("   -> Created file logger with hourly rotation")


def demo_file_logging_builder():
    """Demonstrate FileLoggingBuilder."""
    print("\n=== FileLoggingBuilder Demo ===")
    _demo_basic_file_logging()
    _demo_file_rotation()
    _demo_time_based_rotation()


def _demo_console_and_file_output():
    """Demonstrate basic console and file output."""
    print("\n1. Console and File Output:")
    logger1 = (
        LoggingBuilder("demo.multiple")
        .with_level("info")
        .with_console_handler()
        .with_file_handler(f"{LOG_DIR}/multiple_demo.log")
        .build()
    )
    logger1.info("Multiple handlers configured", extra={"example": "multiple_handlers"})
    print("   -> Created logger with both console and file output")


def _demo_different_handler_levels():
    """Demonstrate handlers with different log levels."""
    print("\n2. Multiple Handlers with Different Levels:")
    logger2 = (
        LoggingBuilder("demo.multiple_levels")
        .with_level("debug")
        .with_console_handler(level="info")
        .with_file_handler(f"{LOG_DIR}/multiple_info.log", level="info")
        .with_rotating_file_handler(
            f"{LOG_DIR}/multiple_debug.log",
            max_bytes=1024,
            backup_count=3,
            level="debug",
        )
        .build()
    )
    logger2.info("This goes to all handlers", extra={"example": "all_handlers"})
    print("   -> Created logger with handlers having different log levels")


def _demo_quick_multi_output():
    """Demonstrate quick multi-output setup."""
    print("\n3. Quick Setup:")
    logger3 = quick_console_and_file(
        "demo.quick_multi", f"{LOG_DIR}/quick_multi_demo.log", "info"
    )
    logger3.info("Quick multi-output setup", extra={"example": "quick_multi"})
    print("   -> Created logger with quick multi-output setup")


def demo_multiple_handlers():
    """Demonstrate using multiple handlers with a single logger."""
    print("\n=== Multiple Handlers Demo ===")
    _demo_console_and_file_output()
    _demo_different_handler_levels()
    _demo_quick_multi_output()


def _demo_json_console():
    """Demonstrate JSON console output."""
    print("\n1. JSON Console Output:")
    logger = (
        JSONLoggingBuilder("demo.json_console")
        .with_level("info")
        .with_json_console(True)
        .build()
    )

    logger.info(
        "JSON console output configured",
        extra={
            "example": "json_console",
            "user_id": "user-123",
            "action": "login",
            "timestamp": time.time(),
        },
    )
    print("   -> Created logger with JSON console output")


def _demo_json_file():
    """Demonstrate JSON file output."""
    print("\n2. JSON File Output:")
    logger = (
        JSONLoggingBuilder("demo.json_file")
        .with_level("debug")
        .with_json_file(f"{LOG_DIR}/json_demo.json")
        .with_pretty_print(True)
        .build()
    )

    logger.debug(
        "JSON file output configured",
        extra={
            "example": "json_file",
            "request_id": "req-456",
            "endpoint": "/api/v1/data",
            "response_time_ms": 125.5,
            "status_code": 200,
        },
    )
    print("   -> Created logger with JSON file output")


def _demo_json_custom_fields():
    """Demonstrate custom JSON fields."""
    print("\n3. Custom JSON Fields:")
    logger = (
        JSONLoggingBuilder("demo.json_custom")
        .with_level("info")
        .with_json_file(f"{LOG_DIR}/json_custom_demo.json")
        .with_custom_fields(
            {"service": "demo", "version": "1.0.0", "environment": "development"}
        )
        .with_json_fields(include=["timestamp", "level", "logger", "message", "extra"])
        .build()
    )

    logger.info(
        "Custom JSON fields configured",
        extra={
            "example": "json_custom",
            "operation": "data_processing",
            "records_processed": 1000,
            "success_rate": 99.5,
        },
    )
    print("   -> Created logger with custom JSON field configuration")


def _demo_json_both_outputs():
    """Demonstrate both console and JSON file output."""
    print("\n4. Both Console and JSON File:")
    logger = quick_both_outputs(
        "demo.json_both", f"{LOG_DIR}/json_both_demo.json", "info"
    )
    logger.info(
        "Both console and JSON file configured",
        extra={
            "example": "json_both",
            "session_id": "sess-789",
            "user_agent": "Mozilla/5.0...",
            "ip_address": "192.168.1.100",
        },
    )
    print("   -> Created logger with both console and JSON file output")


def demo_json_logging_builder():
    """Demonstrate JSONLoggingBuilder."""
    print("\n=== JSONLoggingBuilder Demo ===")
    _demo_json_console()
    _demo_json_file()
    _demo_json_custom_fields()
    _demo_json_both_outputs()


def _demo_quick_basic_loggers():
    """Demonstrate quick console and file logger setup."""
    print("\n1. Quick Console Logger:")
    console_logger = quick_console_logger("demo.quick_console", "info")
    console_logger.info("Quick console setup", extra={"example": "quick_console"})
    print("   -> Quick console logger created")

    print("\n2. Quick File Logger:")
    file_logger = quick_file_logger(
        "demo.quick_file", f"{LOG_DIR}/quick_file_demo.log", "debug"
    )
    file_logger.debug("Quick file setup", extra={"example": "quick_file"})
    print("   -> Quick file logger created")

    print("\n3. Quick Both Logger:")
    both_logger = quick_both_logger(
        "demo.quick_both", f"{LOG_DIR}/quick_both_demo.log", "info"
    )
    both_logger.info("Quick both setup", extra={"example": "quick_both"})
    print("   -> Quick both logger created")


def _demo_quick_json_loggers():
    """Demonstrate quick JSON logger setup functions."""
    print("\n4. Quick JSON Functions:")
    json_console = quick_json_console("demo.quick_json_console", "info")
    json_console.info("Quick JSON console", extra={"example": "quick_json_console"})

    json_file = quick_json_file(
        "demo.quick_json_file", f"{LOG_DIR}/quick_json_demo.json", "debug"
    )
    json_file.debug("Quick JSON file", extra={"example": "quick_json_file"})

    json_both = quick_both_outputs(
        "demo.quick_json_both", f"{LOG_DIR}/quick_json_both_demo.json", "info"
    )
    json_both.info("Quick JSON both", extra={"example": "quick_json_both"})
    print("   -> Quick JSON loggers created")


def demo_quick_setup_functions():
    """Demonstrate quick setup functions."""
    print("\n=== Quick Setup Functions Demo ===")
    _demo_quick_basic_loggers()
    _demo_quick_json_loggers()


def _demo_production_logging():
    """Demonstrate production logging setup."""
    print("\n1. Production Logging Setup:")
    prod_logger = (
        LoggingBuilder("demo.production")
        .with_level("info")
        .with_location(2)
        .with_micros(True)
        .with_console_handler()
        .with_rotating_file_handler(
            f"{LOG_DIR}/production.log", max_bytes=10 * 1024 * 1024, backup_count=10
        )
        .with_timed_rotating_file_handler(
            f"{LOG_DIR}/production_errors.log", when="midnight", backup_count=30
        )
        .build()
    )

    prod_logger.info(
        "Production logging configured",
        extra={
            "example": "production_setup",
            "startup_time": time.time(),
            "memory_usage_mb": 256,
            "cpu_usage_percent": 15.2,
        },
    )
    print("   -> Production logging setup created")


def _demo_development_logging():
    """Demonstrate development logging setup."""
    print("\n2. Development Logging Setup:")
    dev_logger = (
        JSONLoggingBuilder("demo.development")
        .with_level("debug")
        .with_location(3)
        .with_micros(True)
        .with_json_file(f"{LOG_DIR}/development.json")
        .with_pretty_print(True)
        .with_custom_fields({"environment": "development", "debug_mode": True})
        .build()
    )

    dev_logger.debug(
        "Development logging configured",
        extra={
            "example": "development_setup",
            "debug_info": {
                "breakpoints": ["line_42", "line_87"],
                "watch_variables": ["user_id", "session_data"],
                "call_stack_depth": 5,
            },
        },
    )
    print("   -> Development logging setup created")


def _create_microservice_logger(service, port):
    """Create a logger for a specific microservice."""
    return (
        JSONLoggingBuilder(f"demo.microservice.{service}")
        .with_level("info")
        .with_json_file(f"{LOG_DIR}/service_{service}.json")
        .with_custom_fields(
            {
                "service": service,
                "service_type": "microservice",
                "deployment": "kubernetes",
                "namespace": "production",
            }
        )
        .with_json_fields(include=["timestamp", "level", "logger", "message", "extra"])
        .build()
    )


def _log_microservice_startup(service_logger, service, port):
    """Log microservice startup information."""
    service_logger.info(
        f"{service} service started",
        extra={
            "example": "microservice_setup",
            "port": port,
            "health_check": "ok",
            "version": "1.0.0",
            "replicas": 3,
        },
    )


def _demo_microservice_logging():
    """Demonstrate microservice logging setup."""
    print("\n3. Microservice Logging Setup:")
    services = ["auth", "api", "database", "cache"]

    for service in services:
        port = 8080 + services.index(service)
        service_logger = _create_microservice_logger(service, port)
        _log_microservice_startup(service_logger, service, port)

    print(f"   -> Created {len(services)} microservice loggers")


def demo_advanced_scenarios():
    """Demonstrate advanced logging scenarios."""
    print("\n=== Advanced Scenarios Demo ===")
    _demo_production_logging()
    _demo_development_logging()
    _demo_microservice_logging()


def _get_log_files_to_cleanup():
    """Get list of log files created by demos."""
    return [
        f"{LOG_DIR}/multiple_demo.log",
        f"{LOG_DIR}/rotating_demo.log",
        f"{LOG_DIR}/custom_demo.log",
        f"{LOG_DIR}/file_demo.log",
        f"{LOG_DIR}/rotation_demo.log",
        f"{LOG_DIR}/daily_demo.log",
        f"{LOG_DIR}/hourly_demo.log",
        f"{LOG_DIR}/multi_demo.log",
        f"{LOG_DIR}/multi_files1.log",
        f"{LOG_DIR}/multi_files2.log",
        f"{LOG_DIR}/multi_files3.log",
        f"{LOG_DIR}/quick_multi_demo.log",
        f"{LOG_DIR}/json_demo.json",
        f"{LOG_DIR}/json_custom_demo.json",
        f"{LOG_DIR}/json_both_demo.json",
        f"{LOG_DIR}/quick_file_demo.log",
        f"{LOG_DIR}/quick_both_demo.log",
        f"{LOG_DIR}/quick_json_demo.json",
        f"{LOG_DIR}/quick_json_both_demo.json",
        f"{LOG_DIR}/production.log",
        f"{LOG_DIR}/production_errors.log",
        f"{LOG_DIR}/development.json",
        f"{LOG_DIR}/service_auth.json",
        f"{LOG_DIR}/service_api.json",
        f"{LOG_DIR}/service_database.json",
        f"{LOG_DIR}/service_cache.json",
    ]


def cleanup_log_files():
    """Clean up generated log files."""
    log_files = _get_log_files_to_cleanup()
    cleaned_count = sum(
        1
        for log_file in log_files
        if os.path.exists(log_file) and not os.remove(log_file)
    )
    if cleaned_count > 0:
        print(f"\nCleaned up {cleaned_count} log files")


def _run_all_demos():
    """Run all LoggingBuilder demonstration functions."""
    demo_base_logging_builder()
    demo_console_logging_builder()
    demo_file_logging_builder()
    demo_multiple_handlers()
    demo_json_logging_builder()
    demo_quick_setup_functions()
    demo_advanced_scenarios()


def _print_completion_summary():
    """Print demo completion summary."""
    print("\n=== Demo Complete ===")
    print("Various LoggingBuilder configurations have been demonstrated.")
    print(f"Check the {LOG_DIR}/ directory for generated log files.")


def _display_json_examples():
    """Display JSON logging output examples."""
    print("\n=== JSON Output Examples ===")
    json_file = f"{LOG_DIR}/json_demo.json"
    if os.path.exists(json_file):
        print(f"Sample JSON output from {json_file}:")
        with open(json_file) as f:
            lines = f.readlines()
            for line in lines[:3]:  # Show first 3 lines
                try:
                    json_data = json.loads(line.strip())
                    print(json.dumps(json_data, indent=2))
                    print("---")
                except json.JSONDecodeError:
                    print(line.strip())


def main():
    """Main function to run the LoggingBuilder demos."""
    print("=== LoggingBuilder Example ===")

    # Ensure logs directory exists
    os.makedirs(LOG_DIR, exist_ok=True)

    try:
        _run_all_demos()
        _print_completion_summary()
        _display_json_examples()

        # Ask user if they want to keep the log files
        keep_files = input("\nKeep log files for inspection? (y/N): ").lower().strip()
        if keep_files != "y":
            cleanup_log_files()
        else:
            print("Log files preserved for inspection.")

    except Exception as e:
        print(f"\nDemo failed: {e}")
        import traceback

        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
