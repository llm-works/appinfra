#!/usr/bin/env bash

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

# pg.sh — PostgreSQL lifecycle dispatcher
#
# Single entry point for pg operations, invoked by both Makefile.pg shims
# (repo cloners) and the `appinfra pg` CLI (wheel installers). All inputs
# arrive via env — no positional-arg channel — so the caller layer owns
# YAML parsing and flag parsing, and this script owns execution.
#
# Usage:
#   pg.sh <cmd> [args]
#
# Wire-protocol env vars (internal; caller sets before exec):
#   _APPINFRA_PG_CONTAINER_NAME     container --name for the pg server
#   _APPINFRA_PG_VERSION            postgres major version (e.g. 18)
#   _APPINFRA_PG_HOST               connection host
#   _APPINFRA_PG_PORT               primary connection port
#   _APPINFRA_PG_PORT_R             standby port (only when _APPINFRA_PG_REPLICA_ENABLED=true)
#   _APPINFRA_PG_USER               postgres user
#   _APPINFRA_PG_REPLICA_ENABLED    "true" enables replica-aware behavior
#   _APPINFRA_PG_IMAGE              pre-resolved container image (e.g. docker.io/postgres:18)
#   _APPINFRA_PG_MAX_CONNECTIONS    postgres_conf: max_connections (optional)
#   _APPINFRA_PG_SHARED_PRELOAD_LIBRARIES  postgres_conf: shared_preload_libraries (optional)
#   _APPINFRA_PG_WORK_MEM           postgres_conf: work_mem (optional)
#   _APPINFRA_PG_AUTOVACUUM         postgres_conf: autovacuum (optional)
#   _APPINFRA_PG_DATABASES          space-separated allowlist of databases the `clean` verb may drop
#   _APPINFRA_PG_MODE               "single" | "repl" — target mode for `up` / `reboot`
#   _APPINFRA_PG_WAIT               "0" to skip readiness/teardown wait on up/down/reboot
#   _APPINFRA_PG_WAIT_TIMEOUT       wait-up / wait-down loop timeout in seconds (default 30)
#   APPINFRA_CONTAINER_CMD       container runtime (docker/podman); default docker
#   APPINFRA_COMPOSE_CMD         compose runtime (docker compose / podman compose); default docker compose
#
# The `_APPINFRA_PG_*` prefix marks these as an internal wire protocol between the
# caller layer and pg.sh — subject to change, not part of the public
# APPINFRA_PG_* / INFRA_PGSERVER_* user-facing configuration surface.

# All _APPINFRA_PG_* / APPINFRA_* vars are supplied by the caller (Makefile shim or
# `appinfra pg` CLI), not assigned here — silence "may not be assigned" hints.
# shellcheck disable=SC2153

set -euo pipefail

# ---------------------------------------------------------------------------
# Shared: color codes + status marks (see appinfra/scripts/_ui.sh)
# ---------------------------------------------------------------------------

# shellcheck source=./_ui.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_ui.sh"

# ---------------------------------------------------------------------------
# Shared: container / compose helpers
# ---------------------------------------------------------------------------

_pg_script_dir() {
    cd "$(dirname "${BASH_SOURCE[0]}")" && pwd
}

_pg_compose_yaml() {
    # $1 = single|repl
    local script_dir
    script_dir="$(_pg_script_dir)"
    if [ "$1" = "repl" ]; then
        echo "${script_dir}/docker/pg/docker-compose.repl.yaml"
    else
        echo "${script_dir}/docker/pg/docker-compose.single.yaml"
    fi
}

_pg_container_runtime() {
    echo "${APPINFRA_CONTAINER_CMD:-docker}"
}

_pg_ensure_runtime() {
    # Verify the container runtime resolves to an executable on PATH so we can
    # emit actionable install guidance instead of a cryptic
    # `command not found` from the first ${runtime} invocation.
    local runtime explicit
    runtime="$(_pg_container_runtime)"
    if command -v "${runtime}" >/dev/null 2>&1; then
        return 0
    fi
    explicit="${APPINFRA_CONTAINER_CMD:-}"
    if [ -n "${explicit}" ]; then
        printf '%b' "${UI_RED}pg.sh: APPINFRA_CONTAINER_CMD='${explicit}' but '${explicit}' is not on PATH.${UI_RESET}\n" >&2
        local other=""
        if [ "${explicit}" = "podman" ] && command -v docker >/dev/null 2>&1; then other="docker"; fi
        if [ "${explicit}" = "docker" ] && command -v podman >/dev/null 2>&1; then other="podman"; fi
        if [ -n "${other}" ]; then
            echo "Hint: '${other}' is available — set APPINFRA_CONTAINER_CMD=${other} or unset it to auto-detect." >&2
        fi
        return 2
    fi
    # Default "docker" not found; check if podman is available before
    # printing install guidance (avoid "no runtime" when one exists).
    if command -v podman >/dev/null 2>&1; then
        cat >&2 <<'MSG'
pg.sh: 'docker' not found, but 'podman' is available.

Set the runtime explicitly:
  export APPINFRA_CONTAINER_CMD=podman

Or install docker if you prefer it over podman.
MSG
        return 2
    fi
    cat >&2 <<'MSG'
pg.sh: no container runtime found on PATH.

pg requires podman (preferred) or docker to manage the PostgreSQL
container. Install one:

  Linux (Fedora/RHEL):    sudo dnf install podman
  Linux (Debian/Ubuntu):  sudo apt install podman
  macOS:                  brew install podman
                          (then: podman machine init && podman machine start)

Or set APPINFRA_CONTAINER_CMD to point at an installed binary if it lives
under a non-standard name.
MSG
    return 2
}

