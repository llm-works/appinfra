---
title: SPDX Header Check
keywords:
  - spdx
  - license header
  - Apache 2.0
  - cq
  - code quality
---

# SPDX Header Check

The `cq spdx` subcommand asserts that every tracked source file in the current
repository carries the required SPDX license markers in its first five lines:

```text
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright <year> The <package> Authors
```

Two modes: check (default, no side effects) and `--fix` (prepends the header to
files that don't already have it).

## Usage

### Check mode

```bash
python -m appinfra.cli.cli cq spdx
```

Exits 0 if all tracked source files carry the required markers. Exits 1
otherwise, listing the offending file paths on stderr with fix guidance.

### Fix mode

```bash
python -m appinfra.cli.cli cq spdx --fix
```

Prepends the 2-line header (plus one trailing blank line) to every tracked
source file that doesn't already carry it. Idempotent — files that already have
both `SPDX-License-Identifier` and `SPDX-FileCopyrightText` in their first 5
lines are skipped.

Shebangs are preserved. Between the shebang and the SPDX header, one blank line
is inserted so the OS-level directive stays visually separate from license
metadata:

```bash
#!/usr/bin/env bash

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

# ...rest of file
```

### Dry-run

```bash
python -m appinfra.cli.cli cq spdx --fix --dry-run
```

Reports what `--fix` would change without writing anything to disk.

## Package + year auto-derivation

- **Package name**: read from `[project] name` in `./pyproject.toml`. Override
  with `--package <name>`.
- **Year**: current calendar year at runtime. Override with `--year <YYYY>`.

Once a file has a header, re-running `--fix` never touches it (idempotent), so
the year is fixed at first application per file.

## Covered file types

`cq spdx` matches these basename patterns via `fnmatch` (patterns like
`Makefile.*` pick up fragments in any subdirectory, not just the repo root):

| Pattern | Examples |
|---------|----------|
| `*.py` | Python modules |
| `*.pyi` | Python type stubs |
| `*.sh`, `*.bash` | Shell scripts |
| `Makefile`, `Makefile.*`, `*.mk` | Make files and fragments |
| `Dockerfile`, `*.Dockerfile`, `*.dockerfile` | Container recipes |

Excluded (basename pattern `*.in`): scaffolding templates and configure inputs.
Downstream projects generated from templates supply their own copyright.

All covered types share `#` line-comment syntax so a single header template
works across them.

## Makefile integration

`cq spdx` integrates with `make check` via the framework variable
`INFRA_DEV_CQ_SPDX` (default `false`). To enable, set it to `true` in the
project's top-level Makefile before including the framework:

```makefile
INFRA_DEV_CQ_SPDX := true

include path/to/appinfra/Makefile
```

`make check` will then include an SPDX header check step alongside `ruff`,
`mypy`, and `cq cf`. On failure, `make cq.spdx` runs just the header check,
and `python -m appinfra.cli.cli cq spdx --fix` applies missing headers.

The default of `false` means projects reusing this framework that are not on
Apache-2.0 (or that don't want header enforcement) are unaffected.

## CI integration

Add a step to a GitHub Actions lint job:

```yaml
- name: SPDX header check
  run: python -m appinfra.cli.cli -l error cq spdx
```

## Cross-repo usage

`cq spdx` is repo-agnostic. Any project that has `appinfra` installed as a
dependency can run it from that project's repo root. The tool walks that
repo's `git ls-files`, derives the package name from the local
`pyproject.toml`, and applies headers with that project's attribution.

To adopt in a downstream Apache-2.0 repository:

1. Run `python -m appinfra.cli.cli cq spdx --fix` from repo root.
2. Commit the changes.
3. Add the CI step above to the lint workflow.
4. Optionally: set `INFRA_DEV_CQ_SPDX := true` in the top-level Makefile.

## Limitations

The required license marker is hardcoded to `SPDX-License-Identifier:
Apache-2.0`. Projects on other licenses (MIT, BSD, GPL) would false-fail even
with correct SPDX headers for their license. If cross-license support is
needed, the tool would need a `--license <spdx-id>` flag; not planned as of
this release.
