# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

For API stability guarantees and deprecation policy, see
[API Stability Policy](appinfra/docs/guides/api-stability.md).

## [Unreleased]

### Added
- `Channel` and `AsyncChannel` are now **protocols** — smart transports (ZMQ, gRPC) can implement
  the channel interface directly without wrapping in a `BufferedChannel`
- `BufferedChannel` and `AsyncBufferedChannel` are the concrete implementations that wrap a
  `Transport`/`AsyncTransport` with request/response correlation and redelivery buffering
- Pluggable transport for `appinfra.service`: `Transport` and `AsyncTransport` protocols define
  the wire level (`send`/`recv`/`close`/`is_closed`)
- `ChannelPairFactory` protocol and injection points (`channel_factory` on `RunnerFactory`,
  per-call `channel_pair` on `create_*_with_channel()` methods)
- Built-in transports: `QueueTransport`, `ProcessQueueTransport`, `AsyncQueueTransport`,
  `AsyncProcessQueueTransport`

### Changed
- **Breaking**: `Channel` and `AsyncChannel` are now concrete (composition over inheritance);
  `ThreadChannel`, `ProcessChannel`, `AsyncThreadChannel`, `AsyncProcessChannel` removed —
  use `QueueChannelFactory`/`ProcessQueueChannelFactory` or `BufferedChannel(transport)` directly
- **Breaking**: `Channel` and `AsyncChannel` are now protocols; the concrete classes are renamed
  to `BufferedChannel` and `AsyncBufferedChannel` — code constructing `Channel(transport)` must
  use `BufferedChannel(transport)` instead; `isinstance(x, Channel)` still works
- **Breaking**: `ChannelFactory` replaced by `QueueChannelFactory`, `ProcessQueueChannelFactory`,
  `AsyncQueueChannelFactory`, `AsyncProcessQueueChannelFactory` — each with a single
  `create_pair()` method
- **Breaking**: `ChannelPairFactory` protocol uses single `create_pair()` method instead of
  separate `create_thread_pair()`/`create_process_pair()`
- **Breaking:** `IPCChannel.submit()` no longer takes a separate `request_id` parameter. The ID is
  now extracted from the request object's `id` attribute. This simplifies the API and prevents
  mismatches between the request ID and the request object.
  - Old: `await ipc.submit(request_id, request, timeout=30.0)`
  - New: `await ipc.submit(request, timeout=30.0)` (request must have `.id` attribute)
- FastAPI subprocess mode now uses `ProcessRunner` from the service package instead of the internal
  `SubprocessManager`. This provides better integration with the service execution framework and
  enables monitor-based auto-restart.

### Fixed
- `python -m appinfra.version.build_info` now includes `MODIFIED` field, matching setuptools hook
- `make check` reported `cq.strict` target even when `INFRA_DEV_CQ_STRICT=false`
- Documentation index files referenced non-existent `exceptions.md` (renamed to `errors.md` in v0.5.0)
- Missing API doc reference for `fastapi.md` in `docs/api/index.md`
- Missing guides in `docs/index.md`: api-stability, framework-integration, pytest-plugin
- Missing example sections in `docs/index.md` and `examples/README.md` for examples 07-12


### Added
- HTTP rate limiting middleware for FastAPI servers (`appinfra.app.fastapi.ratelimit`):
  - `RateLimiter` ABC defining the interface for pluggable rate limiting strategies
  - `TokenBucketLimiter`: O(1) per-request rate limiting with configurable burst, per-IP or global
    keying, proxy header support (`X-Forwarded-For`, `CF-Connecting-IP`), and automatic stale entry
    cleanup
  - Raw ASGI middleware (not BaseHTTPMiddleware) for correct streaming/background task behavior
  - `ServerBuilder.with_rate_limiter()` integration with exempt path support
  - Multiple limiters can be chained (e.g., global + per-IP); first to deny wins
  - 429 responses with `Retry-After` header; `X-RateLimit-Limit`/`X-RateLimit-Remaining` on 200s
  - Pickle-safe for subprocess mode (fresh state per worker)
