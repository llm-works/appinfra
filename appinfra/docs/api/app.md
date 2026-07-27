# Application Framework

Core application classes, lifecycle management, and tool framework.

## Tool Framework

### ToolConfig

Configuration dataclass for tools.

```python
from dataclasses import dataclass, field


@dataclass
class ToolConfig:
    name: str  # Required: tool name (lowercase, hyphens/underscores)
    aliases: list[str] = field(default_factory=list)  # Optional: command aliases
    help_text: str = ""  # Optional: short help shown in --help
    description: str = ""  # Optional: detailed description
```

### Tool

Base class for command-line tools.

```python
class Tool(Traceable, ToolProtocol):
    def __init__(
        self, parent: Traceable | None = None, config: ToolConfig | None = None
    ): ...
```

**Key Properties:**
- `name` - Tool name from config
- `args` - Parsed command-line arguments (argparse.Namespace)
- `lg` - Logger instance
- `group` - ToolGroup for subcommands
- `app` - Root App instance (for accessing YAML config via `self.app.config`)
- `config` - ToolConfig (name, aliases, help_text, description)

**Key Methods:**
- `add_args(parser)` - Add arguments to the parser (override this)
- `run(**kwargs) -> int` - Execute the tool (override this)
- `setup(**kwargs)` - Initialize tool (called automatically)
- `add_tool(tool)` - Add a subtool
- `add_cmd(name, run_func)` - Add a command function

**Minimal Example:**

```python
from appinfra.app.tools import Tool, ToolConfig


class MyTool(Tool):
    def __init__(self, parent=None):
        config = ToolConfig(
            name="my-tool", aliases=["mt"], help_text="Does something useful"
        )
        super().__init__(parent, config)

    def add_args(self, parser):
        parser.add_argument("--input", required=True, help="Input file")

    def run(self, **kwargs):
        self.lg.info(f"Processing {self.args.input}")
        return 0  # Exit code
```

**Alternative: Override `_create_config()`:**

```python
class MyTool(Tool):
    def _create_config(self):
        return ToolConfig(name="my-tool", help_text="Does something")

    def run(self, **kwargs):
        return 0
```

**Accessing YAML Config:**

Use `self.app.config` to access the application's YAML configuration:

```python
class ServeTool(Tool):
    def configure(self) -> None:
        # Dict-style access with fallbacks (recommended)
        server_cfg = self.app.config.get("server", {})
        self.host = server_cfg.get("host", "127.0.0.1")
        self.port = server_cfg.get("port", 8080)

        # Dot notation (when key is guaranteed to exist)
        self.host = self.app.config.server.host

    def run(self, **kwargs):
        self.lg.info(f"Server at {self.host}:{self.port}")
        return 0
```

Note: `self.config` is the ToolConfig (metadata), while `self.app.config` is the YAML config.

### ToolGroup

Manages a group of related tools/subcommands within a parent tool.

```python
class ToolGroup:
    def __init__(self, parent: Tool, cmd_var: str, default: str | None = None): ...
```

**Key Methods:**
- `add_tool(tool, run_func=None)` - Add a tool to the group
- `get_tool(name)` - Get a tool by name
- `run(**kwargs)` - Run the selected subcommand

**Example with Subtools:**

```python
from appinfra.app.tools import Tool, ToolConfig


class SubTool1(Tool):
    def __init__(self, parent=None):
        super().__init__(parent, ToolConfig(name="sub1", help_text="First subtool"))

    def run(self, **kwargs):
        self.lg.info("Running sub1")
        return 0


class SubTool2(Tool):
    def __init__(self, parent=None):
        super().__init__(parent, ToolConfig(name="sub2", help_text="Second subtool"))

    def run(self, **kwargs):
        self.lg.info("Running sub2")
        return 0


class MainTool(Tool):
    def __init__(self, parent=None):
        super().__init__(parent, ToolConfig(name="main", help_text="Main tool"))
        self.add_tool(SubTool1(self))
        self.add_tool(SubTool2(self))
```

