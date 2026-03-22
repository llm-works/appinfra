#!/usr/bin/env bash
# Code quality check runner with progress indicators
# Supports parallel execution, coverage checking, and fail-fast mode
#
# IMPORTANT: Run via 'make check', not directly. The Makefile exports required
# variables (PYTHON, INFRA_DEV_PKG_NAME, INFRA_DEV_CQ_STRICT, INFRA_DEV_PROJECT_ROOT).
# Direct execution uses fallback defaults that may not match your project configuration.

set -euo pipefail
shopt -s nullglob

# === PARAMETER PARSING ===

PARALLEL=true
NPROC=$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 8)
PYTEST_JOBS=$(( NPROC / 4 > 2 ? NPROC / 4 : 2 ))
PYTEST_PARALLEL="-n ${PYTEST_JOBS}"
COVERAGE_TARGET=""
FAIL_FAST=false
RAW=false
SUMMARY=false
SKIP_TESTS=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --sequential) PARALLEL=false; PYTEST_PARALLEL="-n 0"; shift ;;
        --coverage-target) COVERAGE_TARGET="$2"; shift 2 ;;
        --fail-fast) FAIL_FAST=true; shift ;;
        --raw)
            RAW=true
            PARALLEL=false
            PYTEST_PARALLEL="-n 0"
            FAIL_FAST=true
            shift
            ;;
        --summary) SUMMARY=true; shift ;;
        --skip-tests) SKIP_TESTS=true; shift ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--sequential] [--coverage-target <percentage>] [--fail-fast] [--raw] [--summary] [--skip-tests]"
            exit 1
            ;;
    esac
done

# === CONFIGURATION ===

GREEN=$'\033[32m'
RED=$'\033[31m'
YELLOW=$'\033[33m'
GRAY=$'\033[90m'
RESET=$'\033[0m'
CLEAR=$'\033[K'

CHECK_PENDING="[ ] "
CHECK_RUNNING="[...]"
CHECK_SUCCESS="[✓] "
CHECK_WARNING="[⚠] "
CHECK_FAILURE="[✗] "

# Exit code for "warnings but ok" from cq tool (violations in non-strict mode)
EXIT_CODE_WARNING=42

PYTHON="${PYTHON:-~/.venv/bin/python}"
PKG_NAME="${INFRA_DEV_PKG_NAME:-appinfra}"
CQ_STRICT="${INFRA_DEV_CQ_STRICT:-false}"
COVERAGE_MARKERS="${INFRA_PYTEST_COVERAGE_MARKERS:-unit}"
MYPY_FLAGS="${INFRA_DEV_MYPY_FLAGS:-}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${INFRA_DEV_PROJECT_ROOT:-$(dirname "$SCRIPT_DIR")}"

MAIN_PID=$$
DISPLAY_LOCK="/tmp/infra-check-display-lock-${MAIN_PID}"
STATUS_DIR="/tmp/infra-check-status-${MAIN_PID}"
mkdir -p "$STATUS_DIR"

# Coverage threshold precedence: CLI arg > env var > default (80)
# Set to 0 to disable coverage checking entirely
DEFAULT_COVERAGE_TARGET="${INFRA_PYTEST_COVERAGE_THRESHOLD:-80}"
COVERAGE_TARGET="${COVERAGE_TARGET:-$DEFAULT_COVERAGE_TARGET}"

# Docstring coverage threshold (0 to disable)
DOCSTRING_THRESHOLD="${INFRA_DEV_DOCSTRING_THRESHOLD:-80}"

# Check definitions: "Name|Make Target|Command|Fix Target"
declare -a CHECKS=(
    "Formatting check|fmt.check|${PYTHON} -m ruff format --check .|fmt"
    "Linting|lint|${PYTHON} -m ruff check .|lint.fix"
    "Type checking|type|${PYTHON} -m mypy ${PKG_NAME}/ --exclude 'examples/' --cache-dir .mypy_cache/pkg ${MYPY_FLAGS}|"
)

# Add examples type check only if directory exists (top-level or inside package)
EXAMPLES_DIR=""
if [ -d "examples" ]; then
    EXAMPLES_DIR="examples"
elif [ -d "${PKG_NAME}/examples" ]; then
    EXAMPLES_DIR="${PKG_NAME}/examples"
