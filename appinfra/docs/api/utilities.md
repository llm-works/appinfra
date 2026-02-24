# Utilities

Core utilities including DotDict, Config, rate limiting, EWMA, size formatting, and YAML support.

## Config

Configuration loader with environment variable overrides.

```python
class Config(DotDict):
    def __init__(
        self,
        fname: str,
        enable_env_overrides: bool = True,
        env_prefix: str = "INFRA_",
        merge_strategy: str = "replace"
    ): ...

    def get(self, path: str, default=None) -> Any: ...
    def get_env_overrides(self) -> dict: ...
```

**Usage:**

```python
from appinfra.config import Config, get_config_file_path

config = Config(get_config_file_path())  # Automatic etc/ resolution

# Access with dot notation
print(config.logging.level)
print(config.database.host)

# Get with fallback
port = config.get("database.port", default=5432)
```

**Environment Override Pattern:**

```bash
export INFRA_LOGGING_LEVEL=debug
export INFRA_DATABASE_PORT=5433
```

```python
config = Config(get_config_file_path())
print(config.logging.level)  # "debug" (from env)
```

## DotDict

Dictionary subclass with attribute-style access and dot-notation paths.

Since DotDict subclasses `dict`, `isinstance(dotdict, dict)` returns `True`.

```python
class DotDict(dict):
    def __init__(self, *args, **kwargs): ...            # Accepts dict as positional arg or kwargs

    def get(self, path: str, default=None) -> Any: ...  # Dot-path access, returns None if not found
    def require(self, path: str) -> Any: ...            # Like get(), but raises if path missing
    def has(self, path: str) -> bool: ...               # Check if path exists
    def set(self, **kwargs) -> DotDict: ...
    def dict(self) -> dict: ...
    def to_dict(self) -> dict: ...                      # Recursive conversion to plain dicts
```

**Usage:**

```python
from appinfra.dot_dict import DotDict

# Initialize with keyword arguments
config = DotDict(
    database={"host": "localhost", "port": 5432}
)

# Or from dict (positional argument - matches built-in dict() API)
data = {"database": {"host": "localhost", "port": 5432}}
config = DotDict(data)

# Kwargs override positional dict values
config = DotDict({"port": 3000}, port=8080)  # port will be 8080

# isinstance check works (DotDict is a dict subclass)
isinstance(config, dict)  # True
isinstance(config.database, dict)  # True

# Attribute access
print(config.database.host)  # "localhost"

# Dictionary access
print(config["database"]["port"])  # 5432

# Dot-path get (cleaner than chained .get() calls)
# Instead of: config.get("database", {}).get("host", {}).get("port")
value = config.get("database.host")           # "localhost"
port = config.get("database.port", 5432)      # 5432
missing = config.get("database.missing")      # None

# Require - raises DotDictPathNotFoundError if path missing
from appinfra.dot_dict import DotDictPathNotFoundError
try:
    host = config.require("database.host")    # "localhost"
    user = config.require("database.user")    # Raises!
except DotDictPathNotFoundError as e:
    print(f"Missing required config: {e.path}")

# Check if path exists (useful when None could be a valid value)
if config.has("database.password"):
    password = config.get("database.password")

# Set values
config.database.username = "postgres"

# Convert to dict
data = config.dict()       # One level conversion
data = config.to_dict()    # Recursive conversion
```

## DataDotDict

Typed DotDict with field declarations for IDE autocomplete and validation.

```python
class DataDotDict(DotDict):
    # Subclass with field annotations
    pass

def field(*, default_factory: Callable[[], Any]) -> Any:
    """Declare field with mutable default (list, dict, set)."""
```

**Usage:**

```python
from appinfra import DataDotDict, field

class RunResult(DataDotDict):
    # Required fields (no default)
    status: str
    started_at: datetime
    completed_at: datetime

    # Optional fields (with defaults)
    method: str = "sft"
    error: str | None = None

    # Mutable defaults (use field() to avoid shared state)
    metrics: dict = field(default_factory=dict)

    # Computed fields via __post_init__
    def __post_init__(self):
        self.duration = (self.completed_at - self.started_at).total_seconds()

# Create instance
result = RunResult(status="completed", started_at=t0, completed_at=t1)

result.status    # IDE autocomplete works
result.method    # "sft" (default applied)
result.metrics   # {} (fresh dict per instance)

# Still a dict - no serialization needed
json.dumps(result)       # Just works
yaml.safe_dump(result)   # Just works
isinstance(result, dict) # True
```

