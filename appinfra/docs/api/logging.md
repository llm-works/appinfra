---
title: Logging System
keywords:
  - logging
  - log levels
  - trace
  - debug
  - structured logging
  - handlers
  - formatters
  - colors
  - multiprocess
  - subprocess
  - queue handler
aliases:
  - log-api
  - logging-api
---

# Logging System

Comprehensive logging with structured output, custom levels, and multiple handlers.

## Log Levels

| Level | Value | Description |
|-------|-------|-------------|
| `trace2` | 4 | Most detailed tracing |
| `trace` | 5 | Detailed tracing |
| `debug` | 10 | Debug messages |
| `info` | 20 | Informational |
| `warning` | 30 | Warnings |
| `error` | 40 | Errors |
| `critical` | 50 | Critical errors |
| `False` | - | Disable logging completely |

## LoggingBuilder

Fluent API for configuring loggers.

```python
class LoggingBuilder:
    def __init__(self, name: str): ...

    def with_level(self, level: str | bool) -> LoggingBuilder: ...
    def with_location(
        self, level: int
    ) -> LoggingBuilder: ...  # 0=none, 1=file:line, 2=full
    def with_micros(self, enabled: bool = True) -> LoggingBuilder: ...
    def with_console_handler(self, stream=None, level=None) -> LoggingBuilder: ...
    def with_file_handler(
        self, filename: str, level=None, **kwargs
    ) -> LoggingBuilder: ...
    def with_rotating_file_handler(
        self, filename: str, max_bytes: int = 0, backup_count: int = 0, **kwargs
    ) -> LoggingBuilder: ...
    def build(self) -> Logger: ...
```

**Basic Example:**

```python
from appinfra.log import LoggingBuilder

logger = LoggingBuilder("my_app").with_level("info").with_console_handler().build()

logger.info("Application started")
logger.debug("Debug message")  # Won't show (level is info)
```

## LogConfig

Configuration dataclass for logging.

```python
@dataclass
class LogConfig:
    level: str | bool = "info"  # Log level or False to disable
    location: int = 0  # File location in output (0, 1, 2)
    micros: bool = False  # Microsecond timestamps
    topic: str | None = None  # Topic filter
    console: bool = True  # Enable console output
    file: str | None = None  # Log file path
    max_bytes: int = 10_485_760  # Max file size (10MB)
    backup_count: int = 5  # Number of backup files
```

## LoggerFactory

Factory for creating and managing loggers.

```python
class LoggerFactory:
    @staticmethod
    def create_root(config: LogConfig) -> Logger: ...  # create("/", config)

    @staticmethod
    def create(name: str, config: LogConfig) -> Logger: ...

    @staticmethod
    def create_or_replace(name: str, config: LogConfig) -> Logger: ...

    @staticmethod
    def reconfigure(name: str, config: LogConfig) -> Logger: ...

    @staticmethod
    def destroy(name: str) -> None: ...

    @staticmethod
    def destroy_if_exists(name: str) -> bool: ...

    @staticmethod
    def names() -> set[str]: ...

    @staticmethod
    def derive(parent: Logger, tags: str | list[str]) -> Logger: ...

    @staticmethod
    def create_child(parent: Logger, name: str) -> Logger: ...
```

A logger name belongs to whoever created it. `create()` (and `create_root()`, and every builder's
`build()`) raises `LoggerExistsError` when the name is taken, whatever the config: a name used
twice is almost always an accident, and changing the first logger would surprise its owner. To
change a live logger on purpose, `reconfigure()` applies a new level, location, micros and colors
in place; it raises `LogConfigError` for a view made by `derive()` or `create_child()`, which
shares its root's settings, so the root is the logger to reconfigure. To start over, `destroy()`
closes the logger's handlers and removes it with every logger derived from it, or
`create_or_replace()` does that and creates the name anew. `reconfigure()` and `destroy()` raise
`LoggerNotFoundError` for a name that does not exist; `destroy_if_exists()` returns whether there
was one instead. A handler whose `close()` fails does not stop `destroy()`: the cleanup completes,
then the first such error is raised. `names()` lists the names the factory holds in this process,
created loggers and their views; the `appinfra.testing` pytest plugin uses it to destroy the
loggers each test leaves behind (see the [pytest plugin guide](../guides/pytest-plugin.md)).

Code that runs inside another program's process takes its logger from the host instead of creating
one. An alembic `env.py`, a plugin or a hook that calls `create_root()` works when run on its own,
but raises `LoggerExistsError` when an app that already holds `/` runs it in-process. The host
passes a logger made with `derive()` (for alembic, through `config.attributes`), and the code
creates its own root only when none was passed.

`derive()` and `create_child()` are lookups: they return an existing view of the same name.

A library's own logger under the name does not block `create()`: a plain stdlib logger (or one
`logging.getLogger()` made with appinfra's logger class) is taken over in place. The library keeps
logging through the same object, and through its child loggers, now with the given config and
appinfra's format; its own handlers and filters are dropped. A library's own `Logger` subclass is
not taken over, since rewriting its class would break the library's calls to it, so `create()`
raises `LoggerExistsError` for it.