fi
if [ -n "$EXAMPLES_DIR" ]; then
    CHECKS+=("Type checking (examples)|type|${PYTHON} -m mypy ${EXAMPLES_DIR}/ --disable-error-code=no-untyped-def --disable-error-code=import-untyped --ignore-missing-imports --cache-dir .mypy_cache/examples ${MYPY_FLAGS}|")
fi

# Build exclude flags from INFRA_DEV_CQ_EXCLUDE (subshell contains set -f scope)
CQ_EXCLUDE_FLAGS=""
if [ -n "${INFRA_DEV_CQ_EXCLUDE:-}" ]; then
    CQ_EXCLUDE_FLAGS=$(
        set -f  # Disable glob expansion to preserve patterns like "examples/*"
        sep=""
        for pat in ${INFRA_DEV_CQ_EXCLUDE}; do
            printf '%s--exclude "%s"' "$sep" "$pat"
            sep=" "
        done
    )
fi

# Build CQ command and label based on strictness setting
if [ "$CQ_STRICT" = "true" ]; then
    CQ_CMD="${PYTHON} -m appinfra.cli.cli -l error cq cf --strict ${CQ_EXCLUDE_FLAGS}"
    CQ_LABEL="Function size check (strict)"
    CQ_TARGET="cq.strict"
else
    CQ_CMD="${PYTHON} -m appinfra.cli.cli -l error cq cf ${CQ_EXCLUDE_FLAGS}"
    CQ_LABEL="Function size check (non-strict)"
    CQ_TARGET="cq"
fi

# Docstring coverage check command (only if threshold > 0)
DOCSTRING_CMD="${PYTHON} -m interrogate -v ${PKG_NAME}/ --ignore-init-module --ignore-init-method --fail-under=${DOCSTRING_THRESHOLD}"

# Add remaining checks
CHECKS+=(
    "${CQ_LABEL}|${CQ_TARGET}|${CQ_CMD}|"
)

# Add docstring check only if threshold > 0
if awk "BEGIN {exit !($DOCSTRING_THRESHOLD > 0)}" 2>/dev/null; then
    CHECKS+=("Docstring coverage|cq.docstring.strict|${DOCSTRING_CMD}|docstring:${DOCSTRING_THRESHOLD}")
fi

# Add test suite check only if not skipped
if [ "$SKIP_TESTS" = false ]; then
    CHECKS+=("Test suite|test.all|SPECIAL|test.v")
fi

# Test subchecks: "Name|Make Target|Command|Coverage Target"
COVERAGE_MARKER_ARG=""
if [ -n "$COVERAGE_MARKERS" ]; then
    COVERAGE_MARKER_ARG="-m \"${COVERAGE_MARKERS}\""
fi

declare -a TEST_SUBCHECKS=(
    "Unit tests|test.unit|${PYTHON} -m pytest tests/ -m unit --tb=short --no-header -q -rEfs ${PYTEST_PARALLEL}|"
    "Integration tests|test.integration|${PYTHON} -m pytest tests/ -m integration --tb=short --no-header -q -rEfs ${PYTEST_PARALLEL}|"
    "E2E tests|test.e2e|${PYTHON} -m pytest tests/ -m e2e --tb=short --no-header -q -rEfs ${PYTEST_PARALLEL}|"
    "Security tests|test.security|${PYTHON} -m pytest tests/ -m security --tb=short --no-header -q -rEfs ${PYTEST_PARALLEL}|"
    "Performance tests|test.perf|${PYTHON} -m pytest tests/ -m performance --tb=short --no-header -q -rEfs ${PYTEST_PARALLEL}|"
)
# Add coverage check only if threshold > 0 (awk is more portable than bc)
if awk "BEGIN {exit !($COVERAGE_TARGET > 0)}" 2>/dev/null; then
    TEST_SUBCHECKS+=("Code coverage|test.coverage|${PYTHON} -m pytest tests/ ${COVERAGE_MARKER_ARG} --cov=${PKG_NAME} --cov-report=term -q -rEfs ${PYTEST_PARALLEL}|${COVERAGE_TARGET}")
fi

