#!/usr/bin/env bash

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

# Code quality check runner with progress indicators
# Supports parallel execution, coverage checking, and fail-fast mode
#
# IMPORTANT: Run via 'make check', not directly. The Makefile exports required
# variables (PYTHON, APPINFRA_DEV_PKG_NAME, APPINFRA_DEV_CQ_STRICT, APPINFRA_DEV_PROJECT_ROOT).
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
# shellcheck source=./_settings.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_settings.sh"
appinfra_trim_settings

# Exit code for "warnings but ok" from cq tool (violations in non-strict mode)
EXIT_CODE_WARNING=42

PYTHON="${PYTHON:-$(command -v python3)}"
PKG_NAME="${APPINFRA_DEV_PKG_NAME:-appinfra}"
CQ_STRICT="$(appinfra_bool APPINFRA_DEV_CQ_STRICT false)" || exit 2
CHECK_EXAMPLES="$(appinfra_bool APPINFRA_DEV_CHECK_EXAMPLES false)" || exit 2
CQ_SPDX="$(appinfra_bool APPINFRA_DEV_CQ_SPDX false)" || exit 2
# HOST:PORT for run_examples.py --pg; Makefile.dev derives it from Makefile.pg.
EXAMPLES_PG="${_APPINFRA_DEV_EXAMPLES_PG:-}"
COVERAGE_MARKERS="${APPINFRA_PYTEST_COVERAGE_MARKERS:-unit}"

# Coverage threshold precedence: CLI arg > env var > default (80)
# Set to 0 to disable coverage checking entirely
DEFAULT_COVERAGE_TARGET="${APPINFRA_PYTEST_COVERAGE_THRESHOLD:-80}"
COVERAGE_TARGET="${COVERAGE_TARGET:-$DEFAULT_COVERAGE_TARGET}"
if ! echo "$COVERAGE_TARGET" | grep -qE '^[0-9]+(\.[0-9]+)?$'; then
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
MYPY_FLAGS="${APPINFRA_DEV_MYPY_FLAGS:-}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${APPINFRA_DEV_PROJECT_ROOT:-$(dirname "$SCRIPT_DIR")}"

MAIN_PID=$$
DISPLAY_LOCK="/tmp/infra-check-display-lock-${MAIN_PID}"
STATUS_DIR="/tmp/infra-check-status-${MAIN_PID}"
mkdir -p "$STATUS_DIR"
# Full output of failed checks and of checks with slow tests, copied out of STATUS_DIR (removed
# on exit) so a failure or hang that does not reproduce on rerun can still be read. Each run, a
# concurrent one included, replaces the previous run's logs; concurrent runs in one tree also
# share .coverage and .mypy_cache.
KEPT_LOG_DIR="${PROJECT_ROOT}/.build/check"
# Rows added below the checklist (add_display_row). The count lives in a file because every
# check draws from its own background process and needs the current count to find its line.
DISPLAY_ROWS="${STATUS_DIR}/display-rows"

# A test still running after this many seconds is reported by check_pytest/pytest_hang.py: its
# node id and the stacks of its process go to the check's log, and the check gets a row below
# the checklist. The test is neither stopped nor failed, so on a slow machine this only adds
# rows. 0 disables it.
HANG_DUMP_SECONDS="${APPINFRA_PYTEST_HANG_DUMP_SECONDS:-120}"
if ! [[ "$HANG_DUMP_SECONDS" =~ ^[0-9]+$ ]]; then
    echo "Error: Invalid APPINFRA_PYTEST_HANG_DUMP_SECONDS: $HANG_DUMP_SECONDS" >&2
    exit 1
fi
export APPINFRA_PYTEST_HANG_DUMP_SECONDS="$HANG_DUMP_SECONDS"
# Prefix and flags for the pytest commands: check_pytest/pytest_hang.py (above) and
# check_pytest/pytest_exit_warnings.py, which makes warnings raised at interpreter exit print
# (see check_warnings). The plugins are files of their own next to this script, not part of the
# appinfra package: -p imports a plugin before pytest-cov starts, and importing anything under
# appinfra that early would leave the package's module-level lines unmeasured. Their directory
# holds only the plugins, so nothing else becomes importable in the tests.
PYTEST_PLUGIN_PATH="PYTHONPATH=$(printf '%q' "${SCRIPT_DIR}/check_pytest${PYTHONPATH:+:${PYTHONPATH}}") "
PYTEST_PLUGINS="-p pytest_hang -p pytest_exit_warnings"

