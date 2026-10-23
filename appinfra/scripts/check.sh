#!/usr/bin/env bash

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

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
# --dist=worksteal (xdist ≥ 3.2): idle workers pull tests from busy peers,
# smoothing the tail when one shard's tests are slower than others'.
# Standalone suites use NPROC/4 workers so several suites in the parallel
# group don't oversubscribe cores. Coverage gets NPROC/2 because it
# absorbs one or more standalone suites (see FOLDED_MARKERS below), stays
# alive longer, and benefits from more workers as the others drop out.
PYTEST_JOBS=$(( NPROC / 4 > 2 ? NPROC / 4 : 2 ))
PYTEST_PARALLEL="-n ${PYTEST_JOBS} --dist=worksteal"
PYTEST_JOBS_COVERAGE=$(( NPROC / 2 > 2 ? NPROC / 2 : 2 ))
PYTEST_PARALLEL_COVERAGE="-n ${PYTEST_JOBS_COVERAGE} --dist=worksteal"
COVERAGE_TARGET=""
FAIL_FAST=false
RAW=false
SUMMARY=false
SKIP_TESTS=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --sequential) PARALLEL=false; PYTEST_PARALLEL="-n 0"; PYTEST_PARALLEL_COVERAGE="-n 0"; shift ;;
        --coverage-target) COVERAGE_TARGET="$2"; shift 2 ;;
        --fail-fast) FAIL_FAST=true; shift ;;
        --raw)
            RAW=true
            PARALLEL=false
            PYTEST_PARALLEL="-n 0"
            PYTEST_PARALLEL_COVERAGE="-n 0"
            FAIL_FAST=true
            shift
            ;;
        --raw-parallel)
            RAW=true
            PARALLEL=false
            FAIL_FAST=true
            # Keep PYTEST_PARALLEL at default for parallel pytest
            shift
            ;;
        --summary) SUMMARY=true; shift ;;
        --skip-tests) SKIP_TESTS=true; shift ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--sequential] [--coverage-target <percentage>] [--fail-fast] [--raw] [--raw-parallel] [--summary] [--skip-tests]"
            exit 1
            ;;
    esac
done

# === CONFIGURATION ===

# shellcheck source=./_ui.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_ui.sh"

# Exit code for "warnings but ok" from cq tool (violations in non-strict mode)
EXIT_CODE_WARNING=42

PYTHON="${PYTHON:-~/.venv/bin/python}"
PKG_NAME="${INFRA_DEV_PKG_NAME:-appinfra}"
CQ_STRICT="${INFRA_DEV_CQ_STRICT:-false}"
CHECK_EXAMPLES="${INFRA_DEV_CHECK_EXAMPLES:-false}"
# HOST:PORT for run_examples.py --pg; Makefile.dev derives it from Makefile.pg.
EXAMPLES_PG="${_INFRA_DEV_EXAMPLES_PG:-}"
COVERAGE_MARKERS="${INFRA_PYTEST_COVERAGE_MARKERS:-unit}"

# Coverage threshold precedence: CLI arg > env var > default (80)
# Set to 0 to disable coverage checking entirely
DEFAULT_COVERAGE_TARGET="${INFRA_PYTEST_COVERAGE_THRESHOLD:-80}"
COVERAGE_TARGET="${COVERAGE_TARGET:-$DEFAULT_COVERAGE_TARGET}"
if ! echo "$COVERAGE_TARGET" | grep -qE '^[0-9]+\.?[0-9]*$'; then
    echo "Error: Invalid coverage target: $COVERAGE_TARGET" >&2
    exit 1
fi

