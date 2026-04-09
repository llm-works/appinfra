---
title: Getting Started
keywords:
  - installation
  - setup
  - quickstart
  - install
  - make setup
  - prerequisites
  - python
  - postgresql
aliases:
  - quick-start
  - install-guide
---

# Getting Started

This guide will help you get up and running with the Infra framework quickly.

## Installation

### Prerequisites

- Python 3.11 or higher
- pip (Python package manager)
- PostgreSQL 16 (optional, for database features)

### Install the Framework

```bash
# Clone the repository
git clone https://github.com/your-username/infra.git
cd infra

# Install dependencies (dev environment)
make setup

# Or install base package only
make install

# Install with optional extras
make install INFRA_DEV_INSTALL_EXTRAS=ui           # Rich terminal UI
make install INFRA_DEV_INSTALL_EXTRAS=ui,fastapi   # Multiple extras
make install INFRA_DEV_INSTALL_EXTRAS=dev          # All dev dependencies

# For development (editable mode - changes reflect without reinstall)
make install.e
make install.e INFRA_DEV_INSTALL_EXTRAS=ui,dev     # Editable with extras

# Uninstall
make uninstall
```

**Available extras:** `all`, `dev`, `sql`, `validation`, `docs`, `fastapi`, `hotreload`, `ui`

Alternatively, install directly with pip:

```bash
pip install .                  # Base package
pip install ".[sql]"           # Database support (sqlalchemy, psycopg2)
pip install ".[dev]"           # Development tools
pip install ".[ui]"            # Rich terminal UI
pip install ".[all]"           # Everything (dev + all optional features)
```

## Quick Examples

### 1. Logging

The logging system provides structured output with custom levels and multiple handlers.

**Simple console logging:**

```python
from appinfra.log import LoggingBuilder

logger = (
    LoggingBuilder("my_app")
    .with_level("info")
    .console_handler()
    .build()
)

logger.info("Application started")
logger.debug("Debug message", extra={"user_id": "123"})
```

**File logging with rotation:**

```python
from appinfra.log import LoggingBuilder

logger = (
    LoggingBuilder("my_app")
    .with_level("info")
    .console_handler()
    .file_handler("logs/app.log", max_bytes=10*1024*1024, backup_count=5)
    .build()
)
```

**JSON structured logging:**

```python
from appinfra.log.builder import JSONLoggingBuilder

logger = (
    JSONLoggingBuilder("my_app")
    .with_level("info")
    .console_handler()
    .build()
)

logger.info("User action", extra={"user_id": "123", "action": "login"})
```

See the [Logging Builder Guide](guides/logging-builder.md) for more details.

### 2. Configuration

Load configuration from YAML files with environment variable overrides.

**Load configuration:**

```python
from appinfra.cfg import Config, get_config_file_path

# Recommended: Use get_config_file_path() for automatic etc/ resolution
config = Config(get_config_file_path())  # Finds etc/infra.yaml automatically

# Access with dot notation
print(config.logging.level)
print(config.database.host)

# Get with fallback
db_port = config.get("database.port", default=5432)
```

**Environment variable overrides:**

```bash
# Override via environment variables
export INFRA_LOGGING_LEVEL=debug
export INFRA_DATABASE_PORT=5433
```

```python
config = Config(get_config_file_path())
print(config.logging.level)  # Returns "debug" from environment
```

See the [Environment Variables Guide](guides/environment-variables.md) for more details.

**Accessing config from Tools:**

When building CLI applications with the Tool framework, access the YAML config via
`self.app.config`:

```python
from appinfra.app.tools.base import Tool

class ServeTool(Tool):
    def configure(self) -> None:
        # Access YAML config via self.app.config
        server_cfg = self.app.config.get("server", {})
        self.host = server_cfg.get("host", "127.0.0.1")
        self.port = server_cfg.get("port", 8080)

        # Or with dot notation (when key exists)
        self.host = self.app.config.server.host
```

Note: `self.config` on a Tool is the ToolConfig (name, aliases, help), while `self.app.config`
is the YAML configuration. The `app` property traverses the parent chain to find the root App,
so it works regardless of intermediate parents like ToolGroups.

### 3. Application Framework

Build CLI applications with the fluent AppBuilder API.

**Basic application:**

```python
from appinfra.app.builder import AppBuilder
from appinfra.app.tools import Tool

class MyTool(Tool):
    def add_args(self):
        self.arg_prs.add_argument('--name', required=True, help='Your name')

    def run(self):
        self.lg.info(f"Hello, {self.args.name}!")
        return 0

# Build and run
app = (
    AppBuilder("myapp")
    .with_description("My awesome application")
    .with_version("1.0.0")
    .tools
        .with_tool(MyTool())
        .done()
    .logging
        .with_level("info")
        .done()
    .build()
)

if __name__ == "__main__":
    app.run()
```

**Using decorators:**

```python
from appinfra.app.builder import AppBuilder

app = AppBuilder("myapp").build()

@app.tool(name="greet", help="Greet someone")
@app.argument('--name', required=True)
def greet(self):
    self.lg.info(f"Hello, {self.args.name}!")
    return 0

if __name__ == "__main__":
    app.run()
```

See the [Application Framework API](api/app.md) for more details.

### 4. Database

Connect to PostgreSQL with connection pooling and query logging.

> **Note:** Requires `pip install appinfra[sql]`

**Basic database connection:**

