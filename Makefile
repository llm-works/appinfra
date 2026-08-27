# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

local := $(dir $(realpath $(lastword $(MAKEFILE_LIST))))

# ============================================================================
# Project Configuration
# ============================================================================
# These settings can also be overridden in Makefile.local (gitignored)

# Enable strict code quality checks (30-line function limit)
INFRA_DEV_CQ_STRICT := true

# Enforce SPDX license headers on tracked .py files (Apache-2.0 attribution)
INFRA_DEV_CQ_SPDX := true

# Include all tests in coverage (not just unit tests)
INFRA_PYTEST_COVERAGE_MARKERS := unit or e2e

# Coverage threshold (framework default is 80%)
INFRA_PYTEST_COVERAGE_THRESHOLD := 95

# Docstring coverage threshold (framework default is 80%)
INFRA_DEV_DOCSTRING_THRESHOLD := 95

# Install with all optional extras
INFRA_DEV_INSTALL_EXTRAS := all

# PostgreSQL configuration (filename only - resolved from ETC_DIR)
INFRA_PG_CONFIG_FILE := pg.yaml
#INFRA_PG_CONFIG_KEY := pgserver

# Documentation configuration (filename only - resolved from ETC_DIR)
INFRA_DOCS_CONFIG_FILE := mkdocs.yaml

# ============================================================================
# Load Infra Framework
# ============================================================================

# Load configuration first (sets defaults, handles deprecation)
include $(local)/scripts/make/Makefile.config

# Python environment detection (supports env var, Makefile.local, ~/.venv)
include $(local)/scripts/make/Makefile.env

include $(local)/scripts/make/Makefile.help
include $(local)/scripts/make/Makefile.utils
include $(local)/scripts/make/Makefile.dev
include $(local)/scripts/make/Makefile.install
include $(local)/scripts/make/Makefile.pytest
include $(local)/scripts/make/Makefile.docs
include $(local)/scripts/make/Makefile.pg
include $(local)/scripts/make/Makefile.cicd
include $(local)/scripts/make/Makefile.clean