# Coverage's marker expression can subsume standalone test suites. When
# check.sh runs both a standalone suite and coverage over the same marker
# set, both execute the same work with only a fraction of the effective
# parallelism. Parse the marker expression so we can drop the redundant
# standalone lines.
#
# Recognizes:
#   ""            → coverage runs all tests → fold every standalone suite
#   "<name>"      → fold that suite if it's in the standalone set
#   "<a> or <b>…" → fold each named suite in the standalone set
# Anything else (`and`, `not`, parens, unknown names) → no folding.
# Performance is never folded — perf runs isolated for accurate timing.
#
# Only fold when coverage will actually run. When COVERAGE_TARGET is 0
# (coverage disabled per-project), folding a suite would drop it without
# anywhere to fold it INTO — the standalone line vanishes and no tests
# from that marker execute at all.
FOLDED_MARKERS=""
_STANDALONE_MARKERS="unit integration e2e security"
if awk "BEGIN {exit !($COVERAGE_TARGET > 0)}" 2>/dev/null; then
    if [ -z "$COVERAGE_MARKERS" ]; then
        FOLDED_MARKERS="$_STANDALONE_MARKERS"
    elif [[ "$COVERAGE_MARKERS" =~ ^[a-z0-9_]+([[:space:]]+or[[:space:]]+[a-z0-9_]+)*$ ]]; then
        for _m in $(echo "$COVERAGE_MARKERS" | sed -E 's/[[:space:]]+or[[:space:]]+/ /g'); do
            case " $_STANDALONE_MARKERS " in
                *" $_m "*) FOLDED_MARKERS="${FOLDED_MARKERS:+$FOLDED_MARKERS }$_m" ;;
            esac
        done
    fi
fi

# Coverage subcheck's display label: fold-prefixed. E.g. FOLDED_MARKERS
# = "unit integration" → "Unit & Integration & Coverage"; empty → just
# "Coverage".
_cov_prefix=""
for _m in unit integration e2e security; do
    case " $FOLDED_MARKERS " in
        *" $_m "*)
            case "$_m" in
                unit) _label="Unit" ;;
                integration) _label="Integration" ;;
                e2e) _label="E2E" ;;
                security) _label="Security" ;;
            esac
            _cov_prefix="${_cov_prefix}${_label} & "
            ;;
    esac
done
COVERAGE_LABEL="${_cov_prefix}Coverage tests"
MYPY_FLAGS="${INFRA_DEV_MYPY_FLAGS:-}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${INFRA_DEV_PROJECT_ROOT:-$(dirname "$SCRIPT_DIR")}"

MAIN_PID=$$
DISPLAY_LOCK="/tmp/infra-check-display-lock-${MAIN_PID}"
STATUS_DIR="/tmp/infra-check-status-${MAIN_PID}"
mkdir -p "$STATUS_DIR"
# Failed checks' full output, copied out of STATUS_DIR (removed on exit) so a failure that
# does not reproduce on rerun can still be read. Each run replaces the previous run's logs.
FAILED_LOG_DIR="${PROJECT_ROOT}/.build/check"

# Coverage tracer: on Python 3.12+, use sys.monitoring (PEP 669) via
# COVERAGE_CORE=sysmon — roughly 2x faster than the default C-tracer on
# Python-heavy suites. coverage.py refuses sysmon on 3.11 (raises
# CoverageException), so the env var is set only when the interpreter is
# 3.12 or newer; 3.11 keeps the C-tracer.
COVERAGE_CORE_ENV=""
if ${PYTHON} -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" 2>/dev/null; then
    COVERAGE_CORE_ENV="COVERAGE_CORE=sysmon "
fi

# Docstring coverage threshold (0 to disable)
DOCSTRING_THRESHOLD="${INFRA_DEV_DOCSTRING_THRESHOLD:-80}"
MAX_INLINE_LINES=30

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

# Add SPDX header check only if opted in (INFRA_DEV_CQ_SPDX=true).
# Off by default so closed-source repos that reuse this framework don't
# fail on files without SPDX-License-Identifier headers.
CQ_SPDX="${INFRA_DEV_CQ_SPDX:-false}"
if [ "$CQ_SPDX" = "true" ]; then
    CHECKS+=("SPDX header check|cq.spdx|${PYTHON} -m appinfra.cli.cli -l error cq spdx|")
fi

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

# Scan tests/ once for every pytest marker actually declared, so empty
# suites can skip the pytest invocation entirely. Full pytest with xdist
# spends 5–20s per invocation just importing conftests and spawning
# workers before it even applies the -m filter and finds zero matches;
# on a heavy-import repo this is pure waste. A single grep pass
# extracts the marker set (~tens of ms) and standalone suites whose
# marker isn't present short-circuit to the "no tests" display.
#
# Recognizes ``pytest.mark.<name>`` — the substring shared by decorator
# usage (`@pytest.mark.X`) and module-level `pytestmark = pytest.mark.X`
# (including lists). Dynamic markers applied by
# ``pytest_collection_modifyitems`` hooks are missed; standard patterns
# are not.
_MARKERS_FOUND=$(
    grep -rhoE 'pytest\.mark\.[a-z_][a-z0-9_]*' tests/ --include='*.py' 2>/dev/null \
        | cut -d. -f3 | sort -u | tr '\n' ' ' || true
)

