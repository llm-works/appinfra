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

Absolute paths in `!include` require `allowed_paths` on the `Config` call. See
[Config](../api/config.md#config).

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

## Discovery helper

```python
from pathlib import Path

from appinfra.config import Config, xdg_candidates

NAMESPACE = "myorg"
PACKAGE = "myapp"
BASE_CONFIG = Path(__file__).parent / "etc" / f"{PACKAGE}.yaml"


def load_user_config() -> Config:
    for candidate in xdg_candidates(NAMESPACE, PACKAGE):
        if candidate.exists():
            return Config(str(candidate), allowed_paths=[str(BASE_CONFIG.parent)])
    return Config(str(BASE_CONFIG))
```

`xdg_candidates` is a pure function — no filesystem probing. The `allowed_paths` argument
authorizes absolute `!include` paths in user overrides. Full API contract in
[XDG Config Discovery](../api/config.md#xdg-config-discovery).

## See also

- [Config API](../api/config.md) — Config class, includes, `xdg_candidates`
- [Environment Variables](environment-variables.md) — `INFRA_*` format details
- [Configuration Precedence](configuration-precedence.md) — CLI vs env vs file
- [XDG Base Directory Specification](https://specifications.freedesktop.org/basedir-spec/latest/)