A logger belongs to the process that created it. A forked child inherits its parent's loggers
but may create their names anew; the inherited objects keep working for code that holds them. An
`App` creates the root logger `/` in `setup()` and destroys it at the end of `shutdown()`.

## File Logging with Rotation

```python
from appinfra.log import LoggingBuilder

logger = (
    LoggingBuilder("my_app")
    .with_level("debug")
    .with_console_handler()
    .with_rotating_file_handler(
        "logs/app.log",
        max_bytes=10 * 1024 * 1024,  # 10MB
        backup_count=5,
    )
    .build()
)
```

## JSON Structured Logging

```python
from appinfra.log.builder import JSONLoggingBuilder

logger = JSONLoggingBuilder("my_app").with_level("info").with_console_handler().build()

logger.info("User logged in", extra={"user_id": "123", "ip_address": "192.168.1.1"})
```

## Quick Setup Functions

One-line logger creation:

```python
from appinfra.log import quick_console_logger, quick_file_logger, quick_both_logger

# Console only
logger = quick_console_logger("myapp", level="info")

# File only
logger = quick_file_logger("myapp", "logs/app.log")

# Console + file
logger = quick_both_logger("myapp", "logs/app.log", level="info")
```

## Capturing Third-Party Loggers

Unify all Python logging (including third-party libraries) with appinfra's formatting:

```python
from appinfra.log import capture_all_loggers

# Capture all loggers at INFO level
capture_all_loggers(level="info")

# Now logs from requests, sqlalchemy, boto3, etc. use appinfra format
import requests  # Its logs will now use appinfra formatting
```

**Parameters:**

```python
capture_all_loggers(
    level="info",  # Log level (or False to disable all logging)
    clear_handlers=True,  # Remove existing handlers from all loggers
    colors=True,  # Enable colored console output
    location=False,  # Show file locations in log messages
    micros=False,  # Microsecond precision in timestamps
)
```

**Preserve existing handlers:**

```python
# Keep library-specific handlers, but ensure propagation to root
capture_all_loggers(level="debug", clear_handlers=False)
```

**Pre-capture specific loggers:**

Some libraries create loggers after `capture_all_loggers()` runs. Use `capture_logger()` to
pre-configure them:

```python
from appinfra.log import capture_all_loggers, capture_logger

capture_all_loggers(level="info")

# Pre-capture before import - logger will be ready when library uses it
capture_logger("urllib3", level="warning")
capture_logger("sqlalchemy.engine")

import sqlalchemy  # Logger already configured with appinfra formatting
```

## Topic-Based Logging

Different log levels for different subsystems:

```python
from appinfra.log import LoggingBuilder

# Different levels for different topics; the rules apply process-wide
logger = (
    LoggingBuilder("/infra/db")
    .with_topic_levels({"/infra/db": "debug", "/infra/app": "info"})
    .with_console_handler()
    .build()
)
logger.debug("Database query")  # Will show (debug level for /infra/db)
```

## Disabling Logging

```python
from appinfra.log import LoggingBuilder

# Method 1: with_level(False)
logger = LoggingBuilder("my_app").with_level(False).build()

# Method 2: via config
# INFRA_LOGGING_LEVEL=false
```

## CallbackRegistry

Register callbacks for log events:

```python
from appinfra.log import CallbackRegistry, listens_for


@listens_for("error")
def on_error(record):
    # Handle error log events
    send_alert(record.getMessage())


# Or manually
CallbackRegistry.register("error", my_callback)
```

## LogConfigReloader

Callback for hot-reloading logger configuration. Used with `ConfigWatcher`:

```python
from appinfra.log import LogConfigReloader
from appinfra.config import ConfigWatcher

# Create reloader for root logger
reloader = LogConfigReloader(root_logger, section="logging")

# Use with ConfigWatcher (etc_dir in constructor, config_file in configure)
watcher = ConfigWatcher(lg=lifecycle_logger, etc_dir="/etc/myapp")
watcher.configure("config.yaml", on_change=reloader)
watcher.start()
```

The reloader updates the logger's holder (shared with all child loggers) and level manager when
config changes.

## Hot-Reload Configuration

Automatically reload logging settings when config files change:

```python
from appinfra.app.builder import AppBuilder

app = (
    AppBuilder("my-service")
    .config.with_spec("myorg", "my-service")
    .with_hot_reload(True)  # Enable hot-reload
    .done()
    .build()
)
```

Or via YAML:

```yaml
logging:
  level: info
  location: 1
  hot_reload:
    enabled: true
    debounce_ms: 500
```

**What can be hot-reloaded:**
- Log levels (global and topic-based)
- Display options (location, micros, colors, location_color)

**What cannot be hot-reloaded:**
- File handlers and paths (requires restart)