### Shared Arguments Pattern

When multiple subtools need common arguments (e.g., `--input`, `--output`), use a base class:

```python
from appinfra.app.tools import Tool, ToolConfig


class BaseProcessTool(Tool):
    """Base class with shared processing arguments."""

    def add_args(self, parser):
        # Common args for all processing subtools
        parser.add_argument("--input", "-i", help="Input file")
        parser.add_argument("--output", "-o", help="Output file")
        super().add_args(parser)


class ValidateTool(BaseProcessTool):
    def __init__(self, parent=None):
        super().__init__(
            parent, ToolConfig(name="validate", help_text="Validate input")
        )

    def add_args(self, parser):
        super().add_args(parser)  # Inherit common args
        parser.add_argument("--strict", action="store_true", help="Strict mode")

    def run(self, **kwargs):
        self.lg.info(f"Validating {self.args.input}")
        return 0


class TransformTool(BaseProcessTool):
    def __init__(self, parent=None):
        super().__init__(
            parent, ToolConfig(name="transform", help_text="Transform data")
        )

    def add_args(self, parser):
        super().add_args(parser)  # Inherit common args
        parser.add_argument("--format", choices=["json", "csv"], default="json")

    def run(self, **kwargs):
        self.lg.info(f"Transforming {self.args.input} -> {self.args.output}")
        return 0
```

**Alternative: Mixin Pattern**

```python
class CommonArgsMixin:
    """Mixin for common arguments."""

    def add_common_args(self, parser):
        parser.add_argument("--verbose", "-v", action="store_true")
        parser.add_argument("--dry-run", action="store_true")


class MyTool(CommonArgsMixin, Tool):
    def add_args(self, parser):
        self.add_common_args(parser)  # Add mixin args
        parser.add_argument("--input", required=True)
```

### ToolRegistry

Centralized tool registration and discovery.

```python
class ToolRegistry:
    def __init__(self) -> None: ...

    def register(self, tool: Tool) -> None: ...
    def get(self, name: str) -> Tool | None: ...
    def list_tools(self) -> list[str]: ...
```

**Tool Name Requirements:**
- Must start with a lowercase letter
- Can contain lowercase letters, numbers, underscores, hyphens
- Maximum 64 characters
- Maximum 10 aliases per tool
- Maximum 100 tools per registry

## Using with AppBuilder

The recommended way to build CLI applications:

```python
from appinfra.app.builder import AppBuilder
from appinfra.app.tools import Tool, ToolConfig


class DemoTool(Tool):
    def __init__(self, parent=None):
        super().__init__(parent, ToolConfig(name="demo", aliases=["d"]))

    def run(self, **kwargs):
        self.lg.info("Running demo")
        return 0


app = (
    AppBuilder("myapp")
    .with_description("My CLI application")
    .logging.with_level("info")
    .done()
    .tools.with_tool(DemoTool())
    .done()
    .build()
)

if __name__ == "__main__":
    exit(app.main())
```

## Known Limitations

### Argument Ordering: Positionals Must Come Before Options

When a tool has both positional arguments and options, positional arguments must appear before
options on the command line:

```bash
# Correct - positionals first
./cli.py cmd config.yaml "my comment" --option value

# Incorrect - will fail with "unrecognized arguments"
./cli.py cmd config.yaml --option value "my comment"
```

**Background:** This is a limitation of Python's `argparse` module. The `parse_args()` method stops
consuming positional arguments after encountering options. While `argparse` provides
`parse_intermixed_args()` to handle intermixed arguments, that method
[does not support
subparsers](https://docs.python.org/3/library/argparse.html#argparse.ArgumentParser.parse_intermixed_args),
which appinfra uses for tool hierarchies.

**Workaround:** Place positional arguments before options in CLI invocations.

## See Also

- [AppBuilder](app-builder.md) - Fluent builder API
- [Logging System](logging.md) - Logger configuration
- [Examples](../examples/) - Working code examples
