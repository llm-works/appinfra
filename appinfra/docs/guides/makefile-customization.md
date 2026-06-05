---
title: Customizing Framework Makefiles
keywords:
  - makefile
  - make targets
  - extend
  - override
  - customize
  - INFRA_DEV_
  - double-colon
  - downstream
aliases:
  - makefile-extend
  - make-customize
---

# Customizing Framework Makefiles

The infra framework is designed to be extended by downstream applications. This guide explains how
to customize and extend framework targets without modifying framework files.

## Configuration Protocol

The framework uses a consistent naming convention for configuration variables:
`INFRA_<MODULE>_<VAR>`.

### Quick Start

```makefile
infra := $(shell appinfra scripts-path)

# Set your configuration
INFRA_DEV_PKG_NAME := myproject
INFRA_DEV_CQ_STRICT := true

# Include what you need (selective inclusion)
include $(infra)/make/Makefile.config
include $(infra)/make/Makefile.env
include $(infra)/make/Makefile.help
include $(infra)/make/Makefile.utils
include $(infra)/make/Makefile.dev
include $(infra)/make/Makefile.install  # Optional: only if building a package
include $(infra)/make/Makefile.pytest
include $(infra)/make/Makefile.clean
```

Or include everything:

```makefile
infra := $(shell appinfra scripts-path)
INFRA_DEV_PKG_NAME := myproject
include $(infra)/make/Makefile.all
```

### Configuration Overrides

For local development overrides (not committed to git), use `Makefile.local`:

```makefile
# Makefile.local - Local overrides (gitignored)
INFRA_DEV_CQ_STRICT := false
INFRA_PYTEST_ARGS := -x --pdb
```

### Configuration Precedence

1. Environment variables (highest)
2. Makefile variables set before include
3. Makefile.local (optional overrides)
4. Defaults in Makefile.config

**Important:** This precedence only works for variables using `?=` (conditional assignment). The
framework uses `?=` for all configuration variables, so precedence works as expected.

**Examples:**

```makefile
# Example 1: Environment variable (highest priority)
# $ INFRA_DEV_PKG_NAME=myapp make test.coverage
# Uses myapp regardless of Makefile settings

# Example 2: Makefile variable before include
INFRA_DEV_PKG_NAME := myproject
include $(infra)/make/Makefile.all

# Example 3: Fallback to default
# If nothing sets INFRA_DEV_PKG_NAME, uses "appinfra"
```

**Note on include order:** Always include `Makefile.config` first. It sets up framework defaults
and configuration loading.

### Target Filtering

Hide specific targets from `make help` and block their execution:

```makefile
# Hide specific targets
INFRA_DISABLE_TARGETS := pg.clean pg.clean.internal cicd.erase cicd.erase.internal

# Hide all targets with a prefix
INFRA_DISABLE_GROUPS := pg. cicd.
```

`INFRA_DISABLE_TARGETS` matches names exactly. Confirm-prompt wrappers like `pg.clean` and their
no-prompt `.internal` siblings are independent targets — list both to block a destructive op
entirely. Alternatively, use `INFRA_DISABLE_GROUPS` to cover an entire prefix.

Usage:

```bash
# Hide all postgres targets for this run
INFRA_DISABLE_GROUPS="pg." make help
```

## Health Check

### Project Health Check

Run `make doctor` to diagnose your project setup:

```bash
$ make doctor
Project Health Check
========================================

[ok] Python version: 3.12.3 (>= 3.11 required)
[ok] ruff: 0.8.0
[ok] pytest: 9.0.1
[ok] mypy: 1.13.0
[ok] Package name: 'myproject/' is valid Python package
[ok] Tests directory: 15 test files found

All checks passed!
```

The doctor checks:
- Python version (>= 3.11 required)
- Required tools installed (ruff, pytest, mypy)
- `INFRA_DEV_PKG_NAME` points to a valid Python package
- `tests/` directory exists with test files

Use `--json` for machine-readable output:

```bash
make doctor ARGS="--json"
```

### Dry-Run Mode

Preview what commands would run without executing them:

