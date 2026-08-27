#!/usr/bin/env bash

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

# Convenience script for running tests in a container runtime
# Matches CI environment exactly - great for debugging CI failures locally
#
# Container runtime is selected via env vars (defaults to docker):
#   INFRA_CONTAINER_CMD  - container CLI (docker | podman | ...)
#   INFRA_COMPOSE_CMD    - compose CLI (docker compose | podman compose | ...)

set -euo pipefail

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CICD_DIR="$SCRIPT_DIR/cicd"

# Container runtime (override via env vars)
INFRA_CONTAINER_CMD="${INFRA_CONTAINER_CMD:-docker}"
INFRA_COMPOSE_CMD="${INFRA_COMPOSE_CMD:-docker compose}"

# Default values
PYTHON_VERSION="${1:-3.12}"
COMMAND="${2:-make check.summary}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Print usage
usage() {
    echo "Usage: $0 [PYTHON_VERSION] [COMMAND]"
    echo ""
    echo "Examples:"
    echo "  $0                          # Run complete CI checks (summaries + failures only) with Python 3.12"
    echo "  $0 3.11                     # Run complete CI checks with Python 3.11"
    echo "  $0 3.12 'make check.raw'    # Run with verbose output (all test details)"
    echo "  $0 3.12 'make test.unit'    # Run unit tests only with Python 3.12"
    echo "  $0 3.13 'pytest tests/infra/log -v'  # Run specific tests"
    echo ""
    echo "Available Python versions: 3.11, 3.12, 3.13"
    echo "Default command: make check.summary (CI checks with summaries + failures only)"
    exit 1
}

# Validate Python version
if [[ ! "$PYTHON_VERSION" =~ ^3\.(11|12|13)$ ]]; then
    echo -e "${RED}Error: Invalid Python version '$PYTHON_VERSION'${NC}"
    echo "       Valid versions: 3.11, 3.12, 3.13"
    usage
fi

# Check if the container runtime is available
if ! ${INFRA_CONTAINER_CMD} info >/dev/null 2>&1; then
    echo -e "${RED}Error: '${INFRA_CONTAINER_CMD}' is not available or not running${NC}"
    echo "       Override via INFRA_CONTAINER_CMD / INFRA_COMPOSE_CMD env vars"
    exit 1
fi

# Check if the compose CLI is available
if ! ${INFRA_COMPOSE_CMD} version >/dev/null 2>&1; then
    echo -e "${RED}Error: '${INFRA_COMPOSE_CMD}' is not available${NC}"
    echo "       Override via INFRA_CONTAINER_CMD / INFRA_COMPOSE_CMD env vars"
    exit 1
fi

# Navigate to cicd directory
cd "$CICD_DIR"

echo -e "${GREEN}Starting PostgreSQL and running tests...${NC}"
echo -e "Python version: ${YELLOW}$PYTHON_VERSION${NC}"
echo -e "Command: ${YELLOW}$COMMAND${NC}"
echo ""

# Determine compose file based on Python version
COMPOSE_OVERRIDE="docker-compose.override.py${PYTHON_VERSION}.yml"

# Check if compose override file exists
if [ ! -f "$COMPOSE_OVERRIDE" ]; then
    echo -e "${RED}Error: Compose override file not found: $COMPOSE_OVERRIDE${NC}"
    exit 1
fi

# Log file creation disabled - output is already visible in console
# Uncomment below to save logs to .logs/ directory
# TIMESTAMP=$(date +%Y%m%d-%H%M%S)
# LOG_DIR="$PROJECT_ROOT/.logs"
# LOG_FILE="$LOG_DIR/${TIMESTAMP}-docker-test.log"
# mkdir -p "$LOG_DIR"

# Run compose. Capture exit code via `|| EXIT_CODE=$?` so `set -e` does not
# abort before we reach the cleanup block below (LHS of `||` is exempt from
# `set -e`). Without this, a failing test command skips `down -v`.
EXIT_CODE=0
${INFRA_COMPOSE_CMD} -f docker-compose.yml -f "$COMPOSE_OVERRIDE" run --rm app bash -c "$COMMAND" || EXIT_CODE=$?

# Append postgres service logs (disabled - uncomment if needed)
# echo "" >> "$LOG_FILE"
# echo "========================================" >> "$LOG_FILE"
# echo "PostgreSQL Service Logs" >> "$LOG_FILE"
# echo "========================================" >> "$LOG_FILE"
# docker compose -f docker-compose.yml -f "$COMPOSE_OVERRIDE" logs postgres >> "$LOG_FILE" 2>&1
# echo ""
# echo -e "${GREEN}Logs saved to:${NC} ${YELLOW}$LOG_FILE${NC}"

# Cleanup. `|| true` so a cleanup failure (e.g. network/runtime issue at
# teardown) does not mask EXIT_CODE under `set -e` by aborting before we
# print the result and exit with EXIT_CODE below.
echo ""
echo -e "${GREEN}Cleaning up container resources...${NC}"
${INFRA_COMPOSE_CMD} down -v >/dev/null 2>&1 || true

if [ $EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}✓ Tests passed!${NC}"
else
    echo -e "${RED}✗ Tests failed with exit code $EXIT_CODE${NC}"
fi

exit $EXIT_CODE