# Emit the pytest command for a marker if any test uses it; otherwise a
# fast `(exit 5)` subshell that hits run_check's "no tests" branch
# without paying pytest's discovery cost. The subshell parens matter:
# bare `exit 5` under ``eval`` would kill run_check's own subshell
# before it could inspect the exit code, so ``wait -n`` in the parent
# would count the check as a failure.
_pytest_cmd_for() {
    local suite="$1" marker="$2" flags="$3"
    case " $_MARKERS_FOUND " in
        *" $marker "*)
            echo "INFRA_CHECK_PYTEST_SUITE=$suite ${PYTHON} -m pytest tests/ -m $marker $flags"
            ;;
        *)
            echo "(exit 5)"
            ;;
    esac
}

# INFRA_CHECK_PYTEST_SUITE prevents schema collisions when test suites run in parallel.
# Each suite gets unique schema names: unit_gw0, integ_gw0, e2e_gw0, etc.
#
# Standalone suites are skipped when coverage subsumes their marker (see
# FOLDED_MARKERS above). Perf is always separate — coverage never folds it.
_standalone_suite() {
    local marker="$1" name="$2" target="$3" suite="$4"
    case " $FOLDED_MARKERS " in
        *" $marker "*) return ;;
    esac
    TEST_SUBCHECKS+=("$name|$target|$(_pytest_cmd_for "$suite" "$marker" "--tb=short --no-header -q -rEfs ${PYTEST_PARALLEL}")|")
    TEST_SUBCHECKS_RAW+=("$name|$target.v|$(_pytest_cmd_for "$suite" "$marker" "-v --tb=short -rEfs ${PYTEST_PARALLEL}")|")
}
declare -a TEST_SUBCHECKS=()
declare -a TEST_SUBCHECKS_RAW=()

# Coverage subcheck goes first — it subsumes at least one standalone
# suite (see FOLDED_MARKERS above) and stays alive longest in the
# parallel group; leading the list keeps its running/completed state
# obvious. Uses NPROC/2 workers (see PYTEST_PARALLEL_COVERAGE above).
if awk "BEGIN {exit !($COVERAGE_TARGET > 0)}" 2>/dev/null; then
    TEST_SUBCHECKS+=("${COVERAGE_LABEL}|test.coverage|${COVERAGE_CORE_ENV}INFRA_CHECK_PYTEST_SUITE=cov ${PYTHON} -m pytest tests/ ${COVERAGE_MARKER_ARG} --cov=${PKG_NAME} --cov-report=term -q -rEfs ${PYTEST_PARALLEL_COVERAGE}|${COVERAGE_TARGET}")
    TEST_SUBCHECKS_RAW+=("${COVERAGE_LABEL}|test.coverage|${COVERAGE_CORE_ENV}INFRA_CHECK_PYTEST_SUITE=cov ${PYTHON} -m pytest tests/ ${COVERAGE_MARKER_ARG} --cov=${PKG_NAME} --cov-report=term-missing -rEfs ${PYTEST_PARALLEL_COVERAGE}|${COVERAGE_TARGET}")
fi

_standalone_suite unit        "Unit tests"        test.unit        unit
_standalone_suite integration "Integration tests" test.integration integ
_standalone_suite e2e         "E2E tests"         test.e2e         e2e
_standalone_suite security    "Security tests"    test.security    sec
# Performance tests skip --dist=worksteal — the work-stealing overhead and
# contention skews throughput measurements. Plain -n keeps parallelism for
# multi-test discovery but distributes tests up front, not mid-run.
TEST_SUBCHECKS+=("Performance tests|test.perf|$(_pytest_cmd_for perf performance "--tb=short --no-header -q -rEfs -n ${PYTEST_JOBS}")|")
TEST_SUBCHECKS_RAW+=("Performance tests|test.perf.v|$(_pytest_cmd_for perf performance "-v --tb=short -rEfs -n ${PYTEST_JOBS}")|")