**Strict Mode:**

```python
class StrictConfig(DataDotDict, strict=True):
    host: str
    port: int = 5432

StrictConfig(host="localhost")                    # OK
StrictConfig(host="localhost", extra="field")     # TypeError: unknown field
```

**Key differences from dataclass:**

| Feature | dataclass | DataDotDict |
|---------|-----------|-------------|
| Is a dict | No | Yes |
| JSON serialization | `asdict()` required | Just works |
| Attribute access | Yes | Yes |
| Dict access `obj["key"]` | No | Yes |
| Dot-path `obj.get("a.b")` | No | Yes |

## RateLimiter

Control operation frequency with blocking or non-blocking modes.

```python
class RateLimiter:
    def __init__(
        self,
        lg: Logger,               # Logger (required, first parameter)
        per_minute: float,        # Operations per minute (e.g., 1/60 for hourly)
    ): ...

    def next(self, respect_max_ticks: bool = True) -> float: ...  # Blocking: wait and return delay
    def try_next(self) -> bool: ...                               # Non-blocking: return True if allowed
```

**Blocking Mode (`next()`):**

```python
from appinfra.rate_limit import RateLimiter
from appinfra.log import Logger

lg = Logger("my_app")
limiter = RateLimiter(lg, per_minute=60)  # 1 operation per second

for i in range(10):
    limiter.next()  # Blocks/sleeps if rate limit exceeded
    do_operation()
```

**Non-Blocking Mode (`try_next()`):**

For event loops that cannot block (e.g., message-processing loops):

```python
limiter = RateLimiter(lg, per_minute=60)

while running:
    process_messages()  # Handle SHUTDOWN signals, etc.

    if limiter.try_next():
        do_rate_limited_operation()
    # If rate limited, skip this cycle and retry on next iteration
```

**Bypass Mode:**

```python
limiter.next(respect_max_ticks=False)  # Returns delay but doesn't sleep
```

## Backoff

Exponential backoff for retry logic with configurable delays and jitter.

```python
class Backoff:
    def __init__(
        self,
        lg: Logger,               # Logger (required, first parameter)
        base: float = 1.0,        # Initial delay (seconds, must be > 0)
        max_delay: float = 60.0,  # Maximum delay cap (must be > 0)
        factor: float = 2.0,      # Multiplier per attempt (must be >= 1)
        jitter: bool = True,      # Randomize to avoid thundering herd
    ): ...

    def wait(self) -> float: ...       # Blocking: sleep and return actual delay
    def next_delay(self) -> float: ... # Non-blocking: return delay, increment attempt
    def reset(self) -> None: ...       # Reset after success

    @property
    def attempts(self) -> int: ...     # Current attempt count
```

**Usage:**

```python
from appinfra.rate_limit import Backoff

backoff = Backoff(logger)

while True:
    try:
        response = call_endpoint()
        backoff.reset()  # Success - reset for next time
        return response
    except ConnectionError:
        backoff.wait()  # Exponential backoff: 1s, 2s, 4s, 8s... capped at 60s
```

**Algorithm:**

```text
delay = min(base * (factor ** attempts), max_delay)
if jitter:
    delay = delay * random.uniform(0.0, 1.0)  # Full jitter
```

**Non-Blocking Mode:**

```python
backoff = Backoff(logger, base=1.0, max_delay=30.0)

delay = backoff.next_delay()  # Get delay without sleeping
# ... do something else ...
time.sleep(delay)             # Sleep manually when ready
```

**Custom Configuration:**

```python
# Aggressive backoff for critical services
backoff = Backoff(logger, base=0.1, max_delay=5.0, factor=1.5, jitter=True)

# Conservative backoff for batch jobs
backoff = Backoff(logger, base=5.0, max_delay=300.0, factor=2.0, jitter=False)
```

## EWMA

Exponentially Weighted Moving Average for streaming values.

```python
class EWMA:
    def __init__(self, age: float = 30.0): ...

    def add(self, value: float) -> None: ...   # Add sample
    def value(self) -> float: ...              # Get current average
    def reset(self, value: float = 0.0): ...   # Reset state
```

The `age` parameter controls smoothing:
- Higher age = smoother output, slower to react to changes
- Lower age = noisier output, faster to react to changes

**Usage:**

```python
from appinfra.ewma import EWMA

# Track average request latency with 30-second smoothing
latency = EWMA(age=30.0)
latency.add(0.05)  # 50ms
latency.add(0.08)  # 80ms
latency.add(0.03)  # 30ms
print(f"Average latency: {latency.value():.3f}s")

# Reset to start fresh
latency.reset()
```

