# Example Plugins for infra.app Framework

This directory contains example plugin implementations demonstrating how to extend the infra.app framework with custom functionality.

## Available Example Plugins

### DatabasePlugin
Demonstrates database integration with:
- Database migration tools
- Connection management hooks
- Status checking commands

```python
from examples.plugins import DatabasePlugin

builder = AppBuilder("myapp")
builder.with_plugin(DatabasePlugin(connection_string="postgresql://..."))
app = builder.build()
```

### AuthPlugin
Shows authentication integration with:
- Login/logout commands
- Authentication middleware
- JWT or custom auth strategies

```python
from examples.plugins import AuthPlugin

builder = AppBuilder("myapp")
builder.with_plugin(AuthPlugin(auth_type="jwt"))
app = builder.build()
```

### LoggingPlugin
Demonstrates enhanced logging with:
- Custom log level management
- File-based logging setup
- Error logging hooks

```python
from examples.plugins import LoggingPlugin

builder = AppBuilder("myapp")
builder.with_plugin(LoggingPlugin(log_file="/var/log/myapp.log"))
app = builder.build()
```

### MetricsPlugin
Shows metrics and monitoring with:
- Request/response tracking
- Performance metrics collection
- Metrics endpoint exposure

```python
from examples.plugins import MetricsPlugin

builder = AppBuilder("myapp")
builder.with_plugin(MetricsPlugin(metrics_endpoint="/metrics"))
app = builder.build()
```

## Creating Your Own Plugins

To create a custom plugin, extend the `Plugin` base class:

```python
from appinfra.app.builder.plugin import Plugin
from appinfra.app.builder.tool import ToolBuilder


class MyPlugin(Plugin):
    def __init__(self):
        super().__init__("my-plugin")

    def configure(self, builder):
        """Configure the plugin by adding tools, middleware, hooks, etc."""
        builder.with_tool_builder(
            ToolBuilder("my-command")
            .with_help("My custom command")
            .with_run_function(self._run)
        )

    def _run(self, tool, **kwargs):
        tool.lg.info("Running my custom command")
        return 0
```

## Backward Compatibility

Note: These plugins were previously located in `infra.app.builder.plugin` but have been moved here to separate example code from production code. The old import path still works for backward compatibility but will show deprecation warnings.

**Old (deprecated):**
```python
from appinfra.app.builder.plugin import DatabasePlugin  # Works but deprecated
```

**New (recommended):**
```python
from examples.plugins import DatabasePlugin
```
