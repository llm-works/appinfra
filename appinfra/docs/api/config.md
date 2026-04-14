# Configuration

Configuration loading, environment variable overrides, hot-reload watching, and optional schema
validation.

## Config

Configuration class that loads YAML files with variable substitution, environment overrides, and
include support.

```python
class Config(DotDict):
    def __init__(
        self,
        fname: str,
        enable_env_overrides: bool = True,
        env_prefix: str = "INFRA_",
        merge_strategy: str = "replace"
    ): ...

    def reload(self) -> Config: ...
    def validate(self, raise_on_error: bool = True) -> bool | Any: ...
    def get_env_overrides(self) -> dict[str, Any]: ...
    def get_source_files(self) -> set[Path]: ...
```

**Parameters:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `fname` | required | Path to YAML configuration file |
| `enable_env_overrides` | `True` | Apply environment variable overrides |
| `env_prefix` | `"INFRA_"` | Prefix for environment variables |
| `merge_strategy` | `"replace"` | Strategy for handling `!include` directives: `"replace"` (included content replaces target key) or `"merge"` (deep merge with existing). Note: only `"replace"` is currently fully supported |

**Basic Usage:**

```python
from appinfra.config import Config, get_config_file_path

# Load from explicit path
config = Config("etc/config.yaml")

# Load using path resolution
config = Config(get_config_file_path())

# Access with dot notation (inherits from DotDict)
print(config.logging.level)
print(config.database.host)

# Get with fallback
port = config.get("database.port", default=5432)
```

## Environment Variable Overrides

Environment variables with the configured prefix override config file values.

**Format:** `{PREFIX}{SECTION}_{SUBSECTION}_{KEY}=value`

```bash
export INFRA_LOGGING_LEVEL=debug
export INFRA_DATABASE_PORT=5433
export INFRA_SERVER_HOST=0.0.0.0
```

```python
config = Config("etc/config.yaml")
print(config.logging.level)  # "debug" (from env, not file)
```

**Type Conversion:**

| Value | Converted Type |
|-------|----------------|
| `true`, `false` | `bool` |
| `null`, `none`, `""` | `None` |
| `123` | `int` |
| `1.5` | `float` |
| `a,b,c` | `list[str]` |
| anything else | `str` |

**Check Active Overrides:**

```python
overrides = config.get_env_overrides()
# {"logging.level": "debug", "database.port": 5433}
```

## YAML Includes

Config supports including other YAML files:

```yaml
# config.yaml
database: !include "./database.yaml"           # Include file as value
settings: !include "shared.yaml#app.settings"  # Include specific section

# Document-level include (merges at root)
!include "./base.yaml"

app_name: myapp
```

**Optional Includes:**

Use `!include?` for files that may or may not exist:

```yaml
# Required include (raises if missing)
database: !include "./database.yaml"

# Optional include (returns {} if missing)
overrides: !include? "./.env.yaml"
local_settings: !include? "./local.yaml#settings"

# Document-level optional include
!include? "./local-overrides.yaml"

name: myapp
```

Optional includes are useful for environment-specific overrides that don't exist in all deployments.

**Security:** Includes are protected against path traversal attacks and circular dependencies.

## Path Resolution

Path resolution requires the explicit `!path` YAML tag. Without the tag, paths remain as literal
strings:

```yaml
# etc/config.yaml
logging:
  file: ./logs/app.log           # Stays as "./logs/app.log" (no resolution)
  resolved: !path ./logs/app.log # Resolved to /project/etc/logs/app.log

models:
  path: !path ../models          # Resolved to /project/models
  cache: !path ~/.cache/myapp    # Expands ~ to home directory
```

**The `!path` tag:**
- Resolves relative paths (`./`, `../`) to absolute paths based on config file location
- Expands tilde (`~`) to the user's home directory
- Leaves absolute paths and URLs unchanged