_pg_compose_run() {
    # Invoke compose with the mode-appropriate YAML. $1 = single|repl,
    # remaining args pass through to compose. The compose YAMLs read the
    # _APPINFRA_PG_* wire variables straight from the environment, so they
    # are exported here (the caller may have set them unexported).
    local mode="$1"; shift
    local compose_yaml compose_cmd
    compose_yaml="$(_pg_compose_yaml "${mode}")"
    compose_cmd="${APPINFRA_COMPOSE_CMD:-docker compose}"

    export _APPINFRA_PG_CONTAINER_NAME _APPINFRA_PG_PORT _APPINFRA_PG_PORT_R
    export _APPINFRA_PG_IMAGE _APPINFRA_PG_MAX_CONNECTIONS
    export _APPINFRA_PG_SHARED_PRELOAD_LIBRARIES _APPINFRA_PG_WORK_MEM
    export _APPINFRA_PG_AUTOVACUUM

    # ${compose_cmd} is intentionally unquoted: it commonly holds
    # "docker compose" or "podman compose" (two words) that must word-split.
    # shellcheck disable=SC2086
    ${compose_cmd} -p "${_APPINFRA_PG_CONTAINER_NAME}" -f "${compose_yaml}" "$@"
}

_pg_detect_running_mode() {
    # Echoes: "single" | "repl" | "none"
    local runtime
    runtime="$(_pg_container_runtime)"
    if ${runtime} ps --format '{{.Names}}' 2>/dev/null | grep -q "^${_APPINFRA_PG_CONTAINER_NAME}-primary$"; then
        echo "repl"
    elif ${runtime} ps --format '{{.Names}}' 2>/dev/null | grep -q "^${_APPINFRA_PG_CONTAINER_NAME}$"; then
        echo "single"
    else
        echo "none"
    fi
}

# ---------------------------------------------------------------------------
# up — start server (single or repl mode)
# ---------------------------------------------------------------------------

_pg_up() {
    : "${_APPINFRA_PG_CONTAINER_NAME:?_APPINFRA_PG_CONTAINER_NAME required}"
    : "${_APPINFRA_PG_PORT:?_APPINFRA_PG_PORT required}"
    : "${_APPINFRA_PG_MODE:=single}"
    : "${_APPINFRA_PG_WAIT:=1}"

    if [ "${_APPINFRA_PG_MODE}" != "single" ] && [ "${_APPINFRA_PG_MODE}" != "repl" ]; then
        echo "pg.sh up: _APPINFRA_PG_MODE must be 'single' or 'repl' (got '${_APPINFRA_PG_MODE}')" >&2
        exit 2
    fi
    if [ "${_APPINFRA_PG_MODE}" = "repl" ] && [ -z "${_APPINFRA_PG_PORT_R:-}" ]; then
        echo "pg.sh up: _APPINFRA_PG_PORT_R required for repl mode" >&2
        exit 2
    fi

    local running_mode
    running_mode="$(_pg_detect_running_mode)"

    # Toggle: stop conflicting mode first to free the port.
    if [ "${_APPINFRA_PG_MODE}" = "single" ] && [ "${running_mode}" = "repl" ]; then
        ui_running "Stopping replication mode..."
        if [ -n "${_APPINFRA_PG_PORT_R:-}" ]; then
            _pg_compose_run repl down
        else
            # PORT_R unavailable (replica disabled after prior use); stop containers directly.
            local runtime; runtime="$(_pg_container_runtime)"
            ${runtime} stop "${_APPINFRA_PG_CONTAINER_NAME}-primary" "${_APPINFRA_PG_CONTAINER_NAME}-standby" 2>/dev/null || true
            ${runtime} rm -f "${_APPINFRA_PG_CONTAINER_NAME}-primary" "${_APPINFRA_PG_CONTAINER_NAME}-standby" 2>/dev/null || true
        fi
    elif [ "${_APPINFRA_PG_MODE}" = "repl" ] && [ "${running_mode}" = "single" ]; then
        ui_running "Stopping single instance..."
        _pg_compose_run single down
    fi

    # Header describes the action, not the assumed state. When the
    # desired mode is already running, compose up -d is a no-op and
    # _pg_wait_up serves as the ground-truth check — if detection was
    # wrong and pg isn't actually responsive, the wait will time out
    # and surface the failure.
    local _already_up="false"
    [ "${_APPINFRA_PG_MODE}" = "${running_mode}" ] && _already_up="true"
    if [ "${_APPINFRA_PG_MODE}" = "repl" ]; then
        if [ "${_already_up}" = "true" ]; then
            ui_running "pgserver '${_APPINFRA_PG_CONTAINER_NAME}' already up (repl mode; primary ${_APPINFRA_PG_PORT}, standby ${_APPINFRA_PG_PORT_R}) — verifying"
        else
            ui_running "Starting pgserver '${_APPINFRA_PG_CONTAINER_NAME}' (repl mode; primary ${_APPINFRA_PG_PORT}, standby ${_APPINFRA_PG_PORT_R})"
        fi
    else
        if [ "${_already_up}" = "true" ]; then
            ui_running "pgserver '${_APPINFRA_PG_CONTAINER_NAME}' already up (single mode, port ${_APPINFRA_PG_PORT}) — verifying"
        else
            ui_running "Starting pgserver '${_APPINFRA_PG_CONTAINER_NAME}' (single mode, port ${_APPINFRA_PG_PORT})"
        fi
    fi
    _pg_compose_run "${_APPINFRA_PG_MODE}" up -d

    if [ "${_APPINFRA_PG_WAIT}" != "0" ]; then
        _pg_wait_up
    fi
}

