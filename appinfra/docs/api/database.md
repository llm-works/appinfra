---
title: Database Layer
keywords:
  - database
  - postgresql
  - postgres
  - connection pool
  - session
  - sqlalchemy
  - query
  - PG class
  - pgserver
  - image
  - docker image
  - pgvector
  - timescaledb
  - postgis
  - extensions
  - create extension
  - dbs
  - schema
  - schema isolation
  - parallel tests
  - pytest-xdist
  - multi-tenant
aliases:
  - db-api
  - postgres-api
---

# Database Layer

PostgreSQL interface with connection pooling, query monitoring, and session management.

**Installation:**

```bash
pip install appinfra[sql]
```

This installs sqlalchemy, sqlalchemy-utils, and psycopg2-binary.

## PG (PostgreSQL)

Main PostgreSQL database interface.

```python
class PG:
    def __init__(
        self,
        lg: Logger,  # Logger instance
        cfg: Any,  # Database config (dict or object with url, etc.)
        query_lg_level: Any | None = None,  # Log level for queries
        schema: str | None = None,  # Schema for isolation
    ): ...

    def session(self, autocommit: bool = False) -> ContextManager[Session]: ...
    def engine(self) -> Engine: ...
```

**Basic Usage:**

```python
from appinfra.db import PG
from appinfra.config import Config
from appinfra.log import LoggingBuilder

lg = LoggingBuilder("myapp").build()
cfg = Config("etc/config.yaml")
pg = PG(lg, cfg.dbs.production)

with pg.session() as session:
    result = session.execute(sqlalchemy.text("SELECT version()"))
    print(result.fetchone())
```

**Session Types:**

```python
# Transactional session (default: auto-commit on success, rollback on exception)
with pg.session() as session:
    session.execute(text("INSERT INTO users ..."))
    # Commits automatically

# AUTOCOMMIT session (no transaction overhead, each statement commits immediately)
with pg.session(autocommit=True) as session:
    result = session.execute(text("SELECT * FROM users"))
    # No BEGIN/COMMIT round-trips
```

## Manager

Manages multiple database connections declared under `dbs` in YAML.

```python
class Manager:
    def __init__(self, lg: Logger, cfg: Any): ...

    def setup(self) -> None: ...
    def db(self, name: str) -> Any: ...
    def list_databases(self) -> list[str]: ...
    def close_all(self) -> None: ...
```

**Multiple Databases:**

```python
from appinfra.db import Manager
from appinfra.config import Config
from appinfra.log import LoggingBuilder

lg = LoggingBuilder("myapp").build()
cfg = Config("etc/infra.yaml")

manager = Manager(lg, cfg)
manager.setup()  # creates all configured connections

main_db = manager.db("main")
readonly_db = manager.db("readonly")
```

## Configuration

Database connections are configured in `etc/infra.yaml` under the `dbs` key.

```yaml
dbs:
  main:
    url: "postgresql://postgres:secret@localhost:5432/myapp"
    pool_size: 10              # Connection pool size (default: 5)
    max_overflow: 20           # Max overflow connections (default: 10)
    create_db: true            # Create database if not exists (default: false)
    extensions:                # PostgreSQL extensions to create
      - vector
      - pg_trgm

  readonly:
    url: "postgresql://postgres:secret@localhost:5432/myapp"
    readonly: true             # Read-only mode (default: false)
```

### Database Configuration Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `url` | string | required | PostgreSQL connection URL |
| `pool_size` | int | 5 | Connection pool size |
| `max_overflow` | int | 10 | Max overflow connections |
| `pool_timeout` | int | 30 | Pool timeout in seconds |
| `pool_recycle` | int | 3600 | Connection recycle time in seconds |
| `pool_pre_ping` | bool | true | Enable connection health checks |
| `readonly` | bool | false | Read-only mode |
| `create_db` | bool | false | Create database if not exists |
| `extensions` | list | [] | PostgreSQL extensions to create |
| `schema` | string | null | PostgreSQL schema for isolation |

