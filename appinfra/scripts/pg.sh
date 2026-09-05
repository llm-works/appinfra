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
#   _INFRA_PG_CONTAINER_NAME     container --name for the pg server
#   _INFRA_PG_VERSION            postgres major version (e.g. 18)
#   _INFRA_PG_HOST               connection host
#   _INFRA_PG_PORT               primary connection port
#   _INFRA_PG_PORT_R             standby port (only when _INFRA_PG_REPLICA_ENABLED=true)
#   _INFRA_PG_USER               postgres user
#   _INFRA_PG_REPLICA_ENABLED    "true" enables replica-aware behavior
#   _INFRA_PG_IMAGE              pre-resolved container image (e.g. docker.io/postgres:18)
#   _INFRA_PG_MAX_CONNECTIONS    postgres_conf: max_connections (optional)
#   _INFRA_PG_SHARED_PRELOAD_LIBRARIES  postgres_conf: shared_preload_libraries (optional)
#   _INFRA_PG_WORK_MEM           postgres_conf: work_mem (optional)
#   _INFRA_PG_AUTOVACUUM         postgres_conf: autovacuum (optional)
#   _INFRA_PG_DATABASES          space-separated allowlist of databases the `clean` verb may drop
#   _INFRA_PG_MODE               "single" | "repl" — target mode for `up` / `reboot`
#   _INFRA_PG_WAIT               "0" to skip readiness/teardown wait on up/down/reboot
#   _INFRA_PG_WAIT_TIMEOUT       wait-up / wait-down loop timeout in seconds (default 30)
#   INFRA_CONTAINER_CMD          container runtime (docker/podman); default docker
#   INFRA_COMPOSE_CMD            compose runtime (docker compose / podman compose); default docker compose
#
# The `_INFRA_PG_*` prefix marks these as an internal wire protocol between the
# caller layer and pg.sh — subject to change, not part of the public
# INFRA_PG_* / INFRA_PGSERVER_* user-facing configuration surface.

# All _INFRA_PG_* / INFRA_* vars are supplied by the caller (Makefile shim or
# `appinfra pg` CLI), not assigned here — silence "may not be assigned" hints.
# shellcheck disable=SC2153

set -euo pipefail

# ---------------------------------------------------------------------------
# Shared: color codes
# ---------------------------------------------------------------------------

_BOLD='\033[1m' _RED='\033[0;31m' _GREEN='\033[0;32m'
_YELLOW='\033[0;33m' _BLUE='\033[0;34m' _CYAN='\033[0;36m'
_GRAY='\033[0;90m' _RESET='\033[0m'

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
    echo "${INFRA_CONTAINER_CMD:-docker}"
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
    explicit="${INFRA_CONTAINER_CMD:-}"
    if [ -n "${explicit}" ]; then
        printf '%b' "${_RED}pg.sh: INFRA_CONTAINER_CMD='${explicit}' but '${explicit}' is not on PATH.${_RESET}\n" >&2
        local other=""
        if [ "${explicit}" = "podman" ] && command -v docker >/dev/null 2>&1; then other="docker"; fi
        if [ "${explicit}" = "docker" ] && command -v podman >/dev/null 2>&1; then other="podman"; fi
        if [ -n "${other}" ]; then
            echo "Hint: '${other}' is available — set INFRA_CONTAINER_CMD=${other} or unset it to auto-detect." >&2
        fi
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

Or set INFRA_CONTAINER_CMD to point at an installed binary if it lives
under a non-standard name.
MSG
    return 2
}

