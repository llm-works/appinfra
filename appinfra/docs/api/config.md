# Configuration

Configuration loading, environment variable overrides, hot-reload watching, and optional schema
validation.

## Config

Configuration class that loads YAML files with variable substitution, environment overrides, and
include support.

```python
class Config(DotDict):
    def __init__(
        self,
        fname: str | Path | ConfigFile,
        enable_env_overrides: bool = True,
        env_prefix: str = "INFRA_",
        merge_strategy: str = "replace",
        allowed_paths: list[Path | str] | None = None,
        project_root: Path | str | None = None,
    ): ...

    @classmethod
    def from_path(cls, path: str | Path, **options) -> Config: ...
    @classmethod
    def from_spec(
        cls,
        namespace: str,
        name: str,
        *,
        origin=AUTO,
        etc_dir="etc",
        filename=AUTO,
        path=None,
        **options,
    ) -> Config: ...

    def reload(self) -> Config: ...
    def validate(self, raise_on_error: bool = True) -> bool | Any: ...
    def get_env_overrides(self) -> dict[str, Any]: ...
    def get_source_files(self) -> set[Path]: ...
```

**Parameters:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `fname` | required | Path to a YAML configuration file, or a `ConfigFile` from `ConfigSpec.resolve()` |
| `enable_env_overrides` | `True` | Apply environment variable overrides |
| `env_prefix` | `"INFRA_"` | Prefix for environment variables |
| `merge_strategy` | `"replace"` | Strategy for handling `!include` directives: `"replace"` (included content replaces target key) or `"merge"` (deep merge with existing). Note: only `"replace"` is currently fully supported |
| `allowed_paths` | `None` | Explicit list of specific paths (e.g. `["~/.myapp.yaml"]`) that absolute `!include*` directives may reach even when outside `project_root`. Each entry is `~`-expanded and resolved once; an include path bypasses the guard only if it resolves to an exact match. Applies to absolute / tilde-expanded includes only — relative includes stay bound to `project_root`. Use for narrow user-overlay patterns. See [YAML custom tags](utilities.md#custom-tags) for the overlay-pattern example. |
| `project_root` | `None` | Override for the include-authorization boundary. When set, replaces the auto-derived `project_root` for every include check in the load — both relative and absolute. Auto-derivation walks the config file's ancestry for an `etc/*.yaml` marker and falls back to the file's parent directory; a user overlay under `$XDG_CONFIG_HOME` has no such marker and cannot reach a base config shipped inside a package's `etc/`. A `ConfigFile` from `ConfigSpec.resolve()` carries the right value, the base's own directory; pass a wider ancestor explicitly only when the base's includes reach files outside it. `~`-expanded and resolved once. See [Config Protocol](../guides/config-protocol.md) for the overlay pattern. |

**Constructors:**

- `Config.from_path(path, **options)`: one file, nothing else consulted. The no-spec entry
  point.
- `Config.from_spec(namespace, name, **layout, **options)`: the identity and layout keywords of
  [`ConfigSpec`](#config-spec); resolves with no operator input (project-local `etc/`, XDG
  overlays, packaged base) and loads. It takes no `--etc-dir` / `--config` passthrough: a host
  that parses those builds the spec and passes `resolve(...)` to the constructor.
- `Config(fname | ConfigFile, ...)`: the low-level entry, used by the App and by the flags case.

`**options` are the constructor's keyword parameters; `from_spec` omits `project_root`, which
the resolved file carries.

**Basic Usage:**

```python
from appinfra.config import Config

# One file by path
config = Config.from_path("etc/config.yaml")

# The file the protocol resolves to (see Config Spec below)
config = Config.from_spec("myorg", "myapp")

# Access with dot notation (inherits from DotDict)
print(config.logging.level)
print(config.database.host)

# Get with fallback
port = config.get("database.port", default=5432)
```

## Environment Variable Overrides

Environment variables with the configured prefix override config file values.

**Format:** `{PREFIX}{SECTION}_{SUBSECTION}_{KEY}=value`

```bash
export INFRA_LOGGING_LEVEL=debug
export INFRA_DATABASE_PORT=5433
export INFRA_SERVER_HOST=0.0.0.0
```

```python
config = Config.from_path("etc/config.yaml")
print(config.logging.level)  # "debug" (from env, not file)
```

**Type Conversion:**

| Value | Converted Type |
|-------|----------------|
| `true`, `false` | `bool` |
| `null`, `none`, `""` | `None` |
| `123` | `int` |
| `1.5` | `float` |
| `a,b,c` | `list[str]` |
| anything else | `str` |

**Check Active Overrides:**

```python
overrides = config.get_env_overrides()
# {"logging.level": "debug", "database.port": 5433}
```

## YAML Includes

Config supports including other YAML files:

```yaml
# config.yaml
database: !include "./database.yaml"           # Include file as value
settings: !include "shared.yaml#app.settings"  # Include specific section

# Document-level include (merges at root)
!include "./base.yaml"

app_name: myapp
```

**Optional Includes:**

Use `!include?` for files that may or may not exist:

```yaml
# Required include (raises if missing)
database: !include "./database.yaml"

# Optional include (returns {} if missing)
overrides: !include? "./.env.yaml"
local_settings: !include? "./local.yaml#settings"

# Document-level optional include
!include? "./local-overrides.yaml"

name: myapp
```

Optional includes are useful for environment-specific overrides that don't exist in all deployments.

**Security:** Includes are protected against path traversal attacks and circular dependencies.

## Path Resolution

Path resolution requires the explicit `!path` YAML tag. Without the tag, paths remain as literal
strings:

```yaml
# etc/config.yaml
logging:
  file: ./logs/app.log           # Stays as "./logs/app.log" (no resolution)
  resolved: !path ./logs/app.log # Resolved to /project/etc/logs/app.log

models:
  path: !path ../models          # Resolved to /project/models
  cache: !path ~/.cache/myapp    # Expands ~ to home directory
```

**The `!path` tag:**
- Resolves relative paths (`./`, `../`) to absolute paths based on config file location
- Expands tilde (`~`) to the user's home directory
- Leaves absolute paths and URLs unchanged

See [YAML Tags](utilities.md#yaml-tags) for more details on `!path` and other custom tags.

## Config Spec

`ConfigSpec` names where a config's packaged base lives and resolves, against user
overrides, the one file to load. It never produces a `Config`; the resolved `ConfigFile` is
what `Config` loads.

```python
class ConfigSpec:
    def __init__(
        self,
        namespace: str,
        name: str,
        *,
        origin: str | Path | Auto = AUTO,
        etc_dir: str = "etc",
        filename: str | Auto = AUTO,
        path: str | Path | None = None,
    ): ...

    namespace: str
    name: str
    etc_dir: str
    base_config: Path
    include_root: Path

    def resolve(self, *, etc_dir=None, config_file=None) -> ConfigFile: ...
    def xdg_candidates(self) -> list[Path]: ...
    def project_local(self) -> Path | None: ...


@dataclass(frozen=True)
class ConfigFile:
    path: Path
    project_root: Path
    rule: int
```

**Identity.** `namespace` is the XDG directory shared by related configs (e.g. `"myorg"`).
`name` is the config's name: the base filename stem, the XDG entry `<namespace>/<name>.yaml`,
and what `--etc-dir` looks for. For a package it is the package name.

**Locating the base.** The packaged base is `<origin dir>/<etc_dir>/<filename>`. Every part
defaults from the name, so a conforming package needs only its identity:

```python
ConfigSpec("myorg", "myapp")  # <myapp module dir>/etc/myapp.yaml
```

| Keyword    | Decides                                                        | Default                      |
|------------|----------------------------------------------------------------|------------------------------|
| `origin`   | the anchor: a file's directory (`__file__`) or a directory     | `AUTO`, see below            |
| `etc_dir`  | directory under the anchor; `""` for the anchor itself; an absolute path stands alone | `"etc"` |
| `filename` | the file inside it                                             | `<name>.yaml`                |
| `path`     | the file outright; excludes the other three                    | none                         |

With `origin` left `AUTO`, two candidates are probed in order and the first holding the file
wins: the directory of the module named after the config (`"-"` mapped to `"_"`, located via
`importlib.util.find_spec` without importing it), then the directory of the calling script.
Neither existing raises `ValueError` naming both. Explicit `origin` and `path` never probe.
`origin=None` is a `TypeError`; the absent value is `AUTO`.

**Resolution** (see [rule
6](../guides/config-protocol.md#6---config-and---etc-dir-are-user-authoritative)).
`resolve(etc_dir=, config_file=)` takes the operator's `--etc-dir` and `--config` values for
this run and returns the first tier that applies:

1. `config_file` is a direct path (absolute, `./`, `../`, `~/`, or `~`) → that file; `etc_dir`
   ignored; root is the file's parent.
2. `config_file` is a bare filename → `<etc_dir>/<config_file>` if `etc_dir` is set, else
   `<cwd>/<config_file>`; root is that directory.
3. `etc_dir` alone → `<etc_dir>/<base filename>`; root is `etc_dir`. Unvalidated; a missing file
   surfaces at `Config(...)` load time as a `FileNotFoundError`.
4. Project-local: walk up from cwd for `<spec etc_dir>/<base filename>`; first hit; root is that
   directory. Stops before `$HOME` and before the filesystem root.
5. First existing XDG candidate; root is `include_root`, the base's directory.
6. The packaged base; root is `include_root`.

`ConfigFile.rule` records which tier won. `xdg_candidates()` enumerates tier 5 in load order
(`<namespace>/<name>.yaml` then `<namespace>/config.yaml` under `$XDG_CONFIG_HOME`, then each
`$XDG_CONFIG_DIRS` entry) without touching the filesystem; `project_local()` is tier 4 on its
own.

**Library-mode pattern.** With no operator input, `Config.from_spec` does the whole thing:

```python
from appinfra.config import Config

config = Config.from_spec("myorg", "myapp")
```

A library that surfaces `--etc-dir` / `--config` on its own API builds the spec and resolves
explicitly; the factory takes no operator flags:

```python
from appinfra.config import Config, ConfigSpec

SPEC = ConfigSpec("myorg", "myapp")


def load_user_config(
    etc_dir: str | None = None, config_file: str | None = None
) -> Config:
    return Config(SPEC.resolve(etc_dir=etc_dir, config_file=config_file))
```

A `ConfigFile` carries its own `project_root`; passing `project_root=` alongside it raises.
For applications built on `AppBuilder`, declare the same spec through the
[config block](#appbuilderconfig); the App resolves it on every parse and wires
`ConfigWatcher` with the same `project_root`.

## Config Reload

Reload configuration from disk:

```python
config = Config("etc/config.yaml")

# Later, after file changes...
config.reload()  # Re-reads file, reapplies env overrides
```

**Note:** Not thread-safe. Callers must coordinate access during reload.

## ConfigWatcher

File watcher for hot-reload of configuration. Uses watchdog for efficient file system monitoring.

```python
class ConfigWatcher:
    def __init__(self, lg: Logger, etc_dir: str | Path): ...

    def configure(
        self,
        config_file: str,
        debounce_ms: int = 500,
        on_change: Callable[[dict], None] | None = None,
    ) -> ConfigWatcher: ...

    def start(self) -> None: ...
    def stop(self) -> None: ...
    def is_running(self) -> bool: ...
    def reload_now(self) -> None: ...
    def add_section_callback(self, section: str, callback: Callable) -> None: ...
    def remove_section_callback(self, section: str, callback: Callable) -> None: ...
```

**Basic Usage:**

```python
from appinfra.config import ConfigWatcher
from appinfra.log import LogConfigReloader

# Create reloader callback for logging config
reloader = LogConfigReloader(root_logger, section="logging")

# Create and start watcher
watcher = ConfigWatcher(lg=logger, etc_dir="/etc/myapp")
watcher.configure("config.yaml", on_change=reloader)
watcher.start()

# File changes are now automatically detected
# ...

watcher.stop()
```

**Requirements:**

```bash
pip install appinfra[hotreload]  # Installs watchdog
```

## Section Callbacks

Register callbacks for specific config sections:

```python
watcher = ConfigWatcher(lg=logger, etc_dir="./etc")
watcher.configure("config.yaml")


def on_features_changed(features_config):
    logger.info("Features updated")
    apply_feature_flags(features_config)


def on_plugins_changed(plugins_config):
    logger.info("Plugins updated")
    reload_plugins(plugins_config)


watcher.add_section_callback("features", on_features_changed)
watcher.add_section_callback("proxy.plugins", on_plugins_changed)
watcher.start()
```

## Content-Based Change Detection

ConfigWatcher uses content hashing to avoid spurious reloads when file is touched but content is
unchanged:

```python
# File touched but content identical -> no callback triggered
# File content actually changed -> callback triggered
```

## Include File Watching

ConfigWatcher automatically watches all files that contribute to the config, including files loaded
via `!include`:

```python
watcher.configure("config.yaml")
watcher.start()
# Now watching: config.yaml, database.yaml, base.yaml, etc.

# If any included file changes, config is reloaded
```

## Schema Validation

Optional Pydantic-based validation (requires `appinfra[validation]`):

```python
from appinfra.config import Config

config = Config("etc/config.yaml")

# Validate against schema
try:
    validated = config.validate()
    print("Configuration is valid!")
except ValidationError as e:
    print(f"Invalid configuration: {e}")

# Non-raising validation
if config.validate(raise_on_error=False):
    print("Valid")
else:
    print("Invalid")
```

**Install validation support:**

```bash
pip install appinfra[validation]
```

## Reading `app.etc_dir`

`App.etc_dir` is the etc directory in effect for the current run. It is set
during `setup()`, before any `Tool.setup()` runs, so tools can read it directly:

```python
class MyTool(Tool):
    def configure(self) -> None:
        # Inside Tool.configure(), self.app.etc_dir is the resolved path
        # (or None if no spec is declared and --etc-dir was not passed).
        etc_dir = self.app.etc_dir
        if etc_dir is None:
            raise RuntimeError("MyTool requires a config spec or --etc-dir")
        with open(Path(etc_dir) / "mytool.yaml") as f:
            self._settings = yaml.safe_load(f)
```

Resolution rules:

- **Spec declared** — `app.etc_dir` is the directory of the file the spec resolved to
  (`app.config_path.parent`), whichever precedence rule chose it.
- **`with_standard_args(etc_dir=True)` only** (no spec):
  - `--etc-dir /foo` valid → `app.etc_dir` is `/foo` (resolved).
  - `--etc-dir /bad` missing → raises `FileNotFoundError` at setup (fail-fast).
  - flag omitted → `None`; there is no default directory without a spec.
- **`etc_dir` not opted in and no spec** — `app.etc_dir` is always `None`.

See
[`examples/04_configuration/etc_dir_only_example.py`](../../examples/04_configuration/etc_dir_only_example.py)
for a runnable app that loads its own YAML files from `app.etc_dir` without
declaring a spec.

## Constants

```python
from appinfra.config import MAX_CONFIG_SIZE_BYTES  # security size limit
```

## Integration with AppBuilder

### `AppBuilder.config`

The config-source block. It declares the [`ConfigSpec`](#config-spec) the App resolves at
setup, the programmatic layer above the loaded file, and whether the resolved file is watched
for hot reload. `ConfigWatcher` is wired with the resolved `project_root`, so reloads use the
initial-load boundary.

| Method                                   | Effect                                                                 |
|------------------------------------------|------------------------------------------------------------------------|
| `with_spec(namespace, name, **layout)`   | Declares the spec; same keywords as `ConfigSpec` (`origin`, `etc_dir`, `filename`, `path`). |
| `with_overrides(mapping)`                | Deep-merges any mapping into the programmatic layer.                   |
| `with_value("dotted.key", value)`        | Sets one value in that layer.                                          |
| `with_hot_reload(enabled=True, debounce_ms=500)` | Watches the resolved file; requires a declared source.         |
| `done()`                                 | Returns to the `AppBuilder`.                                           |

Precedence of the layers: loaded file, then `with_overrides` / `with_value`, then CLI
arguments.

Two spellings write the same state. Chained:

```python
from appinfra.app import AppBuilder

app = (
    AppBuilder("myapp")
    .config.with_spec("myorg", "myapp")
    .with_value("logging.level", "debug")
    .with_hot_reload(debounce_ms=500)
    .done()
    .build()
)
```

Keyword, returning the `AppBuilder` directly:

```python
app = (
    AppBuilder("myapp").config(namespace="myorg", name="myapp", hot_reload=True).build()
)
```

The keyword form takes `namespace` and `name` together, the layout keywords, `overrides`,
`hot_reload` and `debounce_ms`.

Flag exposure is orthogonal. To expose the `--etc-dir` and `--config` escape hatches, compose
with `.with_standard_args(etc_dir=True, config_file=True)`; a locked-down CLI skips that call
and the loader reads a missing flag as `None`.

An app built without a spec loads no file: its config is the programmatic layer plus CLI
arguments. With `--etc-dir` opted in, the flag still populates `app.etc_dir` (validated at
setup), but no config is loaded from it. With `--config` opted in, the value is accessible
via `app.args.config` for manual loading.

See [Config Protocol §6](../guides/config-protocol.md#6-etc-dir-is-user-authoritative) for the
full `--etc-dir` semantics, and [`ConfigSpec`](#config-spec) for the resolution chain.

## See Also

- [Configuration Precedence](../guides/configuration-precedence.md) - Full precedence hierarchy (CLI > Env > YAML)
- [Environment Variables](../guides/environment-variables.md) - Detailed env var documentation
- [Utilities](utilities.md#dotdict) - DotDict base class
- [Logging System](logging.md) - LogConfigReloader for hot-reload
- [Hot-Reload Guide](../guides/hot-reload-logging.md) - Full hot-reload documentation
