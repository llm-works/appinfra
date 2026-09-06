---
title: Hot-Reload Logging Configuration
keywords:
  - hot reload
  - live reload
  - dynamic config
  - runtime logging
  - watchdog
  - file watcher
  - log level
  - reload config
aliases:
  - live-logging
  - dynamic-logging
---

# Hot-Reload Logging Configuration

Automatically reload logging configuration when config files change, without restarting your
application. Useful for adjusting log levels and display options in long-running services.

## Installation

Hot-reload requires the optional `watchdog` dependency:

```bash
pip install appinfra[hotreload]
```

## Quick Start

### Via AppBuilder

```python
from appinfra.app.builder import AppBuilder

app = (
    AppBuilder("my-service")
    .with_config_file("config.yaml")
    .config.with_hot_reload(True)  # Watch the resolved config file
    .done()
    .logging.with_level("info")
    .done()
    .build()
)
```

### Via Configuration File

```yaml
# etc/config.yaml
logging:
  level: info
  location: 1
  colors: true
  location_color: gray-15

  hot_reload:
    enabled: true
    debounce_ms: 500  # Wait 500ms after file change before reloading
```

## Configuration Options

### YAML Configuration

```yaml
logging:
  # Standard logging options (can be hot-reloaded)
  level: debug           # Log level: trace2, trace, debug, info, warning, error, critical
  location: 2            # File location depth (0=none, 1=file:line, 2=full path)
  micros: true           # Microsecond timestamp precision
  colors: true           # Enable colored output
  location_color: cyan   # Color for file location (e.g., gray-15, cyan, magenta)

  # Topic-based log levels (can be hot-reloaded)
  topics:
    /db.*: debug         # Database logs at debug level
    /api.*: info         # API logs at info level
    /auth.*: warning     # Auth logs at warning level

  # Hot-reload settings
  hot_reload:
    enabled: true
    debounce_ms: 500     # Debounce rapid file changes (default: 500ms)
```

### Programmatic Configuration

```python
app = (
    AppBuilder("my-service")
    .with_config_file("config.yaml")  # A config source must be declared first
    .config.with_hot_reload(True, debounce_ms=1000)
    .done()
    .build()
)
```

## What Can Be Hot-Reloaded

| Setting | Hot-Reloadable | Notes |
|---------|----------------|-------|
| `level` | Yes | Global log level |
| `location` | Yes | File location depth |
| `micros` | Yes | Timestamp precision |
| `colors` | Yes | Color output toggle |
| `location_color` | Yes | Location text color |
| `topics` | Yes | Topic-based log levels |
| Custom sections | Yes | Via section callbacks |
| File handlers | No | Requires restart |
| Handler paths | No | Requires restart |

## How It Works

1. **File Watcher**: Uses `watchdog` to monitor config files for changes
2. **Include Tracking**: Automatically watches all included files (via `!include` tags)
3. **Debouncing**: Waits for `debounce_ms` after last change to avoid rapid reloads
4. **Holder Update**: Updates root logger's holder (shared with all child loggers)
5. **Thread-Safe**: All updates are thread-safe using locks

### Watching Included Files

If your logging configuration uses `!include` to split configs across files, **all included files
are automatically watched**. Modifying any file in the include chain triggers a reload:

```yaml
# etc/config.yaml (watched)
logging: !include "./logging.yaml"

# etc/logging.yaml (also watched!)
level: info
handlers: !include "./handlers.yaml"

# etc/handlers.yaml (also watched!)
console:
  type: console
  enabled: true
```

Editing `handlers.yaml` will trigger a hot-reload, even though it's nested two levels deep.

### Architecture

```
Config File Change
       ↓
   ConfigWatcher (watchdog)
       ↓ (debounced)
   ┌──────────────────────────────────────┐
   │  on_change callback invoked          │
   │  (LogConfigReloader updates logger)  │
   ├──────────────────────────────────────┤
   │  Root Logger's Holder updated        │  ← Logging updates
   │  All child loggers share holder      │
   │  Formatters read new config          │
   ├──────────────────────────────────────┤
   │  Section callbacks notified          │  ← Custom section updates
   │  (proxy.plugins, cache, etc.)        │
   └──────────────────────────────────────┘
```

