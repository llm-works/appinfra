# Framework Integration Guide

This guide explains how to integrate the appinfra Makefile framework into downstream projects.

## Installation Methods

### Recommended: pip install

Install appinfra as a package and use the `scripts-path` command to locate the Makefile framework:

```bash
pip install appinfra
```

```makefile
# Makefile - using pip-installed appinfra
ifeq ($(origin APPINFRA_SCRIPTS),undefined)
APPINFRA_SCRIPTS := $(shell appinfra scripts-path)
endif

# Configure your project
APPINFRA_DEV_PKG_NAME ?= myproject

# Include framework
include $(APPINFRA_SCRIPTS)/make/Makefile.all
```

This is the recommended approach because:
- No submodule management overhead
- Version controlled via `requirements.txt` or `pyproject.toml`
- Works with standard Python packaging workflows

### Alternative: Git Submodule

Submodules are supported but **should rarely be needed**. Use only if you need to modify the
framework itself or work offline without pip access.

```bash
git submodule add <repo-url> submodules/appinfra
```

```makefile
# Makefile - using submodule
APPINFRA_SCRIPTS ?= submodules/appinfra/appinfra/scripts

APPINFRA_DEV_PKG_NAME ?= myproject
include $(APPINFRA_SCRIPTS)/make/Makefile.all
```

Either way, `APPINFRA_SCRIPTS` is appinfra's scripts directory, so the includes are the same.

## Quick Start

```makefile
# Recommended setup (pip install)
ifeq ($(origin APPINFRA_SCRIPTS),undefined)
APPINFRA_SCRIPTS := $(shell appinfra scripts-path)
endif

# Configure your project
APPINFRA_DEV_PKG_NAME ?= myproject

# Include framework (config must be first)
include $(APPINFRA_SCRIPTS)/make/Makefile.config
include $(APPINFRA_SCRIPTS)/make/Makefile.env
include $(APPINFRA_SCRIPTS)/make/Makefile.help
include $(APPINFRA_SCRIPTS)/make/Makefile.utils
include $(APPINFRA_SCRIPTS)/make/Makefile.dev
include $(APPINFRA_SCRIPTS)/make/Makefile.install  # Optional: only if building a package
include $(APPINFRA_SCRIPTS)/make/Makefile.pytest
include $(APPINFRA_SCRIPTS)/make/Makefile.clean
```

## Include Order

**Critical:** Include order matters. Always follow this sequence:

```makefile
# 1. REQUIRED FIRST - loads Makefile.local, the defaults and the setting checks
include $(APPINFRA_SCRIPTS)/make/Makefile.config

# 2. Core modules (order matters)
include $(APPINFRA_SCRIPTS)/make/Makefile.env      # Python detection
include $(APPINFRA_SCRIPTS)/make/Makefile.help     # Help system
include $(APPINFRA_SCRIPTS)/make/Makefile.utils    # Utilities (areyousure, etc.)

# 3. Feature modules (order flexible)
include $(APPINFRA_SCRIPTS)/make/Makefile.dev      # Requires: env, utils
include $(APPINFRA_SCRIPTS)/make/Makefile.install  # Optional: only if building a package
include $(APPINFRA_SCRIPTS)/make/Makefile.pytest   # Requires: env
include $(APPINFRA_SCRIPTS)/make/Makefile.docs     # Requires: env
include $(APPINFRA_SCRIPTS)/make/Makefile.pg       # Requires: env, utils
include $(APPINFRA_SCRIPTS)/make/Makefile.clean    # Requires: utils
```

Or use `Makefile.all` to include everything in the correct order:

```makefile
include $(APPINFRA_SCRIPTS)/make/Makefile.all
```

## Variable Precedence

Variables are resolved in this order (highest to lowest priority):

1. **Command line** - `make test APPINFRA_DEV_PKG_NAME=foo`
2. **Environment variables** - `APPINFRA_DEV_PKG_NAME=foo make test`
3. **Makefile.local** - Optional overrides file (not committed), `APPINFRA_DEV_PKG_NAME := foo`
4. **Project Makefile, before the include** - `APPINFRA_DEV_PKG_NAME ?= foo`
5. **Framework defaults** - Defined in `Makefile.config`