## Schema Isolation

Schema isolation enables parallel test execution and multi-tenant applications by routing all
queries to a dedicated PostgreSQL schema.

### Basic Usage

```python
from appinfra.db.pg import PG

# Create PG with schema isolation
pg = PG(logger, config, schema="tenant_a")
pg.create_schema()  # Create schema if it doesn't exist
pg.migrate(Base)  # Tables created in tenant_a schema

# All queries now use tenant_a schema
with pg.session() as session:
    session.execute(text("INSERT INTO users ..."))  # Goes to tenant_a.users
```

### Configuration

Schema can be set via parameter or config:

```yaml
dbs:
  tenant_a:
    url: "postgresql://localhost/myapp"
    schema: tenant_a    # All queries use this schema

  tenant_b:
    url: "postgresql://localhost/myapp"
    schema: tenant_b    # Isolated from tenant_a
```

### Parallel Testing with pytest-xdist

The `appinfra.db.pg.testing` module provides fixtures for parallel test execution:

```python
# conftest.py - Minimal setup (one line)
pytest_plugins = ["appinfra.db.pg.testing"]


# Override config fixture to use your database
@pytest.fixture(scope="session")
def pg_test_config():
    return {"url": "postgresql://localhost/test_db"}
```

Each pytest-xdist worker gets an isolated schema (`test_gw0`, `test_gw1`, etc.):

```python
def test_parallel_safe(pg_isolated, pg_session_isolated):
    # This test can run in parallel - each worker has its own schema
    pg_session_isolated.execute(text("INSERT INTO users (id) VALUES (1)"))
    pg_session_isolated.commit()
    # No conflicts with other workers
```

### Available Fixtures

| Fixture               | Scope    | Description                                       |
|-----------------------|----------|---------------------------------------------------|
| `pg_test_schema`      | session  | Schema name for current worker (e.g., `test_gw0`) |
| `pg_isolated`         | session  | PG instance with schema isolation                 |
| `pg_session_isolated` | function | Per-test session with auto commit/rollback        |
| `pg_clean_schema`     | function | Fresh schema (drop + create) for each test        |
| `pg_schema_info`      | session  | Dict with schema configuration details            |
| `pg_migrate_factory`  | session  | Factory for creating PG instances with migrations |

### Migration Fixtures

For tests that need tables, use the `pg_migrate_factory` fixture (recommended):

```python
# conftest.py - no import from testing module needed
from myapp.models import Base

pytest_plugins = ["appinfra.db.pg.testing"]


@pytest.fixture(scope="session")
def pg_with_tables(pg_migrate_factory):
    with pg_migrate_factory(Base, extensions=["vector"]) as pg:
        yield pg


# In tests
def test_with_tables(pg_with_tables):
    # Tables from Base are available in isolated schema
    with pg_with_tables.session() as session:
        session.execute(text("SELECT * FROM my_table"))
```

The `pg_migrate_factory` fixture returns a context manager factory that:
1. Creates a fresh schema
2. Runs migrations to create all tables
3. Cleans up the schema when the context exits

**Legacy approach** (causes `PytestAssertRewriteWarning`):

```python
# This pattern causes a warning because importing from the module
# while also using it as a pytest plugin triggers assertion rewrite issues
from appinfra.db.pg.testing import make_migrate_fixture

pg_with_tables = make_migrate_fixture(Base, extensions=["vector"])
```

### How It Works

1. **Schema creation**: `pg.create_schema()` runs `CREATE SCHEMA IF NOT EXISTS`
2. **Table creation**: `pg.migrate()` creates tables in the configured schema
3. **Query routing**: SQLAlchemy event listeners set `search_path` on every connection
4. **Extension visibility**: `search_path` includes `public` so extensions (pgvector, etc.) work