# ---------------------------------------------------------------------------
# down — stop server (auto-detects mode)
# ---------------------------------------------------------------------------

_pg_down() {
    : "${_APPINFRA_PG_CONTAINER_NAME:?_APPINFRA_PG_CONTAINER_NAME required}"
    : "${_APPINFRA_PG_WAIT:=1}"

    local running_mode
    running_mode="$(_pg_detect_running_mode)"

    case "${running_mode}" in
        repl)
            ui_running "Stopping pgserver '${_APPINFRA_PG_CONTAINER_NAME}' (repl mode)"
            if [ -n "${_APPINFRA_PG_PORT_R:-}" ]; then
                _pg_compose_run repl down || true
            else
                # PORT_R unavailable (replica disabled after prior use); stop containers directly.
                local runtime; runtime="$(_pg_container_runtime)"
                ${runtime} stop "${_APPINFRA_PG_CONTAINER_NAME}-primary" "${_APPINFRA_PG_CONTAINER_NAME}-standby" 2>/dev/null || true
                ${runtime} rm -f "${_APPINFRA_PG_CONTAINER_NAME}-primary" "${_APPINFRA_PG_CONTAINER_NAME}-standby" 2>/dev/null || true
            fi
            ;;
        single)
            ui_running "Stopping pgserver '${_APPINFRA_PG_CONTAINER_NAME}' (single mode)"
            _pg_compose_run single down || true
            ;;
        none)
            # Header describes the state so the output reads honestly on
            # the idempotent no-op path. _pg_wait_down still runs and
            # serves as the ground-truth check — if detection is wrong
            # and containers are actually present, the wait catches it.
            ui_running "pgserver '${_APPINFRA_PG_CONTAINER_NAME}' already down — verifying"
            # Still run single-mode down to sweep any lingering
            # network/volume artifacts. Matches historic Makefile behavior.
            # Filter podman's "no such container/pod" lines from stderr —
            # those are expected when there is nothing to stop and would
            # contradict the "Server is DOWN" message that follows. Any
            # other stderr line still surfaces so real failures aren't lost.
            _pg_compose_run single down \
                2> >(grep -vE '^Error: no (container|pod) with .*: no such (container|pod)$' >&2) \
                || true
            ;;
    esac

    if [ "${_APPINFRA_PG_WAIT}" != "0" ]; then
        _pg_wait_down
    fi
}

# ---------------------------------------------------------------------------
# reboot — restart server (auto-detects mode)
# ---------------------------------------------------------------------------

_pg_reboot() {
    : "${_APPINFRA_PG_CONTAINER_NAME:?_APPINFRA_PG_CONTAINER_NAME required}"
    : "${_APPINFRA_PG_PORT:?_APPINFRA_PG_PORT required}"
    : "${_APPINFRA_PG_WAIT:=1}"

    local running_mode
    running_mode="$(_pg_detect_running_mode)"

    case "${running_mode}" in
        repl)
            if [ -z "${_APPINFRA_PG_PORT_R:-}" ]; then
                echo "pg.sh reboot: _APPINFRA_PG_PORT_R required for repl mode" >&2
                exit 2
            fi
            _pg_compose_run repl down
            _pg_compose_run repl up -d
            ;;
        single)
            _pg_compose_run single down
            _pg_compose_run single up -d
            ;;
        none)
            echo "pg.sh reboot: no server running" >&2
            exit 1
            ;;
    esac

    if [ "${_APPINFRA_PG_WAIT}" != "0" ]; then
        _pg_wait_up
    fi
}

# ---------------------------------------------------------------------------
# logs — tail server logs (auto-detects mode)
# ---------------------------------------------------------------------------

_pg_logs() {
    : "${_APPINFRA_PG_CONTAINER_NAME:?_APPINFRA_PG_CONTAINER_NAME required}"

    local running_mode
    running_mode="$(_pg_detect_running_mode)"

    case "${running_mode}" in
        repl)
            if [ -z "${_APPINFRA_PG_PORT_R:-}" ]; then
                echo "pg.sh logs: _APPINFRA_PG_PORT_R required for repl mode" >&2
                exit 2
            fi
            _pg_compose_run repl logs -f
            ;;
        single)
            _pg_compose_run single logs -f
            ;;
        none)
            echo "pg.sh logs: no server running" >&2
            exit 1
            ;;
    esac
}

