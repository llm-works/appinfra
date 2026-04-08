# Decorator API Examples

This directory contains examples demonstrating the decorator-based API for creating CLI tools in the
`infra.app` framework.

## Overview

The decorator API provides a more concise syntax for creating simple CLI tools while maintaining
full compatibility with the class-based Tool architecture. All decorated tools generate proper Tool
classes under the hood.

## When to Use Decorators vs Classes

### Use Decorators For:
- Simple tools (< 20 lines of logic)
- Tools with no complex initialization
- Tools without state management
- Quick scripts and utilities
- Most CLI commands

### Use Classes For:
- Complex initialization or setup
- State management across methods
- Multiple helper methods
- Tool inheritance
- Server tools with routes
- When you need full lifecycle control

## Examples

### 1. `simple_decorator.py`
Basic decorator usage for simple CLI tools.

```bash
# Run the examples
~/.venv/bin/python simple_decorator.py greet --name "Alice"
~/.venv/bin/python simple_decorator.py analyze --file data.csv --format csv
```

**Key Concepts:**
- `@app.tool()` decorator creates a tool
- `@app.argument()` adds command-line arguments
- Function receives `self` with access to `lg`, `config`, `args`

### 2. `hierarchical_commands.py`
Creating parent tools with subcommands.

```bash
# Database operations
~/.venv/bin/python hierarchical_commands.py db migrate --target v2.0
~/.venv/bin/python hierarchical_commands.py db status
~/.venv/bin/python hierarchical_commands.py db backup --output backup.sql

# Cache operations
~/.venv/bin/python hierarchical_commands.py cache clear --pattern "user:*"
~/.venv/bin/python hierarchical_commands.py cache stats
```

**Key Concepts:**
- `@tool.subtool()` decorator creates hierarchical commands
- Parent tool delegates to selected subtool
- Each subtool has access to parent's config

### 3. `mixed_approach.py`
Mixing decorators and classes for optimal flexibility.

```bash
# Simple decorated tools
~/.venv/bin/python mixed_approach.py analyze --file data.json --format json
~/.venv/bin/python mixed_approach.py export --output results.csv

# Complex class-based tools
~/.venv/bin/python mixed_approach.py server --port 8080 --workers 4
~/.venv/bin/python mixed_approach.py process --input in.csv --output out.csv --pipeline filter transform
```

**Key Concepts:**
- Build app with AppBuilder, then define simple tools via `@app.tool()` decorators
- Use classes for complex tools (registered via builder before `build()`)
- Both approaches work together seamlessly
- Choose based on complexity, not preference

## Decorator API Reference

### Basic Usage

```python
from appinfra.app import App

app = App(config=...)

@app.tool(name="mytool", help="Short help text")
@app.argument('--file', required=True)
@app.argument('--verbose', action='store_true')
def mytool(self):
    """
    Detailed description of the tool.

    This becomes the tool's full documentation.
    """
    # Access framework features via self
    self.lg.info(f"Processing {self.args.file}")
    db_host = self.config.database.host

    # Your logic here

    return 0  # Exit code

if __name__ == '__main__':
    app.main()
```

### Available in `self`

When using decorators, the `self` parameter provides:

- `self.lg`: Logger instance (info, debug, warning, error)
- `self.config`: Configuration from YAML/environment
- `self.args`: Parsed command-line arguments
- `self.parent`: Parent tool (for subtools)
- `self.name`: Tool name
- `self.trace_attr()`: Trace attribute through hierarchy

### Lifecycle Hooks

```python
@app.tool(name="server")
def server(self):
    # Use state set up in hooks
    return self.start_server()

@server.on_setup
def setup_server(self, **kwargs):
    """Called during tool setup"""
    self.routes = load_routes()
    self.middleware = []

@server.on_configure
def configure_server(self):
    """Called after setup"""
    self.port = self.args.port or self.config.server.port
```

### Hierarchical Commands

```python
@app.tool(name="parent")
def parent_tool(self):
    """Parent tool with subcommands"""
    pass

@parent_tool.subtool(name="sub1", help="First subcommand")
@app.argument('--option')
def sub1(self):
    # Access parent if needed
    parent_config = self.parent.config
    return 0

@parent_tool.subtool(name="sub2", help="Second subcommand")
def sub2(self):
    return 0

# Usage: app.py parent sub1 --option value
```

### With AppBuilder (Config Files, Logging, etc.)

When you need AppBuilder features (config files, logging config, etc.), build the app first,
then apply decorators:

```python
from appinfra.app import AppBuilder

app = (
    AppBuilder()
    .with_name("myapp")
    .with_config_file("myapp.yaml")       # deferred: resolved from --etc-dir at runtime
    .logging.with_level("info").done()
    .build()
)

@app.tool(name="tool1")
@app.argument('--file')
def tool1(self):
    backend = self.app.config.get("backend", "default")  # from YAML + env overrides
    return 0

if __name__ == "__main__":
    app.main()
```

The config file is loaded during `app.main()` → `setup()`, so `self.app.config` is fully
resolved (YAML + `INFRA_*` env var overrides) by the time any tool runs.

## Type Hints for IDE Support

For full IDE autocomplete, use the type hint:

```python
from appinfra.app.decorators import ToolContextProtocol

@app.tool()
def mytool(self: ToolContextProtocol):
    # IDE now knows about self.lg, self.config, etc.
    self.lg.info("...")  # ✓ Autocomplete works
    self.config.database.host  # ✓ Autocomplete works
```

## Migration from Classes

Converting a class-based tool to decorator:

**Before:**
```python
class AnalyzeTool(Tool):
    def _create_config(self):
        return ToolConfig(name="analyze", help_text="Analyze data")

    def add_args(self, parser):
        parser.add_argument('--file', required=True)

    def run(self, **kwargs):
        self.lg.info(f"Analyzing {self.args.file}")
        return 0

app.add_tool(AnalyzeTool())
```

**After:**
```python
@app.tool(name="analyze", help="Analyze data")
@app.argument('--file', required=True)
def analyze(self):
    self.lg.info(f"Analyzing {self.args.file}")
    return 0
```

**Result: 40-50% less code for simple tools**

## Best Practices

1. **Start with decorators** - Use decorators by default, switch to classes when needed
2. **Keep decorated tools simple** - If it gets complex, convert to a class
3. **Use lifecycle hooks sparingly** - Most tools don't need setup/configure
4. **Organize subtools logically** - Group related commands under one parent
5. **Provide good help text** - Both short (`help=`) and long (docstring)
6. **Type hint when needed** - Use `ToolContextProtocol` for better IDE support

## Troubleshooting

### `@argument` applied to wrong object
```python
# Wrong - @argument before @tool
@app.argument('--file')
@app.tool()
def tool(self): pass

# Right - @tool first, then @argument
@app.tool()
@app.argument('--file')
def tool(self): pass
```

### Accessing self attributes before setup
```python
# Wrong - config might not be available
@app.tool()
def tool(self):
    db = self.config.database  # May fail if config not loaded

# Right - check or use defaults
@app.tool()
def tool(self):
    db = getattr(self.config, 'database', None)
    if db:
        # Use config
```

### Forgetting return value
```python
# Tool returns None -> exit code 0
@app.tool()
def tool(self):
    self.lg.info("Done")
    # Implicitly returns None -> 0

# Explicitly return exit code
@app.tool()
def tool(self):
    if error:
        return 1  # Failure
    return 0  # Success
```

## Further Reading

- [Decorator API Documentation](../../docs/decorators.md)
- [Tool Development Guide](../../docs/tools.md)
- [Configuration Guide](../../docs/configuration.md)
