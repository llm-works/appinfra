# Logging

Comprehensive logging examples using the infra logging system.

## Examples

### logging_builder_example.py
Comprehensive logging examples covering all features.

**What you'll learn:**
- Console logging
- File logging with rotation
- JSON structured logging
- Custom log levels (TRACE/TRACE2)
- Multiple handlers
- LoggingBuilder fluent API

**Run:**
```bash
~/.venv/bin/python examples/03_logging/logging_builder_example.py
```

**Covers:**
- Basic console logging
- File handlers with size/time rotation
- JSON logging for log aggregation
- Custom fields and structured data
- Pretty-printed JSON for development
- Multiple output destinations

---

### disabled_logging.py
Disabling logging completely (useful for tests).

**What you'll learn:**
- How to disable all logging
- When and why to disable logging
- Configuration-based vs programmatic disabling

**Run:**
```bash
~/.venv/bin/python examples/03_logging/disabled_logging.py
```

**Use cases:**
- Unit tests (reduce noise)
- Performance testing
- Silent production modes

---

### database_logging.py
Logging to PostgreSQL database.

**What you'll learn:**
- Database handler setup
- Logging to PostgreSQL
- Structured log storage
- Querying logs from database

**Run:**
```bash
# Requires PostgreSQL
make pg.server.up
~/.venv/bin/python examples/03_logging/database_logging.py
```

**Prerequisites:**
- PostgreSQL server running
- Database configured in `etc/infra.yaml`

---

### topic_logging_example.py
Fine-grained log level control using topic patterns.

**What you'll learn:**
- Topic-based logging with glob patterns
- YAML, CLI, and programmatic API configuration
- Pattern specificity and precedence
- Runtime logger updates (opt-in)

**Run:**
```bash
~/.venv/bin/python examples/03_logging/topic_logging_example.py
```

**Pattern Syntax:**
- `*` - Single path segment (e.g., `/infra/db/*`)
- `**` - Any depth recursive (e.g., `/infra/**`)
- Exact paths (e.g., `/infra/db/queries`)

**Configuration Methods:**
1. **YAML** - See `topic_logging_config.yaml`
2. **CLI** - `--log-topic '/infra/db/*' debug`
3. **API** - `.logging.with_topic_levels({...})`

**Priority:** API (10) > CLI (5) > YAML (1)

---

## Key Concepts

### LoggingBuilder
Fluent API for configuring loggers:
```python
logger = (
    LoggingBuilder("app")
    .with_level("info")
    .with_location(1)
    .with_micros(True)
    .console_handler()
    .file_handler(".logs/app.log")
    .build()
)
```

### Specialized Builders
- `ConsoleLoggingBuilder` - Console-only logging
- `FileLoggingBuilder` - File-only with rotation
- `JSONLoggingBuilder` - Structured JSON logging

### Topic-Based Logging
Fine-grained control over log levels using glob patterns:
```python
app = (
    AppBuilder("myapp")
    .logging.with_topic_levels(
        {
            "/infra/db/*": "debug",  # DB layer → debug
            "/infra/api/*": "warning",  # API layer → warning
            "/myapp/**": "info",  # All app → info
        }
    )
    .done()
    .build()
)
```

**Pattern Matching:**
- More specific patterns win (exact > `*` > `**`)
- API configuration overrides CLI, which overrides YAML
- Runtime updates available via `.with_runtime_updates(True)`

### Structured Logging
Always use `extra` dict for structured data:
```python
logger.info("User login", extra={"user_id": "123", "ip_address": "192.168.1.1"})
```

### Log Levels
Standard levels plus custom:
- TRACE2 (5) - Very detailed trace
- TRACE (7) - Detailed trace
- DEBUG (10)
- INFO (20)
- WARNING (30)
- ERROR (40)
- CRITICAL (50)

## Best Practices

1. **Use structured logging** - Put data in `extra` dict, not in message string
2. **Configure rotation** - Use size or time-based rotation for production
3. **Multiple handlers** - Different outputs for different purposes
4. **JSON for production** - Structured logs for aggregation systems
5. **Disable for tests** - Reduce noise in test output
6. **Use topic patterns** - Fine-grained control for different components
   - Development: Set framework to `debug`, app to `info`
   - Production: Set framework to `warning`, critical services to `info`
   - Troubleshooting: Set specific component to `trace`

## Next Steps

- [Configuration](../04_configuration/) - Configure logging via YAML
- [Database](../05_database/) - Use logging with database operations

## Related Documentation

- [Logging Builder Guide](../../docs/guides/logging-builder.md) - Complete API reference
- [Config-Based Logging](../../docs/guides/config-based-logging.md) - Test logging setup
- [Main README](../README.md) - Full examples index