**How it works:**

EWMA uses the formula: `avg = (new * decay) + (avg * (1 - decay))` where `decay = 2 / (age + 1)`.

The first sample sets the initial value directly. Subsequent samples blend with exponential
weighting, giving more weight to recent values.

## Size Formatting

Format byte sizes as human-readable strings.

```python
from appinfra.size import size_str, size_to_bytes

# Format bytes to string
size_str(1024)           # "1KB"
size_str(1536)           # "1.5KB"
size_str(1048576)        # "1MB"
size_str(500)            # "500B"

# Precise mode (3 decimal places)
size_str(1536, precise=True)   # "1.500KB"

# SI units (1000-based instead of 1024)
size_str(1500, binary=False)   # "1.5KB"

# Parse size string back to bytes
size_to_bytes("1.5MB")   # 1572864
size_to_bytes("500B")    # 500
size_to_bytes("1GiB")    # 1073741824 (IEC suffixes supported)
```

**Options:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `precise` | `False` | Show 3 decimal places |
| `binary`  | `True`  | Use 1024-based (binary) vs 1000-based (SI) |

**Validation:**

```python
from appinfra.size import validate_size, InvalidSizeError

validate_size(1024)    # True
validate_size(-1)      # False
validate_size("1KB")   # False (not a number)

try:
    size_str(-1)
except InvalidSizeError as e:
    print(f"Invalid: {e}")
```

## YAML Utilities

YAML loading with custom tag support.

```python
from appinfra.yaml import load, Loader
from pathlib import Path

# Load YAML with custom tag support
with open("config.yaml") as f:
    config = load(f, current_file=Path("config.yaml"))
```

### Custom Tags

**`!include`** - Include other YAML files:

```yaml
# Key-level include (as a value)
database: !include "./database.yaml"           # Include entire file
settings: !include "config.yaml#app.settings"  # Include specific section

# Document-level include (merge at root)
!include "./base.yaml"

app_name: myapp
server:
  port: 8080
```

Document-level includes (at column 0) merge included content with the main document. The included
file provides defaults; main document content overrides. Nested includes are supported.

**`!secret`** - Mark sensitive values (warns if not using env var syntax):

```yaml
password: !secret ${DB_PASSWORD}    # Valid - env var reference
api_key: !secret my_literal_key     # Warning - should use ${VAR} syntax
```

**`!path`** - Resolve paths relative to config file location with tilde expansion:

```yaml
models_dir: !path ../.models       # Resolves to absolute path
data_dir: !path /absolute/path     # Absolute paths unchanged
cache: !path ./cache               # Relative to config file
home_cache: !path ~/.cache/myapp   # Expands ~ to home directory
```

## Path Resolution

Path resolution in configuration files requires the explicit `!path` YAML tag. Without the tag,
paths remain as literal strings:

```yaml
# Config at /app/etc/config.yaml
logging:
  file: ./logs/app.log           # Stays as "./logs/app.log" (literal string)
  resolved: !path ./logs/app.log # Resolved to /app/etc/logs/app.log

cache:
  dir: ~/.cache/myapp            # Stays as "~/.cache/myapp" (literal string)
  resolved: !path ~/.cache/myapp # Expands to /home/user/.cache/myapp
```

```python
from appinfra.config import Config, get_config_file_path

config = Config(get_config_file_path("config.yaml"))
print(config.logging.file)      # "./logs/app.log" (literal)
print(config.logging.resolved)  # "/app/etc/logs/app.log" (absolute)
```

**The `!path` tag:**
- Resolves relative paths (`./`, `../`) to absolute paths based on config file location
- Expands tilde (`~`) to the user's home directory
- Leaves absolute paths and URLs unchanged

## Utility Functions

```python
from appinfra.utils import pretty, is_int

# Pretty print data structures
data = {"name": "John", "nested": {"key": "value"}}
print(pretty(data))

# Check if value is integer-like
is_int("123")   # True
is_int("12.3")  # False
```

## Deprecation Decorator

```python
from appinfra.deprecation import deprecated

@deprecated(version="0.2.0", replacement="new_function")
def old_function():
    return "old result"

old_function()  # Warning: old_function is deprecated since 0.2.0
```

## See Also

- [Environment Variables Guide](../guides/environment-variables.md)
- [Configuration examples](../examples/)