```python
from appinfra.db import PG
from appinfra.cfg import get_config_file_path
import sqlalchemy

# Initialize database connection (uses automatic etc/ resolution)
pg = PG(get_config_file_path(), "production")

# Use with context manager
with pg.session() as session:
    result = session.execute(sqlalchemy.text("SELECT version()"))
    print(result.fetchone())
```

**Read-only connection:**

```python
# Open read-only session
with pg.session(readonly=True) as session:
    result = session.execute(sqlalchemy.text("SELECT * FROM users"))
    users = result.fetchall()
```

See the [PostgreSQL Test Helper Guide](guides/pg-test-helper.md) for testing with databases.

### 5. Time & Scheduling

Execute tasks periodically or on a schedule.

**Periodic execution with Ticker:**

```python
from appinfra.time import Ticker

def my_task():
    print("Task executed!")

# Run every 5 seconds
ticker = Ticker(interval=5.0, handler=my_task)
ticker.start()

# Later...
ticker.stop()
```

**Scheduled execution:**

```python
from appinfra.time import Sched, Period

def daily_task():
    print("Daily task executed!")

# Run daily at 3 AM
sched = Sched(period=Period.DAILY, hour=3, handler=daily_task)

for timestamp in sched.run():
    # Task runs at scheduled time
    pass
```

See the [Time & Scheduling API](api/time.md) for more details.

## Next Steps

Now that you've seen the basics, explore:

- **[Guides](index.md#guides)** - In-depth how-to guides for specific features
- **[API Reference](index.md#api-reference)** - Complete API documentation
- **Examples** - Check the `examples/` directory in the repository

## Running Tests

```bash
# Run all unit tests
make test.unit

# Run integration tests (requires PostgreSQL)
make test.integration

# Run with coverage
make test.coverage

# Run specific test category
make test.perf      # Performance tests
make test.security  # Security tests
make test.e2e       # End-to-end tests
```

## Development Workflow

### Project Setup

```bash
# Check your environment is properly configured
make doctor

# Create a new project with scaffold
appinfra scaffold myproject --makefile-style=framework
```

### Code Quality

```bash
# Format code
make fmt

# Run all checks (format, lint, type, tests)
make check

# Preview what checks would run without executing
INFRA_DRY_RUN=1 make check
```

### Database

```bash
# Start PostgreSQL (Docker)
make pg.server.up

# Stop PostgreSQL
make pg.server.down
```

### Shell Completion

Enable tab completion for the `appinfra` CLI:

```bash
# Bash - add to ~/.bashrc
eval "$(appinfra completion bash)"

# Zsh - add to ~/.zshrc
eval "$(appinfra completion zsh)"
```

### Version Information

```bash
# Show version with commit hash
appinfra version
# Output: appinfra 0.1.0 (abc123f)

# Extract specific fields (for scripting)
appinfra version semver    # 0.1.0
appinfra version commit    # abc123f
appinfra version full      # abc123def456789...
appinfra version modified  # true/false/unknown
appinfra version time      # 2025-12-01T10:30:00Z
appinfra version message   # commit message

# JSON output (all fields)
appinfra version --json
```

## Custom Python Environments

Make targets automatically detect Python in this order:
1. `PYTHON` environment variable (highest priority)
2. `Makefile.local` file (project-local override, gitignored)
3. `~/.venv/bin/python` (default virtualenv)

To use a different environment (e.g., conda with CUDA), create a `Makefile.local`:

```bash
echo 'PYTHON ?= /path/to/your/python' > Makefile.local
```

Note: Use `?=` (conditional assignment) so environment variables can still override when needed.

All Make commands will then use your custom Python:

```bash
make install   # Uses your custom Python
make check     # Uses your custom Python
```

Or use the `PYTHON=` prefix for one-off commands:

```bash
PYTHON=/path/to/your/python make install
```

To see your current environment configuration:

```bash
make env
```

## Running Scripts Directly

Example scripts use `#!/usr/bin/env python3` for portability. To run them directly:

**Option 1: Activate the venv first**
```bash
source ~/.venv/bin/activate
./examples/01_basics/hello_world.py
deactivate  # When done
```

**Option 2: Add venv to PATH permanently**
```bash
# Add to ~/.bashrc or ~/.zshrc
export PATH="$HOME/.venv/bin:$PATH"
```

See the [Virtual Environment Guide](guides/virtual-environment.md) for more options.

## Getting Help

- **Documentation**: Browse the guides and API reference
- **Examples**: Check the `examples/` directory
- **Tests**: Look at the test files for usage patterns
- **Issues**: Report issues on GitHub (if applicable)

## Common Patterns

### DotDict for Configuration

```python
from appinfra.dot_dict import DotDict

config = DotDict({
    "database": {
        "host": "localhost",
        "port": 5432
    }
})

# Access with dot notation
print(config.database.host)  # localhost

# Or dictionary style
print(config["database"]["port"])  # 5432
```

### Rate Limiting

```python
from appinfra.rate_limit import RateLimiter
from appinfra.log import Logger

lg = Logger("my_app")
limiter = RateLimiter(lg, per_minute=30)  # 30 calls per minute

for i in range(10):
    limiter.next()  # blocks until next slot is available
    print(f"Call {i}")
```

## Troubleshooting

### Import Errors

If you get import errors, ensure you've installed the package:

```bash
pip install .
```

### PostgreSQL Connection Issues

Make sure PostgreSQL is running:

```bash
make pg.server.up
```

Check your configuration in `etc/infra.yaml`.

### Logger Not Working

Ensure you've built the logger:

```python
logger = LoggingBuilder("app").console_handler().build()
```

Don't forget the `.build()` call!
