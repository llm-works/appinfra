---
title: Decorator API with Config Files
keywords:
  - decorator
  - config file
  - builder
  - with_config_file
  - tool decorator
  - YAML config
  - etc-dir
aliases:
  - decorator-config
  - builder-decorators
  - decorator-builder
  - decorator-yaml
---

# Decorator API with Config Files

How to use the decorator API (`@app.tool`, `@app.argument`) with YAML config files loaded from
`--etc-dir`.

## Pattern

Build the app with `AppBuilder`, then define tools via decorators on the built app:

```python
from appinfra.app.builder import AppBuilder

# 1. Build app (config file resolved from --etc-dir at runtime)
app = (
    AppBuilder()
    .with_name("myapp")
    .with_config_file("myapp.yaml")
    .build()
)

# 2. Define tools on the built app
@app.tool(name="serve", help="Start the server")
@app.argument("--port", type=int, default=8080, help="Listen port")
def serve(self):
    port = self.app.config.get("server", {}).get("port", self.args.port)
    self.lg.info(f"Starting on port {port}")
    return 0

# 3. Run
if __name__ == "__main__":
    exit(app.main())
```

`AppBuilder` handles infrastructure (config files, logging, middleware). Decorators handle tool
definitions. Each does its job.

## Why This Works

Config isn't needed when decorators run — only when tools execute:

| Phase | What happens | Config available? |
|-------|-------------|-------------------|
| **Module load** | `build()` runs, decorators register tools | No |
| **`app.main()` → `setup()`** | `--etc-dir` resolved, YAML loaded, env vars merged | Yes |
| **Tool execution** | `self.app.config` has all sources merged | Yes |

## Accessing Config

Inside decorated tools, use `self.app.config`:

```python
@app.tool(name="search", help="Search for items")
@app.argument("query", help="Search query")
def search(self):
    # Dict-style with fallback (recommended for optional keys)
    cfg = self.app.config.get("search", {})
    backend = cfg.get("backend", "DefaultBackend")

    # Dot notation (when key is guaranteed to exist)
    db_host = self.app.config.database.host

    self.lg.info(f"Searching with {backend}")
    return 0
```

Note: `self.config` is the ToolConfig (name, help text), not the YAML config. Always use
`self.app.config` for application configuration.

## Mixing Decorators and Classes

Use decorators for simple tools, classes for complex ones — both on the same app:

```python
from appinfra.app.builder import AppBuilder
from appinfra.app.tools import Tool, ToolConfig

class ServerTool(Tool):
    """Complex tool with state, lifecycle hooks, multiple methods."""
    def _create_config(self):
        return ToolConfig(name="serve", help_text="Run the server")

    def add_args(self, parser):
        parser.add_argument("--port", type=int, default=8080)

    def configure(self):
        self.port = self.args.port or self.app.config.get("server", {}).get("port", 8080)

    def run(self, **kwargs):
        self.lg.info(f"Server on port {self.port}")
        return 0

# Class-based tools go through the builder
app = (
    AppBuilder()
    .with_name("hybrid")
    .with_config_file("hybrid.yaml")
    .tools.with_tool(ServerTool()).done()
    .build()
)

# Simple tools use decorators on the built app
@app.tool(name="status", help="Show status")
def status(self):
    self.lg.info("All systems operational")
    return 0
```

## Config Precedence

All sources merge with standard precedence (highest wins first):

1. **CLI arguments** — `--port 3000`
2. **Environment variables** — `INFRA_SERVER_PORT=3000`
3. **YAML config file** — `server.port: 9090` in `myapp.yaml`
4. **Built-in defaults** — hardcoded in code

See [Configuration Precedence](configuration-precedence.md) for details.

## See Also

- [AppBuilder API](../api/app-builder.md) — Full builder method reference
- [Configuration Precedence](configuration-precedence.md) — Override rules
- [Environment Variables](environment-variables.md) — `INFRA_*` env var format
- [Decorator Examples](../../examples/08_decorators/) — Runnable code examples
