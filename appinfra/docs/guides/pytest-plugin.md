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

### `fake_clock`

Runs time-based code on a virtual clock, `FakeClock`, that moves only when slept on: a
`time.sleep(3600)` returns at once and advances the clock by exactly 3600 seconds, so a test of
retries, timeouts or rate limits runs in microseconds and asserts exact times. appinfra's
`Ticker`, `RateLimiter` and `ETA` are on the clock for every test that takes the fixture;
`patch()` adds a project's own modules:

```python
# myapp/retry.py
import time


def retry(op, attempts, delay):
    for _ in range(attempts - 1):
        if op():
            return True
        time.sleep(delay)
    return op()
```

```python
from myapp.retry import retry


def test_retry_gives_up_after_three_attempts(fake_clock):
    fake_clock.patch("myapp.retry")
    assert retry(lambda: False, attempts=3, delay=60.0) is False
    assert fake_clock.monotonic() == 1000.0 + 120.0
```

In a patched module, `time.monotonic()`, `time.time()` and `time.sleep()` read and advance the
clock: `monotonic()` starts at 1000.0 and `time()` at the real wall-clock time. Every other
`time` function stays real, and modules not patched (pytest, logging) keep real time. The
patches end with the test.

`FakeClock` also works without the fixture, as a context manager or a decorator, with
`modules` naming the modules to patch:

```python
from appinfra.testing import FakeClock

with FakeClock(modules=["myapp.retry"]) as clock:
    retry(lambda: False, attempts=3, delay=60.0)
    assert clock.monotonic() == 1120.0
```

Limits:

- Only a module-level `import time` is redirected. `from time import sleep` binds the real
  function when the module is imported, so `patch()` cannot reach it; such a module needs
  `import time` to run on the clock.
- Code on the clock runs in one thread. The `Ticker`'s `threading.Event` waits advance the clock
  instead of blocking, so a wait that is not already set runs out its full timeout.
- Objects that capture time functions when created, such as a `Ticker`'s scheduler, must be
  created after the clock is active.

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