# ---------------------------------------------------------------------------
# erase — remove this instance's containers, volumes, networks (destructive)
# ---------------------------------------------------------------------------
#
# Scope guarantee: erase touches ONLY resources named after
# $_APPINFRA_PG_CONTAINER_NAME. It never removes images — the image store is
# shared across every container on the podman/docker runtime, and reaching
# into it would silently take down siblings. A post-erase advisory tells
# the user which other containers currently reference the image and,
# if any, that manual `rmi` will affect them.

_pg_erase() {
    : "${_APPINFRA_PG_CONTAINER_NAME:?_APPINFRA_PG_CONTAINER_NAME required}"

    local runtime name
    runtime="$(_pg_container_runtime)"
    name="${_APPINFRA_PG_CONTAINER_NAME}"

    # Containers: explicit names, single-mode + replication-mode.
    ui_running "Stopping containers..."
    ${runtime} stop "${name}" "${name}-primary" "${name}-standby" 2>/dev/null || true
    ${runtime} rm -f "${name}" "${name}-primary" "${name}-standby" 2>/dev/null || true

    # Volumes: enumerate the exact set compose creates for this instance
    # (project=${name}, volumes pgdata / pgdata_primary / pgdata_standby).
    # Substring filters could catch unrelated volumes like ${name}-backup.
    ui_running "Removing volumes..."
    for vol in "${name}_pgdata" "${name}_pgdata_primary" "${name}_pgdata_standby"; do
        ${runtime} volume rm "${vol}" 2>/dev/null || true
    done

    # Networks: compose creates ${project}_default; same rationale as volumes.
    ui_running "Removing networks..."
    ${runtime} network rm "${name}_default" 2>/dev/null || true

    ui_ok "Erase complete."
    _pg_erase_image_advisory "${runtime}"
}

_pg_erase_image_advisory() {
    # Print the image left behind + which other containers reference it, so
    # the user can decide whether a manual `rmi` is safe. Query is
    # runtime-native (--filter ancestor=X) and works on both podman/docker.
    local runtime="$1"
    [ -n "${_APPINFRA_PG_IMAGE:-}" ] || return 0

    local users
    users="$(${runtime} ps -a --filter "ancestor=${_APPINFRA_PG_IMAGE}" \
        --format '{{.Names}} ({{.Status}})' 2>/dev/null || true)"

    printf '\n'
    printf 'Image not removed (shared runtime resource): %s\n' "${_APPINFRA_PG_IMAGE}"
    if [ -n "${users}" ]; then
        printf '\nStill used by:\n'
        while IFS= read -r user; do
            [ -n "${user}" ] && printf '  - %s\n' "${user}"
        done <<< "${users}"
        printf '\nRemoving the image would affect the above containers.\n'
        printf 'To erase the image anyway:  %s rmi %s\n' "${runtime}" "${_APPINFRA_PG_IMAGE}"
    else
        printf 'No other containers use it.\n'
        printf 'To erase the image:  %s rmi %s\n' "${runtime}" "${_APPINFRA_PG_IMAGE}"
    fi
}

# ---------------------------------------------------------------------------
# wait-up / wait-down — readiness / teardown probes
# ---------------------------------------------------------------------------

_pg_wait_container_up() {
    # $1 = container name, $2 = timeout seconds
    local target="$1" timeout="$2"
    local runtime i
    runtime="$(_pg_container_runtime)"

    # Probe over TCP, not the unix socket. On a fresh volume the image
    # entrypoint runs a socket-only temporary server (listen_addresses='')
    # for init scripts; it answers a socket probe seconds before the real
    # server accepts TCP connections, so a socket probe reports ready early.
    for i in $(seq 1 "${timeout}"); do
        if ${runtime} exec "${target}" psql -h 127.0.0.1 -U "${_APPINFRA_PG_USER}" -c "SELECT 1" >/dev/null 2>&1; then
            return 0
        fi
        if [ $((i % 5)) -eq 0 ]; then
            echo "  still waiting (${i}s elapsed)"
        fi
        sleep 1
    done
    ui_fail "${target} did not become ready within ${timeout}s"
    exit 1
}

_pg_wait_up() {
    : "${_APPINFRA_PG_CONTAINER_NAME:?_APPINFRA_PG_CONTAINER_NAME required}"
    : "${_APPINFRA_PG_USER:?_APPINFRA_PG_USER required}"
    : "${_APPINFRA_PG_PORT:?_APPINFRA_PG_PORT required}"
    : "${_APPINFRA_PG_WAIT_TIMEOUT:=30}"

    local runtime
    runtime="$(_pg_container_runtime)"

    local primary_target="${_APPINFRA_PG_CONTAINER_NAME}"
    if ${runtime} ps --format '{{.Names}}' 2>/dev/null | grep -q "^${_APPINFRA_PG_CONTAINER_NAME}-primary$"; then
        primary_target="${_APPINFRA_PG_CONTAINER_NAME}-primary"
    fi

    ui_running "Waiting for ${primary_target} to accept connections..."
    _pg_wait_container_up "${primary_target}" "${_APPINFRA_PG_WAIT_TIMEOUT}"
    ui_ok "Server is UP (${primary_target} on port ${_APPINFRA_PG_PORT})"

    # In repl mode the standby container's psql only answers once basebackup
    # completes. Fixes the historic wait-up quirk where the target went ready
    # while the standby was still cloning.
    if [ "${primary_target}" = "${_APPINFRA_PG_CONTAINER_NAME}-primary" ]; then
        local standby_target="${_APPINFRA_PG_CONTAINER_NAME}-standby"
        if ${runtime} ps --format '{{.Names}}' 2>/dev/null | grep -q "^${standby_target}$"; then
            ui_running "Waiting for ${standby_target} to accept connections (basebackup)..."
            _pg_wait_container_up "${standby_target}" "${_APPINFRA_PG_WAIT_TIMEOUT}"
            ui_ok "Standby is UP (${standby_target} on port ${_APPINFRA_PG_PORT_R:-?})"
        fi
    fi
}

