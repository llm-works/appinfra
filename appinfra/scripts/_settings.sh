# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

# _settings.sh — helpers for appinfra's scripts (sourced, not run)
#
# One rule for every on/off setting, the same as Makefile.config's and
# appinfra/ui/_env.py's: true, 1, y, yes turn it on; false, 0, n, no turn it
# off; any case; surrounding whitespace ignored; unset takes the default;
# anything else, empty included, is an error.

# appinfra_trim VALUE: prints VALUE without leading or trailing whitespace.
appinfra_trim() {
    local value="$1"
    value="${value#"${value%%[![:space:]]*}"}"
    printf '%s' "${value%"${value##*[![:space:]]}"}"
}

# appinfra_trim_settings: trims every APPINFRA_* variable in place. make keeps
# the spaces before a trailing comment (APPINFRA_X ?= true  # note) and
# exports the value as written.
appinfra_trim_settings() {
    local name
    for name in ${!APPINFRA_@}; do
        printf -v "$name" '%s' "$(appinfra_trim "${!name}")"
    done
}

# appinfra_bool NAME DEFAULT: prints true or false for the variable NAME, or
# prints an error to stderr and returns 2.
appinfra_bool() {
    local name="$1" value
    value="$(appinfra_trim "${!name-$2}" | tr '[:upper:]' '[:lower:]')"
    case "$value" in
        true|1|y|yes) echo true ;;
        false|0|n|no) echo false ;;
        *)
            echo "Error: $name=${!name:-} is not a boolean: use true, 1, y, yes or false, 0, n, no" >&2
            return 2
            ;;
    esac
}

# appinfra_setting NAME DEFAULT TYPE: prints the variable NAME's value, DEFAULT
# when it is unset, or prints an error to stderr and returns 2 when the value is
# not of TYPE. check.sh puts these values into the commands it runs, so no type
# admits anything the shell would read as syntax:
#   percent     a number from 0 to 100, e.g. 80 or 95.5 (as Makefile.config's)
#   package     a Python identifier: the package's directory
#   decorators  dotted names separated by whitespace, e.g. router.get; may be empty
#   rules       ruff rule codes separated by commas, e.g. C90,SIM; empty or false: none
#   suites      suite names (unit integration e2e security performance) separated by
#               whitespace; may be empty
#   share       a worker share: a fraction below 1, e.g. 0.25 or .5 (that share of the
#               CPUs), or a whole number above 0, e.g. 8 (that many workers)
appinfra_setting() {
    local name="$1" kind="$3" value pattern what
    local dotted='[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*'
    value="${!name-$2}"
    case "$kind" in
        percent) pattern='^([0-9]{1,2}(\.[0-9]+)?|100(\.0+)?)$'
            what='a percent: use a number from 0 to 100, e.g. 80 or 95.5' ;;
        package) pattern='^[A-Za-z_][A-Za-z0-9_]*$'
            what='a package name: use a Python identifier, e.g. mypkg' ;;
        decorators) pattern="^[[:space:]]*(${dotted}([[:space:]]+${dotted})*)?[[:space:]]*\$"
            what='a list of decorator names: use dotted names separated by spaces, e.g. router.get' ;;
        rules) pattern='^(false|[A-Z]+[0-9]*(,[A-Z]+[0-9]*)*)?$'
            what='a list of ruff rule codes: use codes separated by commas, e.g. C90,SIM, or false' ;;
        suites) local suite='(unit|integration|e2e|security|performance)'
            pattern="^[[:space:]]*(${suite}([[:space:]]+${suite})*)?[[:space:]]*\$"
            what='a list of suites: use unit, integration, e2e, security or performance separated by spaces, e.g. e2e security' ;;
        share) pattern='^(0?\.[0-9]*[1-9][0-9]*|[1-9][0-9]*)$'
            what='a worker share: use a fraction below 1 for a share of the CPUs, e.g. 0.25, or a whole number of workers, e.g. 8' ;;
        *) echo "Error: unknown setting type: $kind" >&2
            return 2 ;;
    esac
    if ! [[ "$value" =~ $pattern ]]; then
        echo "Error: $name=$value is not $what" >&2
        return 2
    fi
    printf '%s' "$value"
}

# appinfra_pytest_args NAME: prints the variable NAME's value, pytest arguments,
# or prints an error to stderr and returns 2 when one is an xdist worker option.
# The arguments come after check.sh's own, so -n there would override the
# worker counts check.sh sets from APPINFRA_PYTEST_CHECK_WORKERS and
# APPINFRA_PYTEST_COVERAGE_WORKERS, and the serial performance run's -n 1. Makefile.pytest checks the same options for make test*
# (_APPINFRA_PYTEST_WORKER_OPTS), whose workers come from APPINFRA_PYTEST_WORKERS.
appinfra_pytest_args() {
    local name="$1" arg
    local -a args
    read -ra args <<< "${!name-}"
    for arg in "${args[@]}"; do
        case "$arg" in
            -n*|--numprocesses*|--maxprocesses*|--dist*)
                echo "Error: $name=${!name} sets xdist workers ($arg): make check sets its own worker counts; remove it, and set APPINFRA_PYTEST_CHECK_WORKERS or APPINFRA_PYTEST_COVERAGE_WORKERS instead" >&2
                return 2
                ;;
        esac
    done
    printf '%s' "${!name-}"
}

# appinfra_has_test_files DIR: succeeds when DIR holds a .py file other than
# __init__.py and conftest.py, at any depth. Any such file counts, whatever the
# project's python_files: a wrongly counted directory costs a pytest run, a
# missed one would skip its tests. _APPINFRA_SUITE_RUN in make/Makefile.pytest
# applies the same find.
appinfra_has_test_files() {
    [ -n "$(find "$1" -name '*.py' ! -name __init__.py ! -name conftest.py \
        -print -quit 2>/dev/null)" ]
}

# appinfra_suite_markers: prints the markers named in the test files under
# tests/ and the name of each directory under tests/ that holds test files, one
# per line. A suite directory (tests/<suite>/) gives its tests the suite's
# marker without naming it. Markers applied otherwise by a
# pytest_collection_modifyitems hook are missed.
appinfra_suite_markers() {
    {
        grep -rhoE 'pytest\.mark\.[a-z_][a-z0-9_]*' tests/ --include='*.py' 2>/dev/null \
            | cut -d. -f3
        local dir
        for dir in tests/*/; do
            appinfra_has_test_files "$dir" && basename "$dir"
        done
    } | sort -u || true
}