# Verbose versions for raw mode
declare -a TEST_SUBCHECKS_RAW=(
    "Unit tests|test.unit.v|${PYTHON} -m pytest tests/ -m unit -v --tb=short -rEfs ${PYTEST_PARALLEL}|"
    "Integration tests|test.integration.v|${PYTHON} -m pytest tests/ -m integration -v --tb=short -rEfs ${PYTEST_PARALLEL}|"
    "E2E tests|test.e2e.v|${PYTHON} -m pytest tests/ -m e2e -v --tb=short -rEfs ${PYTEST_PARALLEL}|"
    "Security tests|test.security.v|${PYTHON} -m pytest tests/ -m security -v --tb=short -rEfs ${PYTEST_PARALLEL}|"
    "Performance tests|test.perf.v|${PYTHON} -m pytest tests/ -m performance -v --tb=short -rEfs ${PYTEST_PARALLEL}|"
)
# Add coverage check only if threshold > 0 (awk is more portable than bc)
if awk "BEGIN {exit !($COVERAGE_TARGET > 0)}" 2>/dev/null; then
    TEST_SUBCHECKS_RAW+=("Code coverage|test.coverage|${PYTHON} -m pytest tests/ ${COVERAGE_MARKER_ARG} --cov=${PKG_NAME} --cov-report=term-missing -rEfs ${PYTEST_PARALLEL}|${COVERAGE_TARGET}")
fi

declare -A CHECK_LINES
declare -A SUBCHECK_LINES
TOTAL_LINES=0
INTERRUPTED=false

# === CLEANUP ===

cleanup() {
    if [ "$BASHPID" -eq "$MAIN_PID" ]; then
        jobs -p | xargs -r kill -TERM 2>/dev/null || true
        sleep 0.1
        jobs -p | xargs -r kill -KILL 2>/dev/null || true
        rm -rf "$STATUS_DIR" "$DISPLAY_LOCK" 2>/dev/null || true
    fi
}

handle_interrupt() {
    INTERRUPTED=true
    jobs -p | xargs -r kill -TERM 2>/dev/null || true
}

check_interrupted() {
    if [ "$INTERRUPTED" = true ]; then
        cleanup
        tput cnorm 2>/dev/null || printf "\033[?25h"
        echo ""
        echo -e "${RED}✗ Interrupted by user${RESET}"
        exit 130
    fi
}

trap cleanup EXIT
trap handle_interrupt INT TERM

# === DISPLAY HELPERS ===

update_line() {
    local line_num=$1 status=$2 name=$3 extra=$4
    {
        command -v flock &>/dev/null && flock -x 200
        local lines_up=$((TOTAL_LINES - line_num))
        [ $lines_up -gt 0 ] && printf "\033[${lines_up}A"
        printf "\r%b%s %s%b\n" "$CLEAR" "$status" "$name" "$extra"
        [ $lines_up -gt 1 ] && printf "\033[$((lines_up - 1))B"
        printf "\r"
    } 200>"$DISPLAY_LOCK"
}

display_failures() {
    [ -f "${STATUS_DIR}/failures" ] || return 0

    while IFS='|' read -r name make_target fix_target logfile extra; do
        echo -e "${RED}ERROR: ${name} failed${RESET}"
        [ -n "$extra" ] && echo -e "→ ${extra}"
        [ -n "$make_target" ] && echo -e "→ To investigate: ${YELLOW}make ${make_target}${RESET}"
        [ -n "$fix_target" ] && echo -e "→ To fix: ${YELLOW}make ${fix_target}${RESET}"
        if [ "$FAIL_FAST" = true ] && [ -n "$logfile" ] && [ -f "$logfile" ]; then
            echo ""
            # Show FAILED/ERROR lines (pytest short test summary)
            local failed_lines
            failed_lines=$(grep -E "^(FAILED|ERROR) " "$logfile" 2>/dev/null || true)
            if [ -n "$failed_lines" ]; then
                echo -e "${GRAY}Failed tests:${RESET}"
                echo "$failed_lines"
                echo ""
            fi
            # Show error lines (pytest prefixes errors with "E ")
            local error_lines
            error_lines=$(grep -E "^E\s+" "$logfile" 2>/dev/null | head -5 || true)
            if [ -n "$error_lines" ]; then
                echo -e "${GRAY}Errors:${RESET}"
                echo "$error_lines"
            fi
        fi
        echo ""
    done < "${STATUS_DIR}/failures"
}

# === COVERAGE HELPERS ===

