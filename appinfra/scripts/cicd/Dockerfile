# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

# Multi-stage Dockerfile for infra framework CI/CD
# Supports Python 3.11, 3.12, 3.13, 3.14 via build args

ARG PYTHON_VERSION=3.12
FROM python:${PYTHON_VERSION}-slim-bookworm AS base

# Prevent Python from writing pyc files and buffering stdout/stderr
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies
# - postgresql-client: Required for integration tests
# - make: Required for Makefile targets
# - jq: Required for YAML parsing scripts
# - bc: Required for elapsed time calculations in check.sh
# - procps: Required for ps, which check.sh uses to stop its process tree
RUN apt-get update && apt-get install -y \
    postgresql-client \
    make \
    jq \
    bc \
    procps \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# ========================================
# Stage 2: Dependencies layer (cached separately from code)
# ========================================
FROM base AS dependencies

# make setup installs every dependency, not the project: the source tree is
# mounted at run time. It needs the Makefile and the make framework it includes
COPY pyproject.toml Makefile ./
COPY appinfra/scripts/ ./scripts/
COPY appinfra/etc/ ./etc/

# The venv first on PATH, as if activated: the Makefile takes python3 from PATH
ENV PATH="/root/.venv/bin:$PATH"
RUN python -m venv /root/.venv && \
    /root/.venv/bin/python -m pip install --upgrade pip && \
    make setup

# ========================================
# Stage 3: Runtime image
# ========================================
FROM dependencies AS runtime

# Create non-root user for security (prevents tests from running as root)
# UID/GID 1000 matches typical Linux user, avoiding permission issues
RUN groupadd --gid 1000 testuser && \
    useradd --uid 1000 --gid 1000 --shell /bin/bash --create-home testuser

# Copy venv to testuser's home directory before switching users
# This must happen while still root
RUN cp -r /root/.venv /home/testuser/.venv && \
    chown -R testuser:testuser /home/testuser/.venv

# Copy source code
# These layers rebuild on every code change, but dependencies are cached
# Note: appinfra/ now contains docs/, examples/, scripts/, etc/ as real directories
COPY appinfra/ ./appinfra/
COPY tests/ ./tests/
COPY Makefile ./
# scripts and etc are symlinks at root, copy from real locations
COPY appinfra/scripts/ ./scripts/
COPY appinfra/etc/ ./etc/

# Create output directories and caches with proper ownership
# Important: Create cache directories before switching to testuser
RUN mkdir -p /workspace/.deploy-coverage \
             /workspace/.pytest_cache \
             /workspace/.mypy_cache && \
    chown -R testuser:testuser /workspace && \
    chmod -R 777 /workspace/.pytest_cache /workspace/.mypy_cache /workspace/.deploy-coverage

# Update PATH to use testuser's venv
ENV PATH="/home/testuser/.venv/bin:$PATH"

# Switch to non-root user (do this last)
USER testuser

# Default command runs all tests
CMD ["make", "test.all"]