- README documentation for `examples/07_fastapi/` (FastAPI server modes)
- README documentation for `examples/11_docs/` (documentation generation)
- Service execution framework (`appinfra.service`) for managing service lifecycles:
  - **Three-layer architecture**: Service (what to run), Runner (how to run), Manager (orchestration)
  - **State machine**: Explicit states (CREATED, INITD, STARTING, RUNNING, IDLE, STOPPING, STOPPED,
    FAILED, DONE) with validated transitions and state change hooks
  - **ThreadRunner**: Runs `service.execute()` in a daemon thread
  - **ProcessRunner**: Runs `service.execute()` in a subprocess using `multiprocessing.Process`
    - Queue-based logging forwarded to parent process via `LogQueueListener`
    - IPC for shutdown signaling and health status
  - **ScheduledService**: Base class for services with periodic `tick()` execution
  - **Manager**: Orchestrates multiple services with dependency ordering and parallel start/stop
  - **RestartPolicy**: Configurable restart behavior with exponential backoff
  - **Dependency graph**: Uses stdlib `graphlib.TopologicalSorter` for cycle detection and ordering
  - **Bidirectional channels** for service communication (sync and async):
    - Sync: `ThreadChannel`, `ProcessChannel` for threaded code
    - Async: `AsyncThreadChannel`, `AsyncProcessChannel` for asyncio code
    - `Message`: Generic message with id for request/response correlation
    - `submit()`: Request/response pattern with timeout (blocking or async)
    - `submit_stream()`: Streaming responses (yields chunks until `is_final=True`)
    - `send()`/`recv()`: Fire-and-forget messaging
  - **Factory classes** for centralized component creation:
    - `ChannelFactory`: Creates channel pairs with consistent configuration
      - `create_thread_pair()`, `create_process_pair()` for sync channels
      - `create_async_thread_pair()`, `create_async_process_pair()` for async channels
    - `ChannelPair`, `AsyncChannelPair`, `AsyncProcessChannelPair`: Typed pair containers
    - `RunnerFactory`: Creates runners with optional channel wiring
    - `ServiceFactory`: Registry-based service creation with dependency injection
- `Service.lg` property for accessing the logger instance

## [0.5.0] - 2026-03-14

### Fixed
- `make check` now shows failing test names and error details when tests fail
  (previously only showed pass/fail count with no details)
- `RateLimiter` is now thread-safe: concurrent calls from multiple threads no longer
  cause race conditions that could result in exceeding the rate limit
- `RateLimiter` no longer allows burst at startup: first request now waits like
  subsequent requests, preventing thundering herd when multiple threads start
  simultaneously

### Changed
- **BREAKING:** Renamed error classes for consistency (shorter names):
  - `ApplicationError` → `AppError` (appinfra.app.errors)
  - `ConfigurationError` → `ConfigError` (appinfra.app.errors)
  - `LogConfigurationError` → `LogConfigError` (appinfra.log.errors)
  - `InvalidConfigurationError` → `InvalidConfigError` (appinfra.time.sched)
- **BREAKING:** Renamed exception modules from `exceptions.py` to `errors.py` for consistency:
  - `appinfra.exceptions` → `appinfra.errors`
  - `appinfra.log.exceptions` → `appinfra.log.errors`
  - `appinfra.net.exceptions` → `appinfra.net.errors`
  - Update imports: `from appinfra.exceptions import ...` → `from appinfra.errors import ...`
- **BREAKING:** FastAPI `ServerBuilder` and `Server` now require `lg: Logger` as first parameter:
  - Before: `ServerBuilder("name")` / `Server(name="name", ...)`
  - After: `ServerBuilder(lg, "name")` / `Server(lg, name="name", ...)`
  - Enables queue-based subprocess logging that inherits main process log level
  - Exception handlers using `self._lg` now log at correct level in subprocess mode
- **BREAKING:** FastAPI lifecycle callback failures now raise `CallbackError` instead of being swallowed:
  - Startup, shutdown, and exception callbacks that fail now propagate errors
  - Errors are logged first if logger is available, then `CallbackError` is raised
- **BREAKING:** Using both `with_lifespan()` and `with_on_startup()`/`with_on_shutdown()` now raises
  `ConfigError` instead of logging a warning and ignoring callbacks

### Added
- `ScopedPG` for per-operation schema selection without engine-level binding:
  - `pg.scoped("schema_name")` returns a `ScopedPG` instance
  - Sessions have `search_path` set at session level, not via engine event listeners
  - Single PG instance can serve multiple schemas (no instance caching needed)
  - `scoped.session()` is a context manager with automatic commit/rollback/close
  - `scoped.ensure_schema()` creates schema if it doesn't exist
- FastAPI: `ExceptionHandler` base class for subprocess mode with Logger support:
  - Handles Logger pickle/unpickle automatically; subclass and implement `handle()`
  - Build-time validation catches unpicklable handlers with clear error messages
- FastAPI: Queue-based subprocess logging forwards logs to main process:
  - Subprocess Logger inherits level from main process (e.g., debug, info, warning)
  - Uses `Logger.queue_config()` and `Logger.from_queue_config()` pattern
