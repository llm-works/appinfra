# Subprocess

Context manager for subprocess infrastructure, providing signal handling, config hot-reload, and
graceful shutdown for child processes.

## SubprocessContext

Context manager that handles common subprocess boilerplate.

```python
class SubprocessContext:
    def __init__(
        self,
        lg: Logger,
        etc_dir: str | None = None,  # Base directory for config files
        config_file: str | None = None,  # Config filename (e.g., "config.yaml")
        handle_signals: bool = True,  # Install SIGTERM/SIGINT handlers
    ): ...

    @property
    def running(self) -> bool: ...  # False after SIGTERM/SIGINT
    @property
    def lg(self) -> Logger: ...  # Logger for this subprocess
```

**Features:**

- Signal handling (SIGTERM, SIGINT) for graceful shutdown
- Config watcher for hot-reload support
- Clean lifecycle management

## Loop-Based Pattern

For worker processes that run a loop:

```python
from appinfra.subprocess import SubprocessContext


def worker(logger, etc_dir, config_file):
    with SubprocessContext(lg=logger, etc_dir=etc_dir, config_file=config_file) as ctx:
        while ctx.running:
            msg = queue.get(timeout=1.0)
            if msg:
                process(msg)

    # Clean shutdown after SIGTERM/SIGINT
    logger.info("Worker stopped gracefully")
```

The `ctx.running` property returns `False` after receiving SIGTERM or SIGINT, allowing the loop to
exit cleanly.

## Blocking Call Pattern

For processes that run a blocking framework (e.g., uvicorn):

```python
from appinfra.subprocess import SubprocessContext
import uvicorn


def server(logger, etc_dir, config_file, app):
    # Disable signal handling - uvicorn handles its own signals
    with SubprocessContext(
        lg=logger, etc_dir=etc_dir, config_file=config_file, handle_signals=False
    ):
        uvicorn.run(app)
```

Set `handle_signals=False` when the subprocess runs a framework that handles its own signals.

## Hot-Reload Support

When `etc_dir` and `config_file` are provided, SubprocessContext automatically starts a config
watcher for hot-reload support:

```python
with SubprocessContext(
    lg=logger, etc_dir="/etc/myapp", config_file="config.yaml"
) as ctx:
    # Config changes are automatically detected
    # Logger configuration is updated without restart
    while ctx.running:
        do_work()
```

**Requirements:**

```bash
pip install appinfra[hotreload]  # Installs watchdog
```

If watchdog is not installed, hot-reload is silently disabled with a debug log message.

## Signal Handling

By default, SubprocessContext installs handlers for:

- `SIGTERM` - Graceful shutdown signal (from process managers)
- `SIGINT` - Interrupt signal (Ctrl+C)

Both signals set `ctx.running = False`, allowing loops to exit gracefully.

```python
with SubprocessContext(lg=logger) as ctx:
    while ctx.running:
        # This loop exits cleanly on SIGTERM or SIGINT
        time.sleep(1)

    # Cleanup code runs after the loop
    cleanup()
```

## Usage with multiprocessing

```python
import multiprocessing
from appinfra.subprocess import SubprocessContext
from appinfra.log import LoggingBuilder


def worker_process(etc_dir: str, config_file: str):
    # Create logger for this subprocess
    logger = LoggingBuilder("worker").with_level("info").console_handler().build()

    with SubprocessContext(lg=logger, etc_dir=etc_dir, config_file=config_file) as ctx:
        logger.info("Worker started")
        while ctx.running:
            # Do work
            process_items()

        logger.info("Worker stopped")


# In main process
if __name__ == "__main__":
    p = multiprocessing.Process(
        target=worker_process, args=("/etc/myapp", "config.yaml")
    )
    p.start()
```

## Logger Access

The logger is available via `ctx.lg` and is wired to the config watcher for hot-reload:

```python
with SubprocessContext(lg=logger, etc_dir=etc_dir, config_file=config_file) as ctx:
    ctx.lg.info("Starting work")

    while ctx.running:
        ctx.lg.debug("Processing item")
        # Log level can be changed at runtime via config file
        process_item()

    ctx.lg.info("Shutting down")
```

## Lazy

Defers construction of an unpicklable value until after the `mp.Process` pickle boundary.

```python
@dataclass
class Lazy:
    factory: str  # "pkg.mod:build_health"
    config: Any = None  # must be picklable

    def resolve(self) -> Any: ...
```

**Why it exists.** Python 3.14+ changed multiprocessing defaults: `forkserver` on POSIX
(except macOS), `spawn` on Windows and macOS. Both pickle the target's args at
`mp.Process.start()`. Nested closures and other locally-defined callables carry `<locals>`
in their qualname and are rejected by the pickle protocol — any parent-process object
holding one fails to cross the boundary.

Wrapping the value as `Lazy("myapp.workers:build_x", config)` pickles as a plain dataclass;
the child imports `myapp.workers` and calls `build_x(config)` after unpickling, so the
closure is constructed in the child and never crosses pickle.

**Example — worker that needs a nested callable:**

```python
import multiprocessing as mp
from appinfra.subprocess import Lazy


# Module-level factory (importable by qualname)
def build_tick(config):
    counter = {"n": 0}  # captured state — nested closure below is OK

    def tick():
        counter["n"] += 1
        return counter["n"]

    return tick


def child(lazy: Lazy):
    tick = lazy.resolve()
    for _ in range(3):
        print(tick())


# Parent process
lazy = Lazy("myapp.workers:build_tick", WorkerConfig(...))
proc = mp.Process(target=child, args=(lazy,))
proc.start()  # `lazy` pickles fine; a bare `build_tick(...)` result would not
```

**Where used inside appinfra.** `FastAPIAdapter` accepts `Lazy` on every route handler,
router, middleware, exception handler, lifecycle callback, and rate limiter — see the
[FastAPI Subprocess Mode](fastapi.md#nested-closures-in-subprocess-mode) section.

**Unsupported.** Parent state created *after* subprocess spawn (e.g. an `mp.Value` shared
post-spawn) cannot cross `forkserver` at all — `Lazy` is not a workaround for that. Such
consumers must stay on the `fork` start method or Python ≤ 3.13.

## See Also

- [Logging System](logging.md) - Logger configuration
- [Hot-Reload Logging](../guides/hot-reload-logging.md) - Dynamic config reloading
- [Application Framework](app.md) - Main application lifecycle
