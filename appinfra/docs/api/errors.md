# Exceptions

Exception hierarchy for comprehensive error handling across the framework.

## Exception Hierarchy

```
InfraError (base)
├── ConfigError
├── DatabaseError
├── LoggingError
├── ValidationError
├── ToolError
├── ServerError
└── ObservabilityError
```

## Base Exception

```python
class InfraError(Exception):
    """Base exception for all framework errors."""

    def __init__(self, message: str, context: dict | None = None):
        self.message = message
        self.context = context or {}
        super().__init__(message)
```

## Exception Types

| Exception | Use Case |
|-----------|----------|
| `InfraError` | Base for all framework errors |
| `ConfigError` | Configuration loading/parsing errors |
| `DatabaseError` | Database connection/query errors |
| `LoggingError` | Logging setup/handler errors |
| `ValidationError` | Input/config validation errors |
| `ToolError` | Tool execution/lifecycle errors |
| `ServerError` | HTTP server errors |
| `ObservabilityError` | Metrics/tracing errors |

## Usage Examples

**Catching Framework Exceptions:**

```python
from appinfra.errors import InfraError, ConfigError
from appinfra.config import Config

try:
    config = Config("nonexistent.yaml")
except ConfigError as e:
    print(f"Configuration error: {e}")
except InfraError as e:
    print(f"Framework error: {e}")
```

**Catching Specific Exceptions:**

```python
from appinfra.errors import DatabaseError
from appinfra.db import PG
from appinfra.cfg import get_config_file_path

try:
    pg = PG(get_config_file_path(), "production")
    with pg.session() as session:
        result = session.execute("INVALID SQL")
except DatabaseError as e:
    print(f"Database error: {e}")
```

**Raising with Context:**

```python
from appinfra.errors import ValidationError

raise ValidationError(
    "Invalid configuration",
    context={"field": "database.port", "value": "invalid"}
)
```

**Re-raising with Context:**

```python
from appinfra.errors import DatabaseError

try:
    connect_to_database()
except Exception as e:
    raise DatabaseError(
        f"Failed to connect: {e}",
        context={"original_error": str(e)}
    ) from e
```

## Best Practices

1. **Catch specific exceptions** - not bare `Exception`
2. **Provide context** - include relevant details
3. **Use appropriate type** - ValidationError for validation, ConfigError for config
4. **Re-raise properly** - use `from e` to preserve chain

## See Also

- [Application Framework](app.md) - Tool error handling
- [Database Layer](database.md) - Database error handling
