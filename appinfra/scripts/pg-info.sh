#!/usr/bin/env bash
# PostgreSQL infrastructure status display
# Comprehensive operational information with colored output

# Color codes
BOLD='\033[1m'
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
GRAY='\033[0;90m'
RESET='\033[0m'

# Parse options
SHORT_MODE=false
if [ "$1" = "--short" ]; then
    SHORT_MODE=true
    shift
fi

# Arguments passed from Makefile
PG_CONTAINER_NAME="$1"
PG_VERSION="$2"
PG_HOST="$3"
PG_PORT="$4"
PG_PORT_R="$5"
PG_USER="$6"
PG_REPLICA_ENABLED="$7"

# Check connection status first
if psql -h "${PG_HOST}" -p "${PG_PORT}" -U "${PG_USER}" -c "SELECT 1" >/dev/null 2>&1; then
    PRIMARY_UP=true
    PRIMARY_STATUS="${GREEN}UP${RESET}"
else
    PRIMARY_UP=false
    PRIMARY_STATUS="${RED}DOWN${RESET}"
fi

# Only check standby if replica is enabled
STANDBY_UP=false
STANDBY_STATUS="${RED}DOWN${RESET}"
if [ "$PG_REPLICA_ENABLED" = "true" ]; then
    if psql -h "${PG_HOST}" -p "${PG_PORT_R}" -U "${PG_USER}" -c "SELECT 1" >/dev/null 2>&1; then
        STANDBY_UP=true
        STANDBY_STATUS="${GREEN}UP${RESET}"
    fi
fi

# Short mode output
if [ "$SHORT_MODE" = true ]; then
    # Connection status
    if [ "$PG_REPLICA_ENABLED" = "true" ]; then
        echo -e "${BOLD}Endpoints:${RESET} Primary ${PRIMARY_STATUS} (${PG_HOST}:${PG_PORT}) | Standby ${STANDBY_STATUS} (${PG_HOST}:${PG_PORT_R})"
    else
        echo -e "${BOLD}Endpoint:${RESET} ${PRIMARY_STATUS} (${PG_HOST}:${PG_PORT})"
    fi

    if [ "$PRIMARY_UP" = true ]; then
        # Replication status (only show if replica enabled)
        if [ "$PG_REPLICA_ENABLED" = "true" ]; then
            REPL_STATE=$(psql -h "${PG_HOST}" -p "${PG_PORT}" -U "${PG_USER}" -t -A -c "SELECT state FROM pg_stat_replication LIMIT 1;" 2>/dev/null)
            if [ -n "$REPL_STATE" ]; then
                REPL_SYNC=$(psql -h "${PG_HOST}" -p "${PG_PORT}" -U "${PG_USER}" -t -A -c "SELECT sync_state FROM pg_stat_replication LIMIT 1;" 2>/dev/null)
                echo -e "${BOLD}Replication:${RESET} ${YELLOW}${REPL_STATE}${RESET} (${REPL_SYNC})"
            else
                echo -e "${BOLD}Replication:${RESET} ${GRAY}not active${RESET}"
            fi
        fi

        # Database info
        DB_INFO=$(psql -h "${PG_HOST}" -p "${PG_PORT}" -U "${PG_USER}" -t -A -c "SELECT COUNT(*), pg_size_pretty(SUM(pg_database_size(datname))) FROM pg_database WHERE datistemplate = false;" 2>/dev/null)
        DB_COUNT=$(echo "$DB_INFO" | cut -d'|' -f1)
        DB_SIZE=$(echo "$DB_INFO" | cut -d'|' -f2)

        # Active connections
        ACTIVE_CONNS=$(psql -h "${PG_HOST}" -p "${PG_PORT}" -U "${PG_USER}" -t -A -c "SELECT COUNT(*) FROM pg_stat_activity WHERE state != 'idle' AND pid != pg_backend_pid();" 2>/dev/null)

        echo -e "${BOLD}Databases:${RESET} ${BLUE}${DB_COUNT}${RESET} (${DB_SIZE}) | ${BOLD}Active connections:${RESET} ${BLUE}${ACTIVE_CONNS}${RESET}"
    else
        echo -e "${BOLD}Status:${RESET} ${RED}Primary server is down${RESET}"
    fi

    exit 0
fi

# Full mode output
echo ""
echo -e "${BOLD}${CYAN}PostgreSQL Infrastructure Status${RESET}"
echo -e "${CYAN}================================${RESET}"
echo ""

