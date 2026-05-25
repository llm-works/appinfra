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

from tests._pg_probe import (
    PG_SKIP_REASON,
    PG_STATUS_KEY,
    REQUIRE_PG_MARKER,
    probe,
    resolve_pgserver_endpoint,
)

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


_MARKERS = [
    ("unit", "Unit tests (fast, isolated, no external dependencies)"),
    ("integration", "Integration tests (may use DB, network, filesystem)"),
    ("performance", "Performance/benchmark tests"),
    ("security", "Security-focused tests (injection, validation, etc.)"),
    ("e2e", "End-to-end tests (full system integration)"),
    ("slow", "Tests that take >1 second to run"),
    ("asyncio", "Mark test as an async test (requires async runner)"),
    (
        REQUIRE_PG_MARKER,
        "Test requires a running PostgreSQL server "
        "(skipped with a single banner if unavailable)",
    ),
]


def pytest_configure(config):
    """Register custom markers and probe PG availability once per session."""
    for name, desc in _MARKERS:
        config.addinivalue_line("markers", f"{name}: {desc}")

    # One-shot PG reachability probe. Stashed so pytest_collection_modifyitems,
    # the pg_available fixture, and pytest_terminal_summary all read the same result.
    host, port = resolve_pgserver_endpoint()
    config.stash[PG_STATUS_KEY] = {
        "host": host,
        "port": port,
        "available": probe(host, port),
    }


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

    # Skip @pytest.mark.require_pg tests with the uniform sentinel reason when
    # PG is unreachable. The terminal-summary banner consolidates them.
    status = config.stash.get(PG_STATUS_KEY, None)
    if status and not status["available"]:
        skip_marker = pytest.mark.skip(reason=PG_SKIP_REASON)
        for item in items:
            if any(m.name == REQUIRE_PG_MARKER for m in item.iter_markers()):
                item.add_marker(skip_marker)


# =============================================================================
# Output Control Hooks
# =============================================================================


def _partition_pg_skips(skipped):
    """Split skip reports into (kept, sentinel_count). report.longrepr is a
    (file, lineno, reason) tuple for skips."""
    kept = []
    sentinel_count = 0
    for report in skipped:
        reason = ""
        if isinstance(report.longrepr, tuple) and len(report.longrepr) == 3:
            reason = report.longrepr[2] or ""
        if PG_SKIP_REASON in reason:
            sentinel_count += 1
        else:
            kept.append(report)
    return kept, sentinel_count


@pytest.hookimpl(tryfirst=True)
def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Collapse PG-unavailable skips into one banner. Registered tryfirst so we
    filter terminalreporter.stats before pytest's built-in summary plugin runs."""
    skipped = terminalreporter.stats.get("skipped", [])
    if not skipped:
        return
    kept, sentinel_count = _partition_pg_skips(skipped)
    if sentinel_count == 0:
        return
    terminalreporter.stats["skipped"] = kept
    status = config.stash.get(PG_STATUS_KEY, None)
    location = (
        f"{status['host']}:{status['port']}" if status else "configured host:port"
    )
    terminalreporter.write_sep(
        "-",
        f"PG unavailable at {location} — {sentinel_count} tests skipped. "
        f"Run `make pg.server.up` to enable them.",
        yellow=True,
        bold=True,
    )


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