The `ConfigWatcher` is generic - it watches files and calls the `on_change` callback with the full
config dict. The `LogConfigReloader` class (in `appinfra.log`) handles the logger-specific updates.

### Accessing from Tools

Tools can access the watcher via `self.app.config_watcher`:

```python
class MyTool(Tool):
    def setup(self):
        watcher = self.app.config_watcher
        if watcher:
            watcher.add_section_callback("my_tool.options", self._on_options_changed)

    def _on_options_changed(self, options):
        self.timeout = options.get("timeout", 30)
```

## Manual Reload

Force an immediate config reload without waiting for file changes:

```python
# Access watcher via app instance
watcher = app.config_watcher
if watcher:
    watcher.reload_now()
```

## Section Callbacks

Register callbacks for arbitrary config sections (not just logging):

```python
def on_plugins_changed(plugins_config):
    """Called when proxy.plugins section changes."""
    print(f"Plugins updated: {plugins_config}")


def on_cache_changed(cache_config):
    """Called when cache section changes."""
    print(f"Cache TTL: {cache_config.ttl}")


watcher = app.config_watcher
if watcher:
    watcher.add_section_callback("proxy.plugins", on_plugins_changed)
    watcher.add_section_callback("cache", on_cache_changed)
```

Section callbacks receive the section's value as a `DotDict` after each config reload. Use
dot-notation paths for nested sections (e.g., `"proxy.plugins.auth"`).

To unregister:

```python
watcher.remove_section_callback("proxy.plugins", on_plugins_changed)
```

## Hot-Reload in Child Processes

When your application spawns child processes (e.g., background workers), each process needs its own
config watcher since file watchers don't cross process boundaries.

### Using app.subprocess_context() (Recommended)

The simplest approach uses the `app.subprocess_context()` helper, which creates a fresh logger and
wires up config watching automatically:

```python
import multiprocessing


def worker_process(app):
    """Worker that runs in a subprocess with hot-reload support."""
    with app.subprocess_context() as ctx:
        while ctx.running:
            # Do work...
            # Config changes are automatically applied
            pass


# Spawn the worker (app is available via fork)
process = multiprocessing.Process(target=worker_process, args=(app,))
process.start()
```

The helper:
- Creates a fresh logger for the subprocess (forked memory is isolated)
- Automatically uses `app._etc_dir` and `app._config_file`
- Sets up `LogConfigReloader` to apply config changes

### Using SubprocessContext Directly

For more control, use `SubprocessContext` directly:

```python
from appinfra.subprocess import SubprocessContext
from appinfra.log import LoggerFactory
from appinfra.log.config import LogConfig


def worker_process(etc_dir: str, config_file: str):
    """Worker with manual subprocess setup."""
    # Create logger for this subprocess
    config = LogConfig.from_params(level="info", location=1)
    lg = LoggerFactory.create_root(config)

    with SubprocessContext(lg=lg, etc_dir=etc_dir, config_file=config_file) as ctx:
        while ctx.running:
            # Do work...
            pass


# Pass etc_dir and config_file from app
etc_dir = getattr(app, "_etc_dir", None)
config_file = getattr(app, "_config_file", None)
process = multiprocessing.Process(target=worker_process, args=(etc_dir, config_file))
```

`SubprocessContext` provides:
- **Signal handling**: Graceful shutdown on SIGTERM/SIGINT (sets `ctx.running = False`)
- **Config watching**: Starts its own `ConfigWatcher` with `LogConfigReloader`
- **Clean lifecycle**: Proper setup/teardown of infrastructure

For blocking frameworks like uvicorn that handle their own signals:

```python
with SubprocessContext(
    lg=lg, etc_dir=etc_dir, config_file=config_file, handle_signals=False
):
    uvicorn.run(app)  # uvicorn handles SIGTERM/SIGINT
```

### Using Ticker for Periodic Tasks