_pg_compose_run() {
    # Invoke compose with the mode-appropriate YAML and env. $1 = single|repl,
    # remaining args pass through to compose.
    local mode="$1"; shift
    local compose_yaml compose_cmd
    compose_yaml="$(_pg_compose_yaml "${mode}")"
    compose_cmd="${INFRA_COMPOSE_CMD:-docker compose}"

    local -a compose_env=(
        NAME="${_INFRA_PG_CONTAINER_NAME}"
        PORT="${_INFRA_PG_PORT}"
        IMAGE="${_INFRA_PG_IMAGE:-}"
        PG_MAX_CONNECTIONS="${_INFRA_PG_MAX_CONNECTIONS:-}"
        PG_SHARED_PRELOAD_LIBRARIES="${_INFRA_PG_SHARED_PRELOAD_LIBRARIES:-}"
        PG_WORK_MEM="${_INFRA_PG_WORK_MEM:-}"
        PG_AUTOVACUUM="${_INFRA_PG_AUTOVACUUM:-}"
    )
    if [ "${mode}" = "repl" ]; then
        compose_env+=(PORT_R="${_INFRA_PG_PORT_R}")
    fi

    # ${compose_cmd} is intentionally unquoted: it commonly holds
    # "docker compose" or "podman compose" (two words) that must word-split.
    # shellcheck disable=SC2086
    env "${compose_env[@]}" ${compose_cmd} -p "${_INFRA_PG_CONTAINER_NAME}" -f "${compose_yaml}" "$@"
}

_pg_detect_running_mode() {
    # Echoes: "single" | "repl" | "none"
    local runtime
    runtime="$(_pg_container_runtime)"
    if ${runtime} ps --format '{{.Names}}' 2>/dev/null | grep -q "^${_INFRA_PG_CONTAINER_NAME}-primary$"; then
        echo "repl"
    elif ${runtime} ps --format '{{.Names}}' 2>/dev/null | grep -q "^${_INFRA_PG_CONTAINER_NAME}$"; then
        echo "single"
    else
        echo "none"
    fi
}

# ---------------------------------------------------------------------------
# up — start server (single or repl mode)
# ---------------------------------------------------------------------------

_pg_up() {
    : "${_INFRA_PG_CONTAINER_NAME:?_INFRA_PG_CONTAINER_NAME required}"
    : "${_INFRA_PG_PORT:?_INFRA_PG_PORT required}"
    : "${_INFRA_PG_MODE:=single}"
    : "${_INFRA_PG_WAIT:=1}"

    if [ "${_INFRA_PG_MODE}" != "single" ] && [ "${_INFRA_PG_MODE}" != "repl" ]; then
        echo "pg.sh up: _INFRA_PG_MODE must be 'single' or 'repl' (got '${_INFRA_PG_MODE}')" >&2
        exit 2
    fi
    if [ "${_INFRA_PG_MODE}" = "repl" ] && [ -z "${_INFRA_PG_PORT_R:-}" ]; then
        echo "pg.sh up: _INFRA_PG_PORT_R required for repl mode" >&2
        exit 2
    fi

    local running_mode
    running_mode="$(_pg_detect_running_mode)"

    # Toggle: stop conflicting mode first to free the port.
    if [ "${_INFRA_PG_MODE}" = "single" ] && [ "${running_mode}" = "repl" ]; then
        echo "Stopping replication mode..."
        if [ -n "${_INFRA_PG_PORT_R:-}" ]; then
            _pg_compose_run repl down
        else
            # PORT_R unavailable (replica disabled after prior use); stop containers directly.
            local runtime; runtime="$(_pg_container_runtime)"
            ${runtime} stop "${_INFRA_PG_CONTAINER_NAME}-primary" "${_INFRA_PG_CONTAINER_NAME}-standby" 2>/dev/null || true
            ${runtime} rm -f "${_INFRA_PG_CONTAINER_NAME}-primary" "${_INFRA_PG_CONTAINER_NAME}-standby" 2>/dev/null || true
        fi
        echo "Starting single instance..."
    elif [ "${_INFRA_PG_MODE}" = "repl" ] && [ "${running_mode}" = "single" ]; then
        echo "Stopping single instance..."
        _pg_compose_run single down
        echo "Starting PostgreSQL replication mode..."
        echo "  Primary:  port ${_INFRA_PG_PORT}"
        echo "  Standby:  port ${_INFRA_PG_PORT_R} (read-only replica)"
    fi

    _pg_compose_run "${_INFRA_PG_MODE}" up -d

    if [ "${_INFRA_PG_WAIT}" != "0" ]; then
        _pg_wait_up
    fi
}