**Requirements:**

```bash
pip install appinfra[hotreload]  # Installs watchdog
```

See [Hot-Reload Logging Guide](../guides/hot-reload-logging.md) for full documentation.

## Multiprocess Logging

Python's `multiprocessing` creates separate processes that cannot share logging handlers. appinfra
provides two paradigms for multiprocess logging.

### Queue Mode (Centralized)

Best when: Parent process orchestrates subprocesses and needs centralized log aggregation.

```python
from multiprocessing import Process, Queue
from appinfra.log import Logger, LoggingBuilder, LogQueueListener

# Parent process: create logger and queue
queue = Queue()
logger = LoggingBuilder("app").with_level("info").with_console().build()

# Start listener (receives records from subprocesses)
listener = LogQueueListener(queue, logger)
listener.start()

# Create config for workers (captures queue, level, and LogLevelManager rules)
worker_config = logger.queue_config(queue)


def worker(config, worker_id):
    # Subprocess: create logger from config
    lg = Logger.from_queue_config(config, name=f"worker-{worker_id}")
    lg.info("Worker started")
    try:
        raise ValueError("Something failed")
    except Exception as e:
        lg.warning("Operation failed", extra={"exception": e})


# Spawn subprocesses
processes = [Process(target=worker, args=(worker_config, i)) for i in range(4)]
for p in processes:
    p.start()
for p in processes:
    p.join()

# Stop listener when done
listener.stop()
```

**Key points:**
- `logger.queue_config(queue)` captures everything workers need: queue, log level, and
  `LogLevelManager` pattern rules
- `Logger.from_queue_config(config, name)` restores the configuration and applies pattern-based
  level rules to the logger name
- Call `from_queue_config()` once per process, then use `derive_lg()` for additional loggers
- `MPQueueHandler` automatically formats exceptions before pickling (traceback preserved)
- `LogQueueListener` runs in a background daemon thread
- Records are dispatched to the parent logger's handlers

**With pattern-based level rules:**

```python
from appinfra.log import LogLevelManager

# Parent: set up pattern rules
level_manager = LogLevelManager.get_instance()
level_manager.add_rule("/worker/*", "warning", source="config", priority=1)
level_manager.add_rule("/worker/verbose/*", "debug", source="config", priority=2)

# Create config (includes the rules)
worker_config = logger.queue_config(queue)


def worker(config):
    # Gets WARNING level from /worker/* pattern
    lg = Logger.from_queue_config(config, name="/worker/task")
    lg.debug("Won't be logged")
    lg.warning("Will be logged")


def verbose_worker(config):
    # Gets DEBUG level from /worker/verbose/* pattern (higher priority)
    lg = Logger.from_queue_config(config, name="/worker/verbose/task")
    lg.debug("Will be logged")
```

### Independent Mode (Self-Sufficient)

Best when: Subprocesses are long-lived or may outlive the parent.

```python
from multiprocessing import Process
from appinfra.log import LoggingBuilder

# Parent: serialize logging configuration
builder = (
    LoggingBuilder("app")
    .with_level("debug")
    .with_console_handler()
    .with_file_handler("/var/log/app.log")
)
config_dict = builder.to_dict()  # Picklable dict


def worker(log_config, worker_id):
    # Subprocess: reconstruct logger from config
    logger = LoggingBuilder.from_dict(log_config, name=f"worker-{worker_id}").build()
    logger.info("Worker started independently")


# Spawn subprocess with config
p = Process(target=worker, args=(config_dict, 1))
p.start()
```

**Key points:**
- Subprocess creates its own handlers (file handles, etc.)
- No dependency on parent process after startup
- Database handlers cannot be serialized (excluded automatically)

### Important Caveats

**Process Integrity Requirements:**

- **Queue mode requires parent alive**: If the parent process crashes, queued log records are lost
  and subprocesses may block on a full queue. Design for graceful shutdown.
- **Queue size limits**: Default `multiprocessing.Queue` is unbounded but system memory is not.
  Consider queue size for high-throughput logging.
- **File handler contention**: In independent mode, multiple processes writing to the same file
  can cause interleaved/corrupted output. Use separate files or a centralized logging service.

**What Cannot Be Serialized:**

- Database handlers (`DatabaseHandlerConfig`) - require live database connections
- Custom handlers with unpicklable state

**When to Use Which:**

| Scenario | Recommended Mode |
|----------|-----------------|
| Short-lived workers | Queue mode |
| Long-running daemons | Independent mode |
| Need centralized log aggregation | Queue mode |
| Subprocesses may outlive parent | Independent mode |
| High-throughput logging | Independent mode (avoid queue bottleneck) |

## See Also

- [Logging Builder Guide](../guides/logging-builder.md) - Comprehensive guide
- [Config-Based Logging](../guides/config-based-logging.md) - YAML configuration
- [Hot-Reload Logging](../guides/hot-reload-logging.md) - Dynamic config reloading