- FastAPI: Logger injection in subprocess mode:
  - Route handlers: access via `request.state.lg` (set per-request by middleware)
  - Middleware: access via `request.app.state.lg` (set at startup, available immediately)
  - Due to middleware ordering, custom middleware runs before logger injection middleware
- FastAPI: New error classes `CallbackError` and `ConfigError` for cleaner error handling
- `!deep` YAML tag for recursive deep merging with YAML merge keys (`<<`):
  - Standard merge keys do shallow merge (nested dicts replaced entirely)
  - `!deep` enables deep merge where nested dicts are recursively merged
  - Supported syntaxes:
    - `<<: !deep *anchor` - deep merge single anchor
    - `<<: !deep [*a, *b]` - deep merge all items in list
    - `<<: [*a, !deep *b]` - mixed shallow/deep per item
    - Multiple `<<:` keys with independent shallow/deep control
  - Example: template `{nested: {a: 1}}` + override `{nested: {b: 2}}` = `{nested: {a: 1, b: 2}}`
- `!include` now always deep merges when used with merge keys (`<<: !include "file.yaml"`)
- `!reset` YAML tag to bypass deep merge for specific keys:
  - Use when you want to completely replace a value instead of deep merging
  - Example: `options: !reset` followed by indented content replaces entire `options`

### Fixed
- Added `setuptools` to dev dependencies (required by `sphinx.setup_command`)
- Test for `!path` YAML tag now uses non-existent paths to avoid symlink resolution issues
- `PG` testing fixtures now handle `create_db` race conditions with pytest-xdist:
  - Uses PostgreSQL advisory locks to coordinate database creation across workers
  - Prevents "database already exists" errors when multiple workers start simultaneously
- `MPQueueHandler` now recursively sanitizes exceptions in `__infra__extra` for pickling.
  Previously only handled the `exception` key; now handles any key and nested structures.

## [0.4.1] - 2026-02-25

### Added
- `FieldDict` - typed DotDict with field declarations for IDE autocomplete:
  - Required/optional fields with defaults, `field(default_factory=...)` for mutable defaults
  - `__post_init__` hook for computed fields, optional `strict=True` mode
- `appinfra.testing` pytest plugin with `expected_skip` marker for acceptable skips:
  - Prefixes skip reasons with `[expected]` for filtering in `check.sh`
  - See `appinfra docs show pytest-plugin` for usage
- `check.sh` now displays skip summary with grouped reasons:
  - Shows count and reasons for skipped tests at end of check output
  - Expected skips (marked with `[expected]`) are filtered from warnings
  - Helps identify unintentional test skips that need attention
- `make check.nt` target for running code quality checks without tests:
  - Runs formatting, linting, type checking, docstring coverage
  - Skips all test suites (unit, integration, e2e, security, performance)
  - Useful for quick feedback during development

### Fixed
- `make install` and `make install.e` now clean build artifacts before installing:
  - Removes `*.egg-info`, `.dist`, `.build`, `dist`, `build` directories
  - Prevents stale cached files from being reinstalled after `make uninstall`
- Test directory `tests/infra/app/fastapi/` renamed to `tests/infra/app/fastapi_tests/`:
  - Prevents package shadowing when pytest-xdist adds test directories to `sys.path`
  - Eliminates spurious "FastAPI not available" skips in parallel test runs

## [0.4.0] - 2026-02-20

### Fixed
- `INFRA_DEV_SKIP_TARGETS` now works for pytest targets in `Makefile.pytest`:
  - Supported targets: `test.unit`, `test.integration`, `test.e2e`, `test.perf`, `test.security`
  - Skipping a target also skips its verbose variant (e.g., `test.e2e` skips `test.e2e.v`)
  - Use case: Projects needing custom test configurations (e.g., GPU tests with `-n 0`)

### Added
- `appinfra.py` top-level entry point for running CLI during development:
  - Ensures local source takes precedence over installed package
  - Run with `./appinfra.py` instead of `python ./appinfra/cli/cli.py`
- `DependencyError` exception for clear error messages when optional dependencies are missing:
  - Shows which package is missing and how to install it
  - Example: `Database logging requires 'sqlalchemy' which is not installed. Install it with: pip install appinfra[sql]`
- `[sql]` optional extra for database features (sqlalchemy, sqlalchemy-utils, psycopg2-binary):
  - Core appinfra no longer requires sqlalchemy - install only if using database features
  - Enables faster CLI startup and smaller install footprint for non-database use cases
  - Database logging (`log.builder.database`) and database module (`db`) require this extra