# Run the example scripts as the last test subcheck when opted in
# (INFRA_DEV_CHECK_EXAMPLES=true) and an examples directory exists. Same
# runner and flags as `make examples.check`; raw mode adds -v.
if [ "$CHECK_EXAMPLES" = "true" ] && [ -n "$EXAMPLES_DIR" ]; then
    EXAMPLES_CMD="${PYTHON} ${SCRIPT_DIR}/run_examples.py ${EXAMPLES_DIR}${EXAMPLES_PG:+ --pg ${EXAMPLES_PG}}"
    TEST_SUBCHECKS+=("Examples|examples.check|${EXAMPLES_CMD}|")
    TEST_SUBCHECKS_RAW+=("Examples|examples.check|${EXAMPLES_CMD} -v|")
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
        # Reap direct children before removing STATUS_DIR so killed bg subshells
        # can't still be in the middle of writing to it.
        wait 2>/dev/null || true
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
        echo -e "${UI_MARK_FAIL} Interrupted by user"
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
        printf "\r%b%s  %s%b\n" "$UI_CLEAR" "$status" "$name" "$extra"
        [ $lines_up -gt 1 ] && printf "\033[$((lines_up - 1))B"
        printf "\r"
    } 200>"$DISPLAY_LOCK"
}

format_log_output() {
    local logfile="$1" max_lines="$2"
    local total_lines
    total_lines=$(wc -l < "$logfile" 2>/dev/null || echo "0")
    [ "$total_lines" -eq 0 ] && return

    echo ""
    local failed_lines
    failed_lines=$(grep -E "^(FAILED|ERROR) " "$logfile" 2>/dev/null || true)
    if [ -n "$failed_lines" ]; then
        echo -e "${UI_GRAY}Failed tests:${UI_RESET}"
        echo "$failed_lines"
        echo ""
        local error_lines
        error_lines=$(grep -E "^E\s+" "$logfile" 2>/dev/null | head -10 || true)
        [ -n "$error_lines" ] && echo -e "${UI_GRAY}Errors:${UI_RESET}" && echo "$error_lines"
    else
        echo -e "${UI_GRAY}Output:${UI_RESET}"
        if [ "$total_lines" -le "$max_lines" ]; then
            cat "$logfile"
        else
            local hidden=$((total_lines - max_lines))
            echo -e "${UI_GRAY}... ($hidden lines hidden)${UI_RESET}"
            tail -n "$max_lines" "$logfile"
        fi
    fi
}

# Copy a failed check's log to FAILED_LOG_DIR and print the copy's path relative to
# PROJECT_ROOT. The directory ignores itself, so projects need no .gitignore entry.
keep_failed_log() {
    local logfile="$1" make_target="$2"
    mkdir -p "$FAILED_LOG_DIR"
    [ -f "${FAILED_LOG_DIR}/.gitignore" ] || echo "*" > "${FAILED_LOG_DIR}/.gitignore"
    local kept="${FAILED_LOG_DIR}/${make_target:-$(basename "$logfile" .log)}.log"
    cp "$logfile" "$kept" && echo "${kept#"$PROJECT_ROOT"/}"
}

