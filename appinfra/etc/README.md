# Infrastructure Configuration Guide

This directory contains the configuration files for the Infra framework. The main configuration file
is `infra.yaml`, which defines settings for logging, databases, servers, and other infrastructure
components.

## Configuration File Structure

The `infra.yaml` file uses YAML syntax and supports:

- **File inclusion** using `!include` tags for modular configuration
- **Variable substitution** using `${variable_name}` syntax
- **Environment variable overrides** using the `INFRA_*` prefix
- **Hierarchical configuration** with nested sections
- **Type-safe values** with automatic conversion
- **Circular dependency detection** for includes

## Configuration Sections

### 1. Logging Configuration

Controls logging behavior with support for multiple handlers and formats.

**Global Settings:** Apply to all handlers by default
**Handler Settings:** Can override global settings for specific handlers
**Inheritance:** Handlers inherit global settings when not explicitly specified

```yaml
logging:
  # Global logging settings (defaults for all handlers)
  level: info                   # Global log level: trace, debug, info, warning, error, critical, false (disabled)
  location: false              # Show file locations (false = disabled, integer = depth level)

  # Handler configurations (dictionary format with arbitrary names)
  handlers:
    # Handlers are now defined as a dictionary with arbitrary names chosen by the user
    console_text:              # Arbitrary handler name chosen by user
      type: console            # Handler type (console, file, database, rotating_file, timed_rotating_file)
      enabled: true           # Enable console logging
      level: info             # Override global level (inherits if not specified)
      format: text            # Format: text, json
      stream: stdout          # Output stream: stdout, stderr
      colors: true            # Enable colored output
      location: 0             # Location depth (inherits from global if not specified)
      micros: false           # Show microseconds (overwrites global setting)

    file_logger:               # Arbitrary handler name chosen by user
      type: file               # Handler type
      enabled: true            # Enable file logging
      level: debug            # Override global level - log more details
      format: text            # Format: text, json (set to json for JSON output)
      file: "logs/app.log"    # Output file path (same for both text and JSON)
      rotation: size          # Rotation: none, size, timed
      max_size: "50MB"        # Max file size before rotation
      backup_count: 5         # Number of backup files to keep

    database_logger:           # Arbitrary handler name chosen by user
      type: database           # Handler type
      enabled: false          # Enable database logging
      level: warning          # Override global level - only log warnings+
      format: json            # Format: text, json (json recommended for database logging)
      table: error_logs       # Database table name
      db: main                # Database connection to use
      batch_size: 10          # Batch size for database inserts
      flush_interval: 30      # Flush interval in seconds

    # Example: Additional handlers with custom names
    # json_file:
    #   type: file
    #   enabled: true
    #   format: json             # Enable JSON output
    #   file: "logs/app.json"   # You can even change the filename
    #   rotation: daily         # Different rotation for JSON logs
    #   max_size: "10MB"
    #   backup_count: 30
```

### Handler Format Options

Each handler supports different output formats:

| Handler Type | Format | Description |
|--------------|--------|-------------|
| `console`, `file` | `text` | Human-readable text format (supports colors for console) |
| `file` | `json` | Structured JSON format (same file handler, different format) |
| `database` | `text`, `json` | Database storage format |

### New Dictionary-Based Handler Structure

**Key Benefits:**
- ✅ **Arbitrary Names**: Handler names are chosen by the user (e.g., "console_text", "file_logger", "database_logger")
- ✅ **Explicit Type Field**: Each handler explicitly declares its type
- ✅ **Clear Structure**: Dictionary format makes it easy to reference specific handlers
- ✅ **Extensible**: Easy to add new handler types without breaking existing configs

**Configuration Format:**
All handlers are now defined using a dictionary with arbitrary names:
```yaml
handlers:
  console_text:              # Arbitrary name chosen by user
    type: console
    enabled: true
    stream: stdout
  my_file_logger:            # Another arbitrary name
    type: file
    enabled: true
    file: "app.log"
```


**Format Rules:**
- Use `text` for human-readable output (console and file handlers)
- Use `json` for structured data output (file handler with JSON format, database logging)
- The `colors` setting is ignored when format is `json`
- The file handler supports both text and JSON formats - just change the `format` setting

**Log Levels (in order of severity):**
- `trace` - Most detailed logging
- `debug` - Debug information
- `info` - General information
- `warning` - Warning messages
- `error` - Error conditions
- `critical` - Critical errors

