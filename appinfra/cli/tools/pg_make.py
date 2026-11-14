# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Entry of the ``make pg.*`` targets: run a pg.sh verb from a config file.

    python -m appinfra.cli.tools.pg_make <config-file> <key> <verb> [args...]

The file loads through ``Config``, so ``!include`` and ``INFRA_*`` overrides
apply as they do for the application, and ``<key>`` (``APPINFRA_PG_CONFIG_KEY``)
goes through the projection of the ``appinfra pg`` tools. The make settings
``APPINFRA_PG_HOST``, ``APPINFRA_PG_USER`` and ``APPINFRA_PG_DATABASES`` reach
this module as their ``_APPINFRA_PG_*`` wire variables and win over the config.

It runs when a pg target runs, not while make parses: loading ``Config``
costs about 0.1s, which every make invocation would otherwise pay.
"""

import os
import sys
from pathlib import Path

import yaml

from ...config import Config
from ...errors import ConfigError
from .pg_tool import _exec_pg

# Wire variables Makefile.pg sets from make's own settings.
_MAKE_OWNED = ("_APPINFRA_PG_HOST", "_APPINFRA_PG_USER", "_APPINFRA_PG_DATABASES")

_USAGE = (
    "usage: python -m appinfra.cli.tools.pg_make <config-file> <key> <verb> [args...]"
)


def main(argv: list[str]) -> int:
    """Load the config file and run the pg.sh verb; returns its exit code."""
    if len(argv) < 3:
        print(_USAGE, file=sys.stderr)
        return 2
    path, key, verb, *args = argv
    if not Path(path).is_file():
        print(f"pg: config file not found: {path}", file=sys.stderr)
        return 2
    make_owned = {
        name: os.environ[name] for name in _MAKE_OWNED if os.environ.get(name)
    }
    try:
        cfg = Config.from_path(path)
        return _exec_pg(cfg, verb, extra_args=args, extra_env=make_owned, key=key)
    except (ConfigError, ValueError, yaml.YAMLError) as e:
        print(f"pg: {path}: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