### ScopedPG: Dynamic Schema Selection

For applications that need to access multiple schemas from a single PG instance (e.g., multi-tenant
applications where schemas are created dynamically), use `ScopedPG`:

```python
from appinfra.db.pg import PG

# Create a schema-agnostic PG instance
pg = PG(logger, config)

# Get scoped views for different schemas
tenant_a = pg.scoped("tenant_a")
tenant_b = pg.scoped("tenant_b")

# Each scope has its own search_path (set at session level, not engine level)
with tenant_a.session() as session:
    session.execute(text("SELECT * FROM users"))  # Uses tenant_a.users

with tenant_b.session() as session:
    session.execute(text("SELECT * FROM users"))  # Uses tenant_b.users

# Create schema if it doesn't exist
tenant_a.ensure_schema()  # CREATE SCHEMA IF NOT EXISTS tenant_a
```

**Key differences from engine-level schema isolation:**

| Feature | `PG(schema="x")` | `pg.scoped("x")` |
|---------|------------------|------------------|
| Schema binding | Engine-level (all sessions) | Engine-level (dedicated pool per schema) |
| Multiple schemas | Requires multiple PG instances | Single PG manages multiple internal pools |
| Schema must exist | Before first DB operation | At session time (lazy) |
| Session API | Same context manager API | Same context manager API |

**When to use which:**
- **Engine-level (`schema=`)**: Single schema per PG instance, schema known at startup
- **ScopedPG**: Dynamic schemas, multi-tenant with schema-per-tenant, lazy schema creation

### PostgreSQL Extensions (`extensions` field)

The `extensions` field specifies PostgreSQL extensions to create automatically when `pg.migrate()`
is called. Extensions are created using `CREATE EXTENSION IF NOT EXISTS`.

```yaml
dbs:
  main:
    url: "postgresql://localhost/myapp"
    create_db: true
    extensions:
      - vector         # pgvector for embeddings
      - pg_trgm        # Trigram similarity for fuzzy search
      - postgis        # Geospatial support
```

**How it works:**
1. Extensions are created during `pg.migrate()`, before table creation
2. Uses `CREATE EXTENSION IF NOT EXISTS` (safe to run multiple times)
3. Extension names must match pattern: lowercase letters, numbers, underscores, hyphens
   (e.g., `vector`, `pg_trgm`, `pg-cron`)

**Important:** The PostgreSQL server must have the extension binaries installed. Use a custom
Docker image (via `pgserver.image`) that includes the extensions you need.

### Server-Level vs Database-Level Extensions

Some extensions require configuration at both levels:

| Level | Config Location | Purpose |
|-------|-----------------|---------|
| Server | `pgserver.postgres_conf.shared_preload_libraries` | Extensions loaded at server startup |
| Database | `dbs.<name>.extensions` | Extensions created per database |

**Extensions requiring both levels (examples):** `timescaledb`, `pg_cron`, `pg_stat_statements`,
`pgaudit`, `auto_explain`

> **`pgserver.postgres_conf` accepts only** `max_connections`,
> `shared_preload_libraries`, `work_mem`, and `autovacuum`. Unknown keys error
> at `make pg.server.up` and list the supported set.

```yaml
# Server config (pg.yaml)
pgserver:
  image: timescale/timescaledb:latest-pg18
  postgres_conf:
    shared_preload_libraries:
      - timescaledb              # Must be preloaded at server startup

# Database config (infra.yaml)
dbs:
  main:
    url: "postgresql://localhost/myapp"
    extensions:
      - timescaledb              # Also needs CREATE EXTENSION per database
```

**Extensions needing only database-level (examples):** `vector`, `pg_trgm`, `postgis`, `uuid-ossp`

## First-Touch DDL Helpers

Concurrent workers that lazily create the same database object (embedding tables, per-tenant
partitions, materialized views, cache tables, application-managed indexes) hit a first-touch
race:

1. Two workers observe the target as missing (via `SELECT` or reflection).
2. Both fire `CREATE ...`.
3. The loser raises `duplicate_table` / `duplicate_object` / `unique_violation` on
   `pg_type_typname_nsp_index`, and the outer transaction ends up in
   `InFailedSqlTransaction` — not recoverable via naive `try/except`.

`appinfra.db.pg.ensure_object` closes this race with a Postgres transaction-scoped advisory
lock keyed on a stable string:

```python
from appinfra.db.pg import ensure_object, table_exists

with pg.session() as session:
    conn = session.connection()
    ensure_object(
        session,
        key=f"ensure:public.{table_name}",
        exists_fn=lambda: table_exists(conn, table_name, schema="public"),
        create_fn=lambda: MyTable.__table__.create(conn),
    )
```

The advisory lock is database-scoped, so it serializes across every worker and node sharing
the same database — not just within a single process. It auto-releases at commit/rollback, so
there is no explicit release path to get wrong. Contention is limited to the first-touch
path; once the object exists, callers typically short-circuit before entering the block, so
steady-state cost is zero.

### Why not simpler patterns

| Pattern | Why it fails |
|---------|--------------|
| `CREATE ... IF NOT EXISTS` | Doesn't close the race in Postgres; concurrent `CREATE`s still collide on catalog inserts. |
| `Table.create(checkfirst=True)` | Reflection is racy, and SAVEPOINT rollback does not reliably clear the aborted state under every session config. |
| `try/except IntegrityError/ProgrammingError` | Must savepoint-scope AND pgcode-filter (`23505`, `42P07`, `42710`) to avoid swallowing real errors (permission denied, missing extension, invalid DDL). |

### API

```python
from appinfra.db.pg import (
    with_object_lock,
    ensure_object,
    table_exists,
    index_exists,
)

# Context manager form — for custom check/create shapes:
with with_object_lock(session, key):
    # ... arbitrary DDL, serialized database-wide on this key ...
    ...

# Folded form — the common check-and-create shape:
ensure_object(session, key, exists_fn, create_fn)

# Schema-aware existence checks (filter by n.nspname, not pg_table_is_visible):
table_exists(conn, name, schema=None)  # None -> current_schemas(true) fallback
index_exists(conn, name, schema=None)  # None -> any schema
```

`table_exists` and `index_exists` filter by `pg_namespace.nspname` explicitly rather than
relying on `pg_table_is_visible(oid)`, which resolves against `search_path` at query time and
has produced false negatives for callers that manage `search_path` per statement rather than
per session.

### Requirements and caveats

- **Transactional session required.** The lock is transaction-scoped; in AUTOCOMMIT each
  statement is its own transaction, so the lock releases immediately and provides no
  serialization. Do not pair with `pg.session(autocommit=True)`.
- **Thread ownership.** SQLAlchemy `Session` objects are not thread-safe; give each thread
  its own session. Advisory locks then serialize between distinct sessions the same way they
  serialize between processes.
- **Key hashing.** `pg_advisory_xact_lock(hashtext(:k))` reduces the key to an int4;
  unrelated keys can hash-collide and needlessly serialize. This is a performance wart,
  never a correctness issue.
- **Deadlocks.** Keep the block tight (check + create). Nesting locks on multiple keys in
  inconsistent order across workers can deadlock; Postgres detects and aborts one side.

### Composing with ScopedPG

The advisory lock is database-scoped, independent of `search_path`. When two `ScopedPG`
instances might create objects with the same unqualified name in different schemas, include
the schema in the key so the lock is per-schema:

```python
with scoped.session() as session:
    conn = session.connection()
    ensure_object(
        session,
        key=f"ensure:{scoped.schema}.{table_name}",
        exists_fn=lambda: table_exists(conn, table_name, schema=scoped.schema),
        create_fn=lambda: Model.__table__.create(conn),
    )
```