### 2. PostgreSQL Server Configuration

Defines PostgreSQL server connection settings.

```yaml
pgserver:
  version: 16                   # PostgreSQL version (required unless image is specified)
  name: infra-pg               # Server name/identifier
  port: 7432                   # PostgreSQL port
  user: postgres               # Database user
  pass: ''                     # Database password (use environment variable for security)
  image: pgvector/pgvector:pg16  # Optional: custom Docker image (defaults to postgres:VERSION)
  postgres_conf:               # Optional: PostgreSQL -c parameters (see Recommended Settings below)
    max_connections: 500
    shared_preload_libraries:
      - pg_stat_statements
  replica:                     # Optional: replication mode configuration
    enabled: true              # Enable replication targets (pg.server.up.repl, pg.standby)
    port: 7433                 # Standby server port (required when enabled: true)
```

#### Version and Image Configuration

Either `version` or `image` must be specified:

| Configuration | Use Case |
|---------------|----------|
| `version` only | Standard PostgreSQL (uses `postgres:VERSION` image) |
| `image` only | Custom image with extensions (version inferred from image) |
| Both | Custom image with explicit version for documentation |

**Examples:**

```yaml
# Standard PostgreSQL 16
pgserver:
  version: 16
  name: my-pg
  port: 5432

# pgvector for vector similarity search
pgserver:
  name: learn-pg
  port: 5432
  image: pgvector/pgvector:pg16

# TimescaleDB for time-series data
pgserver:
  name: timeseries-pg
  port: 5432
  image: timescale/timescaledb:latest-pg16
```

**Important:** The custom image must be PostgreSQL-compatible (based on the official `postgres`
image). Images that extend the official postgres image (like `pgvector/pgvector`,
`timescale/timescaledb`, `postgis/postgis`) work correctly. Non-PostgreSQL databases or heavily
modified images will fail to start.

#### PostgreSQL Configuration (`postgres_conf`)

Control a curated set of PostgreSQL server parameters via the `postgres_conf` dictionary. Each
configured key is passed as a `-c key=value` argument to the postgres command at start. Unknown
keys raise an error listing the supported set.

**Supported keys:**

| Key | Value type | Postgres default | Use |
|---|---|---|---|
| `max_connections` | integer | 128 | Connection pool cap (e.g. for parallel test runs) |
| `shared_preload_libraries` | list of strings | empty | Load extensions at startup (e.g. `pg_stat_statements`, `timescaledb`) |
| `work_mem` | string with unit | `4MB` | Per-operation working memory |
| `autovacuum` | bool | `on` | Background table maintenance |

Booleans become `on`/`off`; lists are comma-joined.

**Example:**
```yaml
pgserver:
  version: 16
  name: my-pg
  port: 5432
  postgres_conf:
    max_connections: 500
    shared_preload_libraries:
      - pg_stat_statements
      - timescaledb
    work_mem: 256MB
    autovacuum: true
```