- `[all]` optional extra that includes all other extras (dev, docs, sql, ui, fastapi, validation, hotreload):
  - Single install command for full development environment: `pip install appinfra[all]`
- `Backoff` class for exponential backoff retry logic:
  - Configurable base delay, max delay, growth factor, and jitter
  - `wait()` method for blocking backoff (sleeps and returns delay)
  - `next_delay()` method for non-blocking usage (returns delay, increments attempt)
  - `reset()` method to reset attempt counter after successful operations
  - Full jitter pattern (delay * 0.0-1.0) to avoid thundering herd problems
- Non-blocking `RateLimiter.try_next()` method for event loops that cannot block:
  - Returns `True` if operation is allowed (updates `last_t`), `False` if rate limited
  - Does not modify state when returning `False` (safe to call repeatedly)
  - Mirrors `Ticker.try_tick()` semantics: "attempt if ready, skip if not"
  - Use case: Rate-limit retries in message-processing loops without blocking signal handling
- Non-consuming `RateLimiter.can_proceed()` method for availability checks:
  - Returns `True` if rate limit would allow an operation, `False` if rate limited
  - Does NOT consume a rate limit slot (never modifies `last_t`)
  - Safe to call repeatedly - multiple calls return the same value
  - Use case: Event loops that need to check availability without committing to an operation
- Non-blocking Ticker API for mixed event sources (`time_until_next_tick()` and `try_tick()`):
  - `time_until_next_tick(now=None)` returns seconds until next tick (use as timeout for event loops)
  - `try_tick(now=None)` executes tick if ready, returns `bool` (works with or without handler)
  - Both methods accept optional `now` parameter for drift-free operation with shared timestamps
  - Supports timing oracle mode without handler: `if ticker.try_tick(): do_work()`
  - Example: `msg = channel.recv(timeout=ticker.time_until_next_tick()); ticker.try_tick()`
- `TickerMode` enum for timing behavior control:
  - `FLEX` (default): Flexible timing - fixed-rate from tick start, no catch-up (resets if late)
  - `STRICT`: Strict timing - maintains average rate by catching up if tasks run slow
  - `SPACED`: Spaced timing - waits full interval from task completion for guaranteed minimum spacing
- Monotonic time for drift-free ticker operation:
  - All Ticker timing now uses `time.monotonic()` instead of `time.time()`
  - Immune to NTP adjustments, daylight saving time changes, and system clock modifications
  - Guaranteed monotonic progression for accurate interval timing
  - Works correctly with Python's `sched.scheduler`

### Changed
- Coverage output directory renamed from `.coverage/` to `.cover/`:
  - Avoids conflict with pytest-cov's `.coverage` SQLite database file
  - Updated in Makefile.pytest, docker-compose.yml, and GitHub workflows
- Code quality checker (`appinfra cq cf`) now excludes hidden directories by default:
  - Skips `.build/`, `.cover/`, `.venv/`, and other dotfile directories
  - Skips `__pycache__/` directories
  - Prevents false positives from build artifacts
- Linter configuration (ruff, mypy) now excludes build artifact directories:
  - `.build`, `.dist`, `.cover`, `.htmlcov`, `.site`
- Type annotation cleanup (internal):
  - Replaced string-quoted self-returns with `typing.Self` across builder classes
  - Removed unnecessary `from __future__ import annotations` from ~20 files
  - Enabled ruff rule UP037 to enforce unquoted type annotations
  - Standardized forward reference handling via future annotations only where needed
- Ticker timing is now drift-free by capturing `time.monotonic()` once per tick
  - Accurate: 3600 ticks in exactly 3600 seconds (for `secs=1`)
  - No accumulated drift from multiple time queries per tick

### Fixed
- `@builder.tool` decorator now compatible with `with_main_tool()`:
  - `DecoratedTool.set_args()` now accepts `skip_positional` parameter matching base `Tool` class
  - Previously raised `TypeError: got an unexpected keyword argument 'skip_positional'`
- RateLimiter API docs corrected to match actual implementation (`per_minute`/`next()` instead of
  incorrect `max_calls`/`period`/`acquire()`)
- Ticker API mode mixing protection: `try_tick()` and `run()` cannot be mixed on the same instance
  - Prevents state corruption from shared `_first` flag between different API modes
  - Clear error message: "Cannot call run() after using try_tick()"
- `make type` and `make check` now use separate mypy cache directories for package vs examples:
  - Package uses `.mypy_cache/pkg/`, examples use `.mypy_cache/examples/`
  - Prevents cache invalidation caused by different mypy flags between the two runs
  - Reduces repeated type check time from ~17s to ~1s (cache now works correctly)

