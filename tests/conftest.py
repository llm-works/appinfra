"""
Pytest configuration and shared fixtures.

This module provides central pytest configuration, custom markers,
and shared fixtures for the infra test suite.
"""

import shutil
import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest

# =============================================================================
# Plugin Registration
# =============================================================================

# Register integration test fixtures and appinfra testing utilities
pytest_plugins = [
    "appinfra.testing",
    "tests.fixtures.pg_integration",
    "tests.fixtures.sqlite_integration",
    "tests.fixtures.logging",
]


# =============================================================================
# Pytest Configuration
# =============================================================================


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "unit: Unit tests (fast, isolated, no external dependencies)"
    )
    config.addinivalue_line(
        "markers", "integration: Integration tests (may use DB, network, filesystem)"
    )
    config.addinivalue_line("markers", "performance: Performance/benchmark tests")
    config.addinivalue_line(
        "markers", "security: Security-focused tests (injection, validation, etc.)"
    )
    config.addinivalue_line(
        "markers", "e2e: End-to-end tests (full system integration)"
    )
    config.addinivalue_line("markers", "slow: Tests that take >1 second to run")
    config.addinivalue_line(
        "markers", "asyncio: Mark test as an async test (requires async runner)"
    )


# =============================================================================
# Shared Fixtures
# =============================================================================


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """
    Provide a temporary directory that is cleaned up after the test.

    Yields:
        Path: Temporary directory path
    """
    temp_path = Path(tempfile.mkdtemp(prefix="infra-test-", dir="/tmp"))
    try:
        yield temp_path
    finally:
        shutil.rmtree(temp_path, ignore_errors=True)


@pytest.fixture
def temp_file(temp_dir: Path) -> Generator[Path, None, None]:
    """
    Provide a temporary file in a temporary directory.

    Args:
        temp_dir: Temporary directory fixture

    Yields:
        Path: Temporary file path
    """
    temp_file_path = temp_dir / "test_file.txt"
    temp_file_path.touch()
    yield temp_file_path


@pytest.fixture
def sample_config_dict() -> dict:
    """
    Provide a sample configuration dictionary for testing.

    Returns:
        dict: Sample configuration
    """
    return {
        "app": {
            "name": "test_app",
            "version": "1.0.0",
            "debug": True,
        },
        "database": {
            "host": "localhost",
            "port": 5432,
            "name": "test_db",
        },
        "logging": {
            "level": "debug",
            "format": "%(message)s",
        },
    }


# =============================================================================
# Test Collection Hooks
# =============================================================================


def pytest_collection_modifyitems(config, items):
    """
    Modify test collection to add markers and skip conditions.

    Args:
        config: Pytest config object
        items: List of collected test items
    """
    # Add 'unit' marker to tests without other markers
    for item in items:
        if not any(
            mark.name in ["integration", "performance", "security", "e2e"]
            for mark in item.iter_markers()
        ):
            item.add_marker(pytest.mark.unit)


# =============================================================================
# Output Control Hooks
# =============================================================================


def pytest_report_teststatus(report, config):
    """
    Suppress dots and progress output for cleaner test runs.

    When verbosity is low (quiet mode), this hook returns empty strings
    for the test status characters, hiding the dots/F/E/s characters and
    progress percentages while keeping the final summary.

    Args:
        report: Test report object
        config: Pytest config object

    Returns:
        tuple: (outcome, letter, verbose_word) or None
    """
    # Only suppress output in quiet mode (-q or -qq) and only for the main test execution
    if config.option.verbose < 0 and report.when == "call":
        # Return empty letter to suppress dots/progress
        return report.outcome, "", ""
    # Default behavior for normal/verbose modes
    return None