# ---------------------------------------------------------------------------
# down — stop server (auto-detects mode)
# ---------------------------------------------------------------------------

_pg_down() {
    : "${_INFRA_PG_CONTAINER_NAME:?_INFRA_PG_CONTAINER_NAME required}"
    : "${_INFRA_PG_WAIT:=1}"

    local running_mode
    running_mode="$(_pg_detect_running_mode)"

    case "${running_mode}" in
        repl)
            if [ -n "${_INFRA_PG_PORT_R:-}" ]; then
                _pg_compose_run repl down || true
            else
                # PORT_R unavailable (replica disabled after prior use); stop containers directly.
                local runtime; runtime="$(_pg_container_runtime)"
                ${runtime} stop "${_INFRA_PG_CONTAINER_NAME}-primary" "${_INFRA_PG_CONTAINER_NAME}-standby" 2>/dev/null || true
                ${runtime} rm -f "${_INFRA_PG_CONTAINER_NAME}-primary" "${_INFRA_PG_CONTAINER_NAME}-standby" 2>/dev/null || true
            fi
            ;;
        single) _pg_compose_run single down || true ;;
        none)
            # Nothing running; still run single-mode down to sweep any lingering
            # network/volume artifacts. Matches historic Makefile behavior.
            _pg_compose_run single down || true
            ;;
    esac

    if [ "${_INFRA_PG_WAIT}" != "0" ]; then
        _pg_wait_down
    fi
}

# ---------------------------------------------------------------------------
# reboot — restart server (auto-detects mode)
# ---------------------------------------------------------------------------

_pg_reboot() {
    : "${_INFRA_PG_CONTAINER_NAME:?_INFRA_PG_CONTAINER_NAME required}"
    : "${_INFRA_PG_PORT:?_INFRA_PG_PORT required}"
    : "${_INFRA_PG_WAIT:=1}"

    local running_mode
    running_mode="$(_pg_detect_running_mode)"

    case "${running_mode}" in
        repl)
            if [ -z "${_INFRA_PG_PORT_R:-}" ]; then
                echo "pg.sh reboot: _INFRA_PG_PORT_R required for repl mode" >&2
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

    if [ "${_INFRA_PG_WAIT}" != "0" ]; then
        _pg_wait_up
    fi
}

# ---------------------------------------------------------------------------
# logs — tail server logs (auto-detects mode)
# ---------------------------------------------------------------------------

_pg_logs() {
    : "${_INFRA_PG_CONTAINER_NAME:?_INFRA_PG_CONTAINER_NAME required}"

    local running_mode
    running_mode="$(_pg_detect_running_mode)"

    case "${running_mode}" in
        repl)
            if [ -z "${_INFRA_PG_PORT_R:-}" ]; then
                echo "pg.sh logs: _INFRA_PG_PORT_R required for repl mode" >&2
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
# $_INFRA_PG_CONTAINER_NAME. It never removes images — the image store is
# shared across every container on the podman/docker runtime, and reaching
# into it would silently take down siblings. A post-erase advisory tells
# the user which other containers currently reference the image and,
# if any, that manual `rmi` will affect them.

_pg_erase() {
    : "${_INFRA_PG_CONTAINER_NAME:?_INFRA_PG_CONTAINER_NAME required}"

    local runtime name
    runtime="$(_pg_container_runtime)"
    name="${_INFRA_PG_CONTAINER_NAME}"

    # Containers: explicit names, single-mode + replication-mode.
    echo "Stopping containers..."
    ${runtime} stop "${name}" "${name}-primary" "${name}-standby" 2>/dev/null || true
    ${runtime} rm -f "${name}" "${name}-primary" "${name}-standby" 2>/dev/null || true

    # Volumes: enumerate the exact set compose creates for this instance
    # (project=${name}, volumes pgdata / pgdata_primary / pgdata_standby).
    # Substring filters could catch unrelated volumes like ${name}-backup.
    echo "Removing volumes..."
    for vol in "${name}_pgdata" "${name}_pgdata_primary" "${name}_pgdata_standby"; do
        ${runtime} volume rm "${vol}" 2>/dev/null || true
    done

    # Networks: compose creates ${project}_default; same rationale as volumes.
    echo "Removing networks..."
    ${runtime} network rm "${name}_default" 2>/dev/null || true

    echo "Erase complete."
    _pg_erase_image_advisory "${runtime}"
}

