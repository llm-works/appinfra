# Coverage Targets

Makefile targets for test coverage analysis.

## Available Targets

### `make test.coverage`
Console coverage report:
```bash
make test.coverage
```

Output:
```
Name                                            Stmts   Miss  Cover
-------------------------------------------------------------------
infra/__init__.py                                   8      0   100%
infra/app/__init__.py                              13      0   100%
-------------------------------------------------------------------
TOTAL                                           18305   1636    91%
```

### `make test.coverage.html`
Interactive HTML report:
```bash
make test.coverage.html
# Open .htmlcov/index.html in browser
```

Features:
- Line-by-line coverage analysis
- Search and navigation
- Visual indicators for covered/uncovered code

### `make test.coverage.xml`
XML report for CI/CD:
```bash
make test.coverage.xml
# Creates coverage.xml in project root
```

Use with Jenkins, GitHub Actions, or other CI/CD systems.

## Configuration

All targets:
- Include pattern: `infra/*` (project code only)
- Exclude pattern: `*/site-packages/*` (external libraries)
- Test pattern: `*_test.py` (unit tests)
- Uses: `~/.venv/bin/python`

### Coverage Threshold

The `make check` command enforces a coverage threshold. Configure via
`APPINFRA_PYTEST_COVERAGE_THRESHOLD`:

```makefile
# In your Makefile (before includes)
APPINFRA_PYTEST_COVERAGE_THRESHOLD ?= 95    # Require 95% coverage

# Or disable coverage check entirely
APPINFRA_PYTEST_COVERAGE_THRESHOLD ?= 0
```

**Default:** 80%

**Use cases:**
- Open-sourcing existing projects with limited test coverage
- Incremental coverage improvement (start at 30%, raise over time)
- Projects where certain modules are intentionally untested (e.g., GPU-only code)

You can also override at runtime:
```bash
APPINFRA_PYTEST_COVERAGE_THRESHOLD=50 make check
```

## Best Practices

**Regular usage:**
- `make test.coverage` - Quick checks during development
- `make test.coverage.html` - Detailed analysis
- `make test.coverage.xml` - CI/CD integration

**Coverage goals:**
- Maintain 90%+ for critical components
- Focus on areas below 80%
- Monitor trends over time