# How a warning in a passing test check or example ends: strict when the project's pytest
# filterwarnings has a bare "error" (every warning an error), so the check fails; warn
# otherwise, so the check passes with a warning. Asked once from pytest_exit_warnings, in a run
# that only reads the configuration. A tool's own warning lines only ever warn.
WARNINGS_MODE=warn
if [ "$SKIP_TESTS" != true ]; then
    WARNINGS_MODE=$({ cd "$PROJECT_ROOT" && eval "${PYTEST_PLUGIN_PATH}${PYTHON} -m pytest -p pytest_exit_warnings --collect-only -q --noconftest -p no:cacheprovider --ignore-glob='*'" 2>&1 || true; } \
        | sed -nE 's/^=== exit warnings: (strict|warn) ===$/\1/p' | tail -1)
    WARNINGS_MODE="${WARNINGS_MODE:-warn}"
fi

# Terminal width for fit_slow_row, read here because stdout is the terminal only at the top
# level: inside $(...) it is a pipe. Empty without a terminal (CI), where rows are not cut.
DISPLAY_COLS=""
if [ -t 1 ]; then
    DISPLAY_COLS=$(stty size < /dev/tty 2>/dev/null | awk '{print $2}')
    [ "$DISPLAY_COLS" != 0 ] || DISPLAY_COLS=""  # a pseudo-terminal with no size set
fi

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
DOCSTRING_THRESHOLD="${APPINFRA_DEV_DOCSTRING_THRESHOLD:-80}"
MAX_INLINE_LINES=30

# Check definitions: "Name|Make Target|Command|Fix Target", listed from a file's outside in
# (license header, layout, lint, types, docstrings), then the slow ones: code quality, tests
declare -a CHECKS=()

# SPDX header check only if opted in (APPINFRA_DEV_CQ_SPDX=true).
# Off by default so closed-source repos that reuse this framework don't
# fail on files without SPDX-License-Identifier headers.
if [ "$CQ_SPDX" = "true" ]; then
    CHECKS+=("SPDX header check|cq.spdx|${PYTHON} -m appinfra.cli.cli -l error cq spdx|")
fi

CHECKS+=(
    "Formatting check|fmt.check|${PYTHON} -m ruff format --check .|fmt"
    "Linting|lint|lint_check|lint.fix"
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

# Build exclude flags from APPINFRA_DEV_CQ_EXCLUDE (subshell contains set -f scope)
CQ_EXCLUDE_FLAGS=""
if [ -n "${APPINFRA_DEV_CQ_EXCLUDE:-}" ]; then
    CQ_EXCLUDE_FLAGS=$(
        set -f  # Disable glob expansion to preserve patterns like "examples/*"
        sep=""
        for pat in ${APPINFRA_DEV_CQ_EXCLUDE}; do
            printf '%s--exclude "%s"' "$sep" "$pat"
            sep=" "
        done
    )
fi

# Extra ruff rules reported over the package as warnings, never failing: a comma-separated list
# of rule codes (empty or false = off; "-" not ":-" keeps an empty value). Rules that should fail
# the build belong in the project's ruff config.
CQ_LINT_SELECT="${APPINFRA_DEV_CQ_LINT_SELECT-C90,SIM,RET,PIE,PERF,FURB,C4}"

# Duplicated code (pylint) and dead private code checks over the package. Each takes false (off),
# warn (default: report the count, never fail) or strict (fail on findings); any case.
CQ_DUP="$(printf '%s' "${APPINFRA_DEV_CQ_DUP:-warn}" | tr '[:upper:]' '[:lower:]')"
CQ_DEAD="$(printf '%s' "${APPINFRA_DEV_CQ_DEAD:-warn}" | tr '[:upper:]' '[:lower:]')"
for _cq_var in APPINFRA_DEV_CQ_DUP:"$CQ_DUP" APPINFRA_DEV_CQ_DEAD:"$CQ_DEAD"; do
    case "${_cq_var#*:}" in
        false|warn|strict) ;;
        *) echo "Error: ${_cq_var%%:*} must be false, warn or strict, got: ${_cq_var#*:}" >&2; exit 1 ;;
    esac
done

# A check that warns ends its output with "Warnings: <summary>", which its line shows.

# Linting: the project's ruff rules fail the check; the CQ_LINT_SELECT rules only warn.
lint_check() {
    eval "${PYTHON} -m ruff check ." || return 1
    [ -n "$CQ_LINT_SELECT" ] && [ "$CQ_LINT_SELECT" != false ] || return 0
    local out count
    out=$(eval "${PYTHON} -m ruff check ${PKG_NAME}/ --select ${CQ_LINT_SELECT} --no-fix --exit-zero --output-format concise") || return 1
    count=$(printf '%s\n' "$out" | grep -cE '^[^ ].*:[0-9]+:[0-9]+: ' || true)
    [ "$count" -gt 0 ] || return 0
    printf '%s\n' "$out"
    echo "Warnings: ${count} warnings"
    return "$EXIT_CODE_WARNING"
}

# --strict for a cq tool whose mode is strict (true for APPINFRA_DEV_CQ_STRICT)
cq_strict_flag() {
    case "$1" in strict|true) echo "--strict" ;; esac
}