## PostgreSQL Server Configuration (pg.yaml)

Defines the Docker-based PostgreSQL server for local development.

```yaml
pgserver:
  version: 18                      # PostgreSQL version (required unless image is specified)
  name: llm-works-pg               # Server name/identifier (shared across llm-works packages)
  port: 25432                      # PostgreSQL port
  user: postgres                   # Database user
  pass: ''                         # Database password
  image: pgvector/pgvector:pg18   # Optional: custom Docker image
```

### Custom Docker Image (`image` field)

Use the `image` field to run PostgreSQL with extensions like pgvector, TimescaleDB, or PostGIS.

**Either `version` or `image` must be specified:**

| Configuration | Use Case | Image Used |
|---------------|----------|------------|
| `version` only | Standard PostgreSQL | `postgres:VERSION` |
| `image` only | Custom image with extensions | Your specified image |
| Both | Custom image with explicit version for documentation | Your specified image |

**Examples:**

```yaml
# Standard PostgreSQL 18
pgserver:
  version: 18
  name: my-pg
  port: 5432

# pgvector for vector similarity search
pgserver:
  name: learn-pg
  port: 5432
  image: pgvector/pgvector:pg18

# TimescaleDB for time-series data
pgserver:
  name: timeseries-pg
  port: 5432
  image: timescale/timescaledb:latest-pg18

# PostGIS for geospatial data
pgserver:
  name: geo-pg
  port: 5432
  image: postgis/postgis:18-3.6
```

**Important:** The custom image must be PostgreSQL-compatible (based on the official `postgres`
image). Images that extend the official postgres image work correctly:

- `pgvector/pgvector:pg18` - Vector similarity search
- `timescale/timescaledb:latest-pg18` - Time-series database
- `postgis/postgis:18-3.6` - Geospatial database

Non-PostgreSQL databases or heavily modified images will fail to start because the framework passes
PostgreSQL-specific CLI arguments to the container.

## AUTOCOMMIT Sessions

Use `autocommit=True` for read-heavy workloads to avoid transaction overhead:

```python
from appinfra.db import PG
from appinfra.config import Config
from appinfra.log import LoggingBuilder

lg = LoggingBuilder("myapp").build()
cfg = Config("etc/config.yaml")
pg = PG(lg, cfg.dbs.production)

# AUTOCOMMIT session - no BEGIN/COMMIT round-trips
with pg.session(autocommit=True) as session:
    result = session.execute(sqlalchemy.text("SELECT * FROM users"))
    users = result.fetchall()
```

Note: AUTOCOMMIT mode commits each statement immediately. Writes are allowed but
not wrapped in a transaction, so there's no rollback capability.

## Transactions

The `session()` context manager handles transactions automatically:

```python
from appinfra.db import PG
from appinfra.config import Config
from appinfra.log import LoggingBuilder
from sqlalchemy import text

lg = LoggingBuilder("myapp").build()
cfg = Config("etc/config.yaml")
pg = PG(lg, cfg.dbs.production)

with pg.session() as session:
    session.execute(text("INSERT INTO logs (message) VALUES ('Started')"))
    session.execute(text("UPDATE status SET value = 'active'"))
    # Commits automatically on success, rolls back on exception
```

## SQLAlchemy ORM

```python
from appinfra.db import PG
from appinfra.config import Config
from appinfra.log import LoggingBuilder
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import Column, Integer, String


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    name = Column(String)
    email = Column(String)


lg = LoggingBuilder("myapp").build()
cfg = Config("etc/infra.yaml")
pg = PG(lg, cfg.dbs.production)

with pg.session() as session:
    users = session.query(User).filter(User.name == "John").all()
```

## See Also

- [PostgreSQL Test Helper Guide](../guides/pg-test-helper.md) - Testing with databases
- [Environment Variables](../guides/environment-variables.md) - Configuration overrides