_pg_wait_down() {
    : "${_APPINFRA_PG_CONTAINER_NAME:?_APPINFRA_PG_CONTAINER_NAME required}"
    : "${_APPINFRA_PG_WAIT_TIMEOUT:=30}"

    local runtime i present_count noun
    runtime="$(_pg_container_runtime)"

    # Count matching containers up front so the wait line pluralizes
    # correctly (single mode → 1, repl → 2) — and skip the "Waiting…"
    # line entirely when nothing is there (idempotent no-op path).
    present_count=$(
        ${runtime} ps -a --format '{{.Names}}' 2>/dev/null \
            | grep -cE "^${_APPINFRA_PG_CONTAINER_NAME}(-primary|-standby)?$" || true
    )
    if [ "$present_count" -eq 0 ]; then
        ui_ok "Server is DOWN"
        return 0
    fi
    [ "$present_count" -eq 1 ] && noun="container" || noun="containers"

    ui_running "Waiting for ${_APPINFRA_PG_CONTAINER_NAME} ${noun} to be removed..."
    for i in $(seq 1 "${_APPINFRA_PG_WAIT_TIMEOUT}"); do
        if ! ${runtime} ps -a --format '{{.Names}}' 2>/dev/null | grep -qE "^${_APPINFRA_PG_CONTAINER_NAME}(-primary|-standby)?$"; then
            ui_ok "Server is DOWN"
            return 0
        fi
        if [ $((i % 5)) -eq 0 ]; then
            echo "  still waiting (${i}s elapsed)"
        fi
        sleep 1
    done
    # Recount so the failure message reflects what actually remained.
    present_count=$(
        ${runtime} ps -a --format '{{.Names}}' 2>/dev/null \
            | grep -cE "^${_APPINFRA_PG_CONTAINER_NAME}(-primary|-standby)?$" || true
    )
    [ "$present_count" -eq 1 ] && noun="container" || noun="containers"
    ui_fail "${noun} for ${_APPINFRA_PG_CONTAINER_NAME} still present after teardown"
    exit 1
}

# ---------------------------------------------------------------------------
# info — comprehensive server + database status (also --short summary line)
# ---------------------------------------------------------------------------

_pg_require_env() {
    : "${_APPINFRA_PG_CONTAINER_NAME:?_APPINFRA_PG_CONTAINER_NAME required}"
    : "${_APPINFRA_PG_VERSION:?_APPINFRA_PG_VERSION required}"
    : "${_APPINFRA_PG_HOST:?_APPINFRA_PG_HOST required}"
    : "${_APPINFRA_PG_PORT:?_APPINFRA_PG_PORT required}"
    : "${_APPINFRA_PG_USER:?_APPINFRA_PG_USER required}"
    : "${_APPINFRA_PG_REPLICA_ENABLED:=false}"
    : "${_APPINFRA_PG_PORT_R:=}"
}

_pg_check_status() {
    export PGCONNECT_TIMEOUT="${PGCONNECT_TIMEOUT:-5}"
    if psql -w -h "${_APPINFRA_PG_HOST}" -p "${_APPINFRA_PG_PORT}" -U "${_APPINFRA_PG_USER}" -c "SELECT 1" >/dev/null 2>&1; then
        _primary_up=true
        _primary_status="${UI_GREEN}UP${UI_RESET}"
    else
        _primary_up=false
        _primary_status="${UI_RED}DOWN${UI_RESET}"
    fi

    _standby_up=false
    _standby_status="${UI_RED}DOWN${UI_RESET}"
    if [ "$_APPINFRA_PG_REPLICA_ENABLED" = "true" ]; then
        if psql -w -h "${_APPINFRA_PG_HOST}" -p "${_APPINFRA_PG_PORT_R}" -U "${_APPINFRA_PG_USER}" -c "SELECT 1" >/dev/null 2>&1; then
            _standby_up=true
            _standby_status="${UI_GREEN}UP${UI_RESET}"
        fi
    fi
}

