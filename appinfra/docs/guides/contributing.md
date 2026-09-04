---
title: Contributing Guide
keywords:
  - check-funcs
  - funcsize
  - function size
  - line limit
  - cq cf
  - code quality
  - exempt
  - ignore
  - max-lines
  - development setup
aliases:
  - developer-guide
  - dev-setup
---

# Contributing Guide

Guide for developers who want to contribute to appinfra or use it in development mode.

## Development Setup

Clone the repository and set up the development environment:

```bash
git clone https://github.com/llm-works/appinfra.git
cd appinfra

# Install dependencies
make setup

# Run tests
make test.unit
make test.integration
```

## Test Suite

```bash
make test.unit          # Fast unit tests
make test.integration   # Integration tests (requires PostgreSQL)
make test.perf          # Performance benchmarks
make test.security      # Security tests
make test.e2e           # End-to-end tests
make test.all           # All tests

make test.coverage      # Coverage report
make test.coverage.html # HTML coverage report
```

## Code Quality

```bash
make fmt                # Format code with ruff
make lint               # Run linter
make check              # Run all checks (fmt, lint, type check, tests)
```

### Function Size Checker

The framework includes a function size checker under the `cq` (code-quality) command:

```bash
# Check function sizes (default threshold: 30 lines)
appinfra cq cf

# Custom threshold
appinfra cq cf --limit=50

# Check specific paths
appinfra cq cf appinfra/db appinfra/log

# Different output formats
appinfra cq cf --format=summary
appinfra cq cf --format=simple
appinfra cq cf --format=json

# Strict mode for CI (exits 1 if violations found)
appinfra cq cf --strict

# Include test files
appinfra cq cf --include-tests

# List available code-quality subcommands
appinfra cq --help
```

#### Function Line Limit Exceptions

Some functions legitimately need more lines than the default 30-line limit (e.g., large parameter
signatures, constructor calls with many field mappings). Use comment directives to exempt specific
functions:

```python
# Allow up to 40 lines for this function
def from_config(cls, path: str) -> Config:  # cq: max-lines=40
    ...

# Allow up to 50 lines for async generators with many params
async def generate_stream(self, prompt: str, ...):  # cq: max-lines=50
    ...

# Completely exempt from line limit checking
def legacy_parser():  # cq: exempt
    ...
```

**Directive syntax:**
- `# cq: max-lines=N` - Allow function up to N lines (still enforced, just higher limit)
- `# cq: exempt` - Skip line checking entirely for this function

**Properties:**
- Zero runtime impact (just a comment)
- Works with all function types: `def`, `async def`, methods, classmethods, staticmethods
- Case-insensitive (`# CQ: MAX-LINES=40` works)
- Exempt functions are reported separately in output (e.g., "2 functions exempt from line limit")
- Grep-able for auditing: `grep "# cq:" **/*.py`

**Future extensions**: Additional checks can be added as subcommands:
- `cq check-complexity` - Cyclomatic complexity analysis
- `cq check-imports` - Import order and organization
- `cq check-style` - Style guideline enforcement

## Framework Extensibility

The framework Makefiles are designed to be extended by downstream applications using double-colon
rules and variable overrides.

### Extending Targets

```makefile
# Your app's Makefile
include path/to/infra/scripts/make/Makefile.clean

# Add app-specific cleanup
clean::
	@echo "Cleaning app-specific files..."
	rm -rf .app-cache/
	docker-compose down -v
```

### Overriding Variables

```makefile
# Override before including framework
PYTHON = /usr/local/bin/python3.12

include path/to/infra/Makefile
```

See [Makefile Customization Guide](makefile-customization.md) for complete documentation on
extending framework targets, overriding variables, and available extension points.

## PostgreSQL Setup

Integration tests require PostgreSQL. Use Docker (or Podman) for local
development. Two entry points are equivalent — pick by installation shape:

- Repo cloners: `make pg.server.up` (reads `etc/infra.yaml` via Makefile).
- Wheel installers: `appinfra pg up` (reads the packaged base or a config
  named via `--config` / `--etc-dir`).

Both project the same `_INFRA_PG_*` wire protocol into
`appinfra/scripts/pg.sh`, so container state is identical either way.

### Single Instance Mode (Default)

```bash
make pg.server.up       # or: appinfra pg up
make pg.server.down     # or: appinfra pg down
make pg.server.reboot   # or: appinfra pg reboot
make pg.server.logs     # or: appinfra pg logs
make pg                 # or: appinfra pg psql
make pg.info            # or: appinfra pg info
make pg.info.short      # or: appinfra pg status
```

### Replication Mode

Start primary + standby (read-only replica) servers:

```bash
make pg.server.up.repl  # or: appinfra pg up --repl
make pg                 # or: appinfra pg psql
make pg.standby         # or: appinfra pg psql --target standby
make pg.info            # or: appinfra pg info
make pg.info.short      # or: appinfra pg status
make pg.server.down     # or: appinfra pg down
```

**Configuration** (in `etc/infra.yaml`):
- Single instance uses `unittest` database config
- Replication mode adds `unittest_reader` config pointing to standby port
- Standby server automatically replicates from primary using pg_basebackup