## [0.3.5] - 2026-02-11

### Added
- Standard CLI arguments for agent-friendly log output:
  - `--log-json` - Output logs in JSON format (overrides YAML handler `format: text`)
  - `--no-log-colors` - Disable colored log output (overrides YAML handler `colors: true`)
  - Both flags apply to all console handlers defined in config, not just the first one
  - Available by default; disable with `.with_standard_args(log_json=False, log_colors=False)`
- `ConsoleHandlerConfig.colors` parameter for handler-specific color control. When set, overrides
  the global `LogConfig.colors` setting for that specific handler.
- Configuration precedence guide (`docs/guides/configuration-precedence.md`) documenting the full
  override hierarchy: CLI args > Environment variables > YAML config > Defaults. Also covers
  topic-level priorities (API=10, CLI=5, YAML=1) and handler override behavior.
- Docstring coverage checking via `interrogate`:
  - `make cq.docstring` - Report docstring coverage without failing
  - `make cq.docstring.strict` - Fail if below threshold
  - Integrated into `make check` with percentage display (e.g., `95.30% ≥ 95%`)
  - Configurable via `INFRA_DEV_DOCSTRING_THRESHOLD` (default: 80, set to 0 to disable)

### Changed
- `DotDict.__init__()` now accepts dict as positional argument, matching built-in `dict()` API:
  - `DotDict({"a": 1, "b": 2})` now works alongside existing `DotDict(a=1, b=2)`
  - Kwargs override positional dict values when both are provided
  - Backward compatible - existing code using only kwargs continues to work
- Default coverage threshold lowered from 95% to 80% (`INFRA_PYTEST_COVERAGE_THRESHOLD`)
  - Projects can override to higher thresholds as needed
  - appinfra itself still uses 95% for both test and docstring coverage

### Fixed
- Environment variable overrides with hyphenated YAML keys now handle edge cases correctly:
  - Fixed `AttributeError` crash when env vars target non-dict YAML values (scalars, lists, null)
  - Fixed ambiguous key matching - `INFRA_SERVICES_WEB_SERVER_PORT` now correctly prioritizes
    exact matches (`web_server`) over shorter matches (`web`)
  - Scalar and null values are now replaced with dicts when env vars create nested paths
  - List values remain unchanged when env vars attempt nested overrides (cannot traverse into lists)
  - Added comprehensive test coverage (23 new tests) for edge cases and backward compatibility
- Coverage display formatting now consistent across all projects:
  - Both actual and target percentages show 1 decimal place (e.g., `89.9% ≥ 90.0%`)
  - Uses pessimistic floor rounding to prevent misleading displays (89.99% shows as 89.9%, not 90.0%)
  - Previously varied between 0-2 decimals depending on pytest output
- PG config normalization - plain dict configs now converted to DotDict instead of SimpleNamespace,
  providing consistent dot-notation access across all config types

## [0.3.4] - 2026-02-03

### Added
- Documentation for merge policy and release process in contributing guide
- Multiprocess logging support (`appinfra.log.mp`) for child processes:
  - **Queue mode**: `MPQueueHandler` in subprocesses sends records to parent via `LogQueueListener`
  - **Independent mode**: `LoggingBuilder.to_dict()`/`from_dict()` for self-sufficient subprocess logging
  - `Logger.with_queue(queue, name)` convenience method for subprocess queue handlers
  - Automatic exception formatting before pickling (traceback preserved across processes)
  - Database handlers are excluded from serialization (not supported in multiprocess mode)
- Simplified queue config API for multiprocess logging:
  - `Logger.queue_config(queue)` - Creates a picklable config dict containing queue, level, and
    `LogLevelManager` rules. One call captures everything workers need.
  - `Logger.from_queue_config(config, name)` - Creates a subprocess logger from the config. Pattern-based
    level rules are restored and applied based on the logger name.
  - `LogLevelManager.to_dict()` / `from_dict()` - Serialize and restore topic-based level rules for
    multiprocess scenarios
- `ErrorContext` and `IncludeContext` dataclasses in `appinfra.yaml` for error location tracking

### Changed
- Refactored `appinfra.yaml` from single module to package for better maintainability.
  Public API unchanged - all existing imports (`load`, `Loader`, `deep_merge`, `ErrorContext`,
  `IncludeContext`, `SecretLiteralWarning`) continue to work.