parse_coverage() {
    local val=$(grep "^TOTAL" "$1" 2>/dev/null | awk '{print $NF}' | tr -d '%')
    val="${val:-0}"  # Default to 0 if empty
    # Floor to 1 decimal (pessimistic rounding)
    awk "BEGIN {printf \"%.1f\", int($val * 10) / 10}"
}

parse_docstring_coverage() {
    # Parse interrogate output: "RESULT: PASSED (minimum: 95.0%, actual: 95.3%)"
    # Using portable grep+sed instead of grep -oP (not available on macOS BSD grep)
    local val=$(grep -o 'actual: [0-9.]*' "$1" 2>/dev/null | sed 's/actual: //')
    val="${val:-0}"  # Default to 0 if empty
    # Floor to 1 decimal (pessimistic rounding)
    awk "BEGIN {printf \"%.1f\", int($val * 10) / 10}"
}

check_coverage_threshold() {
    local actual="$1" target="$2"
    awk "BEGIN {exit !($actual >= $target)}" 2>/dev/null
}

# Parse fix_target field for embedded coverage target (format: "type:threshold")
# Returns: "coverage_target|actual_fix_target" (pipe-separated)
parse_fix_target() {
    local fix_target="$1"
    if [[ "$fix_target" == docstring:* ]]; then
        echo "${fix_target#docstring:}|"
    else
        echo "|$fix_target"
    fi
}

# === CHECK EXECUTION ===

record_failure() {
    local name="$1" make_target="$2" fix_target="$3" logfile="$4" extra="${5:-}"
    echo "$name|$make_target|$fix_target|$logfile|$extra" >> "${STATUS_DIR}/failures"
}

record_warning() {
    local name="$1" count="${2:-}"
    echo "$name|$count" >> "${STATUS_DIR}/warnings"
}

record_skips() {
    local name="$1" logfile="$2"
    # Parse pytest -rs output for skip reasons
    # Format: "SKIPPED [N] path:line: reason" or "SKIPPED [N] path: reason" (no line number)
    # Using portable grep+sed instead of grep -oP (not available on macOS BSD grep)
    grep -E "^SKIPPED \[" "$logfile" 2>/dev/null | while read -r line; do
        # Extract count: "SKIPPED [6] ..." -> "6"
        # SC2155: Declare and assign separately to preserve exit status
        local count reason
        count=$(echo "$line" | sed -E 's/^SKIPPED \[([0-9]+)\].*/\1/')
        # Extract reason: everything after "path:line: " or "path: " (line number optional)
        reason=$(echo "$line" | sed -E 's/^SKIPPED \[[0-9]+\] [^:]+:([0-9]+:)? //')
        # Skip reasons prefixed with [expected] (from @pytest.mark.expected_skip)
        if [[ "$reason" == "[expected] "* ]]; then
            continue
        fi
        # Use tab delimiter to avoid issues with | in skip reasons
        # Use if block instead of && chain to avoid pipefail issues
        if [ -n "$count" ] && [ -n "$reason" ]; then
            printf '%s\t%s\n' "$count" "$reason" >> "${STATUS_DIR}/skips"
        fi
    done || true  # Guard against pipefail when loop has no matching lines
}

display_skip_summary() {
    [ -f "${STATUS_DIR}/skips" ] || return 0

    # Aggregate skip counts by reason (using tab delimiter)
    declare -A skip_reasons
    local total_skipped=0

    while IFS=$'\t' read -r count reason; do
        skip_reasons["$reason"]=$((${skip_reasons["$reason"]:-0} + count))
        total_skipped=$((total_skipped + count))
    done < "${STATUS_DIR}/skips"

    [ $total_skipped -eq 0 ] && return 0

    echo ""
    echo -e "${YELLOW}⚠ Warning: ${total_skipped} tests skipped${RESET}"

    # Sort reasons by count (descending) and display
    # Use tab delimiter to avoid issues with special characters in skip reasons
    for reason in "${!skip_reasons[@]}"; do
        printf '%s\t%s\n' "${skip_reasons[$reason]}" "$reason"
    done | sort -t$'\t' -k1 -rn | while IFS=$'\t' read -r count reason; do
        printf "  ${GRAY}- %s skipped: %s${RESET}\n" "$count" "$reason"
    done
}