_pg_info_short() {
    if [ "$_APPINFRA_PG_REPLICA_ENABLED" = "true" ]; then
        echo -e "${UI_BOLD}Endpoints:${UI_RESET} Primary ${_primary_status} (${_APPINFRA_PG_HOST}:${_APPINFRA_PG_PORT}) | Standby ${_standby_status} (${_APPINFRA_PG_HOST}:${_APPINFRA_PG_PORT_R})"
    else
        echo -e "${UI_BOLD}Endpoint:${UI_RESET} ${_primary_status} (${_APPINFRA_PG_HOST}:${_APPINFRA_PG_PORT})"
    fi

    if [ "$_primary_up" = true ]; then
        if [ "$_APPINFRA_PG_REPLICA_ENABLED" = "true" ]; then
            local repl_state repl_sync
            repl_state=$(psql -h "${_APPINFRA_PG_HOST}" -p "${_APPINFRA_PG_PORT}" -U "${_APPINFRA_PG_USER}" -t -A -c "SELECT state FROM pg_stat_replication LIMIT 1;" 2>/dev/null)
            if [ -n "$repl_state" ]; then
                repl_sync=$(psql -h "${_APPINFRA_PG_HOST}" -p "${_APPINFRA_PG_PORT}" -U "${_APPINFRA_PG_USER}" -t -A -c "SELECT sync_state FROM pg_stat_replication LIMIT 1;" 2>/dev/null)
                echo -e "${UI_BOLD}Replication:${UI_RESET} ${UI_YELLOW}${repl_state}${UI_RESET} (${repl_sync})"
            else
                echo -e "${UI_BOLD}Replication:${UI_RESET} ${UI_GRAY}not active${UI_RESET}"
            fi
        fi

        local db_info db_count db_size active_conns
        db_info=$(psql -h "${_APPINFRA_PG_HOST}" -p "${_APPINFRA_PG_PORT}" -U "${_APPINFRA_PG_USER}" -t -A -c "SELECT COUNT(*), pg_size_pretty(SUM(pg_database_size(datname))) FROM pg_database WHERE datistemplate = false;" 2>/dev/null)
        db_count=$(echo "$db_info" | cut -d'|' -f1)
        db_size=$(echo "$db_info" | cut -d'|' -f2)
        active_conns=$(psql -h "${_APPINFRA_PG_HOST}" -p "${_APPINFRA_PG_PORT}" -U "${_APPINFRA_PG_USER}" -t -A -c "SELECT COUNT(*) FROM pg_stat_activity WHERE state != 'idle' AND pid != pg_backend_pid();" 2>/dev/null)

        echo -e "${UI_BOLD}Databases:${UI_RESET} ${UI_BLUE}${db_count}${UI_RESET} (${db_size}) | ${UI_BOLD}Active connections:${UI_RESET} ${UI_BLUE}${active_conns}${UI_RESET}"
    else
        echo -e "${UI_BOLD}Status:${UI_RESET} ${UI_RED}Primary server is down${UI_RESET}"
    fi
}

# ---------------------------------------------------------------------------
# info — full output helpers (each ~10-15 lines, single responsibility)
# ---------------------------------------------------------------------------