display_failures() {
    [ -f "${STATUS_DIR}/failures" ] || return 0

    while IFS='|' read -r name make_target fix_target logfile extra; do
        echo -e "${UI_RED}ERROR: ${name} failed${UI_RESET}"
        [ -n "$extra" ] && echo -e "→ ${extra}"
        [ -n "$make_target" ] && echo -e "→ To investigate: ${UI_YELLOW}make ${make_target}${UI_RESET}"
        [ -n "$fix_target" ] && echo -e "→ To fix: ${UI_YELLOW}make ${fix_target}${UI_RESET}"
        if [ -n "$logfile" ] && [ -f "$logfile" ]; then
            local kept
            kept=$(keep_failed_log "$logfile" "$make_target") && echo -e "→ Full output: ${UI_YELLOW}${kept}${UI_RESET}"
            [ "$FAIL_FAST" = true ] && format_log_output "$logfile" "$MAX_INLINE_LINES"
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
    [ -d "$STATUS_DIR" ] || return 0
    # Parses pytest's `SKIPPED [count] location: reason` short-summary lines.
    # This format is only emitted when pytest is invoked with `-r` containing
    # `s` (e.g. `-rEfs`) — all test subchecks in TEST_SUBCHECKS use `-rEfs`.
    # If that flag is ever dropped, this banner silently empties.
    #
    # mapfile + for-loop, NOT `grep | while`: a pipeline runs the loop body in a
    # grandchild subshell that can outlive a SIGKILL on this bg job and keep
    # writing to STATUS_DIR after main has rm -rf'd it.
    local lines=()
    mapfile -t lines < <(grep -E "^SKIPPED \[" "$logfile" 2>/dev/null) || true
    local line count reason
    for line in "${lines[@]}"; do
        count=$(echo "$line" | sed -E 's/^SKIPPED \[([0-9]+)\].*/\1/')
        reason=$(echo "$line" | sed -E 's/^SKIPPED \[[0-9]+\] [^:]+:([0-9]+:)? //')
        # Skip reasons prefixed with [expected] (from @pytest.mark.expected_skip)
        if [[ "$reason" == "[expected] "* ]]; then
            continue
        fi
        if [ -n "$count" ] && [ -n "$reason" ]; then
            [ -d "$STATUS_DIR" ] || return 0
            printf '%s\t%s\n' "$count" "$reason" >> "${STATUS_DIR}/skips"
        fi
    done
}

# Print one "N <noun> skipped" block from a tab-delimited "count<TAB>reason"
# file, reasons aggregated and sorted by count. Silent when the file is
# absent or empty.
display_skips() {
    local skipfile="$1" noun="$2"
    [ -f "$skipfile" ] || return 0

    declare -A skip_reasons
    local total_skipped=0

    while IFS=$'\t' read -r count reason; do
        skip_reasons["$reason"]=$((${skip_reasons["$reason"]:-0} + count))
        total_skipped=$((total_skipped + count))
    done < "$skipfile"

    [ $total_skipped -eq 0 ] && return 0

    local word="${noun}"
    [ $total_skipped -eq 1 ] && word="${noun%s}"
    echo ""
    echo -e "${UI_MARK_WARN} Warning: ${total_skipped} ${word} skipped"

    # Tab delimiter keeps reasons with spaces or colons intact
    for reason in "${!skip_reasons[@]}"; do
        printf '%s\t%s\n' "${skip_reasons[$reason]}" "$reason"
    done | sort -t$'\t' -k1 -rn | while IFS=$'\t' read -r count reason; do
        printf "  ${UI_GRAY}- %s skipped: %s${UI_RESET}\n" "$count" "$reason"
    done
}

display_skip_summary() {
    display_skips "${STATUS_DIR}/skips" "tests"
    display_skips "${STATUS_DIR}/example_skips" "examples"
}