For subprocesses that run periodic tasks, combine `subprocess_context()` with `Ticker`:

```python
from appinfra.time import Ticker


def worker_process(app):
    """Worker that syncs data every 30 seconds."""
    with app.subprocess_context() as ctx:
        with Ticker(ctx.lg, secs=30) as ticker:
            for tick in ticker:
                sync_data()
                # Stops gracefully on SIGTERM/SIGINT
```

The `Ticker` class supports three usage patterns:

```python
# 1. Callback-based (existing pattern)
ticker = Ticker(lg, lambda: do_work(), secs=5)
ticker.run()

# 2. Iterator (for-loop)
for tick in Ticker(lg, secs=5):
    do_work()

# 3. Iterator with context manager (recommended for signal handling)
with Ticker(lg, secs=5) as t:
    for tick in t:
        do_work()
        # Stops gracefully on SIGTERM/SIGINT
```

The context manager installs signal handlers that stop iteration on SIGTERM/SIGINT, and restores
the previous handlers on exit.

## Example: Dynamic Log Level Adjustment

```yaml
# etc/config.yaml - Initial state
logging:
  level: info
  hot_reload:
    enabled: true
```

```python
# my_service.py
from appinfra.app.builder import AppBuilder

app = (
    AppBuilder("my-service")
    .with_config_file("config.yaml")
    .config.with_hot_reload(True)
    .done()
    .build()
)

# Application runs with INFO level...

# Edit config.yaml while running:
# logging:
#   level: debug

# Logs automatically switch to DEBUG level without restart!
```

## Troubleshooting

### Hot-reload not working

1. **Check watchdog is installed**: `pip install appinfra[hotreload]`
2. **Verify config path**: Ensure the path is correct and file exists
3. **Check debounce**: Try reducing `debounce_ms` for faster response
4. **Check logs**: Look for "hot-reload watcher started" debug message

### Performance considerations

- File watching has minimal overhead (OS-level notifications)
- Debouncing prevents excessive reloads
- Config parsing only happens on actual changes
- Thread-safe updates don't block logging

## See Also

- [Logging System](../api/logging.md) - Full logging API reference
- [AppBuilder](../api/app-builder.md) - Application builder documentation
- [Config-Based Logging](config-based-logging.md) - YAML configuration basics

## API Reference

### App Helper Methods

```python
# Create SubprocessContext with fresh logger (recommended for child processes)
with app.subprocess_context(handle_signals=True) as ctx:
    while ctx.running:
        # Do work...
        pass

# Create ConfigWatcher for manual hot-reload setup
watcher = app.create_config_watcher()  # Returns None if not configured
if watcher:
    reloader = LogConfigReloader(lg)
    watcher.configure("config.yaml", on_change=reloader)
    watcher.start()
```

### ConfigWatcher

```python
from appinfra.config import ConfigWatcher

# etc_dir passed to constructor, config_file (filename only) to configure()
watcher = ConfigWatcher(lg=logger, etc_dir="/etc/myapp")
watcher.configure(
    config_file="config.yaml",  # Filename only, relative to etc_dir
    debounce_ms=500,
    on_change=callback,  # Called with full config dict on change
)
watcher.start()
# ...
watcher.stop()
```

### LogConfigReloader

```python
from appinfra.log import LogConfigReloader

# Creates a callback that updates logger config
reloader = LogConfigReloader(root_logger, section="logging")

# Use with ConfigWatcher
watcher.configure("config.yaml", on_change=reloader)
```

### SubprocessContext

```python
from appinfra.subprocess import SubprocessContext

# Get etc_dir and config_file from app
etc_dir = getattr(app, "_etc_dir", None)
config_file = getattr(app, "_config_file", None)

with SubprocessContext(
    lg=logger,  # Logger for subprocess
    etc_dir=etc_dir,  # Config directory (optional)
    config_file=config_file,  # Config filename (optional)
    handle_signals=True,  # Install SIGTERM/SIGINT handlers (default: True)
) as ctx:
    while ctx.running:  # False after signal received
        # Do work...
        pass
```
