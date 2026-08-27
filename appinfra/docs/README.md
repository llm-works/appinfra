# appinfra User Guide

Production-grade Python infrastructure framework providing reusable building blocks for robust
applications.

For feature highlights and code examples, see the [main README](../../README.md).

## Overview

A comprehensive toolkit of battle-tested infrastructure components extracted from many years of
systems programming experience. Designed for building reliable, high-performance Python applications
with clean abstractions and production-ready patterns.

## Scope & Philosophy

This framework provides **low-level infrastructure components** for building production Python
applications. It's designed for composability and reliability, not as a batteries-included web
framework.

| | |
|---|---|
| **In Scope** | Logging infrastructure, PostgreSQL abstraction, CLI framework, lifecycle management, time utilities |
| **Out of Scope** | Web frameworks, ORMs, async-native patterns, multi-database support |
| **Best For** | Production CLI tools, background services, systems-level Python applications |
| **Not For** | REST APIs (use FastAPI/Flask), async-heavy apps, general web development |

## Architecture

```
appinfra/
├── app/          # Application framework (AppBuilder, tools, lifecycle)
├── cli/          # CLI infrastructure (output, prompts, argument parsing)
├── config/       # Configuration loading (YAML, env vars, path resolution)
├── db/           # Database layer (PostgreSQL, SQLite, connection pooling)
├── log/          # Logging system (builders, handlers, formatters)
├── net/          # Network components (TCP/HTTP servers, routing)
├── time/         # Time utilities (ticker, scheduler, delta formatting)
├── security/     # Security utilities (secret masking, validation)
├── observability/# Lightweight hooks for metrics and tracing
├── ui/           # Interactive UI (prompts, progress bars)
└── (core)        # DotDict, YAML utils, type helpers, caching
```

**Design Principles:**

- **Fluent Builders** - All major components use chainable builder APIs
- **Protocol-Based** - Interfaces defined via Python protocols for flexibility
- **Lifecycle-Aware** - Startup/shutdown hooks, graceful termination
- **Config-Driven** - YAML configuration with environment variable overrides
- **Test-Friendly** - Dependency injection, mockable interfaces, test fixtures

## Packages

### `appinfra.app` - Application Framework

Modern framework for CLI tools and applications:
- Fluent AppBuilder API with focused configurers
- Tool registry with decorator-based commands
- Nested subcommands support
- Lifecycle management (startup/shutdown hooks)
- Multi-source version tracking

### `appinfra.log` - Logging System

Advanced logging with structured output:
- Custom log levels (TRACE/TRACE2)
- Multiple handlers (console, file rotation, database)
- Topic-based log level control with glob patterns
- JSON structured logging
- Hot-reload configuration

### `appinfra.db` - Database Layer

PostgreSQL and SQLite interfaces:
- Connection pooling with auto-reconnection
- Query logging and performance monitoring
- Read-only connection support
- Test helpers and fixtures
- pgvector extension support

### `appinfra.config` - Configuration

YAML configuration with powerful features:
- Environment variable overrides (`INFRA_<SECTION>_<KEY>`)
- File includes with `!include` directive
- Path resolution via `!path` YAML tag
- Hot-reload with ConfigWatcher

### `appinfra.time` - Time Utilities

Comprehensive time-related utilities:
- Ticker: periodic/continuous task execution
- Scheduler: daily/weekly/monthly/hourly execution
- Delta: human-readable duration formatting
- ETA: progress estimation with EWMA smoothing
- DateRange: memory-efficient date iteration

### `appinfra.net` - Network Components

TCP/HTTP server infrastructure:
- Single-process and multiprocessing modes
- HTTP request handling with routing
- Graceful shutdown with signal handling

### `appinfra.security` - Security Utilities

- Secret masking with pattern detection (20+ formats)
- Input validation helpers
- Path traversal protection

### `appinfra.ui` - Interactive UI

- Smart prompts (TTY-aware with fallbacks)
- Progress bars with logging coordination
- Testable output abstractions

### Core Utilities

- `DotDict` - Attribute-style access with dot-notation paths
- `rate_limit` - Operation frequency control
- YAML utilities with type checking helpers

## Project Scaffolding

Generate new projects with the scaffold tool:

```bash
# Generate standalone project (self-contained Makefile)
appinfra scaffold myapp

# Generate framework-based project (includes modular Makefiles)
appinfra scaffold myapp --makefile-style=framework

# With database support
appinfra scaffold myapp --with-db

# With HTTP server
appinfra scaffold myapp --with-server

# With database logging handler
appinfra scaffold myapp --with-logging-db
```

**Makefile Styles:**

- **Standalone** (default): Self-contained Makefile with basic targets. No framework dependencies.
- **Framework**: Modular Makefiles with advanced features (test categorization, coverage, hooks).

## Configuration

Configuration via `etc/infra.yaml` with environment variable overrides.

### Environment Variables

**Pattern:** `INFRA_<SECTION>_<KEY>`

```bash
export INFRA_LOGGING_LEVEL=debug      # Override logging level
export INFRA_PGSERVER_PORT=5432       # Override database port
```

See [Environment Variables Guide](guides/environment-variables.md) for full documentation.

### Path Resolution with `!path` Tag

Use the `!path` YAML tag to resolve paths relative to the config file:

```yaml
# Config at /app/etc/config.yaml
logging:
  file: !path ./logs/app.log        # Resolves to /app/etc/logs/app.log
  error_file: !path ../errors.log   # Resolves to /app/errors.log
  cache: !path ~/.cache/myapp       # Expands ~ to home directory
```

- Without `!path`, paths remain as literal strings
- Works correctly with `!include` - paths resolve relative to the included file
- Expands tilde (`~`) to the user's home directory

## CLI Commands

After installation, the `appinfra` command provides:

```bash
appinfra docs              # Show documentation overview
appinfra docs list         # List all available docs and examples
appinfra docs show <topic> # Show specific documentation
appinfra docs search <text># Search documentation (supports --fuzzy)
appinfra scaffold <name>   # Generate a new project
appinfra config [file]     # Show resolved configuration
appinfra cq cf             # Check function sizes
appinfra doctor            # Run project health checks
```

## Further Reading

- [Getting Started](getting-started.md) - Installation and setup
- [API Reference](api/index.md) - Detailed API documentation
- [Contributing](guides/contributing.md) - Development setup and guidelines

## License

Apache License 2.0 - see [LICENSE](LICENSE) for details.

Maintained by [LLM Works LLC](https://llm-works.ai) and contributors.
