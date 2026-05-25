#!/usr/bin/env bash
# Returns path to mkdocs config file
# Usage: docs-config.sh <config_file> <etc_dir> <default_config_file>
#
# If config_file is empty, extracts 'docs' section from default_config_file
# and writes it to a temp mkdocs.yaml. Otherwise, uses config_file directly.
#
# Output: Path to mkdocs config file (for use by mkdocs -f)

CONFIG_FILE="$1"
ETC_DIR="$2"
DEFAULT_CONFIG_FILE="$3"

# If specific docs config provided, use it directly
if [ -n "$CONFIG_FILE" ]; then
    FULL_PATH="$ETC_DIR/$CONFIG_FILE"
    if [ -f "$FULL_PATH" ]; then
        echo "$FULL_PATH"
        exit 0
    else
        echo "Error: Config file not found: $FULL_PATH" >&2
        exit 1
    fi
fi

# No specific config - extract 'docs' section from default config
DEFAULT_PATH="$ETC_DIR/$DEFAULT_CONFIG_FILE"

if [ ! -f "$DEFAULT_PATH" ]; then
    echo "Error: Default config file not found: $DEFAULT_PATH" >&2
    exit 1
fi

# Check if 'docs' section exists and extract it
python3 -c "
import yaml
import sys
import tempfile
import os

# SafeLoader that ignores unknown tags (e.g., !include)
class SafeLoaderIgnoreUnknown(yaml.SafeLoader):
    pass
SafeLoaderIgnoreUnknown.add_constructor(None, lambda loader, node: None)

with open('$DEFAULT_PATH') as f:
    config = yaml.load(f, Loader=SafeLoaderIgnoreUnknown)

docs_config = config.get('docs', {})
if not docs_config:
    print('Error: No docs section found in $DEFAULT_PATH', file=sys.stderr)
    sys.exit(1)

# Write to temp file in project's .cache directory
cache_dir = os.path.join(os.environ.get('CURDIR', '.'), '.cache')
os.makedirs(cache_dir, exist_ok=True)
temp_path = os.path.join(cache_dir, 'mkdocs.yaml')

with open(temp_path, 'w') as f:
    yaml.dump(docs_config, f, default_flow_style=False)

print(temp_path)
"