```bash
$ INFRA_DRY_RUN=1 make fmt
[DRY RUN] Would run: ruff format .

$ INFRA_DRY_RUN=1 make lint
[DRY RUN] Would run: ruff check .

$ INFRA_DRY_RUN=1 make type
[DRY RUN] Would run: mypy myproject/
```

Supported targets: `fmt`, `lint`, `type`, `cq`

### Shell Completion

Enable tab completion for the `appinfra` CLI:

```bash
# Bash - add to ~/.bashrc
eval "$(appinfra completion bash)"

# Zsh - add to ~/.zshrc
eval "$(appinfra completion zsh)"

# Show installation instructions
appinfra completion bash --install
```

### Viewing Current Configuration

Use `make config` to see all current configuration values:

```bash
$ make config
Infra Framework Configuration
==============================

Config file: (none found)

Target Filtering:
  INFRA_DISABLE_TARGETS: (none)
  INFRA_DISABLE_GROUPS:  (none)

Development (DEV):
  INFRA_DEV_PKG_NAME:     myproject
  INFRA_DEV_CQ_STRICT:    true
...
```

## Extending Targets with Double-Colon Rules

The framework uses double-colon rules (`::`) for extensible targets, allowing you to add your own
steps to framework targets. Multiple definitions of the same target will all execute when the target
is run.

### Example: Adding Custom Cleanup

```makefile
# Your app's Makefile
include $(infra)/make/Makefile.clean

clean::
	@echo "Cleaning app-specific files..."
	rm -rf .app-cache/
	docker-compose down -v
```

When you run `make clean`, both the framework's cleanup steps and your app-specific steps will
execute.

### Example: Adding Custom Tests

```makefile
# Your app's Makefile
include $(infra)/make/Makefile.pytest

test.integration::
	@echo "Running app-specific integration tests..."
	./scripts/test-api-endpoints.sh
```

When you run `make test.integration`, both framework integration tests and your custom tests will
run.

### Example: Adding Custom Linting

```makefile
# Your app's Makefile
include $(infra)/make/Makefile.dev

lint::
	@echo "Running app-specific linting..."
	./scripts/check-api-schema.sh
	./scripts/validate-config.sh
```

## Overriding Targets Completely

Some targets can be completely replaced by your project using `INFRA_DEV_SKIP_TARGETS`. This is
useful when a project needs fundamentally different behavior (e.g., different mypy flags for
different directories).

**Supported targets:**
- Code quality: `fmt`, `lint`, `type`, `cq`
- Testing: `test.unit`, `test.integration`, `test.e2e`, `test.perf`, `test.security`

> **Note:** Skipping a target also skips its helper/verbose variants:
> - `fmt` → also skips `fmt.check`
> - `lint` → also skips `lint.fix`, `lint.unsafe`
> - `cq` → also skips `cq.strict`
> - `test.*` → also skips `test.*.v` (verbose variant)

### Example: Custom Type Checking

Projects with mixed dependencies (e.g., core package uses SQLAlchemy, examples import torch) may
need different mypy configurations per directory:

```makefile
# Skip the built-in type target
INFRA_DEV_SKIP_TARGETS := type

include $(infra)/make/Makefile.dev

# Define your own type target
type::
	@echo "* running type checker..."
	@$(PYTHON) -m mypy $(INFRA_DEV_PKG_NAME)/ --exclude 'examples/' --strict
	@$(PYTHON) -m mypy examples/ --follow-imports=skip --ignore-missing-imports
	@echo "* type checking done"
```

### Example: Multiple Overrides

```makefile
# Skip multiple targets
INFRA_DEV_SKIP_TARGETS := type lint

include $(infra)/make/Makefile.dev

type::
	@echo "* custom type checking..."
	# ... your implementation

lint::
	@echo "* custom linting..."
	# ... your implementation
```

### Example: Custom Test Configuration

Projects with special test requirements (e.g., GPU tests that OOM when run in parallel) can skip
framework test targets and provide their own:

