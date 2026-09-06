#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Example demonstrating the new generator methods in HandlerFactory and HandlerRegistry.

This example shows how to use the generators for:
- Discovering supported handler types
- Iterating through loaded handlers
- Memory-efficient handler processing
"""

import sys
from pathlib import Path

# Allow running from a source checkout without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from appinfra import Config
from appinfra.log.handler_factory import HandlerFactory, HandlerRegistry


def demo_handler_factory_generators():
    """Demonstrate HandlerFactory generator methods."""
    print("=== HandlerFactory Generators ===")

    print("\n1. Discovering supported handler types:")
    print("   HandlerFactory.iter_supported_types() yields each supported type:")

    for handler_type in HandlerFactory.iter_supported_types():
        print(f"   ✓ {handler_type}")

    print(
        f"\n   Total supported types: {len(list(HandlerFactory.iter_supported_types()))}"
    )


def _iterate_all_handlers(registry):
    """Iterate and print all handlers."""
    print("\n3. Iterating through all handlers:")
    print("   HandlerRegistry.iter_handlers() yields all handlers:")
    for i, handler in enumerate(registry.iter_handlers()):
        print(f"   Handler {i}: {handler.__class__.__name__}")
    print(f"\n   Total handlers loaded: {len(registry.handlers)}")


def _iterate_enabled_handlers(registry):
    """Iterate and print enabled handlers."""
    print("\n4. Iterating through enabled handlers only:")
    print("   HandlerRegistry.iter_enabled_handlers() yields only enabled handlers:")
    enabled_count = 0
    for handler in registry.iter_enabled_handlers():
        enabled_count += 1
        print(f"   Enabled Handler {enabled_count}: {handler.__class__.__name__}")
    enabled_list = registry.get_enabled_handlers()
    print(f"\n   Enabled handlers (list): {len(enabled_list)}")
    print(f"   Enabled handlers (generator): {enabled_count}")


def demo_handler_registry_generators():
    """Demonstrate HandlerRegistry generator methods."""
    print("\n=== HandlerRegistry Generators ===")

    config = Config(str(Path(__file__).resolve().parents[2] / "etc" / "infra.yaml"))
    handlers_config = config.logging.handlers
    print(f"\n2. Loading {len(handlers_config)} handlers from configuration...")

    registry = HandlerRegistry()
    for handler_config in handlers_config.values():
        registry.add_handler_from_config(handler_config)

    _iterate_all_handlers(registry)
    _iterate_enabled_handlers(registry)


def demo_memory_efficiency():
    """Demonstrate memory efficiency of generators."""
    print("\n=== Memory Efficiency ===")

    print("\n5. Generators vs Lists:")
    print("   Generators are more memory-efficient for large collections")

    # Simulate a large number of handlers
    large_registry = HandlerRegistry()
    for i in range(1000):
        # This is just a simulation - in practice you'd load from config
        pass

    print("   ✓ Generator approach: yields one item at a time")
    print("   ✓ List approach: loads all items into memory at once")
    print("   ✓ Use generators when processing large handler collections")


def _print_handler_examples():
    """Print handler usage examples."""
    print("\n6. Processing all handlers:")
    print("    # Iterate through all handlers (enabled or disabled)")
    print("    for handler_config in registry.iter_handlers():")
    print("        if hasattr(handler_config, 'filename'):")
    print('            print(f"File handler: {handler_config.filename}")')
    print("\n7. Processing only enabled handlers:")
    print("    # Process only enabled handlers for logging setup")
    print("    for handler_config in registry.iter_enabled_handlers():")
    print("        actual_handler = handler_config.create_handler()")
    print("        logger.addHandler(actual_handler)")
    print("\n8. Finding specific handler types:")
    print("    # Find all file handlers")
    print("    file_handlers = [h for h in registry.iter_handlers()")
    print("                     if h.__class__.__name__.endswith('FileHandlerConfig')]")


def demo_practical_usage():
    """Show practical usage patterns."""
    print("\n=== Practical Usage Examples ===")
    _print_handler_examples()


if __name__ == "__main__":
    demo_handler_factory_generators()
    demo_handler_registry_generators()
    demo_memory_efficiency()
    demo_practical_usage()

    print("\n=== Summary ===")
    print("✓ HandlerFactory.iter_supported_types() - discover available types")
    print("✓ HandlerRegistry.iter_handlers() - iterate through all handlers")
    print("✓ HandlerRegistry.iter_enabled_handlers() - iterate through enabled only")
    print("✓ Memory-efficient for large handler collections")
    print("✓ Clean, Pythonic iteration patterns")
