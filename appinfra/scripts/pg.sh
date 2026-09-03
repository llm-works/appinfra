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
#   _INFRA_PG_REPLICA_ENABLED    "true" enables replica-aware output
#   INFRA_CONTAINER_CMD          container runtime (docker/podman); default docker
#
# The `_INFRA_PG_*` prefix marks these as an internal wire protocol between the
# caller layer and pg.sh — subject to change, not part of the public
# INFRA_PG_* / INFRA_PGSERVER_* user-facing configuration surface.

set -euo pipefail

# ---------------------------------------------------------------------------
# Shared: color codes
# ---------------------------------------------------------------------------

_BOLD='\033[1m' _RED='\033[0;31m' _GREEN='\033[0;32m'
_YELLOW='\033[0;33m' _BLUE='\033[0;34m' _CYAN='\033[0;36m'
_GRAY='\033[0;90m' _RESET='\033[0m'

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

_pg_info_full() {
    local container_runtime="${INFRA_CONTAINER_CMD:-docker}"

    echo ""
    echo -e "${_BOLD}${_CYAN}PostgreSQL Infrastructure Status${_RESET}"
    echo -e "${_CYAN}================================${_RESET}"
    echo ""

    echo -e "${_BOLD}CONTAINERS${_RESET}"
    echo -e "${_GRAY}----------${_RESET}"
    local container_output container_exit=0
    container_output=$(${container_runtime} ps -a --filter "name=${_INFRA_PG_CONTAINER_NAME}" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" 2>&1) || container_exit=$?
    if [ $container_exit -ne 0 ]; then
        echo -e "${_RED}Error from '${container_runtime}' (exit $container_exit):${_RESET}"
        echo "$container_output"
        exit $container_exit
    elif [ "$(echo "$container_output" | wc -l)" -le 1 ]; then
        echo "No PostgreSQL containers found"
    else
        echo "$container_output"
    fi
    echo ""

    echo -e "${_BOLD}SYSTEM CONFIGURATION${_RESET}"
    echo -e "${_GRAY}--------------------${_RESET}"
    echo -e "Version:          ${_BLUE}PostgreSQL ${_INFRA_PG_VERSION}${_RESET}"
    echo -e "Container Name:   ${_BLUE}${_INFRA_PG_CONTAINER_NAME}${_RESET}"
    if [ "$_INFRA_PG_REPLICA_ENABLED" = "true" ]; then
        echo -e "Primary Port:     ${_BLUE}${_INFRA_PG_PORT}${_RESET}"
        echo -e "Standby Port:     ${_BLUE}${_INFRA_PG_PORT_R}${_RESET}"
    else
        echo -e "Port:             ${_BLUE}${_INFRA_PG_PORT}${_RESET}"
    fi
    echo ""

    echo -e "${_BOLD}CONNECTION ENDPOINTS${_RESET}"
    echo -e "${_GRAY}--------------------${_RESET}"
    if [ "$_INFRA_PG_REPLICA_ENABLED" = "true" ]; then
        printf "%-30s " "Primary (${_INFRA_PG_HOST}:${_INFRA_PG_PORT}):"
        echo -e "${_primary_status}"
        printf "%-30s " "Standby (${_INFRA_PG_HOST}:${_INFRA_PG_PORT_R}):"
        echo -e "${_standby_status}"
    else
        printf "%-30s " "Server (${_INFRA_PG_HOST}:${_INFRA_PG_PORT}):"
        echo -e "${_primary_status}"
    fi
    echo ""

    if [ "$_primary_up" = true ]; then
        if [ "$_INFRA_PG_REPLICA_ENABLED" = "true" ]; then
            echo -e "${_BOLD}REPLICATION STATUS${_RESET}"
            echo -e "${_GRAY}------------------${_RESET}"
            psql -h "${_INFRA_PG_HOST}" -p "${_INFRA_PG_PORT}" -U "${_INFRA_PG_USER}" -c "SELECT client_addr AS standby_addr, state, sync_state FROM pg_stat_replication;" 2>/dev/null || echo "No replication active"
            echo ""
        fi

        echo -e "${_BOLD}DATABASES${_RESET}"
        echo -e "${_GRAY}---------${_RESET}"
        psql -h "${_INFRA_PG_HOST}" -p "${_INFRA_PG_PORT}" -U "${_INFRA_PG_USER}" -c "SELECT datname AS database, pg_size_pretty(pg_database_size(datname)) AS size, (SELECT count(*) FROM pg_stat_activity WHERE datname = d.datname) AS connections FROM pg_database d WHERE datistemplate = false ORDER BY pg_database_size(datname) DESC;" 2>/dev/null
        echo ""

        echo -e "${_BOLD}TOP TABLES BY SIZE${_RESET}"
        echo -e "${_GRAY}------------------${_RESET}"
        local db
        for db in $(psql -h "${_INFRA_PG_HOST}" -p "${_INFRA_PG_PORT}" -U "${_INFRA_PG_USER}" -t -A -c "SELECT datname FROM pg_database WHERE datistemplate = false AND datname != 'postgres';" 2>/dev/null); do
            echo ""
            echo -e "${_YELLOW}Database: ${db}${_RESET}"
            psql -h "${_INFRA_PG_HOST}" -p "${_INFRA_PG_PORT}" -U "${_INFRA_PG_USER}" -d "${db}" -c "SELECT schemaname || '.' || tablename AS table, pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size FROM pg_tables WHERE schemaname NOT IN ('pg_catalog', 'information_schema') ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC LIMIT 10;" 2>/dev/null || echo "  (no tables or access denied)"
        done
        echo ""

        echo -e "${_BOLD}ACTIVE CONNECTIONS${_RESET}"
        echo -e "${_GRAY}------------------${_RESET}"
        psql -h "${_INFRA_PG_HOST}" -p "${_INFRA_PG_PORT}" -U "${_INFRA_PG_USER}" -c "SELECT datname AS database, usename AS user, application_name AS app, client_addr AS client, state, query_start FROM pg_stat_activity WHERE state != 'idle' AND pid != pg_backend_pid() ORDER BY query_start;" 2>/dev/null
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
# Dispatcher
# ---------------------------------------------------------------------------

_pg_usage() {
    cat >&2 <<'USAGE'
usage: pg.sh <cmd> [args]

commands:
  info [--short]    server + database status (comprehensive or one-line summary)

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
case "$cmd" in
    info) _pg_info "$@" ;;
    -h | --help | help) _pg_usage ;;
    *)
        echo "pg.sh: unknown command: $cmd" >&2
        _pg_usage
        ;;
esac
