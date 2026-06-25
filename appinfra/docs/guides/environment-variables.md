---
title: Environment Variable Overrides
keywords:
  - env vars
  - environment variables
  - config override
  - INFRA_
  - runtime config
  - secrets
  - deployment
aliases:
  - env-config
  - env-override
---

# Environment Variable Overrides for Configuration

This document describes how to use environment variables to override configuration values from
`infra.yaml`.

## Overview

The `appinfra.config.Config` class supports environment variable overrides, allowing you to modify
configuration values without changing the YAML file. Environment variables have **lower precedence
than CLI arguments** but **higher precedence than YAML config values**. See
[Configuration Precedence](configuration-precedence.md) for the full precedence hierarchy.

Environment variable overrides are particularly useful for:

- Development environments
- Testing scenarios
- Production deployments with different settings
- CI/CD pipelines

## Environment Variable Naming Convention

Environment variables follow the pattern: `INFRA_<SECTION>_<SUBSECTION>_<KEY>`

### Examples

```bash
# Override logging level
INFRA_LOGGING_LEVEL=debug

# Override database port
INFRA_PGSERVER_PORT=5432

# Override nested configuration
INFRA_TEST_LOGGING_LEVEL=info
INFRA_TEST_LOGGING_COLORS_ENABLED=true

# Override multiple values
INFRA_LOGGING_MICROS=true
INFRA_PGSERVER_USER=myuser
INFRA_TEST_TIMEOUT=120
```

## Supported Data Types

The system automatically converts environment variable values to appropriate types:

### String Values
```bash
INFRA_LOGGING_LEVEL=debug
INFRA_PGSERVER_USER=myuser
```

### Boolean Values
```bash
INFRA_LOGGING_MICROS=true
INFRA_TEST_CLEANUP=false
```

### Numeric Values
```bash
INFRA_PGSERVER_PORT=5432
INFRA_TEST_TIMEOUT=120
```

### Float Values
```bash
INFRA_TEST_VALUE=3.14
```

### List Values (comma-separated)
```bash
INFRA_TEST_LIST=item1,item2,item3
```

### Null Values
```bash
INFRA_TEST_VALUE=null
INFRA_TEST_VALUE=none
INFRA_TEST_VALUE=  # empty string
```

## Usage Examples

### Basic Usage

```python
from appinfra.cfg import Config

# Load config with environment overrides (default behavior)
config = Config('etc/infra.yaml')

# Access overridden values
print(config.logging.level)  # Will be 'debug' if INFRA_LOGGING_LEVEL=debug
print(config.pgserver.port)  # Will be 5432 if INFRA_PGSERVER_PORT=5432
```

### Disable Environment Overrides

```python
from appinfra.cfg import Config

# Load config without environment overrides
config = Config('etc/infra.yaml', enable_env_overrides=False)
```

### Custom Environment Prefix

```python
from appinfra.cfg import Config

# Use custom prefix for environment variables
config = Config('etc/infra.yaml', env_prefix='MYAPP_')

# Now looks for MYAPP_* environment variables
# MYAPP_LOGGING_LEVEL=debug
```

### Check Applied Overrides

```python
from appinfra.cfg import Config

config = Config('etc/infra.yaml')
overrides = config.get_env_overrides()

print("Applied overrides:")
for key, value in overrides.items():
    print(f"  {key}: {value}")
```

## Command Line Usage

### Development Environment
```bash
# Set development-specific overrides
export INFRA_LOGGING_LEVEL=debug
export INFRA_LOGGING_MICROS=true
export INFRA_PGSERVER_PORT=5432
export INFRA_PGSERVER_USER=devuser

# Run application
python my_app.py
```

### Testing Environment
```bash
# Enable logging for tests
export INFRA_TEST_LOGGING_LEVEL=info
export INFRA_TEST_LOGGING_COLORS_ENABLED=false

# Run tests
make test
```

### Production Environment
```bash
# Production overrides
export INFRA_LOGGING_LEVEL=warning
export INFRA_PGSERVER_PORT=5432
export INFRA_PGSERVER_USER=produser
export INFRA_PGSERVER_PASS=securepassword

# Run application
python my_app.py
```

## Integration with Logging System

The environment variable overrides work seamlessly with the logging system:

```bash
# Disable logging completely
export INFRA_TEST_LOGGING_LEVEL=false

# Enable logging with specific level
export INFRA_TEST_LOGGING_LEVEL=debug

# Disable colors
export INFRA_TEST_LOGGING_COLORS_ENABLED=false
```

```python
from appinfra.test_helpers import create_test_logger

# Logger will use environment variable overrides
logger = create_test_logger('my_test')
logger.info('This will respect INFRA_TEST_LOGGING_LEVEL')
```

## Configuration File Structure

The environment variable names must match the YAML structure:

```yaml
# etc/infra.yaml
logging:
  level: info
  micros: false
  colors: true

pgserver:
  port: 7432
  user: postgres

test:
  timeout: 30
  logging:
    level: false
    colors: false
```

Corresponding environment variables:
```bash
INFRA_LOGGING_LEVEL=debug
INFRA_LOGGING_MICROS=true
INFRA_LOGGING_COLORS_ENABLED=false

INFRA_PGSERVER_PORT=5432
INFRA_PGSERVER_USER=myuser

INFRA_TEST_TIMEOUT=60
INFRA_TEST_LOGGING_LEVEL=info
INFRA_TEST_LOGGING_COLORS_ENABLED=true
```

## Important Notes

### Naming Convention Limitations

