# Database

PostgreSQL integration and database testing patterns.

## Prerequisites

All examples require PostgreSQL:
```bash
# Start PostgreSQL (Docker)
make pg.server.up

# Verify connection
make pg
```

## Examples

### basic_critical_flush_example.py
Basic critical flush pattern with mock database.

**What you'll learn:**
- Critical flush pattern (periodic DB writes)
- Database handler for logging
- Clean shutdown with flush
- Using mock database for examples

**Run:**
```bash
~/.venv/bin/python examples/05_database/basic_critical_flush_example.py
```

**Key concepts:**
- Batching writes for performance
- Periodic flush to database
- Graceful shutdown ensures no data loss
- Mock database for testing/examples

---

### advanced_critical_flush.py
Advanced critical flush with real PostgreSQL.

**What you'll learn:**
- Real database integration
- Production-ready flush pattern
- Error handling and recovery
- Performance tuning

**Run:**
```bash
# Requires PostgreSQL
make pg.server.up
~/.venv/bin/python examples/05_database/advanced_critical_flush.py
```

**Prerequisites:**
- PostgreSQL running
- Database configured in `etc/infra.yaml`

---

### pg_test_helper.py
Comprehensive database test helper demonstration.

**What you'll learn:**
- PGTestCaseHelper for database tests
- Debug table management
- Table persistence on failure (for debugging)
- Automatic cleanup on success
- Table inspection utilities

**Run:**
```bash
make pg.server.up
~/.venv/bin/python examples/05_database/pg_test_helper.py
```

**Key concepts:**
- Inherit from `PGTestCaseHelper`
- Debug tables kept on test failure
- Automatic cleanup on success
- Inspect tables for debugging

---

### pg_test_helper_custom_config.py
Using custom configuration with PGTestCaseHelper.

**What you'll learn:**
- Custom config file paths
- Multiple database configurations
- Test environment setup

**Run:**
```bash
~/.venv/bin/python examples/05_database/pg_test_helper_custom_config.py
```

---

## Database Configuration

Configure PostgreSQL in `etc/infra.yaml`:

```yaml
pgserver:
  host: "127.0.0.1"
  port: 25432
  user: "postgres"
  password: "postgres"
  replica:                     # Optional: for replication mode
    enabled: true
    port: 25433

dbs:
  test:
    host: "${pgserver.host}"
    port: ${pgserver.port}
    user: "${pgserver.user}"
    password: "${pgserver.password}"
    database: "unittest"
```

## Patterns

### Critical Flush Pattern

**Problem:** Writing to database on every log is slow

**Solution:** Buffer writes and flush periodically

```python
# Buffer logs in memory
buffer.append(log_record)

# Flush periodically (e.g., every 5 seconds)
if time_since_last_flush > 5:
    db.bulk_insert(buffer)
    buffer.clear()

# Always flush on shutdown
on_shutdown():
    db.bulk_insert(buffer)
```

### Test Helper Pattern

**Problem:** Database tests leave debug tables on failure

**Solution:** Conditional cleanup based on test outcome

```python
session, table_name, cleanup_needed = self.test_helper.create_debug_table("test")

try:
    # Test logic
    cleanup_needed = True  # Success
except:
    cleanup_needed = False  # Failure - keep table for debugging
    raise
finally:
    self.test_helper.cleanup_debug_table(session, table_name, cleanup_needed)
```

## Best Practices

1. **Use connection pooling** - Reuse connections for performance
2. **Batch writes** - Use critical flush pattern for high-volume logging
3. **Graceful shutdown** - Always flush buffers on shutdown
4. **Test helpers** - Use PGTestCaseHelper for database tests
5. **Debug tables** - Keep tables on failure for debugging
6. **Read-only connections** - Separate connections for read-only operations

## Performance Tips

- **Pool size**: Start with 5-10, adjust based on load
- **Batch size**: 100-1000 records per flush
- **Flush interval**: 1-5 seconds for logging
- **Connection timeout**: 30 seconds default
- **Use indexes**: Index frequently queried columns

## Troubleshooting

### Connection refused
```bash
# Start PostgreSQL
make pg.server.up

# Check status
docker ps | grep postgres
```

### Database doesn't exist
```bash
# Connect to PostgreSQL
make pg

# Create database
CREATE DATABASE infra_test;
```

### Permission denied
Check credentials in `etc/infra.yaml`:
- User: postgres
- Password: postgres
- Port: 25432 (appinfra local pg default)

## Next Steps

- [Logging](../03_logging/) - Combine database with logging
- [Advanced](../06_advanced/) - Advanced patterns

## Related Documentation

- [PostgreSQL Test Helper Guide](../../docs/guides/pg-test-helper.md) - Complete API reference
- [Main README](../README.md) - Full examples index
