# Database Module (`infra/db`)

A comprehensive database management system providing centralized connection management, health monitoring, and error handling for multiple database types.

## Overview

The `infra/db` module provides a robust database management system that supports:
- Multiple named database connections
- Configuration-driven setup
- Health checks and monitoring
- Comprehensive error handling
- Connection pooling and lifecycle management
- PostgreSQL support with extensible architecture

## Architecture

### Manager Pattern
The `Manager` class serves as the central coordinator for all database connections, providing:
- **Registry Pattern**: Stores database connections in a dictionary
- **Factory Pattern**: Creates appropriate database instances based on URL scheme
- **Configuration-Driven**: Uses configuration objects to define database settings

### Abstract Interface
The `Interface` abstract base class defines the contract for all database implementations:
- Ensures consistent behavior across different database types
- Provides extensibility for adding new database types
- Defines standard methods: `connect()`, `session()`, `migrate()`, `health_check()`

### PostgreSQL Implementation
The `PG` class provides a complete PostgreSQL interface with:
- SQLAlchemy integration with connection pooling
- Query logging and performance monitoring
- Read-only connection support
- Database migration capabilities
- Comprehensive error handling

## Key Components

### Manager Class

```python
from appinfra.db import Manager

# Initialize with configuration
manager = Manager(logger, config)
manager.setup()

# Access databases
primary_db = manager.db("primary")
readonly_db = manager.db("readonly")

# Health checks
health_results = manager.health_check()
stats = manager.get_stats()
```

**Key Methods:**
- `setup()`: Initialize all configured database connections
- `db(name)`: Retrieve database connection by name
- `health_check(name=None)`: Perform health checks
- `list_databases()`: Get available database names
- `close_all()`: Gracefully close all connections
- `get_stats()`: Get connection statistics

### PostgreSQL Interface

```python
from appinfra.pg import PG

# Initialize PostgreSQL connection
pg = PG(logger, config, query_lg_level="debug")

# Connect and execute queries
conn = pg.connect()
session = pg.session()

# Health monitoring
health = pg.health_check()
pool_status = pg.get_pool_status()
```

**Key Features:**
- **Connection Pooling**: Configurable pool size, overflow, and timeouts
- **Query Logging**: Comprehensive SQL statement logging with timing
- **Read-only Mode**: Support for read-only connections
- **Health Checks**: Built-in health monitoring
- **Migration Support**: Database schema migration capabilities

## Configuration

### Manager Configuration

```python
config = {
    "dbs": {
        "primary": {
            "url": "postgresql://user:pass@localhost/db",
            "readonly": False,
            "pool_size": 5,
            "max_overflow": 10,
            "pool_timeout": 30,
            "pool_recycle": 3600,
            "pool_pre_ping": True,
        },
        "readonly": {
            "url": "postgresql://user:pass@localhost/db",
            "readonly": True,
            "pool_size": 3,
        },
    }
}
```

### Database Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `url` | string | required | Database connection URL |
| `readonly` | boolean | false | Enable read-only mode |
| `create_db` | boolean | false | Create database if it doesn't exist |
| `pool_size` | integer | 5 | Connection pool size |
| `max_overflow` | integer | 10 | Maximum overflow connections |
| `pool_timeout` | integer | 30 | Pool timeout in seconds |
| `pool_recycle` | integer | 3600 | Connection recycle time |
| `pool_pre_ping` | boolean | true | Test connections before use |
| `echo` | boolean | false | Echo SQL statements |

## Error Handling

### Exception Types

- **`UnknownDBTypeException`**: Raised for unsupported database types
- **`ValueError`**: Invalid configuration or parameters
- **`sqlalchemy.exc.SQLAlchemyError`**: Database connection/query errors
- **`RuntimeError`**: Setup failures or connection issues

### Error Recovery

The system provides graceful error handling:
- **Partial Setup**: Continues setup even if some databases fail
- **Error Tracking**: Maintains error information for failed connections
- **Health Monitoring**: Regular health checks with detailed error reporting
- **Connection Retry**: Built-in connection retry logic

## Usage Examples

### Basic Usage

