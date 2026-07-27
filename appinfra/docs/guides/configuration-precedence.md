---
title: Configuration Precedence
keywords:
  - precedence
  - priority
  - override
  - CLI args
  - environment variables
  - YAML config
  - defaults
  - topic levels
aliases:
  - config-priority
  - override-order
---

# Configuration Precedence

This guide explains the order of precedence when configuration values come from multiple sources.

## General Configuration Values

For most configuration values (log level, colors, location, etc.), the precedence is:

| Priority | Source | Example |
|----------|--------|---------|
| **1 (Highest)** | CLI Arguments | `--log-level debug`, `--log-json` |
| **2** | Environment Variables | `INFRA_LOGGING_LEVEL=debug` |
| **3** | YAML Config File | `logging.level: info` in `infra.yaml` |
| **4 (Lowest)** | Built-in Defaults | `level=info`, `colors=true` |

### Example: Log Level Resolution

```yaml
# etc/infra.yaml
logging:
  level: warning
```

```bash
# Environment
export INFRA_LOGGING_LEVEL=info
```

```bash
# CLI invocation
./myapp --log-level debug serve
```

**Result:** Log level is `debug` (CLI wins)

Without the CLI flag, it would be `info` (env var). Without both, it would be `warning` (YAML).

## Topic-Based Log Levels

Topic-based log levels use numeric priorities. Higher numbers win when patterns overlap.

| Priority | Source | How to Set |
|----------|--------|------------|
| **10 (Highest)** | Programmatic API | `.with_topic_level("/db/*", "debug")` |
| **5** | CLI Arguments | `--log-topic '/db/**' debug` |
| **1 (Lowest)** | YAML Config | `logging.topics: {'/db/**': debug}` |

### Example: Topic Level Resolution

```yaml
# etc/infra.yaml
logging:
  topics:
    '/infra/db/**': warning    # priority=1
```

```bash
# CLI
./myapp --log-topic '/infra/db/**' info serve   # priority=5
```

```python
# Code
builder.logging.with_topic_level("/infra/db/**", "debug")  # priority=10
```

**Result:** `/infra/db/**` logs at `debug` level (API priority=10 wins)

### Pattern Matching

When multiple patterns match a topic, the most specific pattern wins. If specificity is equal,
higher priority wins:

```yaml
logging:
  topics:
    '/infra/**': warning      # Broad pattern
    '/infra/db/*': info       # More specific - wins for /infra/db/queries
```

## Handler-Level Overrides

The `--log-json` and `--no-log-colors` CLI flags override settings for **all console handlers**
defined in YAML config.

### Example: Handler Override

```yaml
# etc/infra.yaml
logging:
  handlers:
    stdout:
      type: console
      format: text
      colors: true
    stderr:
      type: console
      format: text
      colors: true
```

```bash
./myapp --log-json serve
```

**Result:** Both `stdout` and `stderr` handlers output JSON format.

### Default Handler Behavior

When no handlers are configured in YAML, a default console handler is created. CLI flags apply to
this default handler as well:

```bash
./myapp --no-log-colors serve   # Default handler has colors disabled
./myapp --log-json serve        # Default handler outputs JSON
```

## Standard CLI Arguments

These arguments are available by default (can be disabled via `without_standard_args()`):

| Argument | Overrides | Default |
|----------|-----------|---------|
| `--log-level LEVEL` | `logging.level` | `info` |
| `--log-json` | Handler format | `text` |
| `--no-log-colors` | Handler colors | `true` |
| `--log-location DEPTH` | `logging.location` | `0` |
| `--log-micros` | `logging.micros` | `false` |
| `--log-topic PATTERN LEVEL` | `logging.topics` | none |
| `-q, --quiet` | Disables logging | `false` |
| `--etc-dir DIR` | Config directory | auto-detect |

## Environment Variable Format

Environment variables follow the pattern: `INFRA_<SECTION>_<KEY>`

```bash
# Logging settings
INFRA_LOGGING_LEVEL=debug
INFRA_LOGGING_MICROS=true
INFRA_LOGGING_COLORS=false

# Nested settings
INFRA_PGSERVER_PORT=5432
INFRA_TEST_LOGGING_LEVEL=info
```

See [Environment Variable Overrides](environment-variables.md) for detailed documentation.

## Programmatic Configuration

Configuration set via AppBuilder methods has the same precedence as YAML but is applied after YAML
loading:

```python
app = (
    AppBuilder("myapp")
    .with_config_file("app.yaml")  # Load YAML
    .logging.with_level("debug")  # Overrides YAML logging.level
    .with_topic_level("/db/*", "trace")  # Priority=10, highest
    .done()
    .build()
)
```

**Precedence for programmatic config:**
- CLI args still override programmatic settings
- Programmatic settings override YAML values
- Topic levels via API get priority=10 (highest)

## Quick Reference

### What Wins?

| Scenario | Winner |
|----------|--------|
| CLI `--log-level debug` vs YAML `level: info` | CLI (`debug`) |
| Env `INFRA_LOGGING_LEVEL=debug` vs YAML `level: info` | Env (`debug`) |
| CLI `--log-level debug` vs Env `INFRA_LOGGING_LEVEL=warning` | CLI (`debug`) |
| API `.with_topic_level()` vs CLI `--log-topic` | API (priority=10) |
| CLI `--log-json` vs YAML `format: text` | CLI (`json`) |

### Debugging Precedence Issues

Check which overrides are active:

```python
from appinfra.config import Config

config = Config("etc/infra.yaml")

# See environment variable overrides
print("Env overrides:", config.get_env_overrides())

# See final resolved config
print("Final config:", config.to_dict())
```

For topic levels:

```python
from appinfra.log.level_manager import LogLevelManager

manager = LogLevelManager.get_instance()
print("Topic rules:", manager.get_rules())
```

## See Also

- [Environment Variable Overrides](environment-variables.md) - Detailed env var documentation
- [AppBuilder API](../api/app-builder.md) - Standard arguments reference
- [Logging System](../api/logging.md) - Logger configuration
- [Config-Based Logging](config-based-logging.md) - YAML logging configuration
