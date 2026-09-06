# Configuration

Configuration management with YAML files and environment variable overrides.

## Examples

### env_overrides_example.py
Environment variable overrides for configuration values.

**What you'll learn:**
- Loading configuration from YAML
- Overriding config with environment variables
- Environment variable naming convention
- Type conversion (strings, bools, ints, floats, lists)

**Run:**
```bash
# Default configuration
~/.venv/bin/python examples/04_configuration/env_overrides_example.py

# With environment overrides
export INFRA_LOGGING_LEVEL=debug
export INFRA_PGSERVER_PORT=5432
~/.venv/bin/python examples/04_configuration/env_overrides_example.py
```

**Key concepts:**
- `Config` class from `infra.cfg`
- Environment variable pattern: `INFRA_<SECTION>_<KEY>`
- Automatic type conversion
- Precedence: env vars override YAML values

---

### tool_config_access.py
Accessing YAML configuration from within Tool subclasses.

**What you'll learn:**
- Accessing App config via `self.app.config`
- Using dot notation for config access
- Using dict-style access with fallbacks
- The distinction between Tool config and App config

**Run:**
```bash
~/.venv/bin/python examples/04_configuration/tool_config_access.py serve
~/.venv/bin/python examples/04_configuration/tool_config_access.py status
```

**Key concepts:**
- `self.config` is the ToolConfig (name, aliases, help)
- `self.app.config` is the YAML config loaded by the App
- `self.app` traverses the parent chain to find the root App instance
- Works regardless of intermediate parents (e.g., ToolGroups)

**Example usage:**
```python
class ServeTool(Tool):
    def configure(self) -> None:
        # Access YAML config via self.app.config
        server_cfg = self.app.config.get("server", {})
        self.host = server_cfg.get("host", "127.0.0.1")
        self.port = server_cfg.get("port", 8080)

        # Or with dot notation (when key is guaranteed to exist)
        self.host = self.app.config.server.host
```

---

### yaml_include_example.py
YAML file inclusion for modular configuration.

**What you'll learn:**
- Using !include tag to split configuration across files
- Relative and absolute path resolution
- Nested/recursive includes
- Include with variable substitution
- Circular dependency detection
- Organizing configuration by purpose
- Environment-specific configuration patterns

**Run:**
```bash
~/.venv/bin/python examples/04_configuration/yaml_include_example.py
```

**Key concepts:**
- `!include` tag syntax: `database: !include './database.yaml'`
- Relative paths resolved from including file's directory
- Supports recursive includes (A → B → C)
- Automatic circular dependency detection
- Variable substitution works across file boundaries
- Modular configuration organization

**Example usage:**
```yaml
# main.yaml
database: !include './database.yaml'
logging: !include './logging.yaml'

# database.yaml
host: localhost
port: 5432
```

---

### library_mode_config_spec.py
Library-mode bootstrap via `ConfigSpec` for a package that ships
`<pkg>/etc/<pkg>.yaml`.

**What's demonstrated:**
- Resolve then load: `Config(ConfigSpec("example-org", "example-pkg").resolve())`
- Module and filename derived from the config name (`example-pkg` → `example_pkg`,
  `etc/example-pkg.yaml`)
- The winning precedence rule, read off the resolved file
- Pairing with `create_root_lg` for the root logger
- No CLI shell — headless entry point

**Run:**
```bash
python appinfra/examples/04_configuration/library_mode_config_spec.py
```

**See also:** [Library-Mode Bootstrap](../../docs/guides/library-mode-bootstrap.md)

---

## Configuration File Structure

The framework uses `etc/infra.yaml` for configuration:

```yaml
logging:
  level: info
  micros: false

pgserver:
  host: "127.0.0.1"
  port: 25432
  user: "postgres"

test:
  timeout: 30
  logging:
    level: error
```

## Environment Variable Overrides

### Naming Convention
`INFRA_<SECTION>_<SUBSECTION>_<KEY>`

**Examples:**
```bash
# Top-level
export INFRA_LOGGING_LEVEL=debug

# Nested
export INFRA_TEST_LOGGING_LEVEL=info

# Database
export INFRA_PGSERVER_PORT=5432
export INFRA_PGSERVER_USER=myuser
```

### Type Conversion

**Booleans:**
```bash
export INFRA_LOGGING_MICROS=true
export INFRA_TEST_CLEANUP=false
```

**Numbers:**
```bash
export INFRA_PGSERVER_PORT=5432        # int
export INFRA_TEST_TIMEOUT=120          # int
export INFRA_TEST_VALUE=3.14           # float
```

**Lists:**
```bash
export INFRA_TEST_LIST=item1,item2,item3
```

**Null values:**
```bash
export INFRA_TEST_VALUE=null
export INFRA_TEST_VALUE=none
export INFRA_TEST_VALUE=               # empty string
```

## Use Cases

### Development Environment
```bash
export INFRA_LOGGING_LEVEL=debug
export INFRA_LOGGING_MICROS=true
export INFRA_PGSERVER_PORT=5432
python my_app.py
```

### Testing Environment
```bash
export INFRA_TEST_LOGGING_LEVEL=error
export INFRA_TEST_CLEANUP=true
make test
```

### Production Environment
```bash
export INFRA_LOGGING_LEVEL=warning
export INFRA_PGSERVER_HOST=prod-db.example.com
export INFRA_PGSERVER_PORT=5432
python my_app.py
```

## Best Practices

1. **Use YAML for defaults** - Store reasonable defaults in `etc/infra.yaml`
2. **Use env vars for secrets** - Never commit secrets to YAML files
3. **Document overrides** - List common env vars in your README
4. **Validate config** - Check required values at startup
5. **Test overrides** - Ensure env vars work as expected

## Next Steps

- [Basics](../01_basics/) - See config in action with hello_world_with_cfg.py
- [Logging](../03_logging/) - Configure logging via YAML and env vars
- [Database](../05_database/) - Database configuration examples

## Related Documentation

- [Environment Variable Overrides](../../docs/guides/environment-variables.md) - Complete guide
- [Main README](../README.md) - Full examples index