```makefile
# Skip the built-in test.e2e target
INFRA_DEV_SKIP_TARGETS := test.e2e

include $(infra)/make/Makefile.pytest

# Define custom e2e target with sequential execution (-n 0)
test.e2e:: ## runs e2e tests (sequential for GPU)
	@echo "* running e2e tests (sequential)..."
	@$(call run_pytest,tests/ -m e2e -n 0 -qq --tb=short)
	@echo "* e2e tests done"

test.e2e.v:: ## runs e2e tests (verbose, sequential)
	@echo "* running e2e tests (verbose, sequential)..."
	@$(call run_pytest,tests/ -m e2e -n 0 -v)
	@echo "* e2e tests done"
```

> **Note:** `INFRA_DEV_SKIP_TARGETS` must be set **before** the include statement.

## Overriding Variables

All framework variables use `?=` (conditional assignment), making them easy to override:

### Command Line Override

```bash
# Override PYTHON for a single command
make test PYTHON=~/.venv/bin/python

# Override multiple variables
make test PYTHON=python3.12 PYTEST_ARGS="-v -x --pdb"
```

### Makefile Override

```makefile
# Your app's Makefile
infra := $(shell appinfra scripts-path)

# Override before including framework
PYTHON = /usr/local/bin/python3.12

# Include framework
include $(infra)/make/Makefile.pytest

# Now all framework targets use your Python version
```

## Available Extension Points

### Extensible Targets (Double-Colon)

These targets can be extended by defining them again in your Makefile:

**Cleanup:**
- `clean::` - Add cleanup steps

**Testing:**
- `test.unit::` - Add unit tests
- `test.integration::` - Add integration tests
- `test.e2e::` - Add end-to-end tests
- `test.perf::` - Add performance tests
- `test.security::` - Add security tests
- `test.all::` - Extends all test types
- `test::` - Extends all tests
- All verbose variants (`test.*.v::`)
- All coverage targets (`test.coverage::`, etc.)

**Code Quality:**
- `fmt::` - Add formatting steps
- `lint::` - Add linting steps
- `type::` - Add type checking steps
- `check::` - Add quality checks
- `check.quick::` - Add quick checks

**Health Check:**
- `doctor::` - Add project health checks
- `init::` - Add initialization steps

**Documentation:**
- `docs.serve::` - Extend doc server
- `docs.build::` - Add doc build steps
- `docs.check::` - Add doc validation
- `docs.deploy::` - Add deployment steps

**Database:**
- `pg.clean::` - Add steps to "drop databases (with confirmation)". Runs `areyousure`
  upfront; chaining destructive ops in here re-prompts.
- `pg.clean.internal::` - The no-confirmation entry point. Use this when composing
  database cleanup into a downstream higher-level target so the user is prompted
  once (at the top level), not once per layer. Mirrors `pg.server.clean.internal::`
  and `cicd.erase.internal::`.

