#!/usr/bin/env bash

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

# Type hint coverage report script
# Usage: ./scripts/type-hint.sh

set -e

# Default to project venv if PYTHON not set
if [ -z "$PYTHON" ]; then
    PYTHON="$HOME/.venv/bin/python"
fi

echo "=== Type Hint Coverage Report ==="
echo ""
echo "Running mypy to verify type hints..."

# Run mypy and capture output
if "$PYTHON" -m mypy appinfra/ --config-file pyproject.toml 2>&1 | tee .mypy-check.txt; then
    echo ""
    echo "=== Coverage Statistics ==="

    # Extract number of files checked
    FILES_CHECKED=$(grep -oP 'Success: no issues found in \K\d+' .mypy-check.txt || echo "0")

    # Count total production files
    TOTAL_FILES=$(find appinfra/ -name "*.py" -type f ! -path "*/tests/*" ! -path "*/examples/*" ! -path "*/scripts/*" | wc -l)

    echo "Files with complete type hints: $FILES_CHECKED"
    echo "Total production files: $TOTAL_FILES"

    # Calculate and display coverage
    if [ "$FILES_CHECKED" -eq "$TOTAL_FILES" ]; then
        echo "Coverage: 100% ✓"
    else
        PERCENT=$(echo "scale=1; ($FILES_CHECKED * 100) / $TOTAL_FILES" | bc)
        echo "Coverage: ${PERCENT}%"
    fi

    # Show mypy config
    echo ""
    echo "Mypy configuration (pyproject.toml):"
    grep -A 5 "^\[tool.mypy\]" pyproject.toml | head -6

    rm -f .mypy-check.txt
    exit 0
else
    echo ""
    echo "❌ Mypy found type errors. See output above."
    rm -f .mypy-check.txt
    exit 1
fi
