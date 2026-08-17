# Docker Development Guide

This guide explains how to use Docker for local development and testing. The Docker setup provides
identical environments for local development and CI, eliminating "works on my machine" issues.

## Quick Start

### Prerequisites

- Docker and Docker Compose installed
- No Python or PostgreSQL installation required!

### Run Complete CI Checks (Python 3.12)

```bash
# From project root
make docker.test

# Or use the convenience script
./scripts/docker-test.sh
```

That's it! Docker will:
1. Build the Python 3.12 environment
2. Start PostgreSQL
3. Run complete CI checks:
   - Code formatting check (ruff format)
   - Linting (ruff check)
   - Type checking (mypy)
   - Function size validation
   - All 2,682 tests (unit, integration, e2e, performance, security)
   - Code coverage analysis
4. Export logs to `.logs/YYYYMMDD-HHMMSS-docker-test.log`
5. Clean up automatically

**Note:** The default command is `make check`, which runs the same checks as CI.

## Available Commands

### Makefile Targets (Recommended)

```bash
# Run tests with Python 3.12 (default)
make docker.test

# Run tests with Python 3.11
make docker.test.py311

# Run tests with Python 3.13
make docker.test.py313

# Open interactive shell
make docker.shell

# Build all Docker images
make docker.build

# Clean up Docker resources
make docker.clean
```

### Convenience Script

```bash
# Run all tests with Python 3.12
./scripts/docker-test.sh

# Run all tests with Python 3.11
./scripts/docker-test.sh 3.11

# Run unit tests only
./scripts/docker-test.sh 3.12 "make test.unit"

# Run specific test file
./scripts/docker-test.sh 3.12 "pytest tests/infra/log/test_colors.py -v"

# Run with custom command
./scripts/docker-test.sh 3.13 "python -m pytest tests/infra/db/ -v -s"
```

### Direct Docker Compose Usage

```bash
# Navigate to Docker directory
cd scripts/docker/deploy

# Run tests with Python 3.12
docker compose -f docker-compose.yml -f docker-compose.override.py3.12.yml up --abort-on-container-exit

# Run tests with Python 3.11
docker compose -f docker-compose.yml -f docker-compose.override.py3.11.yml up --abort-on-container-exit

# Interactive shell
docker compose -f docker-compose.yml -f docker-compose.override.py3.12.yml run --rm app bash

# Clean up
docker compose down -v
```

## Development Workflows

### 1. Test Before Committing

```bash
# Run full test suite (matches CI exactly)
make docker.test

# If tests pass, you're good to commit!
git add .
git commit -m "Your changes"
```

### 2. Debug CI Failures Locally

CI failed? Reproduce it exactly:

```bash
# CI uses Python 3.12 for coverage
./scripts/docker-test.sh 3.12

# Run the exact failing test
./scripts/docker-test.sh 3.12 "pytest tests/infra/db/test_pg.py::test_specific_failure -v"
```

### 3. Test Multiple Python Versions

```bash
# Test all Python versions locally
make docker.test.py311
make docker.test.py312
make docker.test.py313
```

### 4. Interactive Debugging

```bash
# Open shell in container
make docker.shell

# Inside container:
root@abc123:/workspace# pytest tests/infra/log -v
root@abc123:/workspace# python
>>> from appinfra.log import LoggingBuilder
>>> # Debug interactively

# Exit when done
root@abc123:/workspace# exit
```

### 5. Run Specific Test Categories

```bash
# Unit tests only (fast, ~8s)
./scripts/docker-test.sh 3.12 "make test.unit"

# Integration tests (with PostgreSQL, ~17s)
./scripts/docker-test.sh 3.12 "make test.integration"

# Security tests
./scripts/docker-test.sh 3.12 "make test.security"

# Code quality checks
./scripts/docker-test.sh 3.12 "make fmt.check lint type cq.strict"
```

## Docker Log Export

All test runs automatically export Docker logs to timestamped files in the `.logs/` directory.

**Log file format:** `.logs/YYYYMMDD-HHMMSS-docker-test.log`

**Example:** `.logs/20251129-091530-docker-test.log`

### Viewing Logs

```bash
# After running tests
./scripts/docker-test.sh 3.12
# Logs saved to: .logs/<timestamp>-docker-test.log

# View the latest log
ls -t .logs/*.log | head -1 | xargs cat

# View logs from both app and postgres containers
tail -100 .logs/20251129-091530-docker-test.log

# Search logs for errors
grep -i error .logs/*.log

# View all log files
ls -lh .logs/
```

### Log Contents

Log files contain output from all Docker services:
- **app container**: Test execution output, pytest results, errors
- **postgres container**: Database logs, queries, connection info

**Use cases:**
- Debug CI failures locally by comparing logs
- Audit trail of test runs
- Performance analysis (timing information)
- PostgreSQL query debugging

### Log Management

```bash
# Clean up old logs (older than 7 days)
find .logs -name "*.log" -mtime +7 -delete

# Clean up all logs
rm -rf .logs/

# Archive logs
tar -czf logs-archive-$(date +%Y%m).tar.gz .logs/
```

**Note:** `.logs/` directory is gitignored and won't be committed to the repository.

---

## How It Works

### Directory Structure

