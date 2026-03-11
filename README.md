# appinfra

![Python](https://img.shields.io/badge/python-3.11+-blue.svg)
![Coverage](https://img.shields.io/badge/coverage-95%25-brightgreen.svg)
![Type Hints](https://img.shields.io/badge/type%20hints-100%25-brightgreen.svg)
[![Typed](https://img.shields.io/badge/typed-PEP%20561-brightgreen.svg)](https://peps.python.org/pep-0561/)
[![Linting: Ruff](https://img.shields.io/badge/linting-ruff-brightgreen)](https://github.com/astral-sh/ruff)
[![CI](https://github.com/llm-works/appinfra/actions/workflows/test-docker.yml/badge.svg)](https://github.com/llm-works/appinfra/actions/workflows/test-docker.yml)
[![PyPI](https://img.shields.io/pypi/v/appinfra)](https://pypi.org/project/appinfra/)
![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)

Production-grade Python infrastructure framework for building reliable CLI tools and services.

## Scope

**Best for:** Production CLI tools, background services, systems-level Python applications.

**Not for:** Web APIs (use FastAPI), async-heavy applications, ORMs.

See [docs/README.md](appinfra/docs/README.md) for full scope and philosophy.

## Features

- **Logging** - Structured logging with custom levels, rotation, JSON output, and database handlers
- **Database** - PostgreSQL interface with connection pooling and query monitoring
- **App Framework** - Fluent builder API for CLI tools with lifecycle management
- **Configuration** - YAML config with environment variable overrides and path resolution
- **Time Utilities** - Scheduling, periodic execution, and duration formatting

## Requirements

- Python 3.11+
- PostgreSQL 16 (optional, for database features)

## Installation

```bash
pip install appinfra
```

Optional features:

```bash
pip install appinfra[sql]        # Database support (PostgreSQL, SQLite)
pip install appinfra[ui]         # Rich console, interactive prompts
pip install appinfra[fastapi]    # FastAPI integration
pip install appinfra[validation] # Pydantic config validation
pip install appinfra[hotreload]  # Config file watching
pip install appinfra[all]        # All extras (dev, docs, and all above)
```

## Documentation

Full documentation is available in [docs/README.md](appinfra/docs/README.md), or via CLI:

```bash
appinfra docs           # Overview
appinfra docs list      # List all guides and examples
appinfra docs show <topic>  # Read a specific guide
```

## Highlights

### App Framework

**AppBuilder for CLI tools** - Build production CLI applications with lifecycle management, config,
logging, and tools. Focused configurers provide clean separation of concerns. Config files are
resolved from `--etc-dir` (default: `./etc`):

```python
from appinfra.app import AppBuilder

app = (
    AppBuilder("myapp")
    .with_description("Data processing tool")
    .with_config_file("config.yaml")              # Resolved from --etc-dir
    .logging.with_level("info").with_location(1).done()
    .tools.with_tool(ProcessorTool()).with_main(MainTool()).done()
    .advanced.with_hook("startup", init_database).done()
    .build()
)

app.run()
```

**Fluent builder APIs** - All components use chainable builder patterns for clean, readable
configuration. No more scattered setup code or complex constructor arguments:

```python
from appinfra.log import LoggingBuilder

logger = (
    LoggingBuilder("my_app")
    .with_level("info")
    .with_format("%(asctime)s [%(levelname)s] %(message)s")
    .console_handler(colors=True)
    .file_handler("logs/app.log", rotate_mb=10)
    .build()
)
```

**Decorator-based CLI tools** - Build command-line tools with minimal boilerplate. Tools
automatically get logging, config access, and argument parsing:

```python
from appinfra.app import AppBuilder

app = AppBuilder("mytool").build()

@app.tool(name="sync", help="Synchronize data")
@app.argument("--force", action="store_true", help="Force sync")
@app.argument("--limit", type=int, default=100)
def sync_tool(self):
    self.lg.info(f"Syncing {self.args.limit} items")
    if self.args.force:
        self.lg.warning("Force mode enabled")
    return 0
```

**Nested subcommands** - Organize complex CLIs with hierarchical command structures using the
`@subtool` decorator:

```python
app = AppBuilder("myapp").build()

@app.tool(name="db", help="Database operations")
def db_tool(self):
    return self.run_subtool()

@db_tool.subtool(name="migrate", help="Run migrations")
@app.argument("--step", type=int, default=1)
def db_migrate(self):
    self.lg.info(f"Migrating {self.args.step} steps...")

@db_tool.subtool(name="status")
def db_status(self):
    self.lg.info("Database is healthy")

# Usage: myapp db migrate --step 3
#        myapp db status
```

**Multi-source version tracking** - Automatically detect version and git commit from PEP 610
metadata, build-time info, or git runtime. Integrates with AppBuilder for --version flag and
startup logging:

```python
app = (
    AppBuilder("myapp")
    .version
        .with_semver("1.0.0")
        .with_build_info()              # App's own commit from _build_info.py
        .with_package("appinfra")       # Track framework version
        .done()
    .build()
)
# --version shows: myapp 1.0.0 (abc123f) + tracked packages
# Startup logs commit hash, warns if repo has uncommitted changes
```

### Configuration

**YAML includes with security** - Build modular configurations with file includes, environment
variable validation, and automatic path resolution. Includes are protected against path traversal
and circular dependencies:

```yaml
# config.yaml
!include "./base.yaml"                    # Document-level merge

database:
  primary: !include "./db/primary.yaml"   # Nested includes
  credentials:
    password: !secret ${DB_PASSWORD}      # Validated env var reference

paths:
  models: !path ../models                 # Resolved relative to this file
  cache: !path ~/.cache/myapp             # Expands ~
```

**DotDict config access** - Access nested configuration with attribute syntax or dot-notation paths.
Automatic conversion of nested dicts, with safe traversal methods:

```python
from appinfra.dot_dict import DotDict

config = DotDict({
    "database": {"host": "localhost", "port": 5432},
    "features": {"beta": True}
})

# Attribute-style access
print(config.database.host)               # "localhost"
print(config.features.beta)               # True

# Dot-notation path queries
if config.has("database.ssl.enabled"):
    setup_ssl(config.get("database.ssl.cert"))
```

**Hot-reload configuration** - Change log levels, feature flags, or any config value without
restarting your application. Uses content-based change detection to avoid spurious reloads:

```python
from appinfra.config import ConfigWatcher

def on_config_change(new_config):
    logger.info("Config updated, applying changes...")
    apply_feature_flags(new_config.features)

watcher = ConfigWatcher(lg=logger, etc_dir="./etc")
watcher.configure("config.yaml", debounce_ms=500)
watcher.add_section_callback("features", on_config_change)
watcher.start()
```

### Logging & Security

**Topic-based log levels** - Control logging granularity with glob patterns. Set debug logging for
database queries while keeping network calls at warning level, all without touching application
code:

```python
from appinfra.log import LogLevelManager

manager = LogLevelManager.get_instance()
manager.add_rule("/app/db/*", "debug")      # All database loggers
manager.add_rule("/app/db/queries", "trace") # Even more detail for queries
manager.add_rule("/app/net/**", "warning")   # Network and all children
manager.add_rule("/app/cache", "error")      # Only errors from cache
```

**Automatic secret masking** - Protect sensitive data in logs with pattern-based detection. Covers
20+ secret formats including AWS keys, GitHub tokens, JWTs, and database URLs:

```python
from appinfra.security import SecretMasker, SecretMaskingFilter

masker = SecretMasker()
masker.add_known_secret(os.environ["API_KEY"])  # Track known secrets

# Patterns auto-detect common formats
text = masker.mask("token=ghp_abc123secret")    # "token=[MASKED]"
text = masker.mask("aws_secret=AKIA...")        # "aws_secret=[MASKED]"

# Integrate with logging
handler.addFilter(SecretMaskingFilter(masker))
```

**Lightweight observability hooks** - Event-based callbacks without heavy frameworks. Register
handlers for specific events or globally, with automatic timing in context:

```python
from appinfra.observability import ObservabilityHooks, HookEvent, HookContext

hooks = ObservabilityHooks()

@hooks.on(HookEvent.QUERY_START)
def on_query(ctx: HookContext):
    logger.debug(f"Query: {ctx.data.get('sql')}")

@hooks.on(HookEvent.QUERY_END)
def on_complete(ctx: HookContext):
    logger.info(f"Completed in {ctx.duration:.3f}s")

# Trigger events with arbitrary data
hooks.trigger(HookEvent.QUERY_START, sql="SELECT * FROM users")
```

### Time & Scheduling

**Dual-mode ticker** - Run periodic tasks with scheduled intervals or continuous execution. Context
manager handles signals for graceful shutdown:

```python
from appinfra.time import Ticker

# Scheduled mode: run every 30 seconds
with Ticker(logger, secs=30) as ticker:
    for tick_count in ticker:           # Stops on SIGTERM/SIGINT
        run_health_check()
        if tick_count >= 100:
            break

# Continuous mode: run as fast as possible
for tick in Ticker(logger):              # No secs = continuous
    process_queue_item()
```

**Human-readable durations** - Format seconds to readable strings and parse them back. Supports
microseconds to days, with precise mode for sub-millisecond accuracy:

```python
from appinfra.time import delta_str, delta_to_secs

# Formatting
delta_str(3661.5)                # "1h1m1s"
delta_str(0.000042)              # "42μs"
delta_str(90061)                 # "1d1h1m1s"

# Parsing
delta_to_secs("2h30m")           # 9000.0
delta_to_secs("1d12h")           # 129600.0
delta_to_secs("500ms")           # 0.5
```

**Time-based task scheduler** - Execute tasks at specific times with daily, weekly, monthly, or
hourly periods. Generator-based iteration with signal handling for graceful shutdown:

```python
from appinfra.time import Sched, Period

# Daily at 14:30
sched = Sched(logger, Period.DAILY, "14:30")

# Weekly on Monday at 09:00
sched = Sched(logger, Period.WEEKLY, "09:00", weekday=0)

for timestamp in sched.run():       # Yields after each scheduled time
    generate_report()
```

**ETA progress tracking** - Accurate time-to-completion estimates using EWMA-smoothed processing
rates. Handles variable update intervals without spike errors:

```python
from appinfra.time import ETA, delta_str

eta = ETA(total=1000)
for i, item in enumerate(items):
    process(item)
    eta.update(i + 1)
    remaining = eta.remaining_secs()
    print(f"{eta.percent():.1f}% - {delta_str(remaining)} remaining")
```

**Business day iteration** - Memory-efficient date range processing with weekend filtering. Iterates
from start date to today without materializing the full range:

```python
from appinfra.time import iter_dates
import datetime

start = datetime.date(2025, 12, 1)
for date in iter_dates(start, skip_weekends=True):
    process_business_day(date)              # Mon-Fri only, up to today
```

### CLI & UI

**Testable CLI output** - Write testable CLI tools without mocking stdout. Swap output
implementations for production, testing, or silent operation:

```python
from appinfra.cli.output import ConsoleOutput, BufferedOutput, NullOutput

def run_command(output=None):
    output = output or ConsoleOutput()
    output.write("Processing...")
    output.write("Done!")

# In tests: capture output
buf = BufferedOutput()
run_command(output=buf)
assert "Done!" in buf.text
assert buf.lines == ["Processing...", "Done!"]
```

**Interactive CLI prompts** - Smart prompts that work in TTY, non-interactive, and CI environments.
Auto-detects available libraries with graceful fallbacks:

```python
from appinfra.ui import confirm, select, text

env = select("Environment:", ["dev", "staging", "prod"])
name = text("Project name:", validate=lambda x: len(x) > 0)

if confirm(f"Deploy {name} to {env}?"):
    deploy()
```

**Progress with logging coordination** - Rich spinner or progress bar that pauses for log output.
Falls back to plain logging on non-TTY:

```python
from appinfra.ui import ProgressLogger

with ProgressLogger(lg, "Processing...", total=100) as pl:
    for item in items:
        result = process(item)
        pl.log(f"Processed {item.name}")     # Pauses spinner, logs, resumes
        pl.update(advance=1)
```

### Database

**Database auto-reconnection** - Automatic retry with exponential backoff on transient failures.
Configured via YAML, transparent to application code:

```yaml
# etc/config.yaml
database:
  url: postgresql://...
  auto_reconnect: true
  max_retries: 3        # Attempts before raising
  retry_delay: 0.5      # Initial delay, doubles each retry
```

**Read-only database mode** - Transaction-level enforcement preventing accidental writes. Validates
configuration to catch conflicts early:

```python
pg = PG(config, readonly=True)
with pg.session() as session:
    # SELECT queries work normally
    # INSERT/UPDATE/DELETE raise errors at transaction level
```

### Server

**FastAPI subprocess isolation** - Run FastAPI in a subprocess with queue-based IPC. Main process
stays responsive while workers handle requests, with automatic restart on failure:

```python
from appinfra.app.fastapi import FastAPIBuilder

server = (
    FastAPIBuilder("api")
    .with_config(config)
    .with_port(8000)
    .with_subprocess_mode(
        request_queue=request_q,
        response_queue=response_q,
        auto_restart=True
    )
    .build()
)

server.start()  # Non-blocking, runs in subprocess
```

## Completeness

Built for production with comprehensive validation:

- **4,000+ tests** across unit, integration, e2e, security, and performance categories
- **95% code coverage** on 11,000+ statements
- **100% type hints** verified by mypy strict mode
- **Security tests** for YAML injection, path traversal, ReDoS, and secret exposure

## Contributing

See the [Contributing Guide](appinfra/docs/guides/contributing.md) for development setup and
guidelines.

## Links

- [Changelog](CHANGELOG.md)
- [Security Policy](appinfra/docs/SECURITY.md)
- [API Stability](appinfra/docs/guides/api-stability.md)

## License

Apache License 2.0 - see [LICENSE](LICENSE) for details.
