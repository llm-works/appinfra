#!/usr/bin/env bash
# Outputs Make variable assignments for PG config
# Usage: pg-config.sh <config_file> <config_key> <etc_dir> <default_config_file>
# Output: Pipe-separated Make assignments for $(eval $(subst |,$(newline),...))
#
# If config_file is empty, uses default_config_file
# All filenames are resolved from etc_dir
#
# pgserver.postgres_conf is a curated whitelist of postgres knobs. Each one
# becomes a Make var PG_<UPPER>; values flow into compose-substituted slots in
# docker-compose.{single,repl}.yaml of the form
# `${PG_<UPPER>:-<key>=<postgres-default>}`. Unknown keys error out.

CONFIG_FILE="$1"
CONFIG_KEY="$2"
ETC_DIR="$3"
DEFAULT_CONFIG_FILE="$4"

if [ -z "$CONFIG_FILE" ]; then
    CONFIG_FILE="$DEFAULT_CONFIG_FILE"
fi

FULL_PATH="$ETC_DIR/$CONFIG_FILE"

# Empty postgres_conf vars on missing file — recipes that need PG_* will fail
# at recipe time, but parse-time completes.
if [ ! -f "$FULL_PATH" ]; then
    echo "PG_CONTAINER_NAME:=|PG_VERSION:=|PG_PORT:=|PG_IMAGE:=|PG_REPLICA_ENABLED:=false|PG_PORT_R:=|PG_MAX_CONNECTIONS:=|PG_SHARED_PRELOAD_LIBRARIES:=|PG_WORK_MEM:=|PG_AUTOVACUUM:="
    exit 0
fi

python3 -c "
import sys
import yaml

class SafeLoaderIgnoreUnknown(yaml.SafeLoader):
    pass
SafeLoaderIgnoreUnknown.add_constructor(None, lambda loader, node: None)

with open('$FULL_PATH') as f:
    cfg = yaml.load(f, Loader=SafeLoaderIgnoreUnknown).get('$CONFIG_KEY', {})

replica = cfg.get('replica', {})
replica_enabled = str(replica.get('enabled', False)).lower()
replica_port = replica.get('port', '')

# Curated postgres_conf whitelist. Each entry becomes -c key=value at start.
# Adding a new knob: one entry here + one slot in both compose YAMLs.
SUPPORTED = {'max_connections', 'shared_preload_libraries', 'work_mem', 'autovacuum'}

def render(key, value):
    if isinstance(value, bool):
        return f'{key}=' + ('on' if value else 'off')
    if isinstance(value, list):
        return f'{key}=' + ','.join(str(v) for v in value)
    return f'{key}={value}'

postgres_conf = cfg.get('postgres_conf', {}) or {}
unknown = sorted(set(postgres_conf) - SUPPORTED)
if unknown:
    sys.stderr.write(
        f'pg-config: pgserver.postgres_conf has unsupported key(s) {unknown}. '
        f'Supported: {sorted(SUPPORTED)}\n'
    )
    sys.exit(1)

knobs = {k.upper(): render(k, postgres_conf[k]) for k in postgres_conf}

parts = [
    f'PG_CONTAINER_NAME:={cfg.get(\"name\", \"\")}',
    f'PG_VERSION:={cfg.get(\"version\", \"\")}',
    f'PG_PORT:={cfg.get(\"port\", \"\")}',
    f'PG_IMAGE:={cfg.get(\"image\", \"\")}',
    f'PG_REPLICA_ENABLED:={replica_enabled}',
    f'PG_PORT_R:={replica_port}',
    f'PG_MAX_CONNECTIONS:={knobs.get(\"MAX_CONNECTIONS\", \"\")}',
    f'PG_SHARED_PRELOAD_LIBRARIES:={knobs.get(\"SHARED_PRELOAD_LIBRARIES\", \"\")}',
    f'PG_WORK_MEM:={knobs.get(\"WORK_MEM\", \"\")}',
    f'PG_AUTOVACUUM:={knobs.get(\"AUTOVACUUM\", \"\")}',
]
print('|'.join(parts))
"