```python
from appinfra.db import Manager
from appinfra.log import LoggerFactory, LogConfig

# Setup logging
config = LogConfig.from_params("info")
logger = LoggerFactory.create_root(config)

# Database configuration
db_config = {"dbs": {"primary": {"url": "postgresql://localhost/mydb"}}}

# Initialize manager
manager = Manager(logger, db_config)
manager.setup()

# Use database
db = manager.db("primary")
conn = db.connect()
# ... use connection
conn.close()
```

### Advanced Usage with Health Monitoring

```python
# Setup multiple databases
config = {
    "dbs": {
        "primary": {"url": "postgresql://localhost/primary", "pool_size": 10},
        "readonly": {
            "url": "postgresql://localhost/readonly",
            "readonly": True,
            "pool_size": 5,
        },
    }
}

manager = Manager(logger, config)
manager.setup()

# Health monitoring
health_results = manager.health_check()
for db_name, result in health_results.items():
    if result["status"] == "healthy":
        print(f"✓ {db_name}: {result['response_time_ms']:.2f}ms")
    else:
        print(f"✗ {db_name}: {result['error']}")

# Connection statistics
stats = manager.get_stats()
print(f"Active connections: {stats['successful_setups']}")
print(f"Failed setups: {stats['failed_setups']}")
```

### Session Management

```python
# Using database sessions
db = manager.db("primary")

# Context manager for automatic cleanup
with db.session() as session:
    result = session.execute("SELECT * FROM users")
    users = result.fetchall()
    # Session automatically closed

# Manual session management
session = db.session()
try:
    result = session.execute("INSERT INTO users (name) VALUES ('John')")
    session.commit()
finally:
    session.close()
```

## Testing

The module includes comprehensive test coverage:

```bash
# Run database tests
python -m unittest infra.db_test -v

# Run PostgreSQL tests
python -m unittest infra.pg.pg_test -v
```

**Test Coverage:**
- Manager initialization and setup
- Database connection management
- Error handling and recovery
- Health check functionality
- Configuration validation
- Connection pooling
- Session management

## Performance Considerations

### Connection Pooling
- **Pool Size**: Configure based on expected concurrent connections
- **Overflow**: Allow temporary connections beyond pool size
- **Recycle**: Regularly refresh connections to prevent stale connections
- **Pre-ping**: Test connections before use to detect failures early

### Query Logging
- **Level Control**: Configure logging level to balance visibility and performance
- **Timing Information**: Built-in query execution timing
- **SQL Compilation**: Proper SQL statement logging with parameter binding

### Health Monitoring
- **Lightweight Checks**: Simple `SELECT 1` queries for health checks
- **Response Time Tracking**: Monitor database response times
- **Error Reporting**: Detailed error information for troubleshooting

## Extensibility

### Adding New Database Types

To add support for a new database type:

1. **Implement Interface**: Create a class inheriting from `Interface`
2. **Add URL Detection**: Update `Manager.setup()` to detect new URL schemes
3. **Register Factory**: Add factory logic for creating new database instances

```python
class MySQL(Interface):
    def __init__(self, lg, cfg, query_lg_level=None):
        # Implementation
        pass

    # Implement all abstract methods
    def connect(self):
        pass

    def session(self):
        pass

    def migrate(self):
        pass

    # ... etc
```

### Custom Configuration

Extend configuration options by:
- Adding new configuration parameters
- Implementing custom validation logic
- Creating specialized connection options

## Best Practices

### Configuration Management
- Use environment-specific configurations
- Store sensitive credentials securely
- Validate configurations before deployment

### Connection Management
- Always close connections properly
- Use context managers when possible
- Monitor connection pool usage

### Error Handling
- Implement proper exception handling
- Log errors with sufficient context
- Provide meaningful error messages

### Monitoring
- Regular health checks
- Monitor connection pool statistics
- Track query performance metrics

## Troubleshooting

### Common Issues

**Connection Failures:**
- Check database URL format
- Verify network connectivity
- Validate credentials and permissions

**Pool Exhaustion:**
- Increase pool size or max_overflow
- Check for connection leaks
- Monitor connection usage patterns

**Performance Issues:**
- Review query logging for slow queries
- Optimize connection pool settings
- Consider read-only replicas for read-heavy workloads

### Debugging

Enable debug logging for detailed information:
```python
config = LogConfig.from_params("debug")
logger = LoggerFactory.create_root(config)
```

Check health status and pool statistics:
```python
health = manager.health_check()
stats = manager.get_stats()
pool_status = db.get_pool_status()
```