## Directory Structure

```
.
├── appinfra/          # Main library code
│   ├── app/           # Application framework
│   ├── cli/           # CLI tools
│   ├── db/            # Database layer
│   ├── log/           # Logging system
│   ├── net/           # Network components
│   └── time/          # Time utilities
├── tests/             # Test suite
│   ├── cli/           # CLI tool tests
│   ├── infra/         # Core library tests
│   ├── e2e/           # End-to-end tests
│   ├── integration/   # Integration tests
│   ├── performance/   # Benchmarks
│   ├── property/      # Property-based tests
│   └── security/      # Security tests
├── docs/              # Documentation
├── examples/          # Example code
├── etc/               # Configuration
└── scripts/           # Build scripts
```

## Architecture

### Design Patterns

- **Builder pattern** - LoggingBuilder, AppBuilder for fluent configuration
- **Factory pattern** - LoggerFactory, SessionFactory for object creation
- **Registry pattern** - ToolRegistry, CallbackRegistry for extensibility
- **Protocol/Interface** - DictInterface, ToolProtocol for type safety
- **Configuration-driven** - YAML configs with environment overrides

### Key Principles

- Modular architecture with clear separation of concerns
- Production-ready error handling and resource management
- Performance-conscious (LRU caching, connection pooling, monotonic timing)
- Extensible through builder patterns and plugin system

## Tech Stack

- **Language**: Python 3.11+ (tested with 3.12.3)
- **Database**: PostgreSQL 18
- **Testing**: pytest, hypothesis, coverage
- **Formatting**: ruff
- **Type Checking**: mypy
- **Infrastructure**: Docker, Docker Compose

## Project Stats

- ~9,600 lines of production code
- 100+ implementation files
- 90+ test files
- 95% test coverage
- 5 test categories (unit, integration, performance, security, e2e)

## Security Testing

The framework includes comprehensive security tests covering common attack vectors:

```bash
make test.security       # Run all security tests
make test.security.v     # Verbose security test output
```

### Security Test Coverage

**Injection Attacks:**
- YAML code execution (`!!python/object` tags)
- SQL injection prevention (parameterized queries)
- Shell injection via tool names and aliases
- Environment variable injection
- Log injection (ANSI codes, fake entries)

**Path Traversal Attacks:**
- YAML include path traversal (`../../../etc/passwd`)
- Symlink-based path escapes
- Config path resolution attacks
- Log file path traversal

**ReDoS (Regular Expression Denial of Service):**
- Nested quantifier detection (`(.+)+`, `(.*)*`)
- Pattern complexity validation
- Timeout enforcement on Unix systems
- Pattern length limits

**Resource Exhaustion:**
- Config file size limits (10MB)
- YAML include depth bombs
- YAML entity expansion (billion laughs attack)
- Tool count limits

**Input Validation:**
- Tool name format validation
- Null byte injection prevention
- Type coercion safety
- Credential exposure in logs

**End-to-End Attack Chains:**
- Multi-stage attacks (traversal → code execution)
- Defense-in-depth validation

**Test Statistics:**
- 161 security tests (32 test functions)
- Module-based organization matching codebase structure
- Centralized attack payload library
- Platform-aware (Unix/Windows differences handled)

See [SECURITY.md](../../SECURITY.md) for the full security policy and threat model.

## Sign-off (DCO)

We use the [Developer Certificate of Origin (DCO)](https://developercertificate.org). Every commit
must be signed off, asserting you have the right to submit it under the project's Apache-2.0
license.

Add sign-off automatically:

```bash
git commit -s -m "your commit message"
```

This appends `Signed-off-by: Your Name <your@email>` to the commit message. Forgot? Amend:

```bash
git commit --amend -s
```

## Pull Request Guidelines

1. Ensure all tests pass: `make check`
2. Maintain or improve code coverage
3. Follow existing code style (enforced by ruff)
4. Add tests for new functionality
5. Update documentation as needed
6. Ensure every commit has `Signed-off-by:` (DCO check enforces this on all PRs)

**Merge Policy:** All PRs are squash-merged to keep the git history clean (one commit per feature).

## Release Process

Release prep goes through a normal PR to develop. Only the merge to main and tagging are done via
CLI to preserve full commit history.

```bash
# 1. Create release PR to develop (version bump, changelog)
#    - Branch: release/vX.Y.Z
#    - Commit: "chore(release): prepare vX.Y.Z"
#    - Squash-merge to develop like any other PR

# 2. Merge to main (preserves commit history)
git fetch origin
git checkout main && git pull origin main
git merge origin/develop --no-ff -m "Release vX.Y.Z"
make check  # verify before pushing
git push origin main

# 3. Tag (triggers GitHub Actions release workflow)
git tag vX.Y.Z && git push origin vX.Y.Z

# 4. Sync develop with main (gets merge commit on develop)
git checkout develop && git pull origin develop
git merge main && git push origin develop
```

## License

By contributing, you agree that your contributions will be licensed under the Apache License 2.0.