# Run one cq subcommand: a warning adds "<count> <label>" to CQ_SUMMARY, a failure sets CQ_FAILED.
# Without --strict, findings exit with EXIT_CODE_WARNING, so another nonzero exit is the tool
# failing; that only warns too, so a broken tool does not fail make check.
cq_tool() {
    local label="$1" strict="$2" args="$3" out rc=0 count
    out=$(eval "${PYTHON} -m appinfra.cli.cli -l error cq ${args} ${strict}" 2>&1) || rc=$?
    printf '%s\n' "$out"
    if [ "$rc" -eq "$EXIT_CODE_WARNING" ]; then
        count=$(printf '%s\n' "$out" | sed -nE 's/.*Violations( found)?: ([0-9]+).*/\2/p' | head -1)
        CQ_SUMMARY+=("${count:-?} ${label}")
    elif [ "$rc" -ne 0 ] && [ -z "$strict" ]; then
        CQ_SUMMARY+=("${label} did not run")
    elif [ "$rc" -ne 0 ]; then
        CQ_FAILED=true
    fi
}

# Code quality: function size (cq cf), plus duplicated and dead code when enabled. Every enabled
# tool runs; the check fails if one failed, and otherwise warns with a count per tool.
cq_check() {
    CQ_SUMMARY=()
    CQ_FAILED=false
    cq_tool size "$(cq_strict_flag "$CQ_STRICT")" "cf ${CQ_EXCLUDE_FLAGS}"
    [ "$CQ_DUP" = "false" ] || cq_tool dup "$(cq_strict_flag "$CQ_DUP")" "dup ${PKG_NAME}/ ${CQ_EXCLUDE_FLAGS}"
    [ "$CQ_DEAD" = "false" ] || cq_tool dead "$(cq_strict_flag "$CQ_DEAD")" "dead ${PKG_NAME}/ ${CQ_EXCLUDE_FLAGS}"
    [ "$CQ_FAILED" = false ] || return 1
    [ "${#CQ_SUMMARY[@]}" -gt 0 ] || return 0
    local summary
    printf -v summary '%s, ' "${CQ_SUMMARY[@]}"
    echo "Warnings: ${summary%, }"
    return "$EXIT_CODE_WARNING"
}

CQ_TARGET="cq"
[ "$CQ_STRICT" = "true" ] && CQ_TARGET="cq.strict"

# Docstring coverage check command (only if threshold > 0)
DOCSTRING_CMD="${PYTHON} -m interrogate -v ${PKG_NAME}/ --ignore-init-module --ignore-init-method --fail-under=${DOCSTRING_THRESHOLD}"

# Add docstring check only if threshold > 0
if awk "BEGIN {exit !($DOCSTRING_THRESHOLD > 0)}" 2>/dev/null; then
    CHECKS+=("Docstring coverage|cq.docstring.strict|${DOCSTRING_CMD}|docstring:${DOCSTRING_THRESHOLD}")
fi

# The slowest checks last: the rows above finish first, top down
CHECKS+=(
    "Code quality check|${CQ_TARGET}|cq_check|"
)

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
PERF_DIR="${APPINFRA_PYTEST_PERF_DIR:-tests}"
_MARKERS_FOUND=$(
    grep -rhoE 'pytest\.mark\.[a-z_][a-z0-9_]*' tests/ "$PERF_DIR" --include='*.py' 2>/dev/null \
        | cut -d. -f3 | sort -u | tr '\n' ' ' || true
)

# Emit the pytest command for a marker if any test uses it; otherwise a
# fast `(exit 5)` subshell that hits run_check's "no tests" branch
# without paying pytest's discovery cost. The subshell parens matter:
# bare `exit 5` under ``eval`` would kill run_check's own subshell
# before it could inspect the exit code, so ``wait -n`` in the parent
# would count the check as a failure. The optional fourth argument is the
# directory to collect from (default tests/).
_pytest_cmd_for() {
    local suite="$1" marker="$2" flags="$3" path="${4:-tests/}"
    case " $_MARKERS_FOUND " in
        *" $marker "*)
            echo "${PYTEST_PLUGIN_PATH}_APPINFRA_CHECK_PYTEST_SUITE=$suite ${PYTHON} -m pytest $path -m $marker ${PYTEST_PLUGINS} $flags"
            ;;
        *)
            echo "(exit 5)"
            ;;
    esac
}