_pg_erase_image_advisory() {
    # Print the image left behind + which other containers reference it, so
    # the user can decide whether a manual `rmi` is safe. Query is
    # runtime-native (--filter ancestor=X) and works on both podman/docker.
    local runtime="$1"
    [ -n "${_INFRA_PG_IMAGE:-}" ] || return 0

    local users
    users="$(${runtime} ps -a --filter "ancestor=${_INFRA_PG_IMAGE}" \
        --format '{{.Names}} ({{.Status}})' 2>/dev/null || true)"

    printf '\n'
    printf 'Image not removed (shared runtime resource): %s\n' "${_INFRA_PG_IMAGE}"
    if [ -n "${users}" ]; then
        printf '\nStill used by:\n'
        while IFS= read -r user; do
            [ -n "${user}" ] && printf '  - %s\n' "${user}"
        done <<< "${users}"
        printf '\nRemoving the image would affect the above containers.\n'
        printf 'To erase the image anyway:  %s rmi %s\n' "${runtime}" "${_INFRA_PG_IMAGE}"
    else
        printf 'No other containers use it.\n'
        printf 'To erase the image:  %s rmi %s\n' "${runtime}" "${_INFRA_PG_IMAGE}"
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

    for i in $(seq 1 "${timeout}"); do
        if ${runtime} exec "${target}" psql -U "${_INFRA_PG_USER}" -c "SELECT 1" >/dev/null 2>&1; then
            return 0
        fi
        if [ $((i % 5)) -eq 0 ]; then
            echo "  still waiting (${i}s elapsed)"
        fi
        sleep 1
    done
    echo "ERROR: ${target} did not become ready within ${timeout}s" >&2
    exit 1
}

_pg_wait_up() {
    : "${_INFRA_PG_CONTAINER_NAME:?_INFRA_PG_CONTAINER_NAME required}"
    : "${_INFRA_PG_USER:?_INFRA_PG_USER required}"
    : "${_INFRA_PG_PORT:?_INFRA_PG_PORT required}"
    : "${_INFRA_PG_WAIT_TIMEOUT:=30}"

    local runtime
    runtime="$(_pg_container_runtime)"

    local primary_target="${_INFRA_PG_CONTAINER_NAME}"
    if ${runtime} ps --format '{{.Names}}' 2>/dev/null | grep -q "^${_INFRA_PG_CONTAINER_NAME}-primary$"; then
        primary_target="${_INFRA_PG_CONTAINER_NAME}-primary"
    fi

    echo "Waiting for ${primary_target} to accept connections..."
    _pg_wait_container_up "${primary_target}" "${_INFRA_PG_WAIT_TIMEOUT}"
    echo "Server is UP (${primary_target} on port ${_INFRA_PG_PORT})"

    # In repl mode the standby container's psql only answers once basebackup
    # completes. Fixes the historic wait-up quirk where the target went ready
    # while the standby was still cloning.
    if [ "${primary_target}" = "${_INFRA_PG_CONTAINER_NAME}-primary" ]; then
        local standby_target="${_INFRA_PG_CONTAINER_NAME}-standby"
        if ${runtime} ps --format '{{.Names}}' 2>/dev/null | grep -q "^${standby_target}$"; then
            echo "Waiting for ${standby_target} to accept connections (basebackup)..."
            _pg_wait_container_up "${standby_target}" "${_INFRA_PG_WAIT_TIMEOUT}"
            echo "Standby is UP (${standby_target} on port ${_INFRA_PG_PORT_R:-?})"
        fi
    fi
}

