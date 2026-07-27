---
title: LoggingBuilder Guide
keywords:
  - logging
  - logger
  - fluent API
  - configure logging
  - log format
  - log output
  - console logging
  - file logging
aliases:
  - logger-builder
  - log-config
---

# LoggingBuilder Guide

Fluent API for configuring loggers with various output destinations and formatting options.

## Quick Start

```python
from appinfra.log import LoggingBuilder

logger = (
    LoggingBuilder("my_app")
    .with_level("info")
    .with_location(1)
    .with_micros(True)
    .console_handler()
    .file_handler("logs/app.log")
    .build()
)
```

## Builder Types

### Base LoggingBuilder
General-purpose builder supporting multiple handlers:

```python
logger = (
    LoggingBuilder("my_app")
    .with_level("info")
    .with_location(1)  # Show file locations (0-3 levels)
    .with_micros(True)  # Microsecond precision
    .with_colors(True)  # Colored output
    .console_handler()
    .file_handler("logs/app.log")
    .rotating_file_handler(
        "logs/errors.log", max_bytes=10 * 1024 * 1024, backup_count=5
    )
    .build()
)
```

### ConsoleLoggingBuilder
Console-only logging:

```python
from appinfra.log import ConsoleLoggingBuilder

logger = (
    ConsoleLoggingBuilder("my_app")
    .with_level("info")
    .with_colors(True)  # stdout is the default; use .stderr() if needed
    .build()
)
```

### FileLoggingBuilder
File-only logging with rotation:

```python
from appinfra.log import FileLoggingBuilder

logger = (
    FileLoggingBuilder("my_app", "logs/app.log")
    .with_level("debug")
    .with_rotation(max_bytes=10 * 1024 * 1024, backup_count=5)
    .daily_rotation(backup_count=7)  # Or use daily rotation
    .build()
)
```

### JSONLoggingBuilder
Structured JSON logging:

```python
from appinfra.log import JSONLoggingBuilder

logger = (
    JSONLoggingBuilder("api")
    .with_level("info")
    .with_json_file("logs/api.json")
    .with_custom_fields({"service": "api", "version": "2.0.0"})
    .with_pretty_print(True)  # For development
    .build()
)

# Log structured data
logger.info(
    "User login",
    extra={
        "user_id": "user-123",
        "session_id": "sess-abc",
        "ip_address": "192.168.1.100",
    },
)
```

## Quick Setup Functions

For simple cases, use convenience functions:

```python
from appinfra.log import quick_console_logger, quick_file_logger, quick_json_file

# Console only
logger = quick_console_logger("my_app", "info")

# File only
logger = quick_file_logger("my_app", "logs/app.log", "debug")

# JSON file
logger = quick_json_file("my_app", "logs/app.json", "info")
```

## Usage Examples

### Development
```python
from appinfra.log import JSONLoggingBuilder

dev_logger = (
    JSONLoggingBuilder("my_app.dev")
    .with_level("debug")
    .with_location(2)
    .with_json_file("logs/development.json")
    .with_pretty_print(True)
    .build()
)
```

### Production
```python
from appinfra.log import LoggingBuilder

prod_logger = (
    LoggingBuilder("my_app.prod")
    .with_level("info")
    .console_handler()
    .rotating_file_handler("logs/app.log", max_bytes=10 * 1024 * 1024, backup_count=10)
    .timed_rotating_file_handler("logs/errors.log", when="midnight", backup_count=30)
    .build()
)
```

### Microservice with Structured Logging
```python
from appinfra.log import JSONLoggingBuilder

service_logger = (
    JSONLoggingBuilder("auth-service")
    .with_level("info")
    .with_json_file("logs/auth.json")
    .with_custom_fields({"service": "auth", "environment": "production"})
    .build()
)

service_logger.info(
    "User authentication",
    extra={"user_id": "user-123", "auth_method": "jwt", "success": True},
)
```

## Best Practices

**Choose the right builder:**
- `ConsoleLoggingBuilder` - Console-only applications
- `FileLoggingBuilder` - File-only with rotation
- `LoggingBuilder` - Multiple output destinations
- `JSONLoggingBuilder` - Structured logging for aggregation

**Use structured logging:**
```python
# Good
logger.info("User login", extra={"user_id": "123", "ip": "192.168.1.1"})

# Avoid
logger.info("User 123 logged in from 192.168.1.1")
```

**Configure rotation for production:**
```python
FileLoggingBuilder("app", "logs/app.log")
    .with_rotation(max_bytes=100*1024*1024, backup_count=10)
```

**Handle exceptions properly:**
```python
try:
    result = risky_operation()
except Exception as e:
    logger.error(
        "Operation failed",
        extra={"operation": "risky_operation", "error": str(e)},
        exc_info=True,
    )
```