```
scripts/docker/deploy/
├── Dockerfile                          # Multi-stage build
├── docker-compose.yml                  # Main compose file
├── docker-compose.override.py3.11.yml  # Python 3.11 config
├── docker-compose.override.py3.12.yml  # Python 3.12 config
├── docker-compose.override.py3.13.yml  # Python 3.13 config
├── .env.test                           # Default environment
├── .env.local.example                  # Local customization template
└── DOCKER_DEVELOPMENT.md               # This file
```

### Multi-Stage Docker Build

1. **Base stage:** Python slim + system dependencies (gcc, postgresql-client, make)
2. **Dependencies stage:** Install Python packages from pyproject.toml (cached)
3. **Runtime stage:** Copy source code (rebuilds on code changes)

**Key benefit:** Dependency layer is cached unless pyproject.toml changes, making rebuilds fast
(~5-10s).

### Volume Mounts

Source code is mounted **read-only** to prevent accidental modifications:

```yaml
volumes:
  - ../../../infra:/workspace/infra:ro      # Read-only
  - ../../../tests:/workspace/tests:ro      # Read-only
  - ../../../coverage-output:/workspace/coverage-output  # Read-write (artifacts)
```

## Customization

### Local Environment Overrides

```bash
# Copy template
cp scripts/docker/deploy/.env.local.example scripts/docker/deploy/.env.local

# Edit .env.local (gitignored)
# Override any settings from .env.test
INFRA_TEST_LOGGING_LEVEL=debug
INFRA_TEST_CLEANUP=false
```

### Custom PostgreSQL Configuration

Edit `scripts/docker/deploy/.env.local`:

```bash
POSTGRES_PASSWORD=custom-password
INFRA_PGSERVER_PORT=5432
INFRA_PGSERVER_USER=custom_user
```

## Troubleshooting

### Build Failures

```bash
# Clean rebuild (no cache)
cd scripts/docker/deploy
docker compose build --no-cache

# Or use Makefile
make docker.clean
make docker.build
```

### PostgreSQL Connection Issues

```bash
# Check PostgreSQL is running
docker ps | grep postgres

# View PostgreSQL logs
cd scripts/docker/deploy
docker compose logs postgres

# Restart PostgreSQL
docker compose restart postgres
```

### Slow Performance on macOS

Docker volume mounts on macOS can be slow. Workarounds:

1. Use named volumes for caches (already configured)
2. Consider using Docker Desktop alternatives (Colima, Rancher Desktop)
3. For development, use native Python environment instead

### Permission Issues

If you encounter permission errors with mounted volumes:

```bash
# Check file ownership in container
make docker.shell
ls -la /workspace

# If needed, adjust permissions on host
chmod -R 755 coverage-output/
```

### Out of Disk Space

```bash
# Clean up unused Docker resources
docker system prune -a --volumes

# Remove only infra-related resources
make docker.clean
```

## CI/CD Integration

The same Docker setup runs in GitHub Actions:

- **Linux CI:** Full test suite with all Python versions (3.11, 3.12, 3.13)
- **macOS/Windows CI:** Unit tests only (smoke tests for platform compatibility)

See workflows:
- `.github/workflows/test-docker.yml` - Linux Docker tests
- `.github/workflows/test-native.yml` - Native platform tests

## Performance Comparison

| Environment | Time (2,682 tests) | Setup Required |
|-------------|-------------------|----------------|
| Native (local venv) | ~37s | Python + PostgreSQL |
| Docker (first run) | ~175s | Docker only |
| Docker (cached) | ~85s | Docker only |
| CI (GitHub Actions) | ~85s | None |

**Recommendation:**
- Primary development: Native venv (fastest)
- Pre-commit verification: Docker (matches CI)
- CI debugging: Docker (exact reproduction)

## Advanced Usage

### Testing Against Different PostgreSQL Versions

Edit `scripts/docker/deploy/docker-compose.yml`:

```yaml
postgres:
  image: postgres:17  # Change from postgres:18
```

### Adding Additional Services

```yaml
# scripts/docker/deploy/docker-compose.yml
services:
  redis:
    image: redis:7
    ports:
      - "6379:6379"
```

### Multi-Project Testing

```bash
# Test multiple projects with same environment
cd /path/to/other-project
/path/to/infra/scripts/docker-test.sh 3.12
```

## FAQ

**Q: Do I need to rebuild after code changes?**
A: No! Source code is mounted as volumes. Just re-run tests.

**Q: Do I need to rebuild after pyproject.toml changes?**
A: Yes. Run `make docker.build` to install new dependencies.

**Q: Can I use this on Windows?**
A: Yes! Docker runs Linux containers via WSL2. Commands work identically.

**Q: How do I update Python version?**
A: We support 3.11, 3.12, 3.13. To add 3.14, create `docker-compose.override.py3.14.yml`.

**Q: Why not use the `act` tool to test GitHub Actions locally?**
A: `act` has limitations (service containers, environment differences). Docker Compose is simpler
and more reliable.

**Q: Can I run this without GitHub?**
A: Yes! That's the whole point. Zero GitHub dependency for local testing.

## Resources

- [Docker Compose Documentation](https://docs.docker.com/compose/)
- [Multi-stage Builds](https://docs.docker.com/build/building/multi-stage/)
- [Docker Volumes](https://docs.docker.com/storage/volumes/)
- [Project README](../../../README.md)

## Support

For issues or questions:
1. Check troubleshooting section above
2. Review Docker Compose logs: `docker-compose logs`
3. Open an issue with error details and `docker --version` output