# _APPINFRA_CHECK_PYTEST_SUITE prevents schema collisions when test suites run in parallel.
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
    TEST_SUBCHECKS+=("${COVERAGE_LABEL}|test.coverage|${PYTEST_PLUGIN_PATH}${COVERAGE_CORE_ENV}_APPINFRA_CHECK_PYTEST_SUITE=cov ${PYTHON} -m pytest tests/ ${COVERAGE_MARKER_ARG} ${PYTEST_PLUGINS} --cov=${PKG_NAME} --cov-report=term -q -rEfs ${PYTEST_PARALLEL_COVERAGE}|${COVERAGE_TARGET}")
    TEST_SUBCHECKS_RAW+=("${COVERAGE_LABEL}|test.coverage|${PYTEST_PLUGIN_PATH}${COVERAGE_CORE_ENV}_APPINFRA_CHECK_PYTEST_SUITE=cov ${PYTHON} -m pytest tests/ ${COVERAGE_MARKER_ARG} ${PYTEST_PLUGINS} --cov=${PKG_NAME} --cov-report=term-missing -rEfs ${PYTEST_PARALLEL_COVERAGE}|${COVERAGE_TARGET}")
fi

_standalone_suite unit        "Unit tests"        test.unit        unit
_standalone_suite integration "Integration tests" test.integration integ
_standalone_suite e2e         "E2E tests"         test.e2e         e2e
_standalone_suite security    "Security tests"    test.security    sec
# Performance tests run on one worker: timing tests measure against one quiet
# process rather than sibling workers, and only one process re-imports the test
# tree. A worker rather than in-process: a test that leaves a non-daemon thread
# running costs the controller's 10s exit timeout instead of hanging the run.
# APPINFRA_PYTEST_PERF_DIR narrows collection to where the performance tests live.
TEST_SUBCHECKS+=("Performance tests|test.perf|$(_pytest_cmd_for perf performance "--tb=short --no-header -q -rEfs -n 1" "${PERF_DIR}/")|")
TEST_SUBCHECKS_RAW+=("Performance tests|test.perf.v|$(_pytest_cmd_for perf performance "-v --tb=short -rEfs -n 1" "${PERF_DIR}/")|")

# Run the example scripts as the last test subcheck when opted in
# (APPINFRA_DEV_CHECK_EXAMPLES=true) and an examples directory exists. Same
# runner and flags as `make examples.check`; raw mode adds -v.
if [ "$CHECK_EXAMPLES" = "true" ] && [ -n "$EXAMPLES_DIR" ]; then
    # --full-output: the runner prints a failed example's whole output, so the kept log has it
    EXAMPLES_CMD="${PYTHON} ${SCRIPT_DIR}/run_examples.py ${EXAMPLES_DIR} --full-output${EXAMPLES_PG:+ --pg ${EXAMPLES_PG}}"
    TEST_SUBCHECKS+=("Examples|examples.check|${EXAMPLES_CMD}|")
    TEST_SUBCHECKS_RAW+=("Examples|examples.check|${EXAMPLES_CMD} -v|")
fi

declare -A CHECK_LINES
declare -A SUBCHECK_LINES
TOTAL_LINES=0
INTERRUPTED=false

# === CLEANUP ===

# Every process under check.sh, comma-separated, from one ps snapshot of the process table
process_tree() {
    ps -e -o pid= -o ppid= | awk -v root="$MAIN_PID" '
        { parent[$1] = $2 }
        END {
            for (pid in parent) {
                p = parent[pid]
                while (p != root && p in parent && p > 1) p = parent[p]
                if (p == root) list = list (list ? "," : "") pid
            }
            print list
        }'
}