See [YAML Tags](utilities.md#yaml-tags) for more details on `!path` and other custom tags.

## Config Reload

Reload configuration from disk:

```python
config = Config("etc/config.yaml")

# Later, after file changes...
config.reload()  # Re-reads file, reapplies env overrides
```

**Note:** Not thread-safe. Callers must coordinate access during reload.

## ConfigWatcher

File watcher for hot-reload of configuration. Uses watchdog for efficient file system monitoring.

```python
class ConfigWatcher:
    def __init__(self, lg: Logger, etc_dir: str | Path): ...

    def configure(
        self,
        config_file: str,
        debounce_ms: int = 500,
        on_change: Callable[[dict], None] | None = None
    ) -> ConfigWatcher: ...

    def start(self) -> None: ...
    def stop(self) -> None: ...
    def is_running(self) -> bool: ...
    def reload_now(self) -> None: ...
    def add_section_callback(self, section: str, callback: Callable) -> None: ...
    def remove_section_callback(self, section: str, callback: Callable) -> None: ...
```

**Basic Usage:**

```python
from appinfra.config import ConfigWatcher
from appinfra.log import LogConfigReloader

# Create reloader callback for logging config
reloader = LogConfigReloader(root_logger, section="logging")

# Create and start watcher
watcher = ConfigWatcher(lg=logger, etc_dir="/etc/myapp")
watcher.configure("config.yaml", on_change=reloader)
watcher.start()

# File changes are now automatically detected
# ...

watcher.stop()
```

**Requirements:**

```bash
pip install appinfra[hotreload]  # Installs watchdog
```

## Section Callbacks

Register callbacks for specific config sections:

```python
watcher = ConfigWatcher(lg=logger, etc_dir="./etc")
watcher.configure("config.yaml")

def on_features_changed(features_config):
    logger.info("Features updated")
    apply_feature_flags(features_config)

def on_plugins_changed(plugins_config):
    logger.info("Plugins updated")
    reload_plugins(plugins_config)

watcher.add_section_callback("features", on_features_changed)
watcher.add_section_callback("proxy.plugins", on_plugins_changed)
watcher.start()
```

## Content-Based Change Detection

ConfigWatcher uses content hashing to avoid spurious reloads when file is touched but content is
unchanged:

```python
# File touched but content identical -> no callback triggered
# File content actually changed -> callback triggered
```

## Include File Watching

ConfigWatcher automatically watches all files that contribute to the config, including files loaded
via `!include`:

```python
watcher.configure("config.yaml")
watcher.start()
# Now watching: config.yaml, database.yaml, base.yaml, etc.

# If any included file changes, config is reloaded
```

## Schema Validation

Optional Pydantic-based validation (requires `appinfra[validation]`):

```python
from appinfra.config import Config

config = Config("etc/config.yaml")

# Validate against schema
try:
    validated = config.validate()
    print("Configuration is valid!")
except ValidationError as e:
    print(f"Invalid configuration: {e}")

# Non-raising validation
if config.validate(raise_on_error=False):
    print("Valid")
else:
    print("Invalid")
```

**Install validation support:**

```bash
pip install appinfra[validation]
```

## Path Utilities

```python
from appinfra.config import (
    get_project_root,      # Find project root (contains etc/)
    get_etc_dir,           # Get etc directory path
    get_config_file_path,  # Get path to config file
    get_default_config,    # Lazy-load default config
)

# Get paths
root = get_project_root()           # /path/to/project
etc = get_etc_dir()                 # /path/to/project/etc
config_path = get_config_file_path()  # /path/to/project/etc/infra.yaml
config_path = get_config_file_path("app.yaml")  # /path/to/project/etc/app.yaml

# Lazy-load default config (for scripts/examples)
config = get_default_config()
if config:
    db_host = config.database.host
```

## Constants

```python
from appinfra.config import (
    PROJECT_ROOT,          # Resolved project root or None
    ETC_DIR,               # Resolved etc dir or None
    DEFAULT_CONFIG_FILE,   # Resolved default config path or None
    MAX_CONFIG_SIZE_BYTES, # Maximum config file size (security limit)
)
```

## Integration with AppBuilder

```python
from appinfra.app import AppBuilder

app = (
    AppBuilder("myapp")
    .with_config_file("config.yaml")  # Resolved from --etc-dir
    .logging
        .with_hot_reload(True)        # Enable config hot-reload for logging
        .done()
    .build()
)
```

## See Also

- [Configuration Precedence](../guides/configuration-precedence.md) - Full precedence hierarchy (CLI > Env > YAML)
- [Environment Variables](../guides/environment-variables.md) - Detailed env var documentation
- [Utilities](utilities.md#dotdict) - DotDict base class
- [Logging System](logging.md) - LogConfigReloader for hot-reload
- [Hot-Reload Guide](../guides/hot-reload-logging.md) - Full hot-reload documentation
