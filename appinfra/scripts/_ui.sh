# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

# Shared status/color primitives for appinfra shell scripts. Source with:
#   . "$(dirname "${BASH_SOURCE[0]}")/_ui.sh"
#
# The vocabulary is intentionally small — one palette + five status marks —
# so terminal output reads consistently across every script and log this
# codebase produces. The Python side (appinfra.ui.status) mirrors these
# same names and glyphs.

# Check TTY status for each stream at source time. NO_COLOR disables both.
# See https://no-color.org/
_UI_STDOUT_COLOR=false
_UI_STDERR_COLOR=false
if [[ -z "${NO_COLOR:-}" ]]; then
    [[ -t 1 ]] && _UI_STDOUT_COLOR=true
    [[ -t 2 ]] && _UI_STDERR_COLOR=true
fi

# Color palette (for stdout). Empty when stdout is not a TTY.
if $_UI_STDOUT_COLOR; then
    UI_BOLD=$'\033[1m'
    UI_RED=$'\033[0;31m'
    UI_GREEN=$'\033[0;32m'
    UI_YELLOW=$'\033[0;33m'
    UI_BRIGHT_YELLOW=$'\033[0;93m'
    UI_BLUE=$'\033[0;34m'
    UI_CYAN=$'\033[0;36m'
    UI_GRAY=$'\033[0;90m'
    UI_RESET=$'\033[0m'
    UI_CLEAR=$'\033[K'
else
    UI_BOLD=''
    UI_RED=''
    UI_GREEN=''
    UI_YELLOW=''
    UI_BRIGHT_YELLOW=''
    UI_BLUE=''
    UI_CYAN=''
    UI_GRAY=''
    UI_RESET=''
    UI_CLEAR=''
fi

# Status marks — the canonical six. Colored for stdout. Bright yellow is a warning, mark and text;
# plain yellow marks work in progress, and in reports a path or command to act on.
UI_MARK_PENDING="${UI_GRAY}[ ]${UI_RESET}"
UI_MARK_RUNNING="${UI_YELLOW}[…]${UI_RESET}"
UI_MARK_OK="${UI_GREEN}[✓]${UI_RESET}"
UI_MARK_WARN="${UI_BRIGHT_YELLOW}[⚠]${UI_RESET}"
UI_MARK_FAIL="${UI_RED}[✗]${UI_RESET}"
# Information that is neither a result nor a warning; an ASCII i, as ℹ is double width in some
# terminals
UI_MARK_INFO="${UI_CYAN}[i]${UI_RESET}"

# Convenience printers. ui_fail goes to stderr and checks its own TTY.
ui_ok()      { printf '%s %s\n' "${UI_MARK_OK}"      "$*"; }
ui_warn()    { printf '%s %s\n' "${UI_MARK_WARN}"    "$*"; }
ui_running() { printf '%s %s\n' "${UI_MARK_RUNNING}" "$*"; }
ui_pending() { printf '%s %s\n' "${UI_MARK_PENDING}" "$*"; }
ui_fail() {
    local mark="[✗]"
    $_UI_STDERR_COLOR && mark=$'\033[0;31m[✗]\033[0m'
    printf '%s %s\n' "$mark" "$*" >&2
}
