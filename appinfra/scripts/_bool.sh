# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

# _bool.sh — boolean settings for appinfra's scripts (sourced, not run)
#
# One rule for every on/off setting, the same as Makefile.config's and
# appinfra/ui/_env.py's: true, 1, y, yes turn it on; false, 0, n, no turn it
# off; any case; unset takes the default; anything else, empty included, is
# an error.

# appinfra_bool NAME DEFAULT: prints true or false for the variable NAME, or
# prints an error to stderr and returns 2.
appinfra_bool() {
    local name="$1" value
    value="$(printf '%s' "${!name-$2}" | tr '[:upper:]' '[:lower:]')"
    case "$value" in
        true|1|y|yes) echo true ;;
        false|0|n|no) echo false ;;
        *)
            echo "Error: $name=${!name:-} is not a boolean: use true, 1, y, yes or false, 0, n, no" >&2
            return 2
            ;;
    esac
}
