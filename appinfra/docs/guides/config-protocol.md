---
title: Config Protocol for llm-works Packages
keywords:
  - config protocol
  - XDG
  - llm-works
  - env prefix
  - one-file-per-package
aliases:
  - config-protocol-v1
  - llm-works-config
---

# Config Protocol v1 for llm-works Packages

**Version:** v1 · **Owner:** appinfra

Shared conventions for how llm-works substrate packages locate and load configuration. appinfra
defines and evolves this spec.

The protocol is minimal by design: one file per package, one env-var prefix everywhere, XDG for
user overrides.

## Versioning

This document defines **v1**. The version is a documentation trail — it identifies which spec
applies to a given appinfra release, so future changes have a clean break point. Consumers do not
pin against a protocol version; they pin against an appinfra release and get whatever protocol
version that release ships. Mixing a newer appinfra with an older protocol version is not
supported.

Backwards-incompatible changes ship as v2. Additive clarifications land in place.

## The rules

### 1. One config file per package load

Each package loads exactly **one** configuration file. Multi-file composition happens *inside* that
file via YAML `!include` / `!include?` directives — not by having the framework merge multiple
files in a layered pipeline.

Rationale: a single load path is easier to reason about, easier to debug (`Config.get_source_files`
reports the exact chain), and defers merge semantics to the YAML author who knows their overlay
shape. See [YAML Includes](../api/config.md#yaml-includes).

### 2. Base config ships in the wheel

Every package with default config ships `etc/<package-name>.yaml` inside its wheel. Pure-library
packages with no config-owned surface are exempt.

### 3. User overrides go under XDG directories

Users place override configs at one of:

- `$XDG_CONFIG_HOME/llm-works/<package-name>.yaml` — per-package file, or
- `$XDG_CONFIG_HOME/llm-works/config.yaml` — unified file, top-level key per package

`XDG_CONFIG_HOME` defaults to `~/.config` per spec. System-wide defaults may also live under
`$XDG_CONFIG_DIRS` (default `/etc/xdg`) — packagers, sysadmins, and container images use these to
drop system defaults.

Users pick one location and one shape. The framework loads the first existing candidate in XDG
search order (home first, then system dirs; per-package before unified within each dir). Composing
base + overrides is the user's responsibility, expressed with `!include`:

```yaml
# ~/.config/<namespace>/<package>.yaml
!include <base-config-path>

database:
  pool_size: 20   # override
```

To find the base config path for an installed package:

```bash
python -c "import myapp, pathlib; print(pathlib.Path(myapp.__file__).parent / 'etc' / 'myapp.yaml')"
```

Loading an overlay that pulls in a base config outside the overlay's own
directory requires the caller to widen the include-authorization boundary.
See the discovery-helper example below and [Config](../api/config.md#config)
for the `project_root` and `allowed_paths` arguments.

### 4. `INFRA_*` is the only config-override env prefix

Environment variables that override configuration values use the `INFRA_*` prefix, universally,
across every llm-works package and appinfra itself. There are no per-package prefixes for config
overrides.

Rationale: users move between packages without switching mental models. `INFRA_LOGGING_LEVEL=debug`
applies to every process in the stack.

Per-package `<PKG>_*` env vars MAY exist for non-config purposes — demo-application variables,
non-config runtime state — but never for overriding config fields.

See [Environment Variable Overrides](environment-variables.md) for format and type-conversion
rules, and [Configuration Precedence](configuration-precedence.md) for how env vars combine with
CLI flags and file values.

### 5. Library vs CLI split

- **Library callers** pass an explicit config path to `Config`. No home-sniffing; a library must
  not read from the ambient environment on behalf of its host application.
- **CLI entry points** discover their user override file via
  [`xdg_candidates`](../api/config.md#xdg-config-discovery), iterate the returned list, and load
  the first existing entry.

### 6. `--etc-dir` is user-authoritative

CLI entry points that expose `--etc-dir` MUST honor it as authoritative over XDG discovery.
Registration is the consumer's choice: a locked-down CLI may deliberately skip `--etc-dir` (XDG +
bundled base only); a general-purpose CLI registers it so end users can point at any tree they
own.

Precedence chain when the flag is registered, evaluated left-to-right, first hit wins:

1. `--etc-dir /foo` present → load `/foo/<package>.yaml`, `project_root=/foo`. The user's directory
   IS the include-authorization root; sibling `!include`s inside it resolve by default, anything
   outside is the user's `allowed_paths` problem.
2. Else first existing XDG candidate → load overlay,
   `project_root=include_root_for(base_config)` (the packaged base's `etc/` directory). Defensive.
3. Else the packaged base itself.

When the flag is not registered, the chain starts at step 2.

Rationale: appinfra's include-authorization guard has a job on the DEFAULT path — the user hasn't
specified anything, so defensive boundaries apply. It cannot dictate where a caller pointing
`--etc-dir` is allowed to go — that choice is authoritative. Same principle as `sudo` vs
unprivileged shell.

`--etc-dir` and an XDG overlay cannot compose in one invocation — the overlay's `!include` target
is a static string in a YAML file that no runtime flag can rewrite. A user who wants a custom base
with their own overrides puts a self-contained tree under `<etc-dir>` (base + edits) and skips the
overlay indirection.

## Discovery helper

Consumers pick the CLI shape that fits:

### Hand-wired (any appinfra release ≥ 0.10.4)

```python
from pathlib import Path

from appinfra.config import Config, resolve_config_source

NAMESPACE = "myorg"
PACKAGE = "myapp"
BASE_CONFIG = Path(__file__).parent / "etc" / f"{PACKAGE}.yaml"


def load_user_config(custom_etc_dir: str | None = None) -> Config:
    config_file, project_root = resolve_config_source(
        NAMESPACE, PACKAGE, BASE_CONFIG, custom_etc_dir=custom_etc_dir
    )
    return Config(str(config_file), project_root=project_root)
```

`resolve_config_source` runs the full rule-6 precedence chain and returns both the file to load and
the `project_root` to pass. On the default path, `project_root` is `include_root_for(BASE_CONFIG)`
— the base's `etc/` directory, the tightest boundary that authorizes both the overlay's absolute
`!include <BASE_CONFIG>` and the base's own relative sibling `!include './...'` directives. Under
`--etc-dir`, `project_root` follows the user's directory.

Pick the tightest ancestor that contains all `!include`-reachable files. Usually that's the
base's `etc/` directory (`include_root_for(BASE_CONFIG)`); pass the wider package directory
(`BASE_CONFIG.parent.parent`) explicitly only when the base's includes reach files outside
`etc/`.

Use `allowed_paths` (rather than `project_root`) when the overlay references one specific file
outside the package root — e.g. a shared config elsewhere on disk. The two arguments compose.

### Framework-wired (appinfra ≥ 0.10.5)

`AppBuilder.with_config_spec` runs the rule-6 chain on every parse and wires `ConfigWatcher` with
the same `project_root` so hot-reload matches the initial load. Flag exposure is orthogonal —
compose with `.with_standard_args(etc_dir=True)` to expose the escape hatch to end users, skip
that call for a locked-down CLI:

```python
from pathlib import Path

from appinfra.app import AppBuilder

BASE_CONFIG = Path(__file__).parent / "etc" / "myapp.yaml"

# XDG + bundled base only, no --etc-dir flag exposed:
app = AppBuilder("myapp").with_config_spec("myorg", "myapp", BASE_CONFIG).build()

# With the --etc-dir escape hatch for end users:
app = (
    AppBuilder("myapp")
    .with_config_spec("myorg", "myapp", BASE_CONFIG)
    .with_standard_args(etc_dir=True)
    .build()
)
```

`with_config_spec` and `with_config_file` are mutually exclusive — pick one config-loading mode
per builder. Pre-v1 callers relying on `with_config_file()` need no migration; their code path is
unchanged.

Full API contract in [Config](../api/config.md#config) and
[XDG Config Discovery](../api/config.md#xdg-config-discovery).

## See also

- [Config API](../api/config.md) — Config class, includes, `xdg_candidates`
- [Environment Variables](environment-variables.md) — `INFRA_*` format details
- [Configuration Precedence](configuration-precedence.md) — CLI vs env vs file
- [XDG Base Directory Specification](https://specifications.freedesktop.org/basedir-spec/latest/)