_pg_wait_down() {
    : "${_INFRA_PG_CONTAINER_NAME:?_INFRA_PG_CONTAINER_NAME required}"
    : "${_INFRA_PG_WAIT_TIMEOUT:=30}"

    local runtime i
    runtime="$(_pg_container_runtime)"

    echo "Waiting for ${_INFRA_PG_CONTAINER_NAME} container(s) to be removed..."
    for i in $(seq 1 "${_INFRA_PG_WAIT_TIMEOUT}"); do
        if ! ${runtime} ps -a --format '{{.Names}}' 2>/dev/null | grep -qE "^${_INFRA_PG_CONTAINER_NAME}(-primary|-standby)?$"; then
            echo "Server is DOWN"
            return 0
        fi
        if [ $((i % 5)) -eq 0 ]; then
            echo "  still waiting (${i}s elapsed)"
        fi
        sleep 1
    done
    echo "ERROR: container(s) for ${_INFRA_PG_CONTAINER_NAME} still present after teardown" >&2
    exit 1
}

# ---------------------------------------------------------------------------
# info — comprehensive server + database status (also --short summary line)
# ---------------------------------------------------------------------------

_pg_require_env() {
    : "${_INFRA_PG_CONTAINER_NAME:?_INFRA_PG_CONTAINER_NAME required}"
    : "${_INFRA_PG_VERSION:?_INFRA_PG_VERSION required}"
    : "${_INFRA_PG_HOST:?_INFRA_PG_HOST required}"
    : "${_INFRA_PG_PORT:?_INFRA_PG_PORT required}"
    : "${_INFRA_PG_USER:?_INFRA_PG_USER required}"
    : "${_INFRA_PG_REPLICA_ENABLED:=false}"
    : "${_INFRA_PG_PORT_R:=}"
}

_pg_check_status() {
    export PGCONNECT_TIMEOUT="${PGCONNECT_TIMEOUT:-5}"
    if psql -w -h "${_INFRA_PG_HOST}" -p "${_INFRA_PG_PORT}" -U "${_INFRA_PG_USER}" -c "SELECT 1" >/dev/null 2>&1; then
        _primary_up=true
        _primary_status="${_GREEN}UP${_RESET}"
    else
        _primary_up=false
        _primary_status="${_RED}DOWN${_RESET}"
    fi

    _standby_up=false
    _standby_status="${_RED}DOWN${_RESET}"
    if [ "$_INFRA_PG_REPLICA_ENABLED" = "true" ]; then
        if psql -w -h "${_INFRA_PG_HOST}" -p "${_INFRA_PG_PORT_R}" -U "${_INFRA_PG_USER}" -c "SELECT 1" >/dev/null 2>&1; then
            _standby_up=true
            _standby_status="${_GREEN}UP${_RESET}"
        fi
    fi
}

_pg_info_short() {
    if [ "$_INFRA_PG_REPLICA_ENABLED" = "true" ]; then
        echo -e "${_BOLD}Endpoints:${_RESET} Primary ${_primary_status} (${_INFRA_PG_HOST}:${_INFRA_PG_PORT}) | Standby ${_standby_status} (${_INFRA_PG_HOST}:${_INFRA_PG_PORT_R})"
    else
        echo -e "${_BOLD}Endpoint:${_RESET} ${_primary_status} (${_INFRA_PG_HOST}:${_INFRA_PG_PORT})"
    fi

    if [ "$_primary_up" = true ]; then
        if [ "$_INFRA_PG_REPLICA_ENABLED" = "true" ]; then
            local repl_state repl_sync
            repl_state=$(psql -h "${_INFRA_PG_HOST}" -p "${_INFRA_PG_PORT}" -U "${_INFRA_PG_USER}" -t -A -c "SELECT state FROM pg_stat_replication LIMIT 1;" 2>/dev/null)
            if [ -n "$repl_state" ]; then
                repl_sync=$(psql -h "${_INFRA_PG_HOST}" -p "${_INFRA_PG_PORT}" -U "${_INFRA_PG_USER}" -t -A -c "SELECT sync_state FROM pg_stat_replication LIMIT 1;" 2>/dev/null)
                echo -e "${_BOLD}Replication:${_RESET} ${_YELLOW}${repl_state}${_RESET} (${repl_sync})"
            else
                echo -e "${_BOLD}Replication:${_RESET} ${_GRAY}not active${_RESET}"
            fi
        fi

        local db_info db_count db_size active_conns
        db_info=$(psql -h "${_INFRA_PG_HOST}" -p "${_INFRA_PG_PORT}" -U "${_INFRA_PG_USER}" -t -A -c "SELECT COUNT(*), pg_size_pretty(SUM(pg_database_size(datname))) FROM pg_database WHERE datistemplate = false;" 2>/dev/null)
        db_count=$(echo "$db_info" | cut -d'|' -f1)
        db_size=$(echo "$db_info" | cut -d'|' -f2)
        active_conns=$(psql -h "${_INFRA_PG_HOST}" -p "${_INFRA_PG_PORT}" -U "${_INFRA_PG_USER}" -t -A -c "SELECT COUNT(*) FROM pg_stat_activity WHERE state != 'idle' AND pid != pg_backend_pid();" 2>/dev/null)

        echo -e "${_BOLD}Databases:${_RESET} ${_BLUE}${db_count}${_RESET} (${db_size}) | ${_BOLD}Active connections:${_RESET} ${_BLUE}${active_conns}${_RESET}"
    else
        echo -e "${_BOLD}Status:${_RESET} ${_RED}Primary server is down${_RESET}"
    fi
}

