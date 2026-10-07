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
INFRA_DEV_PKG_NAME := myproject

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

INFRA_DEV_PKG_NAME := myproject
include $(infra)/scripts/make/Makefile.all
```

Note: With submodules, the path is `$(infra)/scripts/make/` vs `$(infra)/make/` with pip install.

## Quick Start

```makefile
# Recommended setup (pip install)
infra := $(shell appinfra scripts-path)

# Configure your project
INFRA_DEV_PKG_NAME := myproject

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

1. **Environment variables** - `INFRA_DEV_PKG_NAME=foo make test`
2. **Makefile variables before include** - `INFRA_DEV_PKG_NAME := foo`
3. **Makefile.local** - Optional overrides file (not committed)
4. **Framework defaults** - Defined in `Makefile.config`

### Example: Setting Package Name

```makefile
# In Makefile (before include)
INFRA_DEV_PKG_NAME := myproject
include $(infra)/make/Makefile.all

# Or via environment variable (for CI/testing)
# INFRA_DEV_PKG_NAME=myproject make test.coverage
```

## Common Configuration

### Minimal Configuration

```makefile
# Makefile
infra := $(shell appinfra scripts-path)
INFRA_DEV_PKG_NAME := myproject

include $(infra)/make/Makefile.all
```

### Full Configuration

```makefile
# Makefile
infra := $(shell appinfra scripts-path)
INFRA_DEV_PKG_NAME := myproject
INFRA_DEV_CQ_STRICT := true
INFRA_PYTEST_TESTS_DIR := tests
INFRA_DOCS_CONFIG_FILE := mkdocs.yaml

# Hide unused features
INFRA_DISABLE_GROUPS := pg.

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

# Incorrect - will use fallback defaults (INFRA_DEV_PKG_NAME=appinfra)
./scripts/check.sh
```

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
INFRA_DEV_PKG_NAME := myproject

# Correct - before include
INFRA_DEV_PKG_NAME := myproject
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
INFRA_DEV_PKG_NAME := myproject
INFRA_DISABLE_GROUPS := pg.

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
