# AppBuilder - Fluent API

Fluent builder for constructing CLI applications with tools, logging, and lifecycle management.

## AppBuilder

```python
class AppBuilder:
    def __init__(self, name: str | None = None): ...
```

**Chain Methods:**
- `with_name(name)` - Set application name
- `with_description(desc)` - Set description
- `with_version(version)` - Set version string
- `config` - Config-source block: `with_spec`, `with_overrides`, `with_value`, `with_hot_reload`; see [Config](config.md#appbuilderconfig)
- `with_main_cls(cls)` - Use custom App subclass
- `with_main_tool(tool)` - Set main tool (runs when no subcommand specified)
- `with_standard_args(**kwargs)` - Enable/disable standard CLI args
- `with_standard_arg(name, **kwargs)` - Override argparse kwargs of a standard arg
- `without_standard_args()` - Disable all standard args
- `build()` - Build and return the App instance

**Sub-builders (accessed via properties):**
- `.config` - ConfigConfigurer for the config source: spec, overrides, hot reload
- `.tools` - ToolConfigurer for adding tools
- `.logging` - LoggingConfigurer for log settings
- `.server` - ServerConfigurer for HTTP server
- `.advanced` - AdvancedConfigurer for hooks, middleware, custom args

## ToolConfigurer

Accessed via `AppBuilder().tools`:

```python
app = (
    AppBuilder("myapp")
    .tools.with_tool(MyTool())  # Add a Tool instance
    .with_plugin(MyPlugin())  # Add a Plugin
    .done()  # Return to AppBuilder
    .build()
)
```

## LoggingConfigurer

Accessed via `AppBuilder().logging`:

```python
app = (
    AppBuilder("myapp")
    .logging.with_level("info")  # Set log level
    .with_location(1)  # Show file/line (0=none, 1=file:line, 2=full path)
    .with_micros(True)  # Microsecond timestamps
    .with_colors(True)  # Enable colored output
    .with_format("%(msg)s")  # Custom format string
    .done()
    .build()
)
```

## ServerConfigurer

Accessed via `AppBuilder().server`:

```python
app = AppBuilder("myapp").server.with_port(8080).with_host("0.0.0.0").done().build()
```

## AdvancedConfigurer

Accessed via `AppBuilder().advanced`:

```python
def on_startup(ctx):
    ctx.app.lg.info("Starting...")


app = (
    AppBuilder("myapp")
    .advanced.with_hook("startup", on_startup)
    .with_argument("-v", "--verbose", action="store_true")
    .done()
    .build()
)
```

## Complete Example

```python
from appinfra.app.builder import AppBuilder
from appinfra.app.tools import Tool, ToolConfig


class GreetTool(Tool):
    def __init__(self, parent=None):
        super().__init__(
            parent, ToolConfig(name="greet", aliases=["g"], help_text="Greet someone")
        )

    def add_args(self, parser):
        parser.add_argument("--name", required=True, help="Name to greet")

    def run(self, **kwargs):
        self.lg.info(f"Hello, {self.args.name}!")
        return 0


app = (
    AppBuilder("myapp")
    .with_description("My CLI application")
    .with_version("1.0.0")
    .logging.with_level("info")
    .with_location(1)
    .done()
    .tools.with_tool(GreetTool())
    .done()
    .build()
)

if __name__ == "__main__":
    exit(app.main())
```

## Config File Loading

Declare the config source with the `config` block. The App resolves it at setup under the
[config protocol](../guides/config-protocol.md): `--config`, `--etc-dir`, a project-local
`etc/`, XDG overlays, then the packaged base.

```python
# Base: etc/inference.yaml beside the `inference` module, or beside the calling script
app = AppBuilder("inference").config.with_spec("myorg", "inference").done().build()

# Base that deviates from the etc/<name>.yaml layout
app = (
    AppBuilder("myapp")
    .config.with_spec("myorg", "myapp", filename="infra.yaml")
    .done()
    .build()
)
```

Programmatic config via builder methods takes precedence over the loaded file. A resolved file
that does not exist raises `FileNotFoundError` at setup.

With `with_standard_args(etc_dir=True)`, the `--etc-dir` CLI argument redirects the load:
```bash
./cli.py --etc-dir /custom/path serve
# → loads /custom/path/inference.yaml
```

Without a spec, no file is loaded; config comes from `.config.with_overrides()` and CLI args:
```python
app = AppBuilder("myapp").config.with_overrides({"logging": {"level": "info"}}).build()
```

See [AppBuilder.config](config.md#appbuilderconfig) for the full block.

## Standard Arguments

Standard CLI arguments are **disabled by default** (except `-h/--help`). Opt-in explicitly:

```python
# Enable all standard args
AppBuilder("myapp").with_standard_args().build()

# Enable specific args
AppBuilder("myapp").with_standard_args(etc_dir=True, log_level=True, quiet=True).build()

# Enable all logging args at once
AppBuilder("myapp").with_standard_args(log=True).build()

# Disable all (including help)
AppBuilder("myapp").without_standard_args().build()
```

**Available standard args:**

| Arg Name | CLI Flag | Description |
|----------|----------|-------------|
| `help` | `-h, --help` | Show help message (default: True) |
| `config_file` | `-c, --config` | Config file path or name |
| `etc_dir` | `--etc-dir` | Configuration directory path |
| `log_level` | `-l, --log-level` | Log level (trace2, trace, debug, info, warning, error) |
| `log_json` | `--log-json` | Output logs in JSON format |
| `log_location` | `--log-location` | Show file location in logs (0, 1, 2) |
| `log_micros` | `--log-micros` | Use microsecond timestamps |
| `log_topic` | `--log-topic` | Log topic filter |
| `log_colors` | `--no-log-colors` | Disable colored log output |
| `quiet` | `-q, --quiet` | Suppress output |

**Aliases:**
- `log=True` enables all 7 log-related args (`log_level`, `log_location`, `log_micros`, `log_topic`,
  `log_colors`, `log_json`, `quiet`)

**Overriding framework defaults:**

Use `with_standard_arg(name, **argparse_kwargs)` to override any argparse parameter
(`default`, `help`, `metavar`, `type`, `choices`, `required`, `nargs`, `action`) of a standard
arg without subclassing `App`. Overrides merge on top of framework defaults — only the passed
keys are changed.

```python
# Quieter default log level for a background service
AppBuilder("myapp").with_standard_args(log_level=True).with_standard_arg(
    "log_level", default="warning"
).build()
```

> The framework populates `app.etc_dir` when `etc_dir` is opted in via
> `with_standard_args(etc_dir=True)` — read it from inside `Tool.configure()`.
> With a spec it is the resolved file's directory; overriding the flag's default
> to `"./etc"` would bypass that resolution (the path is then validated strictly
> and errors if `./etc` is missing).
> See [config docs](config.md#reading-appetc_dir) for the full resolution table.

Restrictions:
- `name` must be a valid standard arg; the `log` alias is rejected (target a specific log arg).
- `help` is rejected — toggle it via `with_standard_args(help=...)`; its kwargs flow through
  argparse's `add_help`, not the standard-arg kwargs path.
- `dest` cannot be overridden — the framework reads parsed args by a fixed attribute name set
  internally, which may differ from `name` (e.g. `log_topic` is read as `args.log_topics`).
- The override is silently ignored if the arg is not opted in via `with_standard_args(<name>=True)`.

> Overriding shape-changing kwargs (`action`, `nargs`, `required`) is allowed but the consumer
> takes on the responsibility of keeping framework assumptions intact. For example, flipping
> `--no-log-colors` from `store_false` to `store_true` inverts the flag's user-visible meaning;
> setting `required=True` on `--etc-dir` makes argparse reject runs that rely on the spec's own
> resolution. Prefer overriding `default`, `help`, `metavar`, `type`, and
> `choices` unless the shape-change is deliberate.

**Precedence:** CLI args override environment variables, which override YAML config values.
See [Configuration Precedence](../guides/configuration-precedence.md) for the full precedence rules.

## Config File CLI Argument

The `-c/--config` argument selects the config file at runtime for an app with a spec:

```bash
# Direct path (absolute, or ./, ../, ~/ prefix)
myapp -c /etc/myapp/prod.yaml
myapp -c ./local-config.yaml

# Bare filename: under --etc-dir when given, otherwise the current directory
myapp -c custom.yaml                    # loads ./custom.yaml
myapp --etc-dir /app/etc -c prod.yaml   # loads /app/etc/prod.yaml
```

Enable via `with_standard_args(config_file=True)`:

```python
app = (
    AppBuilder("myapp")
    .config.with_spec("myorg", "myapp")
    .done()
    .with_standard_args(etc_dir=True, config_file=True)
    .build()
)
```

## Main Tool (Single-Tool Apps)

For single-purpose apps, use `with_main_tool()` to run a tool without requiring a subcommand:

```python
app = AppBuilder("proxy").with_main_tool("run").build()


@app.tool(name="run")
def run_proxy(self):
    self.lg.info("Starting proxy...")
    return 0
```

Now the app can be invoked without the subcommand:
```bash
# Before: ./proxy.py run --port 8080
# After:  ./proxy.py --port 8080
```

Accepts either a tool name (string) or Tool object:
```python
AppBuilder("proxy").with_main_tool("run")  # by name
AppBuilder("proxy").with_main_tool(my_tool)  # by object
```

## Hot-Reload Logging

Enable automatic config reloading when config files change (requires `pip install
appinfra[hotreload]`):

```python
app = (
    AppBuilder("my-service")
    .config.with_spec("myorg", "my-service")
    .with_hot_reload(True)  # Watch the resolved config file
    .done()
    .build()
)
```

See [Hot-Reload Logging Guide](../guides/hot-reload-logging.md) for full documentation.

## See Also

- [Decorator API with Config Files](../guides/decorator-config-pattern.md) - Build app, then decorate
- [Application Framework](app.md) - Tool and ToolConfig
- [Logging System](logging.md) - LoggingBuilder
- [Hot-Reload Logging](../guides/hot-reload-logging.md) - Dynamic config reloading