# ---------------------------------------------------------------------------
# info — full output helpers (each ~10-15 lines, single responsibility)
# ---------------------------------------------------------------------------

_pg_info_containers() {
    local runtime="${INFRA_CONTAINER_CMD:-docker}"
    local output exit_code=0
    output=$(${runtime} ps -a --filter "name=${_INFRA_PG_CONTAINER_NAME}" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" 2>&1) || exit_code=$?
    if [ $exit_code -ne 0 ]; then
        echo -e "${_RED}Error from '${runtime}' (exit $exit_code):${_RESET}"
        echo "$output"
        exit $exit_code
    elif [ "$(echo "$output" | wc -l)" -le 1 ]; then
        echo "No PostgreSQL containers found"
    else
        echo "$output"
    fi
}

_pg_info_config() {
    echo -e "Version:          ${_BLUE}PostgreSQL ${_INFRA_PG_VERSION}${_RESET}"
    echo -e "Container Name:   ${_BLUE}${_INFRA_PG_CONTAINER_NAME}${_RESET}"
    if [ "$_INFRA_PG_REPLICA_ENABLED" = "true" ]; then
        echo -e "Primary Port:     ${_BLUE}${_INFRA_PG_PORT}${_RESET}"
        echo -e "Standby Port:     ${_BLUE}${_INFRA_PG_PORT_R}${_RESET}"
    else
        echo -e "Port:             ${_BLUE}${_INFRA_PG_PORT}${_RESET}"
    fi
}

_pg_info_endpoints() {
    if [ "$_INFRA_PG_REPLICA_ENABLED" = "true" ]; then
        printf "%-30s " "Primary (${_INFRA_PG_HOST}:${_INFRA_PG_PORT}):"
        echo -e "${_primary_status}"
        printf "%-30s " "Standby (${_INFRA_PG_HOST}:${_INFRA_PG_PORT_R}):"
        echo -e "${_standby_status}"
    else
        printf "%-30s " "Server (${_INFRA_PG_HOST}:${_INFRA_PG_PORT}):"
        echo -e "${_primary_status}"
    fi
}

_pg_info_replication() {
    psql -h "${_INFRA_PG_HOST}" -p "${_INFRA_PG_PORT}" -U "${_INFRA_PG_USER}" \
        -c "SELECT client_addr AS standby_addr, state, sync_state FROM pg_stat_replication;" 2>/dev/null \
        || echo "No replication active"
}

_pg_info_databases() {
    psql -h "${_INFRA_PG_HOST}" -p "${_INFRA_PG_PORT}" -U "${_INFRA_PG_USER}" \
        -c "SELECT datname AS database, pg_size_pretty(pg_database_size(datname)) AS size, \
            (SELECT count(*) FROM pg_stat_activity WHERE datname = d.datname) AS connections \
            FROM pg_database d WHERE datistemplate = false ORDER BY pg_database_size(datname) DESC;" 2>/dev/null
}

_pg_info_tables() {
    local db
    for db in $(psql -h "${_INFRA_PG_HOST}" -p "${_INFRA_PG_PORT}" -U "${_INFRA_PG_USER}" \
                -t -A -c "SELECT datname FROM pg_database WHERE datistemplate = false AND datname != 'postgres';" 2>/dev/null); do
        echo ""
        echo -e "${_YELLOW}Database: ${db}${_RESET}"
        psql -h "${_INFRA_PG_HOST}" -p "${_INFRA_PG_PORT}" -U "${_INFRA_PG_USER}" -d "${db}" \
            -c "SELECT schemaname || '.' || tablename AS table, \
                pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size \
                FROM pg_tables WHERE schemaname NOT IN ('pg_catalog', 'information_schema') \
                ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC LIMIT 10;" 2>/dev/null \
            || echo "  (no tables or access denied)"
    done
}

_pg_info_connections() {
    psql -h "${_INFRA_PG_HOST}" -p "${_INFRA_PG_PORT}" -U "${_INFRA_PG_USER}" \
        -c "SELECT datname AS database, usename AS user, application_name AS app, \
            client_addr AS client, state, query_start \
            FROM pg_stat_activity WHERE state != 'idle' AND pid != pg_backend_pid() \
            ORDER BY query_start;" 2>/dev/null
}

_pg_info_full() {
    echo ""
    echo -e "${_BOLD}${_CYAN}PostgreSQL Infrastructure Status${_RESET}"
    echo -e "${_CYAN}================================${_RESET}"
    echo ""

    echo -e "${_BOLD}CONTAINERS${_RESET}"
    echo -e "${_GRAY}----------${_RESET}"
    _pg_info_containers
    echo ""

    echo -e "${_BOLD}SYSTEM CONFIGURATION${_RESET}"
    echo -e "${_GRAY}--------------------${_RESET}"
    _pg_info_config
    echo ""

    echo -e "${_BOLD}CONNECTION ENDPOINTS${_RESET}"
    echo -e "${_GRAY}--------------------${_RESET}"
    _pg_info_endpoints
    echo ""

    if [ "$_primary_up" = true ]; then
        if [ "$_INFRA_PG_REPLICA_ENABLED" = "true" ]; then
            echo -e "${_BOLD}REPLICATION STATUS${_RESET}"
            echo -e "${_GRAY}------------------${_RESET}"
            _pg_info_replication
            echo ""
        fi

        echo -e "${_BOLD}DATABASES${_RESET}"
        echo -e "${_GRAY}---------${_RESET}"
        _pg_info_databases
        echo ""

        echo -e "${_BOLD}TOP TABLES BY SIZE${_RESET}"
        echo -e "${_GRAY}------------------${_RESET}"
        _pg_info_tables
        echo ""

        echo -e "${_BOLD}ACTIVE CONNECTIONS${_RESET}"
        echo -e "${_GRAY}------------------${_RESET}"
        _pg_info_connections
        echo ""
    else
        echo -e "${_BOLD}DATABASES${_RESET}"
        echo -e "${_GRAY}---------${_RESET}"
        echo -e "${_RED}(Cannot connect to database - server may be down)${_RESET}"
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
# clean — drop configured databases (allowlisted via _INFRA_PG_DATABASES)
# ---------------------------------------------------------------------------

_pg_clean() {
    : "${_INFRA_PG_HOST:?_INFRA_PG_HOST required}"
    : "${_INFRA_PG_PORT:?_INFRA_PG_PORT required}"
    : "${_INFRA_PG_USER:?_INFRA_PG_USER required}"

    if [ -z "${_INFRA_PG_DATABASES:-}" ]; then
        echo "no databases configured"
        return 0
    fi

    echo "* cleaning pg databases..."
    local db exists failed=0
    set -f  # disable pathname expansion for the loop
    for db in ${_INFRA_PG_DATABASES}; do
        set +f
        if ! echo "${db}" | grep -Eq '^[A-Za-z_][A-Za-z0-9_]*$'; then
            echo "  * skipping unsafe database name: ${db}"
            continue
        fi
        if ! exists=$(psql -w -h "${_INFRA_PG_HOST}" -p "${_INFRA_PG_PORT}" -U "${_INFRA_PG_USER}" \
            -d postgres -XtAc "SELECT 1 FROM pg_database WHERE datname='${db}'" 2>&1); then
            echo "  * error checking ${db}: ${exists}" >&2
            failed=1
            continue
        fi
        if [ "${exists}" = "1" ]; then
            echo "  * dropping db ${db}..."
            if ! psql -w -h "${_INFRA_PG_HOST}" -p "${_INFRA_PG_PORT}" -U "${_INFRA_PG_USER}" \
                -d postgres -c "DROP DATABASE \"${db}\" WITH (FORCE)"; then
                echo "  * failed to drop ${db}" >&2
                failed=1
            fi
        else
            echo "  * database ${db} not found"
        fi
    done
    set +f
    if [ "${failed}" = "1" ]; then
        echo "* done cleaning pg databases (with errors)" >&2
        return 1
    fi
    echo "* done cleaning pg databases"
}

# ---------------------------------------------------------------------------
# psql — interactive shell (--target primary|standby; default primary)
# ---------------------------------------------------------------------------

_pg_psql() {
    # Connection-only checks (don't require PG_VERSION — not needed for psql).
    : "${_INFRA_PG_HOST:?_INFRA_PG_HOST required}"
    : "${_INFRA_PG_PORT:?_INFRA_PG_PORT required}"
    : "${_INFRA_PG_USER:?_INFRA_PG_USER required}"
    : "${_INFRA_PG_REPLICA_ENABLED:=false}"
    : "${_INFRA_PG_PORT_R:=}"

    local target="primary"
    if [ "${1:-}" = "--target" ]; then
        shift
        target="${1:?pg.sh psql --target: value required (primary|standby)}"
        shift
    fi

    local port
    case "${target}" in
        primary)
            port="${_INFRA_PG_PORT}"
            ;;
        standby)
            if [ "${_INFRA_PG_REPLICA_ENABLED}" != "true" ]; then
                echo "pg.sh psql --target standby: replica not enabled" >&2
                exit 2
            fi
            : "${_INFRA_PG_PORT_R:?_INFRA_PG_PORT_R required for --target standby}"
            port="${_INFRA_PG_PORT_R}"
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

    PAGER='less -S' exec psql -h "${_INFRA_PG_HOST}" -p "${port}" -U "${_INFRA_PG_USER}"
}