# Unified check runner - handles both main checks and subchecks
run_check() {
    local name="$1" cmd="$2" line_num="$3"
    local is_subcheck="${4:-false}" coverage_target="${5:-}"
    local fix_target="${6:-}" make_target="${7:-}"
    local check_id="${8:-$line_num}"

    local prefix=""
    [ "$is_subcheck" = true ] && prefix="  "

    # Update to running state
    update_line "$line_num" "${YELLOW}${CHECK_RUNNING}${RESET}" "${prefix}${name}" ""

    # For test subchecks, check if required directory exists first
    # This prevents hangs from pytest-xdist or unittest on non-existent directories
    if [ "$is_subcheck" = true ]; then
        if [[ "$cmd" == *"tests/e2e"* ]] && [ ! -d "tests/e2e" ]; then
            update_line "$line_num" "${GRAY}${CHECK_PENDING}${RESET}" "${prefix}${name}" " ${GRAY}(no tests)${RESET}"
            return 0
        elif [[ "$cmd" == *"tests/"* ]] && [ ! -d "tests" ]; then
            update_line "$line_num" "${GRAY}${CHECK_PENDING}${RESET}" "${prefix}${name}" " ${GRAY}(no tests)${RESET}"
            return 0
        fi
    fi

    # Execute and capture output
    local tmpfile="${STATUS_DIR}/check-${check_id}.log"
    local exit_code=0
    eval "$cmd" > "$tmpfile" 2>&1 || exit_code=$?

    # Check if cleanup happened (fail-fast triggered by another check)
    [ -d "$STATUS_DIR" ] || return 0

    # Handle result based on exit code
    case "$exit_code" in
        0)
            # Record skips for test subchecks (pytest output)
            # Skip coverage subcheck to avoid double-counting (it re-runs tests with --cov)
            if [ "$is_subcheck" = true ] && [[ "$name" != *"coverage"* ]] && grep -qE "^SKIPPED \[" "$tmpfile" 2>/dev/null; then
                record_skips "$name" "$tmpfile"
            fi

            if [ -n "$coverage_target" ]; then
                # Use appropriate parser based on check type
                local actual
                if [[ "$name" == *"Docstring"* ]]; then
                    actual=$(parse_docstring_coverage "$tmpfile")
                else
                    actual=$(parse_coverage "$tmpfile")
                fi
                # Format target to 1 decimal for consistent display
                local target_display=$(awk "BEGIN {printf \"%.1f\", int($coverage_target * 10) / 10}")
                if check_coverage_threshold "$actual" "$coverage_target"; then
                    update_line "$line_num" "${GREEN}${CHECK_SUCCESS}${RESET}" "${prefix}${name}" " ${GRAY}(${actual}% ≥ ${target_display}%)${RESET}"
                else
                    update_line "$line_num" "${RED}${CHECK_FAILURE}${RESET}" "${prefix}${name}" " ${GRAY}(${actual}% < ${target_display}%)${RESET}"
                    record_failure "$name" "$make_target" "" "$tmpfile" "Coverage: ${actual}% (target: ${target_display}%)"
                    return 1
                fi
            else
                update_line "$line_num" "${GREEN}${CHECK_SUCCESS}${RESET}" "${prefix}${name}" ""
            fi
            rm -f "$tmpfile"
            ;;
        1)  # For docstring check, exit code 1 means coverage below threshold
            if [[ "$name" == *"Docstring"* ]] && [ -n "$coverage_target" ]; then
                local actual=$(parse_docstring_coverage "$tmpfile")
                # Format target to 1 decimal for consistent display
                local target_display=$(awk "BEGIN {printf \"%.1f\", int($coverage_target * 10) / 10}")
                update_line "$line_num" "${RED}${CHECK_FAILURE}${RESET}" "${prefix}${name}" " ${GRAY}(${actual}% < ${target_display}%)${RESET}"
                record_failure "$name" "$make_target" "" "$tmpfile" "Coverage: ${actual}% (target: ${target_display}%)"
                return 1
            fi
            # Fall through to default failure handling for non-docstring checks
            update_line "$line_num" "${RED}${CHECK_FAILURE}${RESET}" "${prefix}${name}" ""
            record_failure "$name" "$make_target" "$fix_target" "$tmpfile"
            return 1
            ;;
        5)  # No tests collected
            update_line "$line_num" "${GRAY}${CHECK_PENDING}${RESET}" "${prefix}${name}" " ${GRAY}(no tests)${RESET}"
            rm -f "$tmpfile"
            ;;
        42)  # Warning: violations found but non-strict mode (EXIT_CODE_WARNING)
            # Extract violation count from output if available
            local warning_count=$(grep -oP '(?<=Violations found: )\d+|(?<=Violations: )\d+' "$tmpfile" 2>/dev/null | head -1)
            if [ -n "$warning_count" ]; then
                update_line "$line_num" "${YELLOW}${CHECK_WARNING}${RESET}" "${prefix}${name}" " ${GRAY}(${warning_count} violations, run make cq)${RESET}"
                record_warning "$name" "$warning_count"
            else
                update_line "$line_num" "${YELLOW}${CHECK_WARNING}${RESET}" "${prefix}${name}" " ${GRAY}(run make cq)${RESET}"
                record_warning "$name"
            fi
            rm -f "$tmpfile"
            # Return 0 - warnings don't fail the build in non-strict mode
            ;;
        *)  # Failure
            update_line "$line_num" "${RED}${CHECK_FAILURE}${RESET}" "${prefix}${name}" ""
            record_failure "$name" "$make_target" "$fix_target" "$tmpfile"
            return $exit_code
            ;;
    esac
    return 0
}