### Fixed
- Examples now work when run from the repository. Path setup was incorrect (`parents[2]` instead
  of `parents[3]`), causing the local `yaml/` module to shadow PyYAML. Also added missing path
  setup to 3 examples and removed stale `02a_app_using_framework` directory.
- YAML `!include` directive errors now logged with file location instead of failing silently.
  Previously, when `AppBuilder.with_config_file()` loaded a config with a bad `!include`
  (missing file, circular include, etc.), the error was silently swallowed, resulting in empty
  config sections with no indication of what went wrong. Now errors are stored during config
  loading and logged with file path, line number, and column once the logger is initialized.
- Variable interpolation in section includes (`!include './file.yaml#section'`) now works
  correctly. Previously, `${sibling.key}` references to other sections in the same source file
  would fail because section extraction happened before variable resolution. Now variables are
  resolved within the full file context before extracting the section.

## [0.3.3] - 2026-01-29

### Added
- PostgreSQL schema isolation for parallel test execution and multi-tenant applications. Each `PG`
  instance can use a dedicated schema (e.g., `test_gw0`, `test_gw1`) to isolate data. Useful for
  running tests with pytest-xdist without race conditions.
  - `PG(logger, config, schema="my_schema")` - Initialize with schema isolation
  - `pg.schema` property - Get configured schema name
  - `pg.create_schema()` - Create the schema if it doesn't exist
  - Tables are created in the schema during `pg.migrate()`
  - Queries are routed via `search_path` (includes `public` for extension visibility)
- `SchemaManager` class for direct schema management (`appinfra.db.pg.SchemaManager`)
- Pytest fixtures module for schema-isolated testing (`appinfra.db.pg.testing`):
  - `pg_test_schema` - Generates unique schema name per pytest-xdist worker
  - `pg_isolated` - Session-scoped PG with schema isolation
  - `pg_session_isolated` - Per-test session with auto commit/rollback
  - `pg_clean_schema` - Fresh schema for each test
  - `pg_migrate_factory` - Context manager factory for PG with migrations (recommended)
  - `make_migrate_fixture(Base)` - Legacy factory for migration fixtures
- `schema` field in database config for declarative schema isolation

### Fixed
- `make check` fail-fast now immediately kills remaining background jobs when a check fails.
  Previously, fail-fast only stopped waiting for results while other checks (especially tests)
  continued running in the background until script exit.
- `PytestAssertRewriteWarning` when using `appinfra.db.pg.testing` with `make_migrate_fixture`.
  The new `pg_migrate_factory` fixture avoids the warning by not requiring imports from the module.

## [0.3.2] - 2026-01-25

### Added
- PEP 561 `py.typed` marker file for type checker support. Downstream packages can now use appinfra's
  type annotations with mypy/pyright without `--ignore-missing-imports`.
- Documentation for argparse positional argument ordering limitation in `app.md`
- `INFRA_DEV_MYPY_FLAGS` variable for passing extra flags to mypy (e.g., `--follow-imports=skip`
  for projects with large dependencies like torch/transformers that cause mypy to hang)
- `INFRA_DEV_SKIP_TARGETS` variable to skip built-in targets (`fmt`, `lint`, `type`, `cq`) so
  projects can provide their own implementations (e.g., custom mypy flags per directory)

### Changed
- `Tool.lg` property now returns `Logger` instead of `Logger | None`. Raises `MissingLoggerError`
  if accessed before `setup()`. This eliminates the need for defensive `if self.lg:` checks or
  `assert self.lg is not None` in tool code. The logger is always available after `setup()` runs.

### Fixed
- `check.sh` now runs E2E and Performance tests sequentially using `-n 0` instead of `-n 1`.
  Previously, `-n 1` still used pytest-xdist with a single worker, which behaves differently than
  true sequential execution.
- `check.sh` now respects `PYTEST_PARALLEL` for E2E and Performance test commands, allowing parallel
  execution when explicitly enabled.

## [0.3.1] - 2026-01-20

### Added
- Lifecycle callback support for FastAPI ServerBuilder:
  - `with_on_startup(callback)` - Run async callbacks when app starts
  - `with_on_shutdown(callback)` - Run async callbacks when app shuts down (continues on errors)
  - `with_lifespan(context_manager)` - Use FastAPI's modern lifespan pattern
  - `with_on_request(callback)` - Run callbacks before each request (after custom middleware)
  - `with_on_response(callback)` - Run callbacks after each request (can modify response)
  - `with_on_exception(callback)` - Run callbacks on unhandled exceptions
- Request/response callbacks run inside custom middleware, allowing access to auth state and other
  middleware-injected context