> **Non-interactive use:** Set `INFRA_NO_CONFIRM=1` to bypass all `areyousure` prompts
> (intended for CI and scripts). See
> [Framework Environment Variables](environment-variables.md#framework-environment-variables).

### Non-Extensible Targets (Single-Colon)

These targets should be used as-is, not extended:

- `help` - Framework controls help generation
- `pg.server.*` - Server control operations (start/stop/reboot)
- `pg.info`, `pg.server.repl.info` - Information display
- `pg`, `pgr` - Database connections
- `install` - Package installation

### Overridable Variables

All configuration variables follow the `INFRA_<MODULE>_<VAR>` naming convention.

**Environment (ENV):**

| Variable | Default | Description |
|----------|---------|-------------|
| `INFRA_ENV_PYTHON` | `~/.venv/bin/python` | Python interpreter path |

**Config:**

| Variable | Default | Description |
|----------|---------|-------------|
| `ETC_DIR` | `$(CURDIR)/etc` | Config directory path |
| `INFRA_DEFAULT_CONFIG_FILE` | `infra.yaml` | Default config filename (contains all sections if specific files not set) |

**Development (DEV):**

| Variable | Default | Description |
|----------|---------|-------------|
| `INFRA_DEV_PKG_NAME` | `appinfra` | Package name for install, type, coverage |
| `INFRA_DEV_CQ_STRICT` | `false` | Code quality: `true`=30-line, `false`=50-line |
| `INFRA_DEV_DOCSTRING_THRESHOLD` | `80` | Docstring coverage threshold for `make check` (0 to disable) |
| `INFRA_DEV_PROJECT_ROOT` | `$(CURDIR)` | Project root for check.sh |
| `INFRA_DEV_INSTALL_EXTRAS` | (empty) | Optional extras for install (e.g., `ui,fastapi`) |
| `INFRA_DEV_MYPY_FLAGS` | (empty) | Extra mypy flags (e.g., `--follow-imports=skip` for large deps) |
| `INFRA_DEV_SKIP_TARGETS` | (empty) | Targets to skip so project can override (e.g., `type`, `test.e2e`) |
| `INFRA_DRY_RUN` | `0` | Set to `1` to preview commands without executing |

**Testing (PYTEST):**

| Variable | Default | Description |
|----------|---------|-------------|
| `INFRA_PYTEST_COVERAGE_PKG` | `$(INFRA_DEV_PKG_NAME)` | Package to measure coverage |
| `INFRA_PYTEST_COVERAGE_THRESHOLD` | `80` | Coverage threshold for `make check` (0 to disable) |
| `INFRA_PYTEST_TESTS_DIR` | `tests` | Tests directory |
| `INFRA_PYTEST_ARGS` | (empty) | Additional pytest arguments |

**Documentation (DOCS):**

| Variable | Default | Description |
|----------|---------|-------------|
| `INFRA_DOCS_CONFIG_FILE` | (empty) | MkDocs config filename (empty = use `INFRA_DEFAULT_CONFIG_FILE`) |
| `INFRA_DOCS_OUTPUT_DIR` | `.site` | Documentation build output |

**PostgreSQL (PG):**

| Variable | Default | Description |
|----------|---------|-------------|
| `INFRA_PG_CONFIG_FILE` | (empty) | PostgreSQL config filename (empty = use `INFRA_DEFAULT_CONFIG_FILE`) |
| `INFRA_PG_CONFIG_KEY` | `pgserver` | Config section key |
| `INFRA_PG_DATABASES` | (empty) | Space-separated database list |
| `INFRA_PG_HOST` | `127.0.0.1` | PostgreSQL host |
| `INFRA_PG_USER` | `postgres` | PostgreSQL user |

**CI/CD (CICD):**

| Variable | Default | Description |
|----------|---------|-------------|
| `INFRA_CICD_PYTHON_VERSION` | `3.12` | Default Python version |

**Cleanup (CLEAN):**

| Variable | Default | Description |
|----------|---------|-------------|
| `INFRA_CLEAN_PRESERVE` | `.data .logs .GRADING.md` | Files/dirs to preserve |

**Target Filtering:**

| Variable | Default | Description |
|----------|---------|-------------|
| `INFRA_DISABLE_TARGETS` | (empty) | Space-separated targets to hide |
| `INFRA_DISABLE_GROUPS` | (empty) | Space-separated prefixes to hide (e.g., `pg.`) |

**Note:** When scaffolding a project with `--makefile-style=framework`, `INFRA_DEV_PKG_NAME` is
automatically set to your project name. `INFRA_PYTEST_COVERAGE_PKG` inherits from it, so you
typically only need to set `INFRA_DEV_PKG_NAME`.

## Complete Example

Here's a complete example of an app extending the framework:

```makefile
# Example app Makefile

# Configuration (before includes)
infra := $(shell appinfra scripts-path)
INFRA_DEV_PKG_NAME := myapp
INFRA_DEV_CQ_STRICT := true
INFRA_DISABLE_TARGETS := pg.clean pg.clean.internal  # Hide destructive targets (wrapper + internal)

# Include framework Makefiles (selectively)
include $(infra)/make/Makefile.config
include $(infra)/make/Makefile.env
include $(infra)/make/Makefile.help
include $(infra)/make/Makefile.utils
include $(infra)/make/Makefile.dev
include $(infra)/make/Makefile.install
include $(infra)/make/Makefile.pytest
include $(infra)/make/Makefile.docs
include $(infra)/make/Makefile.pg
include $(infra)/make/Makefile.clean

##@ App-Specific

# Extend framework's clean target
clean::
	@echo "* app cleanup..."
	@rm -rf .app-cache/ .tmp/
	@docker-compose -f docker-compose.app.yaml down -v

# Extend framework's lint target
lint::
	@echo "* app-specific linting..."
	@./scripts/check-api-schema.sh

# Extend framework's test targets
test.integration::
	@echo "* running app API tests..."
	@./scripts/test-api.sh

# Add completely new targets
.PHONY: deploy
deploy: test  ## Deploy application to production
	@echo "* deploying..."
	@./scripts/deploy.sh

.PHONY: db.migrate
db.migrate:  ## Run database migrations
	@$(PYTHON) -m alembic upgrade head

.PHONY: dev.up
dev.up:  ## Start development environment
	@docker-compose -f docker-compose.dev.yaml up -d
	@make pg.server.up
```

## Using Test Targets in Your Project

### Basic Usage

When you include `Makefile.pytest`, the test targets use **relative paths** that automatically point
to your project's `tests/` directory:

```makefile
# Your project's Makefile
infra := $(shell appinfra scripts-path)
PYTHON = ~/.venv/bin/python
include $(infra)/make/Makefile.pytest

# Now you can run:
# make test.unit        - runs tests in YOUR_PROJECT/tests/
# make test.integration - runs integration tests
# make test.all         - runs all your tests
```

The tests run in your project's `tests/` directory, not infra's.

### Configuring Coverage

By default, coverage targets measure coverage for the package specified by `INFRA_DEV_PKG_NAME`.
Override this for your project:

```makefile
# Your project's Makefile
infra := $(shell appinfra scripts-path)
INFRA_DEV_PKG_NAME := myproject
# INFRA_PYTEST_COVERAGE_PKG inherits from INFRA_DEV_PKG_NAME automatically

include $(infra)/make/Makefile.config
include $(infra)/make/Makefile.env
include $(infra)/make/Makefile.pytest

# Now make test.coverage measures YOUR project's coverage
```

### Testing with Submodules

If you use infra as a submodule (prefer pip install for most cases), you can test both your
code and the submodule:

```makefile
# Your project's Makefile (submodule approach)
infra := submodules/infra
INFRA_DEV_PKG_NAME := myproject

include $(infra)/scripts/make/Makefile.config
include $(infra)/scripts/make/Makefile.env
include $(infra)/scripts/make/Makefile.pytest

# Test the infra submodule
.PHONY: test.infra
test.infra:  ## Test the infra submodule
	@echo "Testing infra submodule..."
	$(MAKE) -C $(infra) test.all
```

Note: With pip install, there's no submodule to test - appinfra is just a dependency.

### How It Works

**Relative paths resolve to the including project:**
- `tests/` → `YOUR_PROJECT/tests/` (not `infra/tests/`)
- `$(PYTHON)` → Your Python interpreter
- `$(INFRA_PYTEST_COVERAGE_PKG)` → Your package name (if overridden)

**This ensures:**
- ✅ Your tests test your code
- ✅ Infra's tests test infra (run with `make -C infra test.all`)
- ✅ Clean separation of concerns
- ✅ No configuration needed for basic usage

### Example: Framework Using pip-installed appinfra

```
MyFramework/
  ├── Makefile
  ├── pyproject.toml       ← includes appinfra dependency
  ├── myframework/         ← Your code
  └── tests/
      ├── unit/            ← Your unit tests
      └── integration/     ← Your integration tests
```

```makefile
# MyFramework/Makefile
infra := $(shell appinfra scripts-path)
INFRA_DEV_PKG_NAME := myframework

include $(infra)/make/Makefile.config
include $(infra)/make/Makefile.env
include $(infra)/make/Makefile.help
include $(infra)/make/Makefile.utils
include $(infra)/make/Makefile.pytest
include $(infra)/make/Makefile.clean

# Extend test targets if needed
test.unit::
	@echo "Running framework-specific validation..."
	./scripts/validate-framework.sh
```

When you run:
- `make test.unit` → Runs tests in `MyFramework/tests/` ✓
- `make test.coverage` → Measures coverage for `myframework` package ✓

## Best Practices

### 1. Selective Inclusion

Only include the framework Makefiles you actually need:

```makefile
# Good - include only what you use
infra := $(shell appinfra scripts-path)
include $(infra)/make/Makefile.config  # Always include first
include $(infra)/make/Makefile.env
include $(infra)/make/Makefile.pytest
include $(infra)/make/Makefile.clean

# Alternative - include everything
include $(infra)/make/Makefile.all
```

### 2. Clear Section Markers

Use `##@` comments to organize your custom targets:

```makefile
##@ App-Specific Targets

deploy: test  ## Deploy to production
	./scripts/deploy.sh

##@ Development

dev.up:  ## Start dev environment
	docker-compose up -d
```

### 3. Self-Documentation

Add `##` comments to make targets discoverable via `make help`:

```makefile
deploy: test  ## Deploy application to production (requires auth)
	./scripts/deploy.sh
```

### 4. Respect Dependencies

When extending targets with dependencies, maintain them:

```makefile
# Framework has: clean: areyousure
# Your extension should also require confirmation if destructive
clean::
	@echo "Destroying app data..."
	rm -rf /critical/data
```

## How Double-Colon Rules Work

When you define a target with `::` instead of `:`, Make allows multiple independent definitions:

```makefile
# First definition (framework)
test::
	pytest tests/unit

# Second definition (your app)
test::
	./scripts/custom-tests.sh

# When you run 'make test', BOTH execute:
# 1. pytest tests/unit
# 2. ./scripts/custom-tests.sh
```

**Important:** All definitions must use `::`. Mixing `:` and `::` for the same target will cause
errors.

## Troubleshooting

### Error: "warning: overriding recipe for target 'clean'"

**Cause:** Mixing single-colon and double-colon rules.

**Solution:** Ensure both framework and your Makefile use `::`:

```makefile
# Wrong - framework uses :: but you used :
clean:  # ERROR

# Correct - both use ::
clean::  # OK
```

### Extension Not Running

**Cause:** Framework Makefile not included, or included after your definitions.

**Solution:** Include framework Makefiles before your custom targets:

```makefile
# Correct order
infra := $(shell appinfra scripts-path)
include $(infra)/make/Makefile.clean  # Framework first

clean::  # Your extension second
	rm -rf .app-cache
```

### Variable Override Not Working

**Cause:** Setting variable after including framework.

**Solution:** Set variables before including:

```makefile
# Wrong
include $(infra)/make/Makefile.config
INFRA_DEV_PKG_NAME := myproject  # Too late

# Correct
INFRA_DEV_PKG_NAME := myproject  # Before include
include $(infra)/make/Makefile.config
```

## Using the Scaffold Tool

The infra framework includes a scaffold tool that generates complete project structures with
pre-configured Makefiles. You can choose between two Makefile styles depending on your needs.

### Basic Scaffolding

```bash
# Generate project with standalone Makefile (default)
./cli/cli.py scaffold myproject

# Generate project with framework-based Makefile
./cli/cli.py scaffold myproject --makefile-style=framework

# Add database configuration
./cli/cli.py scaffold myproject --with-db

# Add HTTP server configuration
./cli/cli.py scaffold myproject --with-server

# Specify custom path
./cli/cli.py scaffold myproject --path=/custom/location
```

### Makefile Styles Comparison

#### Standalone Makefile (Default)

**When to use:**
- Simple projects that don't need advanced features
- Projects that may not have infra installed
- Learning or prototyping
- Projects that want full control over their build system

**Features:**
- Self-contained, no external dependencies
- Basic targets: `help`, `install`, `test`, `clean`, `fmt`, `lint`, `run`
- Uses standard `unittest` for testing
- Simple and easy to understand

**Example usage:**
```bash
./cli/cli.py scaffold simple-app
cd simple-app
make help      # See available targets
make setup   # Install dependencies
make test      # Run tests with unittest
```

#### Framework Makefile

**When to use:**
- Projects that use infra as a dependency
- Need advanced testing features (test categorization, coverage)
- Want extensibility via double-colon rules
- Building on top of infra framework

**Features:**
- Includes modular framework Makefiles
- Advanced pytest targets: `test.unit`, `test.integration`, `test.coverage`, etc.
- Automatic coverage configuration for your package
- Extensible with double-colon rules
- Auto-detects infra location

**Example usage:**
```bash
./cli/cli.py scaffold advanced-app --makefile-style=framework
cd advanced-app

make help              # See all framework targets
make test.unit         # Run unit tests with pytest
make test.coverage     # Generate coverage report for advanced-app
make fmt               # Format with ruff
```

### Infra Location Auto-Detection

When using `--makefile-style=framework`, the generated Makefile automatically detects the infra
framework location in this order:

1. **Manual override** (highest priority):
   ```makefile
   # Set at top of Makefile or via environment variable:
   INFRA_ROOT = /custom/path/to/infra
   ```

2. **Submodule location** (if exists):
   ```
   ./submodules/infra/
   ```

3. **Auto-detection via Python import**:
   ```bash
   # Works if appinfra is installed via pip
   python -c "import appinfra; ..."
   ```

4. **Error if not found**:
   ```
   Cannot locate infra. Set INFRA_ROOT=/path/to/infra at top of Makefile
   or install appinfra package
   ```

### Generated Project Structure

Both styles generate the same project structure:

```
myproject/
├── Makefile              # Standalone or framework-based
├── README.md             # Project documentation
├── pyproject.toml        # Python package configuration
├── .gitignore            # Git ignore patterns
├── etc/
│   └── infra.yaml       # Application configuration
├── myproject/
│   ├── __init__.py      # Package initialization
│   └── __main__.py      # Application entry point with ExampleTool
└── tests/
    ├── __init__.py
    └── test_example.py  # Example test
```

### Working with Scaffolded Projects

#### Standalone Projects

```bash
# Basic workflow
cd myproject
make setup           # Install with pip
make test              # Run unittest
make fmt               # Format with black
make lint              # Lint with ruff
make run               # Run the application
```

#### Framework Projects

```bash
# Advanced workflow
cd myproject

# Available targets
make test.unit         # Run unit tests
make test.integration  # Run integration tests
make test.coverage     # Coverage for myproject package
make test.all          # Run all tests
make fmt               # Format with ruff
make lint              # Lint with ruff
make check             # Run all quality checks
make run               # Run the application
```

### Extending Scaffolded Framework Makefiles

Since framework-based Makefiles use double-colon rules, you can extend them:

```makefile
# myproject/Makefile (generated with --makefile-style=framework)

# ... (auto-generated content above)

##@ Custom Targets

# Extend clean to remove app-specific files
clean::
	@echo "* removing app cache..."
	@rm -rf .app-cache/

# Extend tests with custom validation
test.unit::
	@echo "* running schema validation..."
	@./scripts/validate-schema.sh

# Add completely new targets
.PHONY: deploy
deploy: test.all  ## Deploy to production
	@./scripts/deploy.sh
```

### Migration: Standalone → Framework

If you start with a standalone Makefile and want to upgrade:

1. **Regenerate with framework style:**
   ```bash
   # Back up your current Makefile
   mv Makefile Makefile.old

   # Generate framework Makefile
   cd ..
   ./cli/cli.py scaffold myproject --makefile-style=framework

   # Merge any custom targets from Makefile.old
   ```

2. **Update test imports** (if using unittest → pytest):
   ```python
   # Old (unittest)
   import unittest
   class TestExample(unittest.TestCase):
       pass

   # New (pytest, optional)
   import pytest
   def test_example():
       pass
   ```

### Best Practices

1. **Choose the right style upfront** - Standalone for simple projects, framework for advanced needs
2. **Install appinfra package** - Enables auto-detection of INFRA_ROOT
3. **Document custom targets** - Add `##` comments for `make help` integration
4. **Keep framework Makefiles minimal** - Extend via `::` rather than modifying generated code

## See Also

- [Framework Integration Guide](framework-integration.md) - Integration methods and troubleshooting
- [Getting Started Guide](../getting-started.md)
- [Test Naming Standards](test-naming-standards.md)
- [PostgreSQL Test Helper](pg-test-helper.md)
- [Coverage Targets](coverage-targets.md)
