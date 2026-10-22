# Pytest Plugin (`appinfra.testing`)

The `appinfra.testing` module provides pytest utilities for common testing patterns. Use it as a
pytest plugin to access custom markers, hooks and fixtures.

## Setup

Add to your `conftest.py`:

```python
pytest_plugins = ["appinfra.testing"]
```

## Markers

### `expected_skip`

Mark tests where skipping is expected and acceptable. These skips won't appear in `check.sh`
warning summaries.

**Use cases:**
- Platform-specific tests (Windows-only, Unix-only)
- Tests requiring optional dependencies
- Tests that only run in specific environments (xdist master, CI, etc.)

**Example:**

```python
import os
import sys
import pytest


@pytest.mark.expected_skip
@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only test")
def test_windows_registry():
    """Test Windows registry access."""
    ...


@pytest.mark.expected_skip
@pytest.mark.skipif(
    os.environ.get("PYTEST_XDIST_WORKER") is not None,
    reason="Only runs on master process",
)
def test_cleanup_at_session_start(pg_session):
    """Test that runs only on master, not xdist workers."""
    ...
```

**How it works:**

When a test with `expected_skip` is skipped, the plugin prefixes the skip reason with `[expected]`.
The `check.sh` script filters these from the warning summary, so only unexpected skips are
reported.

## Fixtures

### `destroy_test_loggers` (autouse)

`LoggerFactory.create()` raises `LoggerExistsError` for a name this process already holds, so a
logger one test leaves behind fails the next test in the same process that creates the same name.
This fixture runs around every test: it records `LoggerFactory.names()` before the test and
destroys the names added during it. Loggers created before the test, by session or module
fixtures, stay. A logger shared across tests some other way (a cached helper, a module global)
is destroyed after the test that first creates it, and later tests get the destroyed object, which
has no handlers; create such a logger in a session-scoped fixture instead.

Nothing to add to your tests: loading the plugin is enough. A fixture that builds a logger can
create it with a fixed name:

```python
import logging

import pytest

from appinfra.log import LogConfig, LoggerFactory


@pytest.fixture
def lg():
    return LoggerFactory.create("/test", LogConfig(level=logging.DEBUG))
```

## Integration with `check.sh`

The `make check` command shows a skip summary at the end:

```text
✓ All checks passed in 35.2s

⚠ Warning: 3 tests skipped
  - 2 skipped: Database not available
  - 1 skipped: Requires GPU
```

Tests marked with `expected_skip` are excluded from this warning. This helps you:
- Identify unintentional skips that need attention
- Keep expected skips (platform-specific, optional deps) from cluttering the output
- Maintain a clean baseline where warnings indicate real issues

## Best Practices

1. **Use `expected_skip` sparingly** - Only for genuinely expected skips, not to hide problems
2. **Prefer `skipif` over body skips** - Declarative markers are clearer than `pytest.skip()` in
   test body
3. **Document why** - Include clear skip reasons that explain the constraint
4. **Review periodically** - Expected skips can become stale; review if constraints still apply
