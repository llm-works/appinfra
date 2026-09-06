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

Every package with default config ships `etc/<name>.yaml` inside its wheel, where the name is
the package name. Pure-library packages with no config-owned surface are exempt.

The layout is encoded by the API, not reconstructed by callers. `ConfigSpec(namespace, name)`
locates the packaged base from the name alone; each keyword on it (`origin`, `etc_dir`,
`filename`, `path`) declares one deviation from this rule. A script that is not a package
follows the same layout beside its own file and gets the same treatment. See
[Config Spec](../api/config.md#config-spec).

### 3. User overrides go under XDG directories

Users place override configs at one of:

- `$XDG_CONFIG_HOME/llm-works/<name>.yaml` — per-config file, or
- `$XDG_CONFIG_HOME/llm-works/config.yaml` — unified file, top-level key per config

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
python -c "from appinfra.config import ConfigSpec; print(ConfigSpec('myorg', 'myapp').base_config)"
```

Loading an overlay that pulls in a base config outside the overlay's own
directory requires the caller to widen the include-authorization boundary.
See [Declaring the source](#declaring-the-source) below and [Config](../api/config.md#config)
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

- **Embedded libraries** take a config path, a `ConfigFile`, or a `Config` from their host. They
  do not discover on the host's behalf: no XDG lookup, no cwd walk-up, no `sys.argv`.
- **Entry points that own the process** (CLIs, scripts, notebooks, a host's own bootstrap
  helper) discover: [`ConfigSpec.resolve()`](../api/config.md#config-spec) runs the rule-6
  chain, XDG lookup included. A library that exposes a helper which discovers on the host's
  behalf says so in its own API contract.

### 6. `--config` and `--etc-dir` are user-authoritative

CLI entry points that expose `--etc-dir` or `--config` MUST honor them as authoritative over XDG
discovery. Registration is the consumer's choice: a locked-down CLI may deliberately skip both
(XDG + bundled base only); a general-purpose CLI registers them so end users can point at any tree
or file they own.

Precedence chain when the flags are registered, evaluated top-down, first hit wins:

1. `--config /abs.yaml`, `./rel.yaml`, `../rel.yaml`, or `~/path.yaml` (direct path) → load
   directly, `project_root` = the file's own parent directory. `--etc-dir` is ignored; matches
   non-spec-mode's `_load_direct_config` semantics.
2. `--config bare.yaml` (bare filename) → `<etc-dir>/bare.yaml` if `--etc-dir` passed, else
   `cwd/bare.yaml`. `project_root` = the file's parent.
3. `--etc-dir /foo` alone → load `/foo/<base filename>`, `project_root=/foo`. The user's
   directory IS the include-authorization root; sibling `!include`s inside it resolve by default,
   anything outside is the user's `allowed_paths` problem.
4. **Project-local**: walk up from cwd looking for `<etc_dir>/<base filename>` (`etc/` unless
   the spec declares otherwise). First hit → load it, `project_root` = that directory. A
   developer inside a checkout gets that checkout's config. Keyed on the filename the package
   actually ships, so a base that deviates from `<name>.yaml` matches without a special case.
   Stops before `$HOME` and before filesystem root, so home-dir dotfiles and system `/etc`
   are never picked up.
5. Else first existing XDG candidate → load overlay,
   `project_root` = the packaged base's directory.
   Defensive.
6. Else the packaged base itself.

When neither flag is registered, the chain starts at step 4.

`--config` always bypasses everything below it (project-local walk-up, XDG, packaged base). No
name-comparison special case — `--config <package>.yaml` behaves the same as any other filename,
matching non-spec-mode convention.

#### Resolution table

| `--etc-dir` | `--config`      | Loads from                             | `project_root`      |
|-------------|-----------------|----------------------------------------|---------------------|
| —           | —               | see fallback chain below               | (varies by tier)    |
| —           | direct path     | `<config>` (as given)                  | `<config>.parent`   |
| —           | bare filename   | `cwd/<config>`                         | `cwd`               |
| `/foo`      | —               | `/foo/<base filename>`                 | `/foo`              |
| `/foo`      | direct path     | `<config>` (`/foo` IGNORED)            | `<config>.parent`   |
| `/foo`      | bare filename   | `/foo/<config>`                        | `/foo`              |

*"Direct path"*: absolute (`/x`), `./rel`, `../rel`, `~/x`, or `~`.
*"Bare filename"*: anything else (e.g. `infra.yaml`, `sub/x.yaml`).

Fallback chain (only when neither flag is set):

```text
1. cwd (walk up) → <etc_dir>/<base filename>   first hit, stopping before $HOME
2. first existing XDG candidate:               $XDG_CONFIG_HOME/<ns>/<name>.yaml
                                               $XDG_CONFIG_HOME/<ns>/config.yaml
                                               then each $XDG_CONFIG_DIRS entry, same pair
3. packaged base                               the file the ConfigSpec names
```

Ordering rationale: a developer inside a project checkout gets that checkout's config —
XDG cannot shadow it. An operator running from a wheel install gets the packaged base as
default, with XDG available as a machine-level overlay above that default.

#### Decision tree

```text
                    ┌────────────────────────┐
                    │  --config passed?      │
                    └───┬────────────────┬───┘
                    yes │                │ no
                        ▼                ▼
              ┌─────────────────┐   ┌────────────────────────┐
              │ direct path?    │   │  --etc-dir passed?     │
              └─┬─────────────┬─┘   └───┬────────────────┬───┘
             yes│           no│      yes│                │ no
                ▼             ▼         ▼                ▼
         load <config>   ┌─────────┐  <etc>/<base>       [FALLBACK CHAIN]
         (--etc-dir      │--etc-dir│  root = <etc>       (project-local →
          ignored)       │passed?  │                      XDG → packaged base)
                         └─┬─────┬─┘
                        yes│    no│
                           ▼      ▼
                    <etc>/<cfg>  cwd/<cfg>
                    root=<etc>   root=cwd
```

Rationale: appinfra's include-authorization guard has a job on the DEFAULT path — the user hasn't
specified anything, so defensive boundaries apply. It cannot dictate where a caller pointing
`--etc-dir` or `--config` is allowed to go — that choice is authoritative. Same principle as `sudo`
vs unprivileged shell.

`--etc-dir` and an XDG overlay cannot compose in one invocation — the overlay's `!include` target
is a static string in a YAML file that no runtime flag can rewrite. A user who wants a custom base
with their own overrides puts a self-contained tree under `<etc-dir>` (base + edits) and skips the
overlay indirection.

## Declaring the source

Consumers declare identity, not paths. One `ConfigSpec` serves both entry points.

### Library mode (appinfra ≥ 0.11.0)

```python
from appinfra.config import Config, ConfigSpec

SPEC = ConfigSpec("myorg", "myapp")


def load_user_config(
    etc_dir: str | None = None, config_file: str | None = None
) -> Config:
    return Config(SPEC.resolve(etc_dir=etc_dir, config_file=config_file))
```

`resolve()` runs the full rule-6 chain and returns the file to load together with the
`project_root` that goes with it: the base's directory on the XDG and packaged-base tiers, the
user's directory under `--etc-dir`, the file's own parent under `--config`. `Config` reads that
root off the `ConfigFile`, the tightest boundary that authorizes both an overlay's absolute
`!include <base>` and the base's own relative sibling `!include './...'` directives.

Use `allowed_paths` on `Config` when an overlay references one specific file outside that root,
such as a shared config elsewhere on disk. The two compose.

### Framework mode (appinfra ≥ 0.11.0)

`AppBuilder.config.with_spec` declares the same spec. The App resolves it on every parse and
wires `ConfigWatcher` with the same `project_root` so hot reload matches the initial load. Flag
exposure is orthogonal: compose with `.with_standard_args(etc_dir=True, config_file=True)` to
expose the escape hatches to end users, skip either flag for a locked-down CLI:

```python
from appinfra.app import AppBuilder

# XDG + bundled base only, no escape-hatch flags exposed:
app = AppBuilder("myapp").config.with_spec("myorg", "myapp").done().build()

# With --etc-dir and --config escape hatches for end users:
app = (
    AppBuilder("myapp")
    .config.with_spec("myorg", "myapp")
    .done()
    .with_standard_args(etc_dir=True, config_file=True)
    .build()
)
```

An app declaring a spec does not call `with_config_file`; the two loading modes are mutually
exclusive per builder.

Full API contract in [Config Spec](../api/config.md#config-spec) and
[AppBuilder.config](../api/config.md#appbuilderconfig).

## See also

- [Config API](../api/config.md) — Config class, includes, `ConfigSpec`
- [Environment Variables](environment-variables.md) — `INFRA_*` format details
- [Configuration Precedence](configuration-precedence.md) — CLI vs env vs file
- [XDG Base Directory Specification](https://specifications.freedesktop.org/basedir-spec/latest/)