Due to the underscore-based naming convention, some YAML keys with underscores may not map directly:

```yaml
# YAML
test:
  my_key: value
```

```bash
# Environment variable creates: test.my.key
INFRA_TEST_MY_KEY=value
```

To access: `config.test.my.key` (not `config.test.my_key`)

### Hyphenated Keys

Environment variables with underscores automatically match hyphenated YAML keys:

```yaml
# YAML
services:
  web-server:
    port: 3000
  cache-config:
    ttl: 300
```

```bash
# Underscores in env vars match hyphens in YAML
INFRA_SERVICES_WEB_SERVER_PORT=8080
INFRA_SERVICES_CACHE_CONFIG_TTL=600
```

**Matching priority** (when ambiguous keys exist):
1. Exact match with underscores (e.g., `web_server`)
2. Exact match with hyphens (e.g., `web-server`)
3. Normalized match (e.g., `web-server` or `web_server`)

### List Type Preservation

When overriding a field declared as a list in YAML, single-value overrides are automatically
wrapped into a one-element list:

```yaml
# YAML
cluster:
  endpoints: ['http://localhost']
```

```bash
# Single value wraps to list
INFRA_CLUSTER_ENDPOINTS=http://prod
# Result: endpoints: ['http://prod']

# Comma-separated still works
INFRA_CLUSTER_ENDPOINTS=http://a,http://b
# Result: endpoints: ['http://a', 'http://b']

# Null/empty clears the field
INFRA_CLUSTER_ENDPOINTS=null
# Result: endpoints: null
```

### Undeclared Path Errors

Environment overrides can only target paths that exist in the YAML file. Attempting to override
an undeclared path raises `UndeclaredConfigPathError`:

```yaml
# YAML
logging:
  level: info
# No 'database' section declared
```

```bash
# This raises UndeclaredConfigPathError
INFRA_DATABASE_HOST=localhost

# Fix: declare the field in YAML first
# database:
#   host: ''
```

To add a new overridable field, declare it in YAML with a default value (`''` for scalar,
`[]` for list, `null` for optional).

**Cannot traverse into non-dict values:** Nested overrides on scalar, list, or null fields also
raise `UndeclaredConfigPathError`:

```yaml
# YAML
services:
  web-server: "http://localhost"  # scalar, not a dict
```

```bash
# This raises UndeclaredConfigPathError (cannot nest under scalar)
INFRA_SERVICES_WEB_SERVER_PORT=8080

# This works (direct replacement)
INFRA_SERVICES_WEB_SERVER=https://prod.example.com
```

### Variable Substitution

Environment variable overrides are applied before variable substitution (`${variable_name}`), so
overridden values can be used in variable references:

```yaml
# YAML
pgserver:
  port: 7432
dbs:
  main:
    url: "postgresql://user:pass@localhost:${pgserver.port}/infra_main"
```

```bash
# Override port
export INFRA_PGSERVER_PORT=5432
```

The URL will use the overridden port: `postgresql://user:pass@localhost:5432/infra_main`

### Case Sensitivity

Environment variable paths are case-insensitive:

```bash
# All of these work
INFRA_LOGGING_LEVEL=debug
INFRA_Logging_Level=debug
INFRA_LOGGING_level=debug
```

## Framework Environment Variables

These environment variables control framework behavior (not config value overrides):

| Variable | Default | Description |
|----------|---------|-------------|
| `INFRA_DEFAULT_CONFIG_FILE` | `infra.yaml` | Default config filename used by `with_config_file()` and `get_config_file_path()` |
| `INFRA_NO_CONFIRM` | unset | When set to `1`, bypasses the `areyousure` confirmation prompt used by destructive Make targets (e.g., `pg.server.down`, `pg.server.clean`, `cicd.erase`, `uninstall`). Intended for CI and other non-interactive contexts. |

**Note:** Because this env var starts with `INFRA_`, it can interfere with config keys named
`default`. If your config has a `default` key, the env var will be interpreted as
`config.default.config.file`.
Use a different key name in your config to avoid this collision.

### Example: Custom Config Filename

```bash
# Use app.yaml instead of infra.yaml as default
export INFRA_DEFAULT_CONFIG_FILE=app.yaml
```

```python
from appinfra.app.builder import AppBuilder

# Now loads etc/app.yaml instead of etc/infra.yaml
app = AppBuilder("myapp").with_config_file().build()
```

## Best Practices

1. **Use descriptive names**: Choose environment variable names that clearly indicate what they override
2. **Document overrides**: Keep a list of commonly used environment variables
3. **Use in CI/CD**: Leverage environment variables for different deployment environments
4. **Test overrides**: Verify that environment variable overrides work as expected
5. **Fallback gracefully**: Ensure your application works with default configuration when overrides are not set

## Troubleshooting

### Check Applied Overrides
```python
config = Config('etc/infra.yaml')
print("Environment overrides:", config.get_env_overrides())
```

### Verify Environment Variables
```bash
# List all INFRA_* environment variables
env | grep INFRA_
```

### Debug Configuration Loading
```python
config = Config('etc/infra.yaml')
print("Final configuration:", config.dict())
```

## Examples

See `examples/environment_variable_overrides_example.py` for a comprehensive demonstration of the
environment variable override functionality.

## See Also

- [Configuration Precedence](configuration-precedence.md) - Full precedence hierarchy (CLI > Env > YAML)
- [AppBuilder API](../api/app-builder.md) - Standard CLI arguments
- [Configuration API](../api/config.md) - Config class reference