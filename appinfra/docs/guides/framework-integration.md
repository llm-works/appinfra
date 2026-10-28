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
infra := $(shell appinfra scripts-path)

# Configure your project
APPINFRA_DEV_PKG_NAME := myproject

# Include framework
include $(infra)/make/Makefile.all
```

This is the recommended approach because:
- No submodule management overhead
- Version controlled via `requirements.txt` or `pyproject.toml`
- Works with standard Python packaging workflows

### Alternative: Git Submodule

Submodules are supported but **should rarely be needed**. Use only if you need to modify the
framework itself or work offline without pip access.

```bash
git submodule add <repo-url> submodules/infra
```

```makefile
# Makefile - using submodule
infra := submodules/infra

APPINFRA_DEV_PKG_NAME := myproject
include $(infra)/scripts/make/Makefile.all
```

Note: With submodules, the path is `$(infra)/scripts/make/` vs `$(infra)/make/` with pip install.

## Quick Start

```makefile
# Recommended setup (pip install)
infra := $(shell appinfra scripts-path)

# Configure your project
APPINFRA_DEV_PKG_NAME := myproject

# Include framework (config must be first)
include $(infra)/make/Makefile.config
include $(infra)/make/Makefile.env
include $(infra)/make/Makefile.help
include $(infra)/make/Makefile.utils
include $(infra)/make/Makefile.dev
include $(infra)/make/Makefile.install  # Optional: only if building a package
include $(infra)/make/Makefile.pytest
include $(infra)/make/Makefile.clean
```

## Include Order

**Critical:** Include order matters. Always follow this sequence:

```makefile
# 1. REQUIRED FIRST - Handles config loading and deprecation
include $(infra)/make/Makefile.config

# 2. Core modules (order matters)
include $(infra)/make/Makefile.env      # Python detection
include $(infra)/make/Makefile.help     # Help system
include $(infra)/make/Makefile.utils    # Utilities (areyousure, etc.)

# 3. Feature modules (order flexible)
include $(infra)/make/Makefile.dev      # Requires: env, utils
include $(infra)/make/Makefile.install  # Optional: only if building a package
include $(infra)/make/Makefile.pytest   # Requires: env
include $(infra)/make/Makefile.docs     # Requires: env
include $(infra)/make/Makefile.pg       # Requires: env, utils
include $(infra)/make/Makefile.clean    # Requires: utils
```

Or use `Makefile.all` to include everything in the correct order:

```makefile
include $(infra)/make/Makefile.all
```

## Variable Precedence

Variables are resolved in this order (highest to lowest priority):

1. **Environment variables** - `APPINFRA_DEV_PKG_NAME=foo make test`
2. **Makefile variables before include** - `APPINFRA_DEV_PKG_NAME := foo`
3. **Makefile.local** - Optional overrides file (not committed)
4. **Framework defaults** - Defined in `Makefile.config`

### Example: Setting Package Name

```makefile
# In Makefile (before include)
APPINFRA_DEV_PKG_NAME := myproject
include $(infra)/make/Makefile.all

# Or via environment variable (for CI/testing)
# APPINFRA_DEV_PKG_NAME=myproject make test.coverage
```

## Common Configuration

### Minimal Configuration

```makefile
# Makefile
infra := $(shell appinfra scripts-path)
APPINFRA_DEV_PKG_NAME := myproject

include $(infra)/make/Makefile.all
```

### Full Configuration

```makefile
# Makefile
infra := $(shell appinfra scripts-path)
APPINFRA_DEV_PKG_NAME := myproject
APPINFRA_DEV_CQ_STRICT := true
APPINFRA_PYTEST_TESTS_DIR := tests
APPINFRA_DOCS_CONFIG_FILE := mkdocs.yaml

# Hide unused features
APPINFRA_DISABLE_GROUPS := pg.

include $(infra)/make/Makefile.all
```

## Extending Targets

Use double-colon rules (`::`) to extend framework targets:

```makefile
include $(infra)/make/Makefile.all

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
make check
make check.raw      # For CI logs
make check.summary  # Summaries only

# Incorrect - will use fallback defaults (APPINFRA_DEV_PKG_NAME=appinfra)
./scripts/check.sh
```

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
include $(infra)/make/Makefile.all
APPINFRA_DEV_PKG_NAME := myproject

# Correct - before include
APPINFRA_DEV_PKG_NAME := myproject
include $(infra)/make/Makefile.all
```

### Include Order Errors

**Cause:** Including modules before their dependencies.

```makefile
# Wrong - dev requires env and utils
include $(infra)/make/Makefile.dev
include $(infra)/make/Makefile.env

# Correct - use Makefile.all or follow documented order
include $(infra)/make/Makefile.all
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
infra := $(shell appinfra scripts-path)
APPINFRA_DEV_PKG_NAME := myproject
APPINFRA_DISABLE_GROUPS := pg.

include $(infra)/make/Makefile.all

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
