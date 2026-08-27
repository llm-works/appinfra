#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Topic-Based Logging Example

This example demonstrates how to use topic-based logging to control log levels
for different parts of your application using glob patterns.

Topic-based logging allows fine-grained control over log levels by matching
logger names against patterns. You can configure topics via:
1. YAML configuration files
2. CLI arguments (--log-topic)
3. Programmatic API (AppBuilder)

Pattern Syntax:
- '*' matches single path segment (e.g., '/infra/db/*' matches '/infra/db/pg' but not '/infra/db/pg/queries')
- '**' matches any depth (e.g., '/infra/**' matches all descendants)
- Exact paths for precise matching (e.g., '/infra/db/queries')

Priority: API (10) > CLI (5) > YAML (1)
"""

import logging
import pathlib
import sys

# Add the project root to the path
project_root = str(pathlib.Path(__file__).resolve().parents[3])
sys.path.insert(0, project_root)

from appinfra.app.builder import AppBuilder
from appinfra.log import LogConfig, LoggerFactory


def _print_yaml_config_instructions():
    """Print YAML configuration instructions."""
    print("\n" + "=" * 70)
    print("Example 1: YAML Configuration")
    print("=" * 70)
    print("\nTo load topic configuration from YAML, create a config file like:")
    print("  topic_logging_config.yaml (see example file)")
    print("\nThen in your app:")
    print("  from appinfra.app.core.config import create_config")
    print("  config = create_config('topic_logging_config.yaml')")
    print("  logger, registry = setup_logging_from_config(config)")
    print("\nSee topic_logging_config.yaml for YAML configuration examples.")


def _create_topic_loggers():
    """Create loggers with topic-based configuration."""
    print("\nFor this example, using programmatic API (equivalent to YAML):")
    app = (
        AppBuilder("yaml-example")
        .logging.with_topic_levels(
            {
                "/infra/db/queries": "debug",
                "/infra/api/rest": "warning",
                "/myapp/service/auth": "error",
            }
        )
        .done()
        .build()
    )

    log_config = LogConfig.from_params("info", location=0, micros=False)
    db_logger = LoggerFactory.create("/infra/db/queries", log_config)
    api_logger = LoggerFactory.create("/infra/api/rest", log_config)
    app_logger = LoggerFactory.create("/myapp/service/auth", log_config)

    return db_logger, api_logger, app_logger


def _test_topic_loggers(db_logger, api_logger, app_logger):
    """Test loggers at different levels."""
    print("\nLogger levels from configuration:")
    print(f"  /infra/db/queries  → {logging.getLevelName(db_logger.level)}")
    print(f"  /infra/api/rest    → {logging.getLevelName(api_logger.level)}")
    print(f"  /myapp/service/auth → {logging.getLevelName(app_logger.level)}")

    print(
        f"\nTesting /infra/db/queries logger (level={logging.getLevelName(db_logger.level)}):"
    )
    db_logger.debug("This DEBUG message SHOULD appear")
    db_logger.info("This INFO message should appear")

    print(
        f"\nTesting /infra/api/rest logger (level={logging.getLevelName(api_logger.level)}):"
    )
    api_logger.debug("This DEBUG message should NOT appear")
    api_logger.warning("This WARNING message SHOULD appear")

    print(
        f"\nTesting /myapp/service/auth logger (level={logging.getLevelName(app_logger.level)}):"
    )
    app_logger.info("This INFO message should NOT appear")
    app_logger.error("This ERROR message SHOULD appear")


def example_1_yaml_configuration():
    """Example 1: Configure topic levels via YAML."""
    _print_yaml_config_instructions()
    db_logger, api_logger, app_logger = _create_topic_loggers()
    _test_topic_loggers(db_logger, api_logger, app_logger)


def example_2_cli_override():
    """Example 2: Override YAML configuration with CLI arguments."""
    print("\n" + "=" * 70)
    print("Example 2: CLI Arguments Override YAML")
    print("=" * 70)

    print("\nTo override YAML config from command line:")
    print("  ./topic_logging_example.py --log-topic '/infra/db/*' trace")
    print("  ./topic_logging_example.py --log-topic '/infra/api/*' debug")
    print("  ./topic_logging_example.py --log-topic '/myapp/**' warning")

    print("\nMultiple --log-topic arguments can be specified:")
    print("  ./topic_logging_example.py \\")
    print("      --log-topic '/infra/db/*' debug \\")
    print("      --log-topic '/infra/api/*' warning \\")
    print("      --log-topic '/myapp/**' info")

    print("\nCLI arguments have priority 5, overriding YAML (priority 1)")


def _create_api_configured_app():
    """Create app with programmatically configured topic levels."""
    return (
        AppBuilder("api-example")
        .logging.with_level("info")
        .with_topic_levels(
            {
                "/infra/db/*": "debug",
                "/infra/api/*": "warning",
                "/myapp/**": "error",
            }
        )
        .done()
        .build()
    )


def _create_and_display_api_loggers():
    """Create loggers and display their configured levels."""
    log_config = LogConfig.from_params("info", location=0, micros=False)
    db_logger = LoggerFactory.create("/infra/db/connection", log_config)
    api_logger = LoggerFactory.create("/infra/api/handlers", log_config)
    app_logger = LoggerFactory.create("/myapp/business/logic", log_config)

    print("\nLogger levels from API configuration:")
    print(f"  /infra/db/connection → {logging.getLevelName(db_logger.level)}")
    print(f"  /infra/api/handlers  → {logging.getLevelName(api_logger.level)}")
    print(f"  /myapp/business/logic → {logging.getLevelName(app_logger.level)}")

    return db_logger, api_logger, app_logger


def _test_api_loggers(db_logger, api_logger, app_logger):
    """Test loggers at different configured levels."""
    print("\nTesting /infra/db/connection logger:")
    db_logger.debug("DEBUG: Connection pool initialized")

    print("\nTesting /infra/api/handlers logger:")
    api_logger.info("This INFO message should NOT appear")
    api_logger.warning("WARNING: Rate limit approaching")

    print("\nTesting /myapp/business/logic logger:")
    app_logger.warning("This WARNING should NOT appear")
    app_logger.error("ERROR: Business rule violation detected")


def example_3_programmatic_api():
    """Example 3: Configure topic levels via AppBuilder API."""
    print("\n" + "=" * 70)
    print("Example 3: Programmatic API Configuration")
    print("=" * 70)

    app = _create_api_configured_app()
    db_logger, api_logger, app_logger = _create_and_display_api_loggers()
    _test_api_loggers(db_logger, api_logger, app_logger)


def _create_specificity_app():
    """Create app with overlapping pattern configurations."""
    return (
        AppBuilder("specificity-example")
        .logging.with_level("info")  # Global default
        .with_topic_levels(
            {
                "/infra/**": "warning",  # All infra → warning (specificity=10)
                "/infra/db/*": "debug",  # DB loggers → debug (specificity=21)
                "/infra/db/queries": "trace",  # Queries → trace (specificity=30)
            }
        )
        .done()
        .build()
    )


def _demonstrate_pattern_matching():
    """Create loggers and demonstrate pattern specificity matching."""
    log_config = LogConfig.from_params("info", location=0, micros=False)
    infra_logger = LoggerFactory.create("/infra/cache", log_config)
    db_logger = LoggerFactory.create("/infra/db/connection", log_config)
    queries_logger = LoggerFactory.create("/infra/db/queries", log_config)

    print("\nPattern matching (most specific wins):")
    print(f"  /infra/cache → {logging.getLevelName(infra_logger.level)}")
    print("    Matched: /infra/** (specificity=10)")
    print(f"\n  /infra/db/connection → {logging.getLevelName(db_logger.level)}")
    print("    Matched: /infra/db/* (specificity=21) over /infra/** (specificity=10)")
    print(f"\n  /infra/db/queries → {logging.getLevelName(queries_logger.level)}")
    print(
        "    Matched: /infra/db/queries (specificity=30) over /infra/db/* (specificity=21)"
    )


def _print_specificity_rules():
    """Print specificity scoring rules."""
    print("\nSpecificity scoring:")
    print("  - Exact segment = 10 points")
    print("  - '*' wildcard = 1 point")
    print("  - '**' wildcard = 0 points")


def example_4_pattern_specificity():
    """Example 4: Pattern specificity - more specific patterns win."""
    print("\n" + "=" * 70)
    print("Example 4: Pattern Specificity")
    print("=" * 70)

    app = _create_specificity_app()
    _demonstrate_pattern_matching()
    _print_specificity_rules()


def _create_runtime_update_app():
    """Create app with runtime updates enabled."""
    return (
        AppBuilder("runtime-example")
        .logging.with_level("info")
        .with_runtime_updates(True)  # Opt-in to runtime changes
        .with_topic_level("/myapp/**", "info")
        .done()
        .build()
    )


def _demonstrate_initial_logging(logger):
    """Demonstrate logging before runtime level change."""
    print(f"\nInitial logger level: {logging.getLevelName(logger.level)}")
    logger.debug("This DEBUG message should NOT appear")
    logger.info("This INFO message SHOULD appear")


def _update_runtime_level(logger):
    """Change logger level at runtime and demonstrate."""
    print("\nChanging /myapp/** level to DEBUG at runtime...")
    from appinfra.log.level_manager import LogLevelManager

    manager = LogLevelManager.get_instance()
    manager.add_rule("/myapp/**", "debug", source="runtime", priority=20)

    print(f"Updated logger level: {logging.getLevelName(logger.level)}")
    logger.debug("This DEBUG message SHOULD now appear")
    logger.info("This INFO message still appears")


def example_5_runtime_updates():
    """Example 5: Runtime updates to existing loggers."""
    print("\n" + "=" * 70)
    print("Example 5: Runtime Updates (Opt-in)")
    print("=" * 70)

    app = _create_runtime_update_app()
    log_config = LogConfig.from_params("info", location=0, micros=False)
    logger = LoggerFactory.create("/myapp/service", log_config)

    _demonstrate_initial_logging(logger)
    _update_runtime_level(logger)

    print("\nNote: Runtime updates are disabled by default for safety.")
    print("Use .with_runtime_updates(True) to enable.")


def example_6_priority_demonstration():
    """Example 6: Priority system - API > CLI > YAML."""
    print("\n" + "=" * 70)
    print("Example 6: Priority System")
    print("=" * 70)

    from appinfra.log.level_manager import LogLevelManager

    # Reset manager for clean demo
    LogLevelManager.reset_instance()
    manager = LogLevelManager.get_instance()

    # Add rules with different priorities
    manager.add_rule("/test/*", "info", source="yaml", priority=1)
    manager.add_rule("/test/*", "debug", source="cli", priority=5)
    manager.add_rule("/test/*", "warning", source="api", priority=10)

    # Check effective level
    effective = manager.get_effective_level("/test/logger")

    print("\nRules for pattern '/test/*':")
    print("  YAML rule: info    (priority=1)")
    print("  CLI rule:  debug   (priority=5)")
    print("  API rule:  warning (priority=10)")
    print(f"\nEffective level: {effective}")
    print("  → API rule wins (highest priority)")

    print("\nPriority levels:")
    print("  10 = API (programmatic configuration)")
    print("   5 = CLI (command-line arguments)")
    print("   1 = YAML (configuration files)")


def main():
    """Run all examples."""
    print("\n" + "=" * 70)
    print("Topic-Based Logging Examples")
    print("=" * 70)

    try:
        example_1_yaml_configuration()
    except Exception as e:
        print(f"\nSkipping Example 1 (YAML): {e}")

    example_2_cli_override()
    example_3_programmatic_api()
    example_4_pattern_specificity()
    example_5_runtime_updates()
    example_6_priority_demonstration()

    print("\n" + "=" * 70)
    print("Examples Complete")
    print("=" * 70)
    print("\nKey Takeaways:")
    print("  1. Use topics for fine-grained log level control")
    print("  2. Patterns support *, **, and exact paths")
    print("  3. More specific patterns win")
    print("  4. API > CLI > YAML priority")
    print("  5. Runtime updates are opt-in via .with_runtime_updates()")


if __name__ == "__main__":
    main()