_pg_info_containers() {
    local runtime="${APPINFRA_CONTAINER_CMD:-docker}"
    local output exit_code=0
    output=$(${runtime} ps -a --filter "name=${_APPINFRA_PG_CONTAINER_NAME}" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" 2>&1) || exit_code=$?
    if [ $exit_code -ne 0 ]; then
        echo -e "${UI_RED}Error from '${runtime}' (exit $exit_code):${UI_RESET}"
        echo "$output"
        exit $exit_code
    elif [ "$(echo "$output" | wc -l)" -le 1 ]; then
        echo "No PostgreSQL containers found"
    else
        echo "$output"
    fi
}

_pg_info_config() {
    echo -e "Version:          ${UI_BLUE}PostgreSQL ${_APPINFRA_PG_VERSION}${UI_RESET}"
    echo -e "Container Name:   ${UI_BLUE}${_APPINFRA_PG_CONTAINER_NAME}${UI_RESET}"
    if [ "$_APPINFRA_PG_REPLICA_ENABLED" = "true" ]; then
        echo -e "Primary Port:     ${UI_BLUE}${_APPINFRA_PG_PORT}${UI_RESET}"
        echo -e "Standby Port:     ${UI_BLUE}${_APPINFRA_PG_PORT_R}${UI_RESET}"
    else
        echo -e "Port:             ${UI_BLUE}${_APPINFRA_PG_PORT}${UI_RESET}"
    fi
}

_pg_info_endpoints() {
    if [ "$_APPINFRA_PG_REPLICA_ENABLED" = "true" ]; then
        printf "%-30s " "Primary (${_APPINFRA_PG_HOST}:${_APPINFRA_PG_PORT}):"
        echo -e "${_primary_status}"
        printf "%-30s " "Standby (${_APPINFRA_PG_HOST}:${_APPINFRA_PG_PORT_R}):"
        echo -e "${_standby_status}"
    else
        printf "%-30s " "Server (${_APPINFRA_PG_HOST}:${_APPINFRA_PG_PORT}):"
        echo -e "${_primary_status}"
    fi
}

_pg_info_replication() {
    psql -h "${_APPINFRA_PG_HOST}" -p "${_APPINFRA_PG_PORT}" -U "${_APPINFRA_PG_USER}" \
        -c "SELECT client_addr AS standby_addr, state, sync_state FROM pg_stat_replication;" 2>/dev/null \
        || echo "No replication active"
}

_pg_info_databases() {
    psql -h "${_APPINFRA_PG_HOST}" -p "${_APPINFRA_PG_PORT}" -U "${_APPINFRA_PG_USER}" \
        -c "SELECT datname AS database, pg_size_pretty(pg_database_size(datname)) AS size, \
            (SELECT count(*) FROM pg_stat_activity WHERE datname = d.datname) AS connections \
            FROM pg_database d WHERE datistemplate = false ORDER BY pg_database_size(datname) DESC;" 2>/dev/null
}

_pg_info_tables() {
    local db
    for db in $(psql -h "${_APPINFRA_PG_HOST}" -p "${_APPINFRA_PG_PORT}" -U "${_APPINFRA_PG_USER}" \
                -t -A -c "SELECT datname FROM pg_database WHERE datistemplate = false AND datname != 'postgres';" 2>/dev/null); do
        echo ""
        echo -e "${UI_YELLOW}Database: ${db}${UI_RESET}"
        psql -h "${_APPINFRA_PG_HOST}" -p "${_APPINFRA_PG_PORT}" -U "${_APPINFRA_PG_USER}" -d "${db}" \
            -c "SELECT schemaname || '.' || tablename AS table, \
                pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size \
                FROM pg_tables WHERE schemaname NOT IN ('pg_catalog', 'information_schema') \
                ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC LIMIT 10;" 2>/dev/null \
            || echo "  (no tables or access denied)"
    done
}

_pg_info_connections() {
    psql -h "${_APPINFRA_PG_HOST}" -p "${_APPINFRA_PG_PORT}" -U "${_APPINFRA_PG_USER}" \
        -c "SELECT datname AS database, usename AS user, application_name AS app, \
            client_addr AS client, state, query_start \
            FROM pg_stat_activity WHERE state != 'idle' AND pid != pg_backend_pid() \
            ORDER BY query_start;" 2>/dev/null
}

_pg_info_full() {
    echo ""
    echo -e "${UI_BOLD}${UI_CYAN}PostgreSQL Infrastructure Status${UI_RESET}"
    echo -e "${UI_CYAN}================================${UI_RESET}"
    echo ""

    echo -e "${UI_BOLD}CONTAINERS${UI_RESET}"
    echo -e "${UI_GRAY}----------${UI_RESET}"
    _pg_info_containers
    echo ""

    echo -e "${UI_BOLD}SYSTEM CONFIGURATION${UI_RESET}"
    echo -e "${UI_GRAY}--------------------${UI_RESET}"
    _pg_info_config
    echo ""

    echo -e "${UI_BOLD}CONNECTION ENDPOINTS${UI_RESET}"
    echo -e "${UI_GRAY}--------------------${UI_RESET}"
    _pg_info_endpoints
    echo ""

    if [ "$_primary_up" = true ]; then
        if [ "$_APPINFRA_PG_REPLICA_ENABLED" = "true" ]; then
            echo -e "${UI_BOLD}REPLICATION STATUS${UI_RESET}"
            echo -e "${UI_GRAY}------------------${UI_RESET}"
            _pg_info_replication
            echo ""
        fi

        echo -e "${UI_BOLD}DATABASES${UI_RESET}"
        echo -e "${UI_GRAY}---------${UI_RESET}"
        _pg_info_databases
        echo ""

        echo -e "${UI_BOLD}TOP TABLES BY SIZE${UI_RESET}"
        echo -e "${UI_GRAY}------------------${UI_RESET}"
        _pg_info_tables
        echo ""

        echo -e "${UI_BOLD}ACTIVE CONNECTIONS${UI_RESET}"
        echo -e "${UI_GRAY}------------------${UI_RESET}"
        _pg_info_connections
        echo ""
    else
        echo -e "${UI_BOLD}DATABASES${UI_RESET}"
        echo -e "${UI_GRAY}---------${UI_RESET}"
        echo -e "${UI_RED}(Cannot connect to database - server may be down)${UI_RESET}"
        echo ""
    fi
}

_pg_info() {
    local short_mode=false
    if [ "${1:-}" = "--short" ]; then
        short_mode=true
        shift
    fi

    _pg_require_env
    _pg_check_status

    if [ "$short_mode" = true ]; then
        _pg_info_short
    else
        _pg_info_full
    fi
}

# ---------------------------------------------------------------------------
# clean — drop configured databases (allowlisted via _APPINFRA_PG_DATABASES)
# ---------------------------------------------------------------------------

_pg_clean() {
    : "${_APPINFRA_PG_HOST:?_APPINFRA_PG_HOST required}"
    : "${_APPINFRA_PG_PORT:?_APPINFRA_PG_PORT required}"
    : "${_APPINFRA_PG_USER:?_APPINFRA_PG_USER required}"

    if [ -z "${_APPINFRA_PG_DATABASES:-}" ]; then
        echo "no databases configured"
        return 0
    fi

    ui_running "Cleaning pg databases..."
    local db exists failed=0
    set -f  # disable pathname expansion for the loop
    for db in ${_APPINFRA_PG_DATABASES}; do
        set +f
        if ! echo "${db}" | grep -Eq '^[A-Za-z_][A-Za-z0-9_]*$'; then
            ui_warn "skipping unsafe database name: ${db}"
            continue
        fi
        if ! exists=$(psql -w -h "${_APPINFRA_PG_HOST}" -p "${_APPINFRA_PG_PORT}" -U "${_APPINFRA_PG_USER}" \
            -d postgres -XtAc "SELECT 1 FROM pg_database WHERE datname='${db}'" 2>&1); then
            ui_fail "error checking ${db}: ${exists}"
            failed=1
            continue
        fi
        if [ "${exists}" = "1" ]; then
            ui_running "  dropping db ${db}..."
            if ! psql -w -h "${_APPINFRA_PG_HOST}" -p "${_APPINFRA_PG_PORT}" -U "${_APPINFRA_PG_USER}" \
                -d postgres -c "DROP DATABASE \"${db}\" WITH (FORCE)"; then
                ui_fail "failed to drop ${db}"
                failed=1
            fi
        else
            ui_pending "database ${db} not found"
        fi
    done
    set +f
    if [ "${failed}" = "1" ]; then
        ui_fail "cleaning pg databases finished with errors"
        return 1
    fi
    ui_ok "cleaning pg databases complete"
}

# ---------------------------------------------------------------------------
# psql — interactive shell (--target primary|standby; default primary)
# ---------------------------------------------------------------------------

_pg_psql() {
    # Connection-only checks (don't require PG_VERSION — not needed for psql).
    : "${_APPINFRA_PG_HOST:?_APPINFRA_PG_HOST required}"
    : "${_APPINFRA_PG_PORT:?_APPINFRA_PG_PORT required}"
    : "${_APPINFRA_PG_USER:?_APPINFRA_PG_USER required}"
    : "${_APPINFRA_PG_REPLICA_ENABLED:=false}"
    : "${_APPINFRA_PG_PORT_R:=}"

    local target="primary"
    if [ "${1:-}" = "--target" ]; then
        shift
        target="${1:?pg.sh psql --target: value required (primary|standby)}"
        shift
    fi

    local port
    case "${target}" in
        primary)
            port="${_APPINFRA_PG_PORT}"
            ;;
        standby)
            if [ "${_APPINFRA_PG_REPLICA_ENABLED}" != "true" ]; then
                echo "pg.sh psql --target standby: replica not enabled" >&2
                exit 2
            fi
            : "${_APPINFRA_PG_PORT_R:?_APPINFRA_PG_PORT_R required for --target standby}"
            port="${_APPINFRA_PG_PORT_R}"
            ;;
        *)
            echo "pg.sh psql --target: unknown target '${target}' (expected primary|standby)" >&2
            exit 2
            ;;
    esac

    _pg_check_status
    _pg_info_short
    echo ""
    if [ "${target}" = "standby" ]; then
        echo "Connecting to standby server (read-only)..."
    fi

    PAGER='less -S' exec psql -h "${_APPINFRA_PG_HOST}" -p "${port}" -U "${_APPINFRA_PG_USER}"
}

