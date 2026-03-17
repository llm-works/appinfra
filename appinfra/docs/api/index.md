# API Reference

Complete API documentation auto-generated from docstrings.

## Overview

The Infra framework is organized into several major modules, each providing specific functionality:

| Module | Description |
|--------|-------------|
| [Application Framework](app.md) | Core application classes, lifecycle management, and tool framework |
| [AppBuilder](app-builder.md) | Fluent API for constructing CLI applications with builders |
| [CLI Framework](cli.md) | Output abstractions and built-in CLI tools |
| [Configuration](config.md) | Config loading, environment overrides, hot-reload watching |
| [Logging System](logging.md) | Advanced logging with structured output, builders, and handlers |
| [Security](security.md) | Secret masking for logs and console output |
| [UI Components](ui.md) | Rich terminal output, progress bars, spinners, and prompts |
| [Database Layer](database.md) | PostgreSQL interface with connection pooling and query monitoring |
| [Network](net.md) | TCP/HTTP server with background ticker support |
| [Time & Scheduling](time.md) | Periodic execution, scheduling, and time utilities |
| [Version Tracking](version.md) | Git commit tracking for installed packages |
| [Observability](observability.md) | Callback-based hooks for monitoring and instrumentation |
| [Service](service.md) | Service execution with dependency ordering and state management |
| [Subprocess](subprocess.md) | Context manager for subprocess lifecycle management |
| [Utilities](utilities.md) | Core utilities (DotDict, rate limiting, EWMA, etc.) |
| [Exceptions](exceptions.md) | Exception hierarchy for error handling |

## Design Patterns

The framework uses several well-established design patterns:

- **Builder Pattern** - Fluent APIs for LoggingBuilder, AppBuilder
- **Factory Pattern** - LoggerFactory, SessionFactory for object creation
- **Registry Pattern** - ToolRegistry for managing tools and plugins
- **Protocol/Interface** - Type-safe abstractions (ToolProtocol, DictInterface)
- **Plugin Architecture** - Extensible plugin system with dependencies

## Module Organization

```
appinfra/
├── app/              # Application framework
│   ├── core/        # Core application classes
│   ├── tools/       # Tool framework and registry
│   ├── builder/     # Fluent builder API
│   ├── cli/         # Command-line interface
│   ├── server/      # HTTP server (experimental)
│   └── decorators/  # Decorator-based API
├── cli/              # CLI output abstractions and built-in tools
├── config/           # Configuration loading, watching, validation
├── db/               # Database layer
│   └── pg/          # PostgreSQL implementation
├── log/              # Logging system
│   └── builder/     # Logging builders
├── net/              # TCP/HTTP server components
├── observability/    # Monitoring hooks
├── security/         # Secret masking
├── service/          # Service execution and orchestration
├── subprocess/       # Subprocess lifecycle management
├── time/             # Time and scheduling
├── ui/               # Terminal UI components
└── version/          # Version and commit tracking
```

## Quick Navigation

### Most Commonly Used Classes

**Application Framework:**
- [`App`](app.md#appinfra.app.core.App) - Main application orchestrator
- [`AppBuilder`](app-builder.md#appinfra.app.builder.AppBuilder) - Fluent builder for apps
- [`Tool`](app.md#appinfra.app.tools.Tool) - Base class for commands

**Logging:**
- [`LoggingBuilder`](logging.md#appinfra.log.builder.LoggingBuilder) - Main logging builder
- [`Logger`](logging.md#appinfra.log.Logger) - Logger class with custom formatting
- [`LoggerFactory`](logging.md#appinfra.log.LoggerFactory) - Factory for creating loggers

**UI:**
- [`ProgressLogger`](ui.md#progresslogger) - Spinner/progress bar with logging coordination
- [`console`](ui.md#console) - Rich console for styled output

**Database:**
- [`PG`](database.md#appinfra.db.pg.PG) - PostgreSQL database interface
- [`Manager`](database.md#appinfra.db.Manager) - Multi-database manager

**Time:**
- [`Ticker`](time.md#appinfra.time.Ticker) - Periodic task executor
- [`Sched`](time.md#appinfra.time.Sched) - Time-based scheduler

**Configuration:**
- [`Config`](config.md#config) - Configuration management
- [`ConfigWatcher`](config.md#configwatcher) - Hot-reload file watching
- [`DotDict`](utilities.md#dotdict) - Dot-notation dictionary

**Security & Observability:**
- [`SecretMasker`](security.md#secretmasker) - Secret detection and masking
- [`ObservabilityHooks`](observability.md#observabilityhooks) - Event callbacks

## Naming Conventions

The framework follows consistent naming conventions:

- **Classes**: PascalCase (`AppBuilder`, `LoggingBuilder`)
- **Functions/Methods**: snake_case (`with_level`, `create_logger`)
- **Constants**: UPPER_SNAKE_CASE (`MAX_TOOL_COUNT`)
- **Private members**: Leading underscore (`_internal_method`)

## Type Hints

All public APIs use comprehensive type hints for better IDE support and type checking:

```python
def with_level(self, level: str) -> "LoggingBuilder":
    """Set logging level."""
    ...
```

## Docstring Format

Documentation uses Google-style docstrings:

```python
def get(self, path: str, default: Any = None) -> Any:
    """Get value by dot-separated path.

    Args:
        path: Dot-separated path (e.g., "database.host")
        default: Value to return if path not found

    Returns:
        Found value or default

    Raises:
        ValueError: If path is invalid
    """
```

## Version Support

- **Python**: 3.11+ (tested with 3.11, 3.12)
- **PostgreSQL**: 16 (for database features)
- **SQLAlchemy**: 2.0+

## Browse by Category

### Application Development
- [Application Framework](app.md) - Core classes and lifecycle
- [AppBuilder](app-builder.md) - Fluent builder API
- [CLI Framework](cli.md) - Output abstractions and CLI tools
- [Service](service.md) - Service execution and orchestration
- [Subprocess](subprocess.md) - Subprocess lifecycle management

### Configuration & Data
- [Configuration](config.md) - Config loading, hot-reload
- [Database Layer](database.md) - PostgreSQL interface

### Logging & Security
- [Logging System](logging.md) - Advanced logging
- [Security](security.md) - Secret masking
- [Observability](observability.md) - Monitoring hooks

### Network & UI
- [Network](net.md) - TCP/HTTP servers
- [UI Components](ui.md) - Progress bars, spinners, prompts

### Utilities & Helpers
- [Time & Scheduling](time.md) - Periodic execution
- [Version Tracking](version.md) - Git commit tracking
- [Core Utilities](utilities.md) - DotDict, rate limiting

### Error Handling
- [Exceptions](exceptions.md) - Exception hierarchy

## Next Steps

- **New to the framework?** Start with the [Getting Started Guide](../getting-started.md)
- **Looking for examples?** Check the [Guides](../index.md#guides) section
- **Need specific functionality?** Browse the modules listed above
