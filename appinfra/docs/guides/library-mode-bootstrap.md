---
title: Library-Mode Bootstrap
keywords:
  - library mode
  - headless
  - script
  - Config
  - create_root_lg
  - Config.from_spec
aliases:
  - library-mode
  - headless-bootstrap
---

# Library-Mode Bootstrap

Guide to wiring appinfra into any Python entry point that is not a CLI: standalone scripts,
notebooks, embedded clients, in-process factory calls, and full libraries that ship a wheel with
their own default config.

Framework mode (`AppBuilder.with_config_spec(...).build().setup()`) owns `sys.argv` and adds a
CLI shell on top of the same primitives — see the
[framework-wired discovery helper](config-protocol.md#discovery-helper) for that side. This guide
covers everywhere argv is not the entry point.

## The spectrum at a glance

| Shape                                     | Config surface                        | Section    |
|-------------------------------------------|---------------------------------------|------------|
| Script, no config file                    | None — logger only                    | [Case A](#case-a--script-no-config-file) |
| Script with a config file next to it      | `Config(str(Path(__file__).parent / "config.yaml"))` | [Case B](#case-b--script-with-a-config-file) |
| Script with `App`/`Tool` shape            | `AppBuilder(...)` — framework mode    | [Case C](#case-c--script-with-app-shape) |
| Library that ships a packaged base config | `Config.from_spec(namespace, module)` | [Case D](#case-d--library-with-a-packaged-base-config) |

Cases are ordered simplest first. A caller reaching the guide starts at the top and stops when
the shape matches.

## Case A — Script, no config file

Runnable file, no config to load, only a logger. `create_root_lg` is enough.

```python
from appinfra.log import create_root_lg

lg = create_root_lg(level="warning")
lg.warning("hello")
```

That is the whole bootstrap. `create_root_lg` returns a configured root `Logger`; no `Config`
object exists in this scenario. Reach for `Config` only when there is actual configuration to
load.

## Case B — Script with a config file

The script has a YAML file next to it (or somewhere on disk) and no packaged `etc/` layout —
typical for one-off jobs, benchmarks, or exploratory scripts. Use `Config` directly with the
file path; there is no package identity to spec.

```
my_script/
├── run.py
└── config.yaml
```

```python
from pathlib import Path

from appinfra.config import Config
from appinfra.log import create_root_lg

config = Config(str(Path(__file__).parent / "config.yaml"))
lg = create_root_lg(level="warning")
```

`Config.from_spec` does not fit here — no package module, no namespace identity, no XDG
overlay chain to walk. Plain `Config(path)` is the right primitive.

## Case C — Script with `App` shape

The script defines a `Tool` subclass or uses `AppBuilder` to compose subcommands. That path
is framework mode, not library mode — `App.setup()` parses `sys.argv`, resolves the config
via the v1 protocol, and drives the tool lifecycle.

```python
from pathlib import Path

from appinfra.app import AppBuilder

BASE_CONFIG = Path(__file__).parent / "etc" / "myapp.yaml"

app = (
    AppBuilder("myapp")
    .with_config_spec("myorg", "myapp", BASE_CONFIG)
    .with_standard_args(etc_dir=True, config_file=True)
    .build()
)
app.setup()
```

Full detail lives in
[config-protocol.md § Discovery helper](config-protocol.md#discovery-helper). This guide does
not duplicate that surface — reach for library mode only when the entry point does not own
argv.

## Case D — Library with a packaged base config

A library shipped as a wheel with its default config at `<pkg>/etc/<pkg>.yaml`
(per [protocol rule 2](config-protocol.md#2-base-config-ships-in-the-wheel)) is the canonical
target for `Config.from_spec`.

```
my_package/
├── __init__.py
├── etc/
│   └── my-package.yaml
└── ...
```

Downstream construction:

```python
import my_package
from appinfra.config import Config
from appinfra.log import create_root_lg

config = Config.from_spec("myorg", my_package)
lg = create_root_lg(level="warning")
```

Two positional arguments — `namespace` (XDG scope) and `package_module` (the imported top-level
module). Everything else — deriving the config filename, running the precedence chain, choosing
the include-authorization root — happens inside `from_spec`.

### D1 — Filename convention

The default config filename is derived as
`package_module.__name__.replace("_", "-") + ".yaml"`. Under the standard PEP 8 / packaging
convention (dashed distribution name → underscored module name), this produces the right
filename automatically: a module named `my_package` looks up `etc/my-package.yaml`, a module
named `simple` looks up `etc/simple.yaml`.

### D2 — Non-conventional filename

When the config filename does not follow the convention (e.g. a legacy layout, or a package
whose identity carries multiple words that do not map cleanly), pass `package=` explicitly:

```python
config = Config.from_spec("myorg", my_package, package="legacy-name")
# Looks up: <my_package.__file__>/../etc/legacy-name.yaml
```

The explicit form also flows through to XDG discovery — `$XDG_CONFIG_HOME/myorg/legacy-name.yaml`
is what the overlay chain probes.

### D3 — Accepting user overrides

A library that wants to let its own callers point at an alternate config location surfaces
`etc_dir` and `config_file` as parameters on its own API. `Config.from_spec` takes them as
keyword-only kwargs and threads them into the precedence chain, equivalent to the framework's
`--etc-dir` / `--config` flags.

```python
def load_config(
    *,
    etc_dir: str | None = None,
    config_file: str | None = None,
) -> Config:
    return Config.from_spec(
        "myorg",
        my_package,
        etc_dir=etc_dir,
        config_file=config_file,
    )
```

These values MUST come from the caller — a function parameter, a host-application setting, a
constructor kwarg. A library must not read them from `sys.argv` or environment variables on
behalf of its host, per
[protocol rule 5](config-protocol.md#5-library-vs-cli-split).

## Logger configuration

Two shapes for driving the root logger.

**Fixed level, no YAML.** For scripts and libraries that do not want their logger driven from
the config file, `create_root_lg(level=...)` is one call:

```python
from appinfra.log import create_root_lg

lg = create_root_lg(level="warning")
```

**YAML-driven.** For entry points where the config file carries a `logging:` section that
should shape the root logger, load it after `Config`:

```python
from appinfra.log import LogConfig, LoggerFactory

log_config = LogConfig.from_config(config.dict(), "logging")
lg = LoggerFactory.create_root(log_config)
```

This mirrors what `AppBuilder` does at framework setup time. Reach for it when the config file
is authoritative for logging shape; stay with `create_root_lg` otherwise.

`Config.from_spec` deliberately does not fuse the logger into its return value — the YAML-driven
path above is a real branch, and a `(config, logger)` return would hide it.

## Packaging as a helper

Library authors typically lift the bootstrap into a package-level function so downstream code
reduces to one call:

```python
# in my_package/__init__.py

import my_package
from appinfra.config import Config
from appinfra.log import create_root_lg


def quickstart(
    *,
    etc_dir: str | None = None,
    config_file: str | None = None,
    log_level: str = "warning",
) -> "Client":
    config = Config.from_spec(
        "myorg",
        my_package,
        etc_dir=etc_dir,
        config_file=config_file,
    )
    lg = create_root_lg(level=log_level)
    return ClientFactory(lg).create_from_config(config=config)
```

Downstream:

```python
from my_package import quickstart

client = quickstart()
```

appinfra does not ship a generic bundling helper for this pattern — the shape is thin enough
that each library tailors it to the surface its own consumers need (custom context types,
factory signatures, sensible default log levels, additional wiring).

## When to graduate to framework mode

Migrate to `AppBuilder.with_config_spec(...)` when any of these become true:

- The entry point runs from a terminal and end users expect `--etc-dir` / `--config` /
  `--log-level` on the CLI surface.
- The entry point grows subcommands or tools (the `Tool` protocol pays for itself).
- Long-running lifecycle hooks show up: hot-reload, graceful shutdown, subprocess supervision.

For a headless script, notebook, or in-process client construction, library mode stays lighter
and imposes no argv contract on the caller.

## See also

- [Config Protocol](config-protocol.md) — v1 spec, precedence rules, XDG search
- [Config API](../api/config.md) — `Config`, `resolve_config_source`, `xdg_candidates`
- [Logging API](../api/logging.md) — `LoggerFactory`, `LogConfig`, `create_root_lg`
- [Configuration Precedence](configuration-precedence.md) — CLI vs env vs file