# Stop every process check.sh started, at once, with KILL: pytest, the examples runner and the
# tools have no TERM cleanup worth waiting for. The tree is listed before the signal, from one
# snapshot. Signalling the background jobs alone is not enough: bash starts them with SIGINT
# ignored, and a signal to a check's subshell does not reach the pytest, xdist workers or
# examples runner running under it.
stop_children() {
    local pids
    pids=$(process_tree)
    # Bash reports a job killed by KILL ("line N: PID Killed run_check ..."), which is noise
    # to the user and moves the cursor under the display; a disowned job is not reported
    disown -a 2>/dev/null || true
    [ -z "$pids" ] || kill -KILL ${pids//,/ } 2>/dev/null || true
}

cleanup() {
    if [ "$BASHPID" -eq "$MAIN_PID" ]; then
        stop_children
        # Reap direct children before removing STATUS_DIR so killed bg subshells
        # can't still be in the middle of writing to it.
        wait 2>/dev/null || true
        close_display
        rm -rf "$STATUS_DIR" "$DISPLAY_LOCK" "${DISPLAY_LOCK}.d" 2>/dev/null || true
    fi
}

handle_interrupt() {
    INTERRUPTED=true
    stop_children
}

check_interrupted() {
    if [ "$INTERRUPTED" = true ]; then
        close_display
        tput cnorm 2>/dev/null || printf "\033[?25h"
        echo ""
        echo -e "${UI_MARK_FAIL} Interrupted by user"
        display_slow_logs
        cleanup
        exit 130
    fi
}

trap cleanup EXIT
trap handle_interrupt INT TERM HUP

# === DISPLAY HELPERS ===

# Serialize drawing. Every cursor move is relative to the bottom of the display, which moves
# when a row is added, so a writer holds the lock while it reads the row count and draws.
# flock where it exists; macOS has none, so fall back to a mkdir lock, waited on for at most 2s
# so a writer killed while holding it cannot freeze the display. Call inside a block that
# opens fd 200 on DISPLAY_LOCK.
lock_display() {
    if command -v flock &>/dev/null; then
        flock -x 200
        return 0
    fi
    local tries=200
    until mkdir "${DISPLAY_LOCK}.d" 2>/dev/null; do
        tries=$((tries - 1))
        [ "$tries" -gt 0 ] || return 0
        sleep 0.01
    done
}

# flock's lock goes with fd 200 at the end of the block; the mkdir lock is removed here
unlock_display() {
    command -v flock &>/dev/null || rmdir "${DISPLAY_LOCK}.d" 2>/dev/null || true
}

# True while checks may draw: until main prints below the display (close_display), and until
# STATUS_DIR, which holds the row count, is gone
display_open() {
    [ -d "$STATUS_DIR" ] && [ ! -e "${STATUS_DIR}/display-closed" ]
}

# Once main prints below the display, its last line is no longer where the row count says, so
# nothing may draw any more
close_display() {
    {
        lock_display
        [ -d "$STATUS_DIR" ] && : > "${STATUS_DIR}/display-closed"
        unlock_display
    } 200>"$DISPLAY_LOCK"
}

# The optional fifth argument separates the mark from the text: two spaces on the checklist
# (the default), one on the report rows below it (add_display_row)
update_line() {
    local line_num=$1 status=$2 name=$3 extra=$4 sep=${5:-  }
    {
        lock_display
        if display_open; then
            local added
            added=$(cat "$DISPLAY_ROWS" 2>/dev/null) || added=0
            local lines_up=$((TOTAL_LINES + added - line_num))
            [ $lines_up -gt 0 ] && printf "\033[${lines_up}A"
            printf "\r%b%s%s%s%b\n" "$UI_CLEAR" "$status" "$sep" "$name" "$extra"
            [ $lines_up -gt 1 ] && printf "\033[$((lines_up - 1))B"
            printf "\r"
        fi
        unlock_display
    } 200>"$DISPLAY_LOCK"
}

# Add a row below the checklist, the first after a blank line that sets the rows apart, and set
# ADDED_ROW to its line number for update_line (0 if the display is closed). A report row has
# one space after its mark, where the checklist has two.
add_display_row() {
    local status=$1 text=$2 extra=$3
    ADDED_ROW=0
    {
        lock_display
        if display_open; then
            local added
            added=$(cat "$DISPLAY_ROWS" 2>/dev/null) || added=0
            if [ "$added" -eq 0 ]; then
                printf "\r%b\n" "$UI_CLEAR"
                added=1
            fi
            printf "\r%b%s %s%b\n" "$UI_CLEAR" "$status" "$text" "$extra"
            ADDED_ROW=$((TOTAL_LINES + added))
            echo "$((added + 1))" > "$DISPLAY_ROWS"
        fi
        unlock_display
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

# Copy a check's log to KEPT_LOG_DIR and print the copy's path relative to PROJECT_ROOT. The
# file is named after the check's display name, which is unique (make targets are not: both
# mypy checks use "type"). The directory ignores itself, so projects need no .gitignore entry.
keep_log() {
    local logfile="$1" name="$2"
    mkdir -p "$KEPT_LOG_DIR"
    [ -f "${KEPT_LOG_DIR}/.gitignore" ] || echo "*" > "${KEPT_LOG_DIR}/.gitignore"
    local slug
    slug=$(echo "$name" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-|-$//g')
    local kept="${KEPT_LOG_DIR}/${slug}.log"
    cp "$logfile" "$kept" && echo "${kept#"$PROJECT_ROOT"/}"
}

# Fit a slow-test row to the terminal: a wrapped row would shift every line below it. The node
# id loses its start, so the file and test name stay. Without a terminal (CI) the row is kept
# whole: a log has no width, and a CI log keeps every row even when the job is killed.
fit_slow_row() {
    local name="$1" test_id="$2" extra_len="$3"
    if [ -n "$DISPLAY_COLS" ]; then
        # 4: "[⚠] "; 2: ": "; 1: margin, so the row never touches the last column
        local room=$((DISPLAY_COLS - 4 - ${#name} - 2 - extra_len - 1))
        if [ "${#test_id}" -gt "$room" ] && [ "$room" -gt 3 ]; then
            test_id="...${test_id: -$((room - 3))}"
        fi
    fi
    echo "${name}: ${test_id}"
}

# Fit a warning row to the terminal, like fit_slow_row, but the message loses its middle: its
# start says what was raised, its end where (the source location, a connection's dbname). Without
# a terminal (CI) the row is kept whole.
fit_warning_row() {
    local name="$1" message="$2" extra_len="$3"
    if [ -n "$DISPLAY_COLS" ]; then
        # 4: "[⚠] "; 2: ": "; 1: margin, so the row never touches the last column
        local room=$((DISPLAY_COLS - 4 - ${#name} - 2 - extra_len - 1))
        if [ "${#message}" -gt "$room" ] && [ "$room" -gt 3 ]; then
            # The start up to the object's repr ("connection "), the rest of the room to the end
            local head=$(((room - 3) / 2))
            if [[ "$message" == *" <"* ]]; then
                local lead="${message%% <*} "
                if [ "${#lead}" -lt "$head" ]; then
                    head=${#lead}
                fi
            fi
            local tail=$((room - 3 - head))
            message="${message:0:$head}...${message: -$tail}"
        fi
    fi
    echo "${name}: ${message}"
}

# While a pytest check runs, turn the lines pytest_hang writes to its log into rows below the
# checklist: a row for each test reported running past HANG_DUMP_SECONDS, rewritten once the
# test ends, and one for each test that left a thread running at exit. A check with a report
# has its log, which holds the stacks, kept and recorded for display_slow_logs. run_check's
# TERM means the command ended: one last pass reads what it wrote last.
watch_slow_tests() {
    local logfile="$1" name="$2"
    local stop=0 seen=0 line test_id took text kept=""
    local -A rows=()
    # The node id runs to the closing " ===": parametrized ids can contain spaces
    local report_re='=== test running >[0-9.]+s: (.+) ===' done_re='=== test done after ([0-9.]+s): (.+) ==='
    local thread_re='=== thread left running by (.+) ==='
    trap 'stop=1' TERM
    while :; do
        sleep 1 &
        wait $! 2>/dev/null || true
        display_open || return 0
        local lines=()
        mapfile -t lines < <(grep -oE "${report_re}|${done_re}|${thread_re}" "$logfile" 2>/dev/null)
        for line in "${lines[@]:$seen}"; do
            if [[ "$line" =~ $thread_re ]]; then
                # 20: room for " thread left running"
                text=$(fit_slow_row "$name" "${BASH_REMATCH[1]}" 20)
                add_display_row "${UI_MARK_WARN}" "$text" " ${UI_YELLOW}thread left running${UI_RESET}"
            elif [[ "$line" =~ $report_re ]]; then
                test_id="${BASH_REMATCH[1]}"
                # 16: room for the longer note, " running >NNNNs" or " took NNNN.Ns"
                text=$(fit_slow_row "$name" "$test_id" 16)
                add_display_row "${UI_MARK_WARN}" "$text" " ${UI_YELLOW}running >${HANG_DUMP_SECONDS}s${UI_RESET}"
                rows["$test_id"]=$ADDED_ROW
            elif [[ "$line" =~ $done_re ]] && [ -n "${rows[${BASH_REMATCH[2]}]:-}" ]; then
                took="${BASH_REMATCH[1]}"
                test_id="${BASH_REMATCH[2]}"
                text=$(fit_slow_row "$name" "$test_id" 16)
                update_line "${rows[$test_id]}" "${UI_MARK_WARN}" "$text" " ${UI_GRAY}took ${took}${UI_RESET}" " "
            fi
        done
        # Copy on news, and once more at the end for the complete log; record the first copy
        # at once, so an interrupt that stops this loop early still lists it
        if [ "${#lines[@]}" -gt "$seen" ] || { [ "$stop" -eq 1 ] && [ -n "$kept" ]; }; then
            seen=${#lines[@]}
            if [ -n "$kept" ]; then
                keep_log "$logfile" "$name" > /dev/null || true
            else
                kept=$(keep_log "$logfile" "$name") || kept=""
                [ -z "$kept" ] || echo "${name}|${kept}" >> "${STATUS_DIR}/slow"
            fi
        fi
        [ "$stop" -eq 0 ] || break
    done
}

# Name the kept logs of the checks that had slow tests, threads left running or leaks at exit;
# all are marked on the display above. A line's third field says what the log holds.
display_slow_logs() {
    [ -f "${STATUS_DIR}/slow" ] || return 0
    local name kept what
    while IFS='|' read -r name kept what; do
        echo -e "→ ${name}: ${what:-stacks} in ${UI_YELLOW}${kept}${UI_RESET}"
    done < "${STATUS_DIR}/slow"
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
            kept=$(keep_log "$logfile" "$name") && echo -e "→ Full output: ${UI_YELLOW}${kept}${UI_RESET}"
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

# The mode for a passing check's warnings: the project's (WARNINGS_MODE) for test and example
# checks, whose warnings come from the project's code; warn for a tool, whose warning lines are
# about the tool and its configuration
warnings_mode_for() {
    local name="$1" cmd="$2"
    if [[ "$cmd" == *" -m pytest "* || "$name" == "Examples" ]]; then
        echo "$WARNINGS_MODE"
    else
        echo warn
    fi
}

# The distinct warnings check_warnings.py finds in a log, as "count<TAB>kind<TAB>message". Run
# through eval like every check command: PYTHON may hold "~/..." or arguments. A scan that fails
# is a warning of its own, never "no warnings".
found_warnings() {
    local out rc=0
    out=$(eval "${PYTHON} $(printf '%q ' "${SCRIPT_DIR}/check_warnings.py" "$1" --root "$PROJECT_ROOT")" 2>&1) || rc=$?
    if [ "$rc" -ne 0 ]; then
        printf '1\ttool\tcheck_warnings.py failed (exit %s): %s\n' "$rc" "$(tail -1 <<< "$out")"
        return 0
    fi
    [ -z "$out" ] || printf '%s\n' "$out"
}

# What a warning row says after its message: where the warning was raised (nothing for a tool's
# own line), and how often when it repeats
warning_note() {
    local kind="$1" count="$2" note=""
    case "$kind" in
        session) note="in tests" ;;
        exit) note="at exit" ;;
    esac
    if [ "$count" -gt 1 ]; then
        note="${note:+${note} }(${count}×)"
    fi
    echo "$note"
}

# A passing check's warnings: a row below the checklist for each distinct one, like the
# slow-test rows, and the check's own line left to the caller. Warn records a warning and keeps
# the log for display_slow_logs. Strict returns 1 and sets warning_failure, a local of the
# caller, to the reason, so the caller records one failure even when coverage fails the check too.
check_warnings() {
    local name="$1" make_target="$2" logfile="$3" mode="$4"
    local found
    found=$(found_warnings "$logfile")
    [ -n "$found" ] || return 0
    local mark="${UI_MARK_WARN}"
    if [ "$mode" = strict ]; then
        mark="${UI_MARK_FAIL}"
    fi
    local count kind message note total=0
    while IFS=$'\t' read -r count kind message; do
        note=$(warning_note "$kind" "$count")
        add_display_row "$mark" "$(fit_warning_row "$name" "$message" "$((${#note} ? ${#note} + 1 : 0))")" \
            "${note:+ ${UI_YELLOW}${note}${UI_RESET}}"
        total=$((total + count))
    done <<< "$found"
    local text="${total} warning"
    if [ "$total" -gt 1 ]; then
        text="${text}s"
    fi
    if [ "$mode" = strict ]; then
        warning_failure="${text}: filterwarnings makes every warning an error"
        return 1
    fi
    record_warning "$name" "$text"
    local kept
    if kept=$(keep_log "$logfile" "$name"); then
        echo "${name}|${kept}|warnings" >> "${STATUS_DIR}/slow"
    fi
    return 0
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
        # The leading space matches tests/ as a whole argument, not the tail of perf_tests/
        if [[ "$cmd" == *" tests/e2e"* ]] && [ ! -d "tests/e2e" ]; then
            update_line "$line_num" "${UI_MARK_PENDING}" "${prefix}${name}" " ${UI_GRAY}(no tests)${UI_RESET}"
            return 0
        elif [[ "$cmd" == *" tests/"* ]] && [ ! -d "tests" ]; then
            update_line "$line_num" "${UI_MARK_PENDING}" "${prefix}${name}" " ${UI_GRAY}(no tests)${UI_RESET}"
            return 0
        fi
    fi

    # Execute and capture output
    local tmpfile="${STATUS_DIR}/check-${check_id}.log"
    local exit_code=0
    local _start=$SECONDS
    local watch_pid=""
    if [[ "$cmd" == *" -m pytest "* ]] && [ "$HANG_DUMP_SECONDS" -gt 0 ]; then
        watch_slow_tests "$tmpfile" "$name" &
        watch_pid=$!
    fi
    eval "$cmd" > "$tmpfile" 2>&1 || exit_code=$?
    if [ -n "$watch_pid" ]; then
        kill -TERM "$watch_pid" 2>/dev/null || true
        wait "$watch_pid" 2>/dev/null || true
    fi
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

            # Warnings get rows below the checklist; in strict mode they also fail the check,
            # whose line then shows its usual text with the failure mark
            local warning_failure="" pass_mark="${UI_MARK_OK}"
            if ! check_warnings "$name" "$make_target" "$tmpfile" "$(warnings_mode_for "$name" "$cmd")"; then
                pass_mark="${UI_MARK_FAIL}"
            fi

            # A failed Examples check takes the failure line below, not the unmet warning line
            if [[ "$name" == "Examples" ]] && [ -z "$warning_failure" ] && mark_examples_unmet "$line_num" "${prefix}${name}" "$tmpfile" "$timing_suffix"; then
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
                    update_line "$line_num" "$pass_mark" "${prefix}${name}" " ${UI_GRAY}(${actual}% ≥ ${target_display}%)${UI_RESET}${timing_suffix}"
                else
                    update_line "$line_num" "${UI_MARK_FAIL}" "${prefix}${name}" " ${UI_GRAY}(${actual}% < ${target_display}%)${UI_RESET}${timing_suffix}"
                    record_failure "$name" "$make_target" "" "$tmpfile" "Coverage: ${actual}% (target: ${target_display}%)${warning_failure:+; ${warning_failure}}"
                    return 1
                fi
            else
                update_line "$line_num" "$pass_mark" "${prefix}${name}" "${timing_suffix}"
            fi
            if [ -n "$warning_failure" ]; then
                record_failure "$name" "$make_target" "" "$tmpfile" "$warning_failure"
                return 1
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
        42)  # Warning: findings that do not fail the build (EXIT_CODE_WARNING)
            # The check's "Warnings: <summary>" line, e.g. "9 dup, 22 dead"
            local warning_summary=$(sed -n 's/^Warnings: //p' "$tmpfile" 2>/dev/null | tail -1)
            if [ -n "$warning_summary" ]; then
                update_line "$line_num" "${UI_MARK_WARN}" "${prefix}${name}" " ${UI_GRAY}(${warning_summary}, run make ${make_target})${UI_RESET}${timing_suffix}"
                record_warning "$name" "$warning_summary"
            else
                update_line "$line_num" "${UI_MARK_WARN}" "${prefix}${name}" " ${UI_GRAY}(run make ${make_target})${UI_RESET}${timing_suffix}"
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
                # Stop the remaining checks, and everything they started, immediately
                stop_children
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
                run_raw_subcheck "$subname" "$subcmd" || sub_exit_code=$?
                if [ $sub_exit_code -eq "$EXIT_CODE_WARNING" ]; then
                    has_warnings=true
                elif [ $sub_exit_code -ne 0 ] && [ $sub_exit_code -ne 5 ]; then
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
                echo "${UI_MARK_WARN} $name (warnings, run make ${make_target})"
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

# Run one test subcheck in raw mode: its output streams to the terminal, and a copy goes to a
# log for the warning scan (see check_warnings), whose findings follow the subcheck's line.
# Returns 0 (passed), 5 (no tests collected, shown like run_check's case 5), EXIT_CODE_WARNING
# (passed, with warnings) or a failing code.
run_raw_subcheck() {
    local subname="$1" subcmd="$2"
    local log="${STATUS_DIR}/raw-subcheck.log"
    # Through tee, pytest's stdout is a pipe: keep its colors when the terminal had them
    local colors=""
    [ -t 1 ] && colors="PY_COLORS=1 "
    local rc
    set +e
    # -i: on Ctrl-C tee keeps passing output until the check closes the pipe, so what pytest
    # prints on its way out still reaches the terminal; stop_children ends the rest
    eval "${colors}${subcmd}" 2>&1 | tee -i "$log"
    rc=${PIPESTATUS[0]}
    set -e

    local found="" note=""
    if [ "$rc" -eq 0 ]; then
        found=$(found_warnings "$log")
    fi
    if [ -n "$found" ]; then
        note=" ($(awk -F'\t' '{ n += $1 } END { print n }' <<< "$found") warnings)"
        if [ "$(warnings_mode_for "$subname" "$subcmd")" = strict ]; then
            rc=1
        else
            rc=$EXIT_CODE_WARNING
        fi
    fi
    case "$rc" in
        0) echo "  ${UI_MARK_OK} $subname passed" ;;
        5) echo "  ${UI_GRAY}[ ]${UI_RESET} $subname ${UI_GRAY}(no tests)${UI_RESET}" ;;
        "$EXIT_CODE_WARNING") echo "  ${UI_MARK_WARN} $subname passed${note}" ;;
        *) echo "  ${UI_MARK_FAIL} $subname failed${note}" ;;
    esac
    local count kind message
    while IFS=$'\t' read -r count kind message; do
        [ -n "$message" ] || continue
        echo "    - ${message} $(warning_note "$kind" "$count")"
    done <<< "$found"
    return "$rc"
}

# === MAIN ===

main() {
    cd "$PROJECT_ROOT"
    rm -rf "$KEPT_LOG_DIR"

    [ "$RAW" = true ] && { run_raw; return $?; }

    # Calculate line numbers for cursor positioning
    local current_line=1
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
    close_display

    # Show cursor and display results
    tput cnorm 2>/dev/null || printf "\033[?25h"
    local elapsed=$(printf "%.1f" $(echo "$(date +%s.%N) - $start_time" | bc))

    echo ""
    if [ "$success" = false ]; then
        local failure_count=$(wc -l < "${STATUS_DIR}/failures" 2>/dev/null || echo "1")
        echo -e "${UI_MARK_FAIL} ${failure_count} check(s) failed ${UI_GRAY}after ${elapsed}s${UI_RESET}"
        echo ""
        display_failures
        display_slow_logs
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
        display_slow_logs
        display_skip_summary
    fi
}

main "$@"