# ---------------------------------------------------------------------------
# top — pg_top for the primary server
# ---------------------------------------------------------------------------

_pg_top() {
    : "${_APPINFRA_PG_HOST:?_APPINFRA_PG_HOST required}"
    : "${_APPINFRA_PG_PORT:?_APPINFRA_PG_PORT required}"
    : "${_APPINFRA_PG_USER:?_APPINFRA_PG_USER required}"
    exec pg_top -h "${_APPINFRA_PG_HOST}" -p "${_APPINFRA_PG_PORT}" -U "${_APPINFRA_PG_USER}"
}

# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

_pg_usage() {
    cat >&2 <<'USAGE'
usage: pg.sh <cmd> [args]

commands:
  up                start server (mode via _APPINFRA_PG_MODE=single|repl; wait unless _APPINFRA_PG_WAIT=0)
  down              stop server (auto-detects mode; wait unless _APPINFRA_PG_WAIT=0)
  reboot            restart server (auto-detects mode; wait unless _APPINFRA_PG_WAIT=0)
  logs              tail server logs (auto-detects mode)
  wait-up           wait for server to accept connections (timeout _APPINFRA_PG_WAIT_TIMEOUT)
  wait-down         wait for containers to be fully removed
  info [--short]    server + database status (comprehensive or one-line summary)
  erase             remove this instance's containers, volumes, networks (destructive;
                    images are never touched — see the post-erase advisory)
  clean             drop databases in _APPINFRA_PG_DATABASES allowlist (server keeps running)
  psql [--target primary|standby]
                    interactive psql shell (default primary; standby is read-only)
  top               pg_top for the primary server

All inputs are read from environment variables; see the header of this script
for the required set per command.
USAGE
    exit 2
}

if [ $# -eq 0 ]; then
    _pg_usage
fi

cmd="$1"
shift

# Fail fast with actionable install guidance when the runtime is missing,
# BEFORE any verb tries to shell out and get a `command not found`.
case "$cmd" in
    -h | --help | help) : ;;
    *) _pg_ensure_runtime || exit $? ;;
esac

case "$cmd" in
    up)        _pg_up ;;
    down)      _pg_down ;;
    reboot)    _pg_reboot ;;
    logs)      _pg_logs ;;
    wait-up)   _pg_wait_up ;;
    wait-down) _pg_wait_down ;;
    info)      _pg_info "$@" ;;
    erase)     _pg_erase ;;
    clean)     _pg_clean ;;
    psql)      _pg_psql "$@" ;;
    top)       _pg_top ;;
    -h | --help | help) _pg_usage ;;
    *)
        echo "pg.sh: unknown command: $cmd" >&2
        _pg_usage
        ;;
esac