# === EXECUTION MODES ===

monitor_jobs() {
    local pids=("$@")
    local any_failed=false
    local remaining=${#pids[@]}

    # Use wait -n to wait for jobs by completion order, not launch order
    # This ensures fail-fast triggers immediately when ANY job fails
    while [ $remaining -gt 0 ]; do
        if ! wait -n 2>/dev/null; then
            any_failed=true
            if [ "$FAIL_FAST" = true ]; then
                # Kill remaining background jobs immediately
                jobs -p | xargs -r kill -TERM 2>/dev/null || true
                break
            fi
        fi
        remaining=$((remaining - 1))
    done

    [ "$any_failed" = false ]
}

run_test_suite() {
    local line_num="$1"
    update_line "$line_num" "${YELLOW}${CHECK_RUNNING}${RESET}" "Test suite" ""

    if [ "$PARALLEL" = true ]; then
        # Run test subchecks in parallel (except performance tests - need isolated CPU)
        local pids=()
        local perf_subcheck=""
        for subcheck_def in "${TEST_SUBCHECKS[@]}"; do
            IFS='|' read -r subname submake subcmd coverage_target <<< "$subcheck_def"
            if [[ "$subname" == "Performance tests" ]]; then
                perf_subcheck="$subcheck_def"
                continue
            fi
            local subline=${SUBCHECK_LINES["$subname"]}
            run_check "$subname" "$subcmd" "$subline" true "$coverage_target" "" "$submake" &
            pids+=($!)
        done
        monitor_jobs "${pids[@]}" || true

        # Run performance tests last (needs isolated CPU for accurate timing)
        if [ -n "$perf_subcheck" ]; then
            IFS='|' read -r subname submake subcmd coverage_target <<< "$perf_subcheck"
            local subline=${SUBCHECK_LINES["$subname"]}
            run_check "$subname" "$subcmd" "$subline" true "$coverage_target" "" "$submake" || true
        fi
    else
        # Run test subchecks sequentially
        for subcheck_def in "${TEST_SUBCHECKS[@]}"; do
            IFS='|' read -r subname submake subcmd coverage_target <<< "$subcheck_def"
            local subline=${SUBCHECK_LINES["$subname"]}
            if ! run_check "$subname" "$subcmd" "$subline" true "$coverage_target" "" "$submake"; then
                [ "$FAIL_FAST" = true ] && { update_line "$line_num" "${RED}${CHECK_FAILURE}${RESET}" "Test suite" ""; return 1; }
            fi
        done
    fi

    if [ -f "${STATUS_DIR}/failures" ]; then
        update_line "$line_num" "${RED}${CHECK_FAILURE}${RESET}" "Test suite" ""
        return 1
    else
        update_line "$line_num" "${GREEN}${CHECK_SUCCESS}${RESET}" "Test suite" ""
        return 0
    fi
}

run_checks() {
    local any_failed=false
    local test_suite_line=""

    if [ "$PARALLEL" = true ]; then
        # Run ALL checks in parallel (except perf tests)
        local pids=()
        local perf_subcheck=""

        # Launch pre-test checks
        for check_def in "${CHECKS[@]}"; do
            IFS='|' read -r name make_target cmd fix_target <<< "$check_def"
            local line_num=${CHECK_LINES["$name"]}

            if [[ "$name" == "Test suite" ]]; then
                test_suite_line="$line_num"
                update_line "$line_num" "${YELLOW}${CHECK_RUNNING}${RESET}" "Test suite" ""
            else
                local parsed=$(parse_fix_target "$fix_target")
                local coverage_target="${parsed%%|*}"
                local actual_fix_target="${parsed#*|}"
                run_check "$name" "$cmd" "$line_num" false "$coverage_target" "$actual_fix_target" "$make_target" &
                pids+=($!)
            fi
        done

        # Launch test subchecks in parallel (except perf tests) - only if tests enabled
        if [ -n "$test_suite_line" ]; then
            for subcheck_def in "${TEST_SUBCHECKS[@]}"; do
                IFS='|' read -r subname submake subcmd coverage_target <<< "$subcheck_def"
                if [[ "$subname" == "Performance tests" ]]; then
                    perf_subcheck="$subcheck_def"
                    continue
                fi
                local subline=${SUBCHECK_LINES["$subname"]}
                run_check "$subname" "$subcmd" "$subline" true "$coverage_target" "" "$submake" &
                pids+=($!)
            done
        fi

        # Wait for all parallel checks
        monitor_jobs "${pids[@]}" || any_failed=true

        # Run performance tests last (needs isolated CPU) - only if tests enabled
        if [ -n "$test_suite_line" ] && [ -n "$perf_subcheck" ]; then
            [ "$FAIL_FAST" = true ] && [ "$any_failed" = true ] && {
                update_line "$test_suite_line" "${RED}${CHECK_FAILURE}${RESET}" "Test suite" ""
                return 1
            }
            IFS='|' read -r subname submake subcmd coverage_target <<< "$perf_subcheck"
            local subline=${SUBCHECK_LINES["$subname"]}
            run_check "$subname" "$subcmd" "$subline" true "$coverage_target" "" "$submake" || any_failed=true
        fi

        # Update test suite status - only if tests enabled
        if [ -n "$test_suite_line" ]; then
            if [ -f "${STATUS_DIR}/failures" ]; then
                update_line "$test_suite_line" "${RED}${CHECK_FAILURE}${RESET}" "Test suite" ""
            else
                update_line "$test_suite_line" "${GREEN}${CHECK_SUCCESS}${RESET}" "Test suite" ""
            fi
        fi
    else
        # Sequential mode
        for check_def in "${CHECKS[@]}"; do
            IFS='|' read -r name make_target cmd fix_target <<< "$check_def"
            local line_num=${CHECK_LINES["$name"]}

            if [[ "$name" == "Test suite" ]]; then
                run_test_suite "$line_num" || { any_failed=true; [ "$FAIL_FAST" = true ] && break; }
            else
                local parsed=$(parse_fix_target "$fix_target")
                local coverage_target="${parsed%%|*}"
                local actual_fix_target="${parsed#*|}"
                run_check "$name" "$cmd" "$line_num" false "$coverage_target" "$actual_fix_target" "$make_target" || {
                    any_failed=true; [ "$FAIL_FAST" = true ] && break
                }
            fi
        done
    fi

    [ "$any_failed" = false ]
}

run_raw() {
    cd "$PROJECT_ROOT"
    echo "Running code quality checks (raw mode)..."
    echo ""

    local start_time=$(date +%s.%N)
    local failed=false
    local has_warnings=false

    local subchecks=()
    [ "$SUMMARY" = true ] && subchecks=("${TEST_SUBCHECKS[@]}") || subchecks=("${TEST_SUBCHECKS_RAW[@]}")

    for check_def in "${CHECKS[@]}"; do
        IFS='|' read -r name make_target cmd fix_target <<< "$check_def"

        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo "Running: $name"
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

        if [[ "$name" == "Test suite" ]]; then
            for subcheck_def in "${subchecks[@]}"; do
                IFS='|' read -r subname submake subcmd coverage_target <<< "$subcheck_def"
                echo "  → $subname"
                echo ""

                if eval "$subcmd"; then
                    echo "  ${GREEN}✓${RESET} $subname passed"
                else
                    echo "  ${RED}✗${RESET} $subname failed"
                    failed=true
                    [ "$FAIL_FAST" = true ] && break 2
                fi
                echo ""
            done
        else
            # Parse fix_target for embedded coverage threshold (e.g., "docstring:95" -> "")
            local parsed=$(parse_fix_target "$fix_target")
            local actual_fix_target="${parsed#*|}"

            local cmd_exit_code=0
            eval "$cmd" || cmd_exit_code=$?

            if [ $cmd_exit_code -eq 0 ]; then
                echo "${GREEN}✓${RESET} $name passed"
            elif [ $cmd_exit_code -eq 42 ]; then  # EXIT_CODE_WARNING
                echo "${YELLOW}⚠${RESET} $name (warnings, run make cq)"
                has_warnings=true
                # Don't fail on warnings in non-strict mode
            else
                echo "${RED}✗${RESET} $name failed"
                [ -n "$actual_fix_target" ] && echo "  To fix: make $actual_fix_target"
                failed=true
                [ "$FAIL_FAST" = true ] && break
            fi
            echo ""
        fi
    done

    local elapsed=$(printf "%.1f" $(echo "$(date +%s.%N) - $start_time" | bc))
    echo ""
    if [ "$failed" = true ]; then
        echo "${RED}✗ Some checks failed${RESET} ${GRAY}in ${elapsed}s${RESET}"
        exit 1
    elif [ "$has_warnings" = true ]; then
        echo "${YELLOW}⚠ All checks passed with warnings${RESET} ${GRAY}in ${elapsed}s${RESET}"
    else
        echo "${GREEN}✓ All checks passed${RESET} ${GRAY}in ${elapsed}s${RESET}"
    fi
}

# === MAIN ===

main() {
    cd "$PROJECT_ROOT"

    [ "$RAW" = true ] && { run_raw; return $?; }

    echo "Running code quality checks..."
    echo ""

    # Calculate line numbers for cursor positioning
    local current_line=3
    for check_def in "${CHECKS[@]}"; do
        IFS='|' read -r name _ _ _ <<< "$check_def"
        CHECK_LINES["$name"]=$current_line
        current_line=$((current_line + 1))

        if [[ "$name" == "Test suite" ]]; then
            for subcheck_def in "${TEST_SUBCHECKS[@]}"; do
                IFS='|' read -r subname _ _ _ <<< "$subcheck_def"
                SUBCHECK_LINES["$subname"]=$current_line
                current_line=$((current_line + 1))
            done
        fi
    done
    TOTAL_LINES=$current_line

    # Print initial checkboxes
    for check_def in "${CHECKS[@]}"; do
        IFS='|' read -r name _ _ _ <<< "$check_def"
        printf "%b %s\n" "$CHECK_PENDING" "$name"

        if [[ "$name" == "Test suite" ]]; then
            for subcheck_def in "${TEST_SUBCHECKS[@]}"; do
                IFS='|' read -r subname _ _ _ <<< "$subcheck_def"
                printf "  %b %s\n" "$CHECK_PENDING" "$subname"
            done
        fi
    done

    # Hide cursor during updates
    tput civis 2>/dev/null || printf "\033[?25l"

    local start_time=$(date +%s.%N)
    local success=true

    run_checks || success=false

    check_interrupted

    # Show cursor and display results
    tput cnorm 2>/dev/null || printf "\033[?25h"
    local elapsed=$(printf "%.1f" $(echo "$(date +%s.%N) - $start_time" | bc))

    echo ""
    if [ "$success" = false ]; then
        local failure_count=$(wc -l < "${STATUS_DIR}/failures" 2>/dev/null || echo "1")
        echo -e "${RED}✗ ${failure_count} check(s) failed${RESET} ${GRAY}after ${elapsed}s${RESET}"
        echo ""
        display_failures
        display_skip_summary
        exit 1
    else
        # Check for warnings
        if [ -f "${STATUS_DIR}/warnings" ]; then
            local warning_count=$(wc -l < "${STATUS_DIR}/warnings")
            echo -e "${YELLOW}⚠ All checks passed with ${warning_count} warning(s)${RESET} ${GRAY}in ${elapsed}s${RESET}"
        else
            echo -e "${GREEN}✓ All checks passed${RESET} ${GRAY}in ${elapsed}s${RESET}"
        fi
        display_skip_summary
    fi
}

main "$@"
