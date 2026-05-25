#!/usr/bin/env bash
# Outputs Make variable assignments for PG config
# Usage: pg-config.sh <config_file> <config_key> <etc_dir> <default_config_file>
# Output: Pipe-separated Make assignments for $(eval $(subst |,$(newline),...))
#
# If config_file is empty, uses default_config_file
# All filenames are resolved from etc_dir

CONFIG_FILE="$1"
CONFIG_KEY="$2"
ETC_DIR="$3"
DEFAULT_CONFIG_FILE="$4"

# Use default if config file not specified
if [ -z "$CONFIG_FILE" ]; then
    CONFIG_FILE="$DEFAULT_CONFIG_FILE"
fi

# Resolve full path
FULL_PATH="$ETC_DIR/$CONFIG_FILE"

# Check if file exists
if [ ! -f "$FULL_PATH" ]; then
    echo "PG_DOCKER_IMAGE:=|PG_VERSION:=|PG_PORT:=|PG_IMAGE:=|PG_REPLICA_ENABLED:=false|PG_PORT_R:=|PG_COMMAND:=postgres"
    exit 0
fi

python3 -c "
import yaml

# SafeLoader that ignores unknown tags (e.g., !include)
class SafeLoaderIgnoreUnknown(yaml.SafeLoader):
    pass
SafeLoaderIgnoreUnknown.add_constructor(None, lambda loader, node: None)

with open('$FULL_PATH') as f:
    cfg = yaml.load(f, Loader=SafeLoaderIgnoreUnknown).get('$CONFIG_KEY', {})

replica = cfg.get('replica', {})
replica_enabled = str(replica.get('enabled', False)).lower()
replica_port = replica.get('port', '')

# Build postgres command from config
postgres_conf = cfg.get('postgres_conf', {})

cmd_parts = ['postgres']

# Add config params as -c key=value arguments
# PostgreSQL quoting rules (per docs):
# - Booleans (on/off/true/false): no quotes
# - Numbers (int/float): no quotes
# - Strings: single quotes required
for key, value in postgres_conf.items():
    if isinstance(value, bool):
        # Boolean -> on/off (no quotes needed)
        value = 'on' if value else 'off'
        cmd_parts.extend(['-c', f'{key}={value}'])
    elif isinstance(value, (int, float)):
        # Numbers don't need quotes
        cmd_parts.extend(['-c', f'{key}={value}'])
    elif isinstance(value, list):
        # Lists become comma-separated strings (single quotes)
        value = ','.join(str(v) for v in value)
        cmd_parts.extend(['-c', f\"{key}='{value}'\"])
    else:
        # String values need single quotes
        cmd_parts.extend(['-c', f\"{key}='{value}'\"])

pg_command = ' '.join(cmd_parts)

# Output Make variable assignments (pipe-separated, converted to newlines by Makefile)
parts = [
    f'PG_DOCKER_IMAGE:={cfg.get(\"name\", \"\")}',
    f'PG_VERSION:={cfg.get(\"version\", \"\")}',
    f'PG_PORT:={cfg.get(\"port\", \"\")}',
    f'PG_IMAGE:={cfg.get(\"image\", \"\")}',
    f'PG_REPLICA_ENABLED:={replica_enabled}',
    f'PG_PORT_R:={replica_port}',
    f'PG_COMMAND:={pg_command}',
]
print('|'.join(parts))
"
