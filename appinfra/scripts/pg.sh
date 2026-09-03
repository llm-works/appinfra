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
# info — comprehensive server + database status (also --short summary line)
# ---------------------------------------------------------------------------

_pg_info() {
    local short_mode=false
    if [ "${1:-}" = "--short" ]; then
        short_mode=true
        shift
    fi

    : "${_INFRA_PG_CONTAINER_NAME:?_INFRA_PG_CONTAINER_NAME required}"
    : "${_INFRA_PG_VERSION:?_INFRA_PG_VERSION required}"
    : "${_INFRA_PG_HOST:?_INFRA_PG_HOST required}"
    : "${_INFRA_PG_PORT:?_INFRA_PG_PORT required}"
    : "${_INFRA_PG_USER:?_INFRA_PG_USER required}"
    : "${_INFRA_PG_REPLICA_ENABLED:=false}"
    : "${_INFRA_PG_PORT_R:=}"
    local container_runtime="${INFRA_CONTAINER_CMD:-docker}"

    local BOLD='\033[1m' RED='\033[0;31m' GREEN='\033[0;32m'
    local YELLOW='\033[0;33m' BLUE='\033[0;34m' CYAN='\033[0;36m'
    local GRAY='\033[0;90m' RESET='\033[0m'

    # Check connection status first
    local primary_up primary_status
    if psql -h "${_INFRA_PG_HOST}" -p "${_INFRA_PG_PORT}" -U "${_INFRA_PG_USER}" -c "SELECT 1" >/dev/null 2>&1; then
        primary_up=true
        primary_status="${GREEN}UP${RESET}"
    else
        primary_up=false
        primary_status="${RED}DOWN${RESET}"
    fi

    # Only check standby if replica is enabled
    local standby_up=false
    local standby_status="${RED}DOWN${RESET}"
    if [ "$_INFRA_PG_REPLICA_ENABLED" = "true" ]; then
        if psql -h "${_INFRA_PG_HOST}" -p "${_INFRA_PG_PORT_R}" -U "${_INFRA_PG_USER}" -c "SELECT 1" >/dev/null 2>&1; then
            standby_up=true
            standby_status="${GREEN}UP${RESET}"
        fi
    fi

    # Short mode output
    if [ "$short_mode" = true ]; then
        if [ "$_INFRA_PG_REPLICA_ENABLED" = "true" ]; then
            echo -e "${BOLD}Endpoints:${RESET} Primary ${primary_status} (${_INFRA_PG_HOST}:${_INFRA_PG_PORT}) | Standby ${standby_status} (${_INFRA_PG_HOST}:${_INFRA_PG_PORT_R})"
        else
            echo -e "${BOLD}Endpoint:${RESET} ${primary_status} (${_INFRA_PG_HOST}:${_INFRA_PG_PORT})"
        fi

        if [ "$primary_up" = true ]; then
            if [ "$_INFRA_PG_REPLICA_ENABLED" = "true" ]; then
                local repl_state repl_sync
                repl_state=$(psql -h "${_INFRA_PG_HOST}" -p "${_INFRA_PG_PORT}" -U "${_INFRA_PG_USER}" -t -A -c "SELECT state FROM pg_stat_replication LIMIT 1;" 2>/dev/null)
                if [ -n "$repl_state" ]; then
                    repl_sync=$(psql -h "${_INFRA_PG_HOST}" -p "${_INFRA_PG_PORT}" -U "${_INFRA_PG_USER}" -t -A -c "SELECT sync_state FROM pg_stat_replication LIMIT 1;" 2>/dev/null)
                    echo -e "${BOLD}Replication:${RESET} ${YELLOW}${repl_state}${RESET} (${repl_sync})"
                else
                    echo -e "${BOLD}Replication:${RESET} ${GRAY}not active${RESET}"
                fi
            fi

            local db_info db_count db_size active_conns
            db_info=$(psql -h "${_INFRA_PG_HOST}" -p "${_INFRA_PG_PORT}" -U "${_INFRA_PG_USER}" -t -A -c "SELECT COUNT(*), pg_size_pretty(SUM(pg_database_size(datname))) FROM pg_database WHERE datistemplate = false;" 2>/dev/null)
            db_count=$(echo "$db_info" | cut -d'|' -f1)
            db_size=$(echo "$db_info" | cut -d'|' -f2)
            active_conns=$(psql -h "${_INFRA_PG_HOST}" -p "${_INFRA_PG_PORT}" -U "${_INFRA_PG_USER}" -t -A -c "SELECT COUNT(*) FROM pg_stat_activity WHERE state != 'idle' AND pid != pg_backend_pid();" 2>/dev/null)

            echo -e "${BOLD}Databases:${RESET} ${BLUE}${db_count}${RESET} (${db_size}) | ${BOLD}Active connections:${RESET} ${BLUE}${active_conns}${RESET}"
        else
            echo -e "${BOLD}Status:${RESET} ${RED}Primary server is down${RESET}"
        fi

        return 0
    fi

    # Full mode output
    echo ""
    echo -e "${BOLD}${CYAN}PostgreSQL Infrastructure Status${RESET}"
    echo -e "${CYAN}================================${RESET}"
    echo ""

    echo -e "${BOLD}CONTAINERS${RESET}"
    echo -e "${GRAY}----------${RESET}"
    local container_output container_exit
    container_output=$(${container_runtime} ps -a --filter "name=${_INFRA_PG_CONTAINER_NAME}" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" 2>&1)
    container_exit=$?
    if [ $container_exit -ne 0 ]; then
        echo -e "${RED}Error from '${container_runtime}' (exit $container_exit):${RESET}"
        echo "$container_output"
        exit $container_exit
    elif [ "$(echo "$container_output" | wc -l)" -le 1 ]; then
        echo "No PostgreSQL containers found"
    else
        echo "$container_output"
    fi
    echo ""

    echo -e "${BOLD}SYSTEM CONFIGURATION${RESET}"
    echo -e "${GRAY}--------------------${RESET}"
    echo -e "Version:          ${BLUE}PostgreSQL ${_INFRA_PG_VERSION}${RESET}"
    echo -e "Container Name:   ${BLUE}${_INFRA_PG_CONTAINER_NAME}${RESET}"
    if [ "$_INFRA_PG_REPLICA_ENABLED" = "true" ]; then
        echo -e "Primary Port:     ${BLUE}${_INFRA_PG_PORT}${RESET}"
        echo -e "Standby Port:     ${BLUE}${_INFRA_PG_PORT_R}${RESET}"
    else
        echo -e "Port:             ${BLUE}${_INFRA_PG_PORT}${RESET}"
    fi
    echo ""

    echo -e "${BOLD}CONNECTION ENDPOINTS${RESET}"
    echo -e "${GRAY}--------------------${RESET}"
    if [ "$_INFRA_PG_REPLICA_ENABLED" = "true" ]; then
        printf "%-30s " "Primary (${_INFRA_PG_HOST}:${_INFRA_PG_PORT}):"
        echo -e "${primary_status}"
        printf "%-30s " "Standby (${_INFRA_PG_HOST}:${_INFRA_PG_PORT_R}):"
        echo -e "${standby_status}"
    else
        printf "%-30s " "Server (${_INFRA_PG_HOST}:${_INFRA_PG_PORT}):"
        echo -e "${primary_status}"
    fi
    echo ""

    if [ "$primary_up" = true ]; then
        if [ "$_INFRA_PG_REPLICA_ENABLED" = "true" ]; then
            echo -e "${BOLD}REPLICATION STATUS${RESET}"
            echo -e "${GRAY}------------------${RESET}"
            psql -h "${_INFRA_PG_HOST}" -p "${_INFRA_PG_PORT}" -U "${_INFRA_PG_USER}" -c "SELECT client_addr AS standby_addr, state, sync_state FROM pg_stat_replication;" 2>/dev/null || echo "No replication active"
            echo ""
        fi

        echo -e "${BOLD}DATABASES${RESET}"
        echo -e "${GRAY}---------${RESET}"
        psql -h "${_INFRA_PG_HOST}" -p "${_INFRA_PG_PORT}" -U "${_INFRA_PG_USER}" -c "SELECT datname AS database, pg_size_pretty(pg_database_size(datname)) AS size, (SELECT count(*) FROM pg_stat_activity WHERE datname = d.datname) AS connections FROM pg_database d WHERE datistemplate = false ORDER BY pg_database_size(datname) DESC;" 2>/dev/null
        echo ""

        echo -e "${BOLD}TOP TABLES BY SIZE${RESET}"
        echo -e "${GRAY}------------------${RESET}"
        local db
        for db in $(psql -h "${_INFRA_PG_HOST}" -p "${_INFRA_PG_PORT}" -U "${_INFRA_PG_USER}" -t -A -c "SELECT datname FROM pg_database WHERE datistemplate = false AND datname != 'postgres';" 2>/dev/null); do
            echo ""
            echo -e "${YELLOW}Database: ${db}${RESET}"
            psql -h "${_INFRA_PG_HOST}" -p "${_INFRA_PG_PORT}" -U "${_INFRA_PG_USER}" -d "${db}" -c "SELECT schemaname || '.' || tablename AS table, pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size FROM pg_tables WHERE schemaname NOT IN ('pg_catalog', 'information_schema') ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC LIMIT 10;" 2>/dev/null || echo "  (no tables or access denied)"
        done
        echo ""

        echo -e "${BOLD}ACTIVE CONNECTIONS${RESET}"
        echo -e "${GRAY}------------------${RESET}"
        psql -h "${_INFRA_PG_HOST}" -p "${_INFRA_PG_PORT}" -U "${_INFRA_PG_USER}" -c "SELECT datname AS database, usename AS user, application_name AS app, client_addr AS client, state, query_start FROM pg_stat_activity WHERE state != 'idle' AND pid != pg_backend_pid() ORDER BY query_start;" 2>/dev/null
        echo ""
    else
        echo -e "${BOLD}DATABASES${RESET}"
        echo -e "${GRAY}---------${RESET}"
        echo -e "${RED}(Cannot connect to database - server may be down)${RESET}"
        echo ""
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