- Startup callback failures now include callback name in error message for easier debugging
- Shutdown callbacks continue executing even if earlier callbacks fail (errors are logged)
- `INFRA_DEV_CQ_EXCLUDE` variable for excluding directories from function size checks. Set glob
  patterns (e.g., `INFRA_DEV_CQ_EXCLUDE := examples/* scripts/*`) to skip specified paths in both
  `make cq` and `make check`.

### Fixed
- `with_on_startup()` no longer breaks IPC response queue in subprocess mode. Previously, using
  lifecycle callbacks with `.subprocess.with_ipc()` caused responses to never be delivered because
  FastAPI ignores `on_event()` handlers when a lifespan is present. IPC polling is now integrated
  directly into the adapter's lifespan context manager.
- `with_main_tool()` no longer causes positional argument conflicts with subcommands. Previously,
  main tool positional args were hoisted to the root parser, consuming arguments before the
  subcommand name could be recognized (e.g., `./app query "file"` would fail because `"query"` was
  consumed by the main tool's positional arg). Now only optional arguments are hoisted.
- YAML merge keys (`<<: *anchor`) now work correctly when source tracking is enabled. Previously,
  Config class would fail with `ConstructorError` when loading YAML files using anchors and merge
  keys.

## [0.3.0] - 2026-01-15

### Added
- Custom Docker image support for PostgreSQL server via `pgserver.image` config field. Enables using
extension images like `pgvector/pgvector:pg16` or `timescale/timescaledb:latest-pg16`. When `image`
is specified, `version` becomes optional. The image must be PostgreSQL-compatible (based on official
  `postgres` image) as docker-compose passes postgres-specific CLI arguments.
- PostgreSQL server configuration via `pgserver.postgres_conf` dict for passing `-c key=value`
  parameters to postgres. Supports strings, integers, booleans (converted to on/off), and lists
  (joined with commas for `shared_preload_libraries` etc.).
- Declarative PostgreSQL extension support via `dbs.<name>.extensions` list. Extensions are created
  with `CREATE EXTENSION IF NOT EXISTS` during `PG.migrate()`. Extension names are validated to
  prevent SQL injection.
- Lifecycle hooks for PG class: `pg.on_before_migrate(callback)` and `pg.on_after_migrate(callback)`
  for custom setup/teardown during migrations. Callbacks receive a SQLAlchemy connection object.

### Changed
- Removed hardcoded PostgreSQL parameters from docker-compose files. Server now starts with
  PostgreSQL defaults unless `postgres_conf` is specified. Recommended settings are documented.

### Fixed
- `appinfra.db.pg.PG` now accepts dict configs by normalizing them to `SimpleNamespace` at
  initialization. Previously, dict configs would silently fail because `getattr()` on a dict returns
  the default value instead of the dict key value.
- `DotDict` now correctly prioritizes data over inherited dict methods. Previously, keys like
  `copy`, `pop`, or `update` would return the dict method instead of the stored value.

## [0.2.1] - 2026-01-11

### Fixed
- `appinfra.db.pg` now uses consistent attribute access pattern (`getattr`) throughout instead of
  dict-style `.get()`. This allows using SimpleNamespace, dataclasses, or any object with attributes
as config. Affected: `ConfigValidator`, `PG.readonly`, `PG.migrate()`,
`ConnectionManager.connect()`.

## [0.2.0] - 2026-01-11

### Added
- API documentation for CLI framework (`cli.md`), configuration (`config.md`), network (`net.md`),
  observability (`observability.md`), security (`security.md`), and subprocess (`subprocess.md`)
- Configurable coverage threshold via `INFRA_PYTEST_COVERAGE_THRESHOLD` (default: 95.0, set to 0 to disable)
- SQLite database support (`appinfra.db.sqlite`) for lightweight/embedded use cases
- pgvector extension support (`appinfra.db.pg.vector`) for embedding storage and similarity search
- SQLite integration fixtures for fast DB tests (no external server needed)
- Session-start cleanup for stale debug tables (prevents orphaned tables from accumulating)
- Session detachment utilities (`appinfra.db.utils`) for background processing
- Test for debug table retention-on-failure behavior
- YAML frontmatter support for `appinfra docs search` - docs can include searchable keywords/aliases
- Fuzzy matching for `appinfra docs search` via `--fuzzy` flag with configurable `--threshold`
- Root-level SECURITY.md symlink for GitHub security integration discoverability
- CodeRabbit AI code review integration (`.coderabbit.yaml`) for automated PR reviews
- CODEOWNERS file requiring @serendip-ml approval for all changes

### Changed
- Restructure `docs/README.md` as focused user guide with Architecture and Packages sections
- Default PostgreSQL version changed from 17 to 16 (psql client compatibility issues with PG17)
- Database names standardized to `infra_main` and `infra_test` to avoid global name conflicts
- Replace `exec()` with `importlib.util` in version/info.py for safer module loading

### Removed
- **BREAKING:** Remove automatic path resolution from `Config` class. The `resolve_paths` parameter
  has been removed. Path resolution now requires the explicit `!path` YAML tag. This provides a
  cleaner mental model: without `!path`, paths remain as literal strings; with `!path`, paths are
  resolved relative to the config file and tilde (`~`) is expanded. Migration: add `!path` tag to
  config values that need path resolution (e.g., `file: !path ./logs/app.log`).

### Fixed
- Fix flaky integration tests with pytest-xdist by skipping stale table cleanup on worker processes
- Fix documentation links to use actual paths instead of symlinks (GitHub doesn't follow symlinks)
- Suppress passlib `crypt` module deprecation warning (upstream issue, Python 3.13 compatibility)
- Coverage directory handling in Makefile (properly cleans existing .coverage file/directory)

## [0.1.3] - 2026-01-05

### Added
- `DotDict.require()` method - raises `DotDictPathNotFoundError` if path not found

### Changed
- `DotDict` now subclasses `dict` - `isinstance(dotdict, dict)` returns `True`
- Removed SECURITY.md symlink from repository root (still available via `appinfra docs`)

### Fixed
- LICENSE now displays properly on GitHub (converted from symlink to real file)
- `appinfra docs show LICENSE` command now works correctly
- Removed obsolete symlink resolution step from release workflow
- CONTRIBUTING.md symlink now points directly to `appinfra/docs/` for single-click navigation

### Documentation
- Added missing `select_table` parameters (`default_index`, `column_spacing`) to UI docs
- Added shared arguments pattern for tool hierarchies (base class and mixin patterns)

## [0.1.2] - 2026-01-05

### Fixed
- Wheel builds now work correctly (reversed symlink direction: real files in `appinfra/`, symlinks at root)
- Duplicate CI checks on develop branch PRs
- Docker build context and paths for new project structure
- Coverage job configuration (postgres service, cleanup, output paths)

### Changed
- Restructured CI workflow: lint gate runs first, then parallel test matrix
- Shortened workflow and job names for cleaner GitHub UI
- Consolidated coverage output under `.coverage/` directory
- Aligned `make cicd.test` with GitHub CI workflow

## [0.1.1] - 2026-01-03

### Added
- README as PyPI project description

### Changed
- Lowered performance test threshold for CI environments

## [0.1.0] - 2026-01-02

### Added
- Advanced logging system with structured output, custom levels (TRACE/TRACE2), and multiple handlers
- PostgreSQL database layer with connection pooling, query logging, and migration support
- Application framework with fluent AppBuilder API, tool registry, and lifecycle management
- Time utilities: Ticker (periodic execution), Scheduler (cron-like), Delta (duration formatting), DateRange
- Network components: TCP/HTTP server with single-process and multiprocessing modes
- Core utilities: DotDict, LRU cache, rate limiting, YAML configuration with environment overrides
- Comprehensive test suite with 95% coverage across unit, integration, performance, security, and e2e tests
- Documentation for all major components and configuration patterns
- Security best practices and vulnerability reporting policy

### Changed
- Package renamed to `appinfra` (install and import both use `appinfra`)

[Unreleased]: https://github.com/llm-works/appinfra/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/llm-works/appinfra/compare/v0.4.1...v0.5.0
[0.4.1]: https://github.com/llm-works/appinfra/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/llm-works/appinfra/compare/v0.3.5...v0.4.0
[0.3.5]: https://github.com/llm-works/appinfra/compare/v0.3.4...v0.3.5
[0.3.4]: https://github.com/llm-works/appinfra/compare/v0.3.3...v0.3.4
[0.3.3]: https://github.com/llm-works/appinfra/compare/v0.3.2...v0.3.3
[0.3.2]: https://github.com/llm-works/appinfra/compare/v0.3.1...v0.3.2
[0.3.1]: https://github.com/llm-works/appinfra/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/llm-works/appinfra/compare/v0.2.1...v0.3.0
[0.2.1]: https://github.com/llm-works/appinfra/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/llm-works/appinfra/compare/v0.1.3...v0.2.0
[0.1.3]: https://github.com/llm-works/appinfra/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/llm-works/appinfra/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/llm-works/appinfra/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/llm-works/appinfra/releases/tag/v0.1.0