**Need a knob not in the table?** File an issue or PR — each addition is small (one entry
in `pg-config.sh`'s whitelist plus one slot in both compose YAMLs).

#### Recommended PostgreSQL Settings

When no `postgres_conf` is specified, PostgreSQL starts with its built-in defaults. Consider these
settings for production use:

| Setting | Recommended | Description |
|---------|-------------|-------------|
| `max_connections` | 500 | Maximum concurrent connections (default: 100) |
| `shared_preload_libraries` | `pg_stat_statements` | Extensions to load at startup for query statistics |
| `autovacuum` | true | Automatic table maintenance (PostgreSQL default, but worth being explicit) |

**Example with recommended settings:**
```yaml
pgserver:
  version: 16
  name: my-pg
  port: 5432
  postgres_conf:
    max_connections: 500
    shared_preload_libraries:
      - pg_stat_statements
    autovacuum: true
```

**Extensions requiring `shared_preload_libraries`:**
Some extensions must be loaded at server startup:
- `pg_stat_statements` - Query statistics
- `timescaledb` - Time-series data
- `pg_cron` - Job scheduling
- `auto_explain` - Automatic query plan logging

#### Replication Mode

When `replica.enabled` is `true`:
- Replication targets are available (`make pg.server.up.repl`, `make pg.standby`)
- `replica.port` is required and used for the standby server
- Database URLs can reference `${pgserver.replica.port}` for read replicas

When `replica` is omitted or `replica.enabled` is `false`:
- Only single-instance mode is available
- Replication targets are hidden from `make help`

### 3. Database Configurations

Defines multiple named database connections with various settings.

```yaml
dbs:
  main:
    url: "postgresql://${pgserver.user}:${pgserver.pass}@127.0.0.1:${pgserver.port}/infra_main"
    create_db: true              # Create database if it doesn't exist
    readonly: false              # Enable read-only mode
    extensions:                  # PostgreSQL extensions to create (CREATE EXTENSION)
      - vector
      - pg_trgm
    # Pool configuration (defaults defined in infra/db/pg/pg.py)
    pool_size: 5                 # Connection pool size (default: 5)
    max_overflow: 10             # Maximum overflow connections (default: 10)

  test:
    url: "postgresql://${pgserver.user}:${pgserver.pass}@127.0.0.1:${pgserver.port}/infra_test"
    readonly: false
    create_db: true
    # Custom pool settings
    pool_size: 5
    max_overflow: 10

  unittest_ro:
    url: "postgresql://${pgserver.user}:${pgserver.pass}@127.0.0.1:${pgserver.port}/infra_test"
    readonly: true               # Read-only database
    create_db: false
    # Custom pool settings for read-only
    pool_size: 3
    max_overflow: 5
```

#### PostgreSQL Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `url` | string | **required** | Database connection URL |
| `readonly` | boolean | `false` | Enable read-only mode |
| `create_db` | boolean | `false` | Create database if it doesn't exist |
| `extensions` | list | `[]` | PostgreSQL extensions to create (e.g., `vector`, `pg_trgm`) |
| `pool_size` | integer | `5` | Connection pool size |
| `max_overflow` | integer | `10` | Maximum overflow connections |
| `pool_timeout` | integer | `30` | Pool timeout in seconds |
| `pool_recycle` | integer | `3600` | Connection recycle time |
| `pool_pre_ping` | boolean | `true` | Test connections before use |
| `echo` | boolean | `false` | Echo SQL statements |

#### Database Extensions

The `extensions` field allows you to declaratively specify PostgreSQL extensions to create in each
database. Extensions are created during `PG.migrate()` using `CREATE EXTENSION IF NOT EXISTS`.

**Example:**
```yaml
dbs:
  main:
    url: "postgresql://localhost/myapp"
    create_db: true
    extensions:
      - vector      # pgvector for embeddings
      - pg_trgm     # Trigram similarity for fuzzy search
      - postgis     # Geospatial support
```

**Server vs Database extensions:**
- **Server-level** (`pgserver.postgres_conf.shared_preload_libraries`): Extensions loaded at server
  startup. Required for `timescaledb`, `pg_stat_statements`, `pg_cron`, etc.
- **Database-level** (`dbs.<name>.extensions`): Extensions created per database via `CREATE
  EXTENSION`. Most extensions only need this.

**Some extensions require both:**
```yaml
pgserver:
  version: 16
  image: timescale/timescaledb:latest-pg16
  postgres_conf:
    shared_preload_libraries:
      - timescaledb  # Must be preloaded

dbs:
  main:
    url: "postgresql://localhost/myapp"
    extensions:
      - timescaledb  # Also needs CREATE EXTENSION in each database
```

#### SQLite Database Configuration

SQLite databases are configured the same way as PostgreSQL, but with `sqlite://` URLs:

```yaml
dbs:
  # In-memory database (great for unit tests - data lost when process exits)
  test:
    url: "sqlite:///:memory:"

  # File-based database (relative path - 3 slashes)
  local:
    url: "sqlite:///./data/app.db"

  # Absolute path (4 slashes)
  production:
    url: "sqlite:////var/lib/myapp/data.db"
```

#### SQLite URL Formats

| Format | Example | Description |
|--------|---------|-------------|
| In-memory | `sqlite:///:memory:` | Temporary database, lost when process exits |
| Relative path | `sqlite:///./data/app.db` | Path relative to working directory |
| Absolute path | `sqlite:////var/lib/app.db` | Absolute filesystem path |

#### SQLite Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `url` | string | **required** | SQLite connection URL |
| `check_same_thread` | boolean | `false` | SQLite thread safety check (false allows multi-threaded access) |
| `echo` | boolean | `false` | Echo SQL statements |

**Example with options:**
```yaml
dbs:
  local:
    url: "sqlite:///./app.db"
    check_same_thread: false  # Allow multi-threaded access (default)
    echo: true                # Echo SQL for debugging
```

#### PostgreSQL vs SQLite Comparison

| Feature | PostgreSQL | SQLite |
|---------|------------|--------|
| URL prefix | `postgresql://` or `postgres://` | `sqlite://` |
| Connection pooling | Yes (pool_size, max_overflow) | No (not needed) |
| create_db option | Yes | No (file auto-created) |
| readonly option | Yes | No |
| check_same_thread | No | Yes (SQLite-specific) |
| Use case | Production, multi-user | Testing, single-user, embedded |

### 4. Test Configuration

Controls test execution and cleanup behavior.

**Note**: No timeout is configured - CursorIDE and test runners handle timeouts automatically.

```yaml
test:
  cleanup: true                 # Cleanup test data after tests
  create_test_tables: true      # Create test tables automatically
  logging:
    level: false                # Test logging level (false = disabled)
    colors: true                # Enable colored output
```

### 5. Database Logging Configuration

Controls database logging behavior including critical error handling. Critical flush parameters are
configured in a `critical_flush` section within the database handler.

```yaml
logging:
  handlers:
    database_logger:             # Arbitrary handler name chosen by user
      type: database             # Handler type
      enabled: false             # Enable database logging
      level: warning             # Override global level - only log warnings+
      format: json               # Format: text, json (json recommended for database logging)
      table: error_logs          # Database table name
      db: main                   # Database connection to use
      batch_size: 10             # Batch size for database inserts
      flush_interval: 30         # Flush interval in seconds
      
      # Critical error handling - ensures exceptions are immediately flushed
      critical_flush:
        enabled: true                # Enable critical error immediate flush
        trigger_fields: ["exception"] # Fields in 'extra' that trigger immediate flush
        timeout: 5.0                 # Max time to wait for critical flush in seconds
        fallback_to_console: true    # If DB flush fails, log to console
```

**Critical Flush Feature**: When enabled, log records containing exception information or specified
trigger fields in the `extra` dictionary will be immediately flushed to the database, bypassing the
normal batching mechanism. This ensures critical error information is preserved even during
application crashes.


## Runtime Logging Overrides

You can override logging settings during runtime by uncommenting and modifying the section in
`etc/infra.yaml`:

```yaml
# Runtime Logging Overrides (Global)
# ===================================
# These settings can be used to override the main logging configuration during runtime
# Simply uncomment and modify as needed
logging:
  # Runtime override of global settings
  level: "info"                # Runtime log level override
  location: 0                  # Runtime location depth override
  micros: false                # Runtime microseconds override

  # Runtime override of specific handler settings (using handler names)
  handlers:
    console_text:              # Handler name from configuration
      enabled: true
      colors: true
    file_logger:               # Handler name from configuration
      enabled: true
      file: "logs/runtime.json"
    database_logger:           # Handler name from configuration
      enabled: true
      level: "warning"
```

## Variable Substitution

The configuration supports variable substitution using `${variable_name}` syntax:

```yaml
dbs:
  main:
    url: "postgresql://${pgserver.user}:${pgserver.pass}@${pgserver.host}:${pgserver.port}/infra_main"
```

**Available Variables:**
- `${pgserver.user}` - Database username
- `${pgserver.pass}` - Database password
- `${pgserver.port}` - Database port (primary)
- `${pgserver.replica.port}` - Database port (standby/replica)
- `${pgserver.name}` - Database server name
- Any configuration value can be referenced

## File Inclusion with !include

The configuration supports including external YAML files using the `!include` tag. This allows you
to:
- **Modularize configuration** - Split large configs into manageable files
- **Reuse common settings** - Share configuration across multiple files
- **Organize by environment** - Separate dev/staging/prod configs
- **Build hierarchical configs** - Layer configuration for different use cases

### Basic Usage

**Key-level includes** - include content as a value:
```yaml
# main.yaml
database: !include './database.yaml'
logging: !include './logging.yaml'
app_name: myapp
```

```yaml
# database.yaml
host: localhost
port: 5432
user: postgres
```

**Document-level includes** - merge content at document root:
```yaml
# main.yaml
!include "./base.yaml"

app_name: myapp
server:
  port: 8080
```

```yaml
# base.yaml
logging:
  level: info
server:
  host: localhost
```

Result: The included content provides defaults, and the main document overrides. The final config
has `logging.level: info`, `server.host: localhost`, `server.port: 8080`, and `app_name: myapp`.

Document-level includes must be at column 0 (no indentation) and appear before other content.

### Path Resolution

**Relative Paths** (recommended):
- Resolved from the including file's directory
- Use `./` for current directory, `../` for parent

```yaml
# /etc/config/main.yaml
database: !include './db/connection.yaml'    # Resolves to /etc/config/db/connection.yaml
cache: !include '../cache/redis.yaml'        # Resolves to /etc/cache/redis.yaml
```

**Absolute Paths**:
- Use full filesystem paths
- Less portable but explicit

```yaml
database: !include '/etc/infra/database.yaml'
```

### Recursive Includes

Included files can themselves include other files:

```yaml
# main.yaml
app: !include './app.yaml'

# app.yaml
database: !include './database.yaml'
logging: !include './logging.yaml'

# database.yaml
connection: !include './connection.yaml'
```

This creates a chain: `main.yaml → app.yaml → database.yaml → connection.yaml`

### Circular Dependency Detection

The system automatically detects and prevents circular includes:

```yaml
# a.yaml
b: !include './b.yaml'

# b.yaml
a: !include './a.yaml'  # ERROR: Circular include detected
```

**Error message:**
```
yaml.YAMLError: Circular include detected: /path/to/a.yaml -> /path/to/b.yaml -> /path/to/a.yaml
```

### Include with Variable Substitution

Included content supports variable substitution:

```yaml
# main.yaml
pgserver:
  host: localhost
  port: 5432
  user: admin
  pass: secret
dbs: !include './databases.yaml'

# databases.yaml
main:
  url: "postgresql://${pgserver.user}:${pgserver.pass}@${pgserver.host}:${pgserver.port}/infra_main"
test:
  url: "postgresql://${pgserver.user}:${pgserver.pass}@${pgserver.host}:${pgserver.port}/infra_test"
```

**Note:** Variable substitution happens after all includes are resolved, so variables work across
file boundaries.

### Advanced Examples

**Environment-specific configuration:**
```yaml
# config.yaml
pgserver: !include './pgserver.yaml'
dbs: !include './env/${ENV}/databases.yaml'  # Include based on environment

# env/dev/databases.yaml
main:
  url: "postgresql://postgres:@localhost:5432/dev_db"

# env/prod/databases.yaml
main:
  url: "postgresql://app:@prod-server:5432/prod_db"
```

**Multiple includes:**
```yaml
# main.yaml
database: !include './database.yaml'
cache: !include './cache.yaml'
logging: !include './logging.yaml'
monitoring: !include './monitoring.yaml'
```

**Partial overrides:**
```yaml
# base.yaml (base configuration)
logging:
  level: info
  handlers:
    console: !include './handlers/console.yaml'
    file: !include './handlers/file.yaml'

# handlers/console.yaml
type: console
enabled: true
format: text
stream: stdout

# handlers/file.yaml
type: file
enabled: true
format: json
file: "logs/app.json"
```

### Best Practices

1. **Use relative paths** - More portable across environments
2. **Organize by purpose** - Group related configuration (database/, logging/, etc.)
3. **Keep includes shallow** - Avoid deeply nested include chains (max 2-3 levels)
4. **Document dependencies** - Add comments showing what each file includes
5. **Use descriptive filenames** - `database_connection.yaml` vs `db.yaml`

### Common Patterns

**Shared configuration:**
```yaml
# Common settings shared across environments
common: !include './common.yaml'

# Environment-specific overrides
database: !include './env/${ENV}/database.yaml'
```

**Component-based organization:**
```
etc/
  infra.yaml              # Main config with includes
  database/
    connection.yaml       # Database connection settings
    pools.yaml           # Connection pool configuration
  logging/
    handlers.yaml        # Log handler configuration
    formatters.yaml      # Log format configuration
  cache/
    redis.yaml           # Redis configuration
```

**Usage in code:**
```python
from appinfra.config import Config

# Load configuration with includes automatically resolved
config = Config("etc/infra.yaml")

# Access configuration normally
db_host = config.get("database.host")
log_level = config.get("logging.level")
```

## Environment Variable Overrides

You can override any configuration value using environment variables with the `INFRA_*` prefix:

```bash
# Override logging level
export INFRA_LOGGING_LEVEL=debug

# Override database port
export INFRA_PGSERVER_PORT=5432

# Override nested configuration
export INFRA_TEST_LOGGING_LEVEL=info
export INFRA_TEST_LOGGING_COLORS_ENABLED=true

# Override multiple values
export INFRA_LOGGING_MICROSECONDS=true
export INFRA_PGSERVER_USER=myuser
```

### Environment Variable Naming Convention

Environment variables follow the pattern: `INFRA_<SECTION>_<SUBSECTION>_<KEY>`

**Examples:**
- `INFRA_LOGGING_LEVEL=debug`
- `INFRA_PGSERVER_PORT=5432`
- `INFRA_TEST_LOGGING_LEVEL=info`

### Supported Data Types

The system automatically converts environment variable values:

| Value | Type | Example |
|-------|------|---------|
| `true/false` | boolean | `INFRA_LOGGING_MICROSECONDS=true` |
| `123` | integer | `INFRA_PGSERVER_PORT=5432` |
| `3.14` | float | `INFRA_TEST_VALUE=3.14` |
| `item1,item2` | list | `INFRA_TEST_LIST=item1,item2,item3` |
| `null/none` | null | `INFRA_TEST_VALUE=null` |
| `text` | string | `INFRA_LOGGING_LEVEL=debug` |

## Best Practices

### Security

1. **Passwords**: Never store passwords in the YAML file. Use environment variables:
   ```bash
   export INFRA_PGSERVER_PASS=mypassword
   ```

2. **Sensitive Data**: Keep sensitive configuration in environment variables rather than the YAML file.

### Development vs Production

1. **Development**: Use relaxed settings for easier debugging:
   ```yaml
   logging:
     level: debug
     location: 2
   ```

2. **Production**: Use more restrictive settings:
   ```yaml
   logging:
     level: warning
     location: false
   ```

### Database Configuration

1. **Connection Pooling**: Adjust pool settings based on your application's needs:
   - High-traffic apps: Increase `pool_size` and `max_overflow`
   - Read-heavy apps: Use separate read-only databases with appropriate pool settings

2. **Performance**: Consider these settings:
   - `pool_pre_ping: true` - Ensures connections are valid before use
   - `echo: false` - Disable SQL echoing in production
   - `pool_recycle: 3600` - Recycle connections every hour

### Testing

1. **Test Databases**: Use separate databases for testing:
   ```yaml
   dbs:
     test:
       create_db: true  # Create test database if needed
       pool_size: 5     # Smaller pool for tests
   ```

2. **Test Cleanup**: Enable automatic cleanup:
   ```yaml
   test:
     cleanup: true
     create_test_tables: true
   ```

## Examples

### Basic Setup
```yaml
# Minimal configuration for development
logging:
  level: info

pgserver:
  port: 5432
  user: postgres
  pass: ''

dbs:
  main:
    url: "postgresql://postgres:@localhost:5432/myapp"
    create_db: true

test:
  cleanup: true
```

### Production Setup
```yaml
# Production configuration
logging:
  level: warning

pgserver:
  port: 5432
  user: app_user
  pass: ''  # Set via environment variable

dbs:
  main:
    url: "postgresql://app_user:@prod-db:5432/myapp"
    pool_size: 20
    max_overflow: 30

  readonly:
    url: "postgresql://app_user:@prod-replica:5432/myapp"
    readonly: true
    pool_size: 10

test:
  cleanup: true
  timeout: 60

errors:
  enabled: true
  keep: 30d
```

## Troubleshooting

### Common Issues

1. **Database Connection Errors**:
   - Check `pgserver` configuration
   - Verify database URL format
   - Ensure PostgreSQL is running

2. **Environment Variables Not Applied**:
   - Use `INFRA_` prefix
   - Check variable naming (uppercase with underscores)
   - Restart application after setting variables

3. **Performance Issues**:
   - Adjust `pool_size` and `max_overflow`
   - Consider read-only databases for read-heavy workloads
   - Check `pool_pre_ping` setting

### Debugging Configuration

To debug configuration loading:

```python
from appinfra import Config

config = Config("etc/infra.yaml")
print("Configuration loaded:")
print(config)

# Check environment overrides
overrides = config.get_env_overrides()
print("Environment overrides:", overrides)
```

## Support

For more information about specific configuration options:

- **Database Configuration**: See `infra/db/README.md`
- **Logging Configuration**: See `infra/log/README.md`
- **Environment Overrides**: See `../docs/guides/environment-variables.md`