# Containers (runtime via INFRA_CONTAINER_CMD; defaults to docker)
echo -e "${BOLD}CONTAINERS${RESET}"
echo -e "${GRAY}----------${RESET}"
${INFRA_CONTAINER_CMD:-docker} ps -a --filter "name=${PG_CONTAINER_NAME}" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null || echo "No PostgreSQL containers found"
echo ""

# System configuration
echo -e "${BOLD}SYSTEM CONFIGURATION${RESET}"
echo -e "${GRAY}--------------------${RESET}"
echo -e "Version:          ${BLUE}PostgreSQL ${PG_VERSION}${RESET}"
echo -e "Container Name:   ${BLUE}${PG_CONTAINER_NAME}${RESET}"
if [ "$PG_REPLICA_ENABLED" = "true" ]; then
    echo -e "Primary Port:     ${BLUE}${PG_PORT}${RESET}"
    echo -e "Standby Port:     ${BLUE}${PG_PORT_R}${RESET}"
else
    echo -e "Port:             ${BLUE}${PG_PORT}${RESET}"
fi
echo ""

# Connection endpoints
echo -e "${BOLD}CONNECTION ENDPOINTS${RESET}"
echo -e "${GRAY}--------------------${RESET}"
if [ "$PG_REPLICA_ENABLED" = "true" ]; then
    printf "%-30s " "Primary (${PG_HOST}:${PG_PORT}):"
    echo -e "${PRIMARY_STATUS}"
    printf "%-30s " "Standby (${PG_HOST}:${PG_PORT_R}):"
    echo -e "${STANDBY_STATUS}"
else
    printf "%-30s " "Server (${PG_HOST}:${PG_PORT}):"
    echo -e "${PRIMARY_STATUS}"
fi
echo ""

# Only show database information if primary is up
if [ "$PRIMARY_UP" = true ]; then
    # Replication status (only if replica enabled)
    if [ "$PG_REPLICA_ENABLED" = "true" ]; then
        echo -e "${BOLD}REPLICATION STATUS${RESET}"
        echo -e "${GRAY}------------------${RESET}"
        psql -h "${PG_HOST}" -p "${PG_PORT}" -U "${PG_USER}" -c "SELECT client_addr AS standby_addr, state, sync_state FROM pg_stat_replication;" 2>/dev/null || echo "No replication active"
        echo ""
    fi

    # Databases with sizes
    echo -e "${BOLD}DATABASES${RESET}"
    echo -e "${GRAY}---------${RESET}"
    psql -h "${PG_HOST}" -p "${PG_PORT}" -U "${PG_USER}" -c "SELECT datname AS database, pg_size_pretty(pg_database_size(datname)) AS size, (SELECT count(*) FROM pg_stat_activity WHERE datname = d.datname) AS connections FROM pg_database d WHERE datistemplate = false ORDER BY pg_database_size(datname) DESC;" 2>/dev/null
    echo ""

    # Top tables by size for each database
    echo -e "${BOLD}TOP TABLES BY SIZE${RESET}"
    echo -e "${GRAY}------------------${RESET}"
    for db in $(psql -h "${PG_HOST}" -p "${PG_PORT}" -U "${PG_USER}" -t -A -c "SELECT datname FROM pg_database WHERE datistemplate = false AND datname != 'postgres';" 2>/dev/null); do
        echo ""
        echo -e "${YELLOW}Database: ${db}${RESET}"
        psql -h "${PG_HOST}" -p "${PG_PORT}" -U "${PG_USER}" -d "${db}" -c "SELECT schemaname || '.' || tablename AS table, pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size FROM pg_tables WHERE schemaname NOT IN ('pg_catalog', 'information_schema') ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC LIMIT 10;" 2>/dev/null || echo "  (no tables or access denied)"
    done
    echo ""

    # Active connections
    echo -e "${BOLD}ACTIVE CONNECTIONS${RESET}"
    echo -e "${GRAY}------------------${RESET}"
    psql -h "${PG_HOST}" -p "${PG_PORT}" -U "${PG_USER}" -c "SELECT datname AS database, usename AS user, application_name AS app, client_addr AS client, state, query_start FROM pg_stat_activity WHERE state != 'idle' AND pid != pg_backend_pid() ORDER BY query_start;" 2>/dev/null
    echo ""
else
    echo -e "${BOLD}DATABASES${RESET}"
    echo -e "${GRAY}---------${RESET}"
    echo -e "${RED}(Cannot connect to database - server may be down)${RESET}"
    echo ""
fi