A `:=` in the project Makefile pins the value against the environment; see
[Configuration Precedence](makefile-customization.md#configuration-precedence).

### Example: Setting Package Name

```makefile
# In Makefile (before include)
APPINFRA_DEV_PKG_NAME ?= myproject
include $(APPINFRA_SCRIPTS)/make/Makefile.all

# Or via environment variable (for CI/testing)
# APPINFRA_DEV_PKG_NAME=myproject make test.coverage
```

## Common Configuration

### Minimal Configuration

```makefile
# Makefile
ifeq ($(origin APPINFRA_SCRIPTS),undefined)
APPINFRA_SCRIPTS := $(shell appinfra scripts-path)
endif
APPINFRA_DEV_PKG_NAME ?= myproject

include $(APPINFRA_SCRIPTS)/make/Makefile.all
```

### Full Configuration

```makefile
# Makefile
ifeq ($(origin APPINFRA_SCRIPTS),undefined)
APPINFRA_SCRIPTS := $(shell appinfra scripts-path)
endif
APPINFRA_DEV_PKG_NAME ?= myproject
APPINFRA_DEV_CQ_STRICT ?= true
APPINFRA_PYTEST_TESTS_DIR ?= tests
APPINFRA_DOCS_CONFIG_FILE ?= mkdocs.yaml

# Hide unused features
APPINFRA_DISABLE_GROUPS ?= pg.

include $(APPINFRA_SCRIPTS)/make/Makefile.all
```

## Extending Targets

Use double-colon rules (`::`) to extend framework targets:

```makefile
include $(APPINFRA_SCRIPTS)/make/Makefile.all

# Extend cleanup
clean::
	@echo "* cleaning app-specific files..."
	@rm -rf .app-cache/

# Extend tests
test.integration::
	@echo "* running app integration tests..."
	@./scripts/test-api.sh

# Extend linting
lint::
	@./scripts/check-schemas.sh
```

## Running check.sh

The `check.sh` script is designed to be run via Make, not directly:

```bash
# Correct - uses exported variables from Makefile
make check      # Interactive: live checklist, rows below it
make check.ci   # The same checks and warning policy as plain text, for logs and CI
make check.raw  # Every tool's output as is, every test listed: the reference without check.sh's policy

# Incorrect - will use fallback defaults (APPINFRA_DEV_PKG_NAME=appinfra)
./scripts/check.sh
```

`make check.ci` runs what `make check` runs, fail-fast, and applies the same warning policy, but
prints plain text without cursor movement: use it wherever output goes to a file or CI log. Its
checks run one after another, so their output stays in order, with pytest on its xdist workers
within each; that makes it slower than `make check`, which also runs the checks alongside each
other. `make check.raw` runs every tool with its output untouched and pytest in one
process with every test listed; it applies no warning policy, so comparing it with `make check`
shows whether `check.sh` itself changed an outcome.

With fail-fast (`make check`), the summary of a failed run shows only the failed test ids and
their first `E` lines; `make check.all` shows only which checks failed. The full output of each
failed check is kept in `.build/check/`, in a file named after the check (for example
`.build/check/type-checking-examples.log`), and the summary prints that path. This is the only
record of a failure that does not reproduce on rerun. Each run of `make check`, a concurrent one
included, empties the directory first, so copy a log elsewhere before running it again. The
directory carries its own `.gitignore`. A failed example's whole stdout and stderr are in the
Examples log: `make check` runs the examples with `run_examples.py --full-output`.

A test still running after `APPINFRA_PYTEST_HANG_DUMP_SECONDS` (default 120) gets a row below the
checklist, after a blank line:

```text
[⚠] Unit & E2E & Coverage tests: tests/test_server.py::test_shutdown running >120s
```

The row changes to `took 131.4s` if the test ends; a row still saying `running` when the run
ends or is interrupted is a hung test. The test's node id and the stack of every thread in its
process go to the check's log, which is kept in `.build/check/` and named in the summary. The
test is neither stopped nor failed, so a slow machine only gets more rows. In a terminal the
node id is shortened from the start to fit the width; without one (CI) it is printed whole, and
the CI log keeps the rows even when the job is killed by its timeout.

A non-daemon thread a test starts and leaves running holds up its process's exit; a
pytest-xdist worker in that state waits for it up to a 10s timeout, which the check's time
includes. The test that started such a thread gets a row below the checklist, and the thread's
name and stack go to the kept log:

```text
[⚠] Unit & E2E & Coverage tests: tests/test_proc.py::test_stream thread left running
```

A warning in a check that passed gets a row below the checklist, each distinct one once, with
how often it repeated:

```text
[⚠] Unit & E2E & Coverage tests: DeprecationWarning: old api (src/pkg/api.py:12) in tests (4×)
[⚠] Unit & E2E & Coverage tests: ResourceWarning: unclosed file tests/data/sample.csv at exit
[⚠] Examples: client.py: DeprecationWarning: old api (src/pkg/api.py:12)
[⚠] Linting: The top-level linter settings are deprecated in favour of `lint`.
```

- **In tests:** an entry of pytest's warnings summary.
- **At exit:** a warning, or an exception a finalizer raised ("Exception ignored in: ..."),
  printed when the interpreter exits, after pytest has removed its warning filters. Under
  Python's default filters ResourceWarning and DeprecationWarning would not print at all; in a
  test check they do, from the main process and every pytest-xdist worker. A resource still
  open at exit (a file, socket or database connection held by a module global or a cache) shows
  up here. Python 3.14 drops a warning that a finalizer raises late in shutdown.
- **Examples:** a warning in a passing example's stderr; examples run with every warning shown.
- **Tools:** a tool's own `warning:` line, about the tool or its configuration.

When the project's pytest `filterwarnings` has a bare `error` entry, which makes every warning an
error, a warning fails the check that printed it (`[✗]`), a tool's own line included; otherwise
the check passes with a warning and its log is kept in `.build/check/`. A check a tool itself
fails (an unformatted file, a type error) fails in either mode. Rows show paths relative to the
project and a file by its name; the kept log has the full message. `make check.ci` lists each
check's warnings under its passed or failed line, with the same policy; `make check.raw` collects
none and fails on none, and shows them only as the tools print them. Warnings in interpreters a
test starts belong to that test and are not collected.

A warning at exit comes after the last test, so it names no test. Narrow it down with `-k` in a
pytest run that loads the plugin (the `make test.*` targets do not), until the line is gone:

```bash
PYTHONPATH=<appinfra scripts>/check_pytest python -m pytest tests/ -p pytest_exit_warnings -k <expression>
```

Interrupting `make check` (Ctrl-C, `TERM`, a closed terminal), or a fail-fast stop, kills every
process it started at once: pytest and its workers, the tools and the examples runner.

## Handling Empty Test Directories

The framework handles pytest exit code 5 (no tests collected) gracefully. Running `make test.unit`
on a project without unit tests will succeed silently rather than failing.

This allows downstream projects to include the full test framework even if they don't have all
test categories implemented yet.

## Troubleshooting

### Variable Not Taking Effect

**Cause:** Setting variable after include.

```makefile
# Wrong - too late
include $(APPINFRA_SCRIPTS)/make/Makefile.all
APPINFRA_DEV_PKG_NAME ?= myproject

# Correct - before include
APPINFRA_DEV_PKG_NAME ?= myproject
include $(APPINFRA_SCRIPTS)/make/Makefile.all
```

### Include Order Errors

**Cause:** Including modules before their dependencies.

```makefile
# Wrong - dev requires env and utils
include $(APPINFRA_SCRIPTS)/make/Makefile.dev
include $(APPINFRA_SCRIPTS)/make/Makefile.env

# Correct - use Makefile.all or follow documented order
include $(APPINFRA_SCRIPTS)/make/Makefile.all
```

### check.sh Uses Wrong Package Name

**Cause:** Running check.sh directly instead of via Make.

**Solution:** Always use `make check`, which exports the correct variables.

## Example: Complete Integration

```
myproject/
├── Makefile
├── pyproject.toml      # includes appinfra as dependency
├── myproject/
│   └── __init__.py
└── tests/
    └── test_example.py
```

```makefile
# Makefile
ifeq ($(origin APPINFRA_SCRIPTS),undefined)
APPINFRA_SCRIPTS := $(shell appinfra scripts-path)
endif
APPINFRA_DEV_PKG_NAME ?= myproject
APPINFRA_DISABLE_GROUPS ?= pg.

include $(APPINFRA_SCRIPTS)/make/Makefile.all

##@ Application

run:  ## Run the application
	@$(PYTHON) -m myproject
```

pyproject.toml:
```toml
[project]
name = "myproject"
dependencies = [
    "appinfra",
]
```

## See Also

- [Makefile Customization Guide](makefile-customization.md) - Detailed variable reference
- [Test Naming Standards](test-naming-standards.md) - Test organization