# The examples runner's summary ends with "N unmet (reason[, reason])" when
# files declared a service (`# ci-requires:`) that was unreachable. Show that
# count on the Examples line with a warning mark and record it for the
# examples block of the skip summary. Returns 1 when nothing was unmet.
mark_examples_unmet() {
    local line_num="$1" label="$2" logfile="$3" timing_suffix="${4:-}"
    local clause
    clause=$(grep -oE '[0-9]+ unmet \([^)]*\)' "$logfile" 2>/dev/null | tail -1)
    [ -n "$clause" ] || return 1
    local count="${clause%% *}"
    local reasons="${clause#*(}"
    reasons="${reasons%)}"
    update_line "$line_num" "${UI_MARK_WARN}" "$label" " ${UI_GRAY}(${count} skipped: ${reasons})${UI_RESET}${timing_suffix}"
    [ -d "$STATUS_DIR" ] && printf '%s\t%s\n' "$count" "$reasons" >> "${STATUS_DIR}/example_skips"
    return 0
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
    update_line "$line_num" "${UI_MARK_RUNNING}" "${prefix}${name}" ""

    # For test subchecks, check if required directory exists first
    # This prevents hangs from pytest-xdist or unittest on non-existent directories
    if [ "$is_subcheck" = true ]; then
        if [[ "$cmd" == *"tests/e2e"* ]] && [ ! -d "tests/e2e" ]; then
            update_line "$line_num" "${UI_MARK_PENDING}" "${prefix}${name}" " ${UI_GRAY}(no tests)${UI_RESET}"
            return 0
        elif [[ "$cmd" == *"tests/"* ]] && [ ! -d "tests" ]; then
            update_line "$line_num" "${UI_MARK_PENDING}" "${prefix}${name}" " ${UI_GRAY}(no tests)${UI_RESET}"
            return 0
        fi
    fi

    # Execute and capture output
    local tmpfile="${STATUS_DIR}/check-${check_id}.log"
    local exit_code=0
    local _start=$SECONDS
    eval "$cmd" > "$tmpfile" 2>&1 || exit_code=$?
    local _elapsed=$((SECONDS - _start))

    # Timing suffix appended to every result line for this check. Muted
    # below the noise threshold so the display stays clean — pre-test
    # lint checks that finish in a second or two aren't worth annotating.
    local timing_suffix=""
    if [ "$_elapsed" -ge 5 ]; then
        timing_suffix=" ${UI_GRAY}[${_elapsed}s]${UI_RESET}"
    fi

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

            if [[ "$name" == "Examples" ]] && mark_examples_unmet "$line_num" "${prefix}${name}" "$tmpfile" "$timing_suffix"; then
                :  # line carries the warning mark and skip count
            elif [ -n "$coverage_target" ]; then
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
                    update_line "$line_num" "${UI_MARK_OK}" "${prefix}${name}" " ${UI_GRAY}(${actual}% ≥ ${target_display}%)${UI_RESET}${timing_suffix}"
                else
                    update_line "$line_num" "${UI_MARK_FAIL}" "${prefix}${name}" " ${UI_GRAY}(${actual}% < ${target_display}%)${UI_RESET}${timing_suffix}"
                    record_failure "$name" "$make_target" "" "$tmpfile" "Coverage: ${actual}% (target: ${target_display}%)"
                    return 1
                fi
            else
                update_line "$line_num" "${UI_MARK_OK}" "${prefix}${name}" "${timing_suffix}"
            fi
            rm -f "$tmpfile"
            ;;
        1)  # For docstring check, exit code 1 means coverage below threshold
            if [[ "$name" == *"Docstring"* ]] && [ -n "$coverage_target" ]; then
                local actual=$(parse_docstring_coverage "$tmpfile")
                # Format target to 1 decimal for consistent display
                local target_display=$(awk "BEGIN {printf \"%.1f\", int($coverage_target * 10) / 10}")
                update_line "$line_num" "${UI_MARK_FAIL}" "${prefix}${name}" " ${UI_GRAY}(${actual}% < ${target_display}%)${UI_RESET}${timing_suffix}"
                record_failure "$name" "$make_target" "" "$tmpfile" "Coverage: ${actual}% (target: ${target_display}%)"
                return 1
            fi
            # Fall through to default failure handling for non-docstring checks
            update_line "$line_num" "${UI_MARK_FAIL}" "${prefix}${name}" "${timing_suffix}"
            record_failure "$name" "$make_target" "$fix_target" "$tmpfile"
            return 1
            ;;
        5)  # No tests collected
            update_line "$line_num" "${UI_MARK_PENDING}" "${prefix}${name}" " ${UI_GRAY}(no tests)${UI_RESET}${timing_suffix}"
            rm -f "$tmpfile"
            ;;
        42)  # Warning: violations found but non-strict mode (EXIT_CODE_WARNING)
            # Extract violation count from output if available
            local warning_count=$(grep -oP '(?<=Violations found: )\d+|(?<=Violations: )\d+' "$tmpfile" 2>/dev/null | head -1)
            if [ -n "$warning_count" ]; then
                update_line "$line_num" "${UI_MARK_WARN}" "${prefix}${name}" " ${UI_GRAY}(${warning_count} violations, run make cq)${UI_RESET}${timing_suffix}"
                record_warning "$name" "$warning_count"
            else
                update_line "$line_num" "${UI_MARK_WARN}" "${prefix}${name}" " ${UI_GRAY}(run make cq)${UI_RESET}${timing_suffix}"
                record_warning "$name"
            fi
            rm -f "$tmpfile"
            # Return 0 - warnings don't fail the build in non-strict mode
            ;;
        *)  # Failure
            update_line "$line_num" "${UI_MARK_FAIL}" "${prefix}${name}" "${timing_suffix}"
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
    update_line "$line_num" "${UI_MARK_RUNNING}" "Test suite" ""

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
                [ "$FAIL_FAST" = true ] && { update_line "$line_num" "${UI_MARK_FAIL}" "Test suite" ""; return 1; }
            fi
        done
    fi

    if [ -f "${STATUS_DIR}/failures" ]; then
        update_line "$line_num" "${UI_MARK_FAIL}" "Test suite" ""
        return 1
    else
        update_line "$line_num" "${UI_MARK_OK}" "Test suite" ""
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
                update_line "$line_num" "${UI_MARK_RUNNING}" "Test suite" ""
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
                update_line "$test_suite_line" "${UI_MARK_FAIL}" "Test suite" ""
                return 1
            }
            IFS='|' read -r subname submake subcmd coverage_target <<< "$perf_subcheck"
            local subline=${SUBCHECK_LINES["$subname"]}
            run_check "$subname" "$subcmd" "$subline" true "$coverage_target" "" "$submake" || any_failed=true
        fi

        # Update test suite status - only if tests enabled
        if [ -n "$test_suite_line" ]; then
            if [ -f "${STATUS_DIR}/failures" ]; then
                update_line "$test_suite_line" "${UI_MARK_FAIL}" "Test suite" ""
            else
                update_line "$test_suite_line" "${UI_MARK_OK}" "Test suite" ""
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

                local sub_exit_code=0
                eval "$subcmd" || sub_exit_code=$?
                # pytest exit 5 = no tests collected; treat as gray-skip to match
                # run_check's classification (see case 5 in run_check above).
                if [ $sub_exit_code -eq 0 ]; then
                    echo "  ${UI_MARK_OK} $subname passed"
                elif [ $sub_exit_code -eq 5 ]; then
                    echo "  ${UI_GRAY}[ ]${UI_RESET} $subname ${UI_GRAY}(no tests)${UI_RESET}"
                else
                    echo "  ${UI_MARK_FAIL} $subname failed"
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
                echo "${UI_MARK_OK} $name passed"
            elif [ $cmd_exit_code -eq 42 ]; then  # EXIT_CODE_WARNING
                echo "${UI_MARK_WARN} $name (warnings, run make cq)"
                has_warnings=true
                # Don't fail on warnings in non-strict mode
            else
                echo "${UI_MARK_FAIL} $name failed"
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
        echo "${UI_MARK_FAIL} Some checks failed ${UI_GRAY}in ${elapsed}s${UI_RESET}"
        exit 1
    elif [ "$has_warnings" = true ]; then
        echo "${UI_MARK_WARN} All checks passed with warnings ${UI_GRAY}in ${elapsed}s${UI_RESET}"
    else
        echo "${UI_MARK_OK} All checks passed ${UI_GRAY}in ${elapsed}s${UI_RESET}"
    fi
}

# === MAIN ===

main() {
    cd "$PROJECT_ROOT"
    rm -rf "$FAILED_LOG_DIR"

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
        printf "%b  %s\n" "$UI_MARK_PENDING" "$name"

        if [[ "$name" == "Test suite" ]]; then
            for subcheck_def in "${TEST_SUBCHECKS[@]}"; do
                IFS='|' read -r subname _ _ _ <<< "$subcheck_def"
                printf "%b    %s\n" "$UI_MARK_PENDING" "$subname"
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
        echo -e "${UI_MARK_FAIL} ${failure_count} check(s) failed ${UI_GRAY}after ${elapsed}s${UI_RESET}"
        echo ""
        display_failures
        display_skip_summary
        exit 1
    else
        # Check for warnings
        if [ -f "${STATUS_DIR}/warnings" ]; then
            local warning_count=$(wc -l < "${STATUS_DIR}/warnings")
            echo -e "${UI_MARK_WARN} All checks passed with ${warning_count} warning(s) ${UI_GRAY}in ${elapsed}s${UI_RESET}"
        else
            echo -e "${UI_MARK_OK} All checks passed ${UI_GRAY}in ${elapsed}s${UI_RESET}"
        fi
        display_skip_summary
    fi
}

main "$@"