# ---------------------------------------------------------------------------
# top — pg_top for the primary server
# ---------------------------------------------------------------------------

_pg_top() {
    : "${_INFRA_PG_HOST:?_INFRA_PG_HOST required}"
    : "${_INFRA_PG_PORT:?_INFRA_PG_PORT required}"
    : "${_INFRA_PG_USER:?_INFRA_PG_USER required}"
    exec pg_top -h "${_INFRA_PG_HOST}" -p "${_INFRA_PG_PORT}" -U "${_INFRA_PG_USER}"
}

# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

_pg_usage() {
    cat >&2 <<'USAGE'
usage: pg.sh <cmd> [args]

commands:
  up                start server (mode via _INFRA_PG_MODE=single|repl; wait unless _INFRA_PG_WAIT=0)
  down              stop server (auto-detects mode; wait unless _INFRA_PG_WAIT=0)
  reboot            restart server (auto-detects mode; wait unless _INFRA_PG_WAIT=0)
  logs              tail server logs (auto-detects mode)
  wait-up           wait for server to accept connections (timeout _INFRA_PG_WAIT_TIMEOUT)
  wait-down         wait for containers to be fully removed
  info [--short]    server + database status (comprehensive or one-line summary)
  erase             remove this instance's containers, volumes, networks (destructive;
                    images are never touched — see the post-erase advisory)
  clean             drop databases in _INFRA_PG_DATABASES allowlist (server keeps running)
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
