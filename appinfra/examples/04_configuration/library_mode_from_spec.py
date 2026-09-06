#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Library-mode bootstrap via Config.from_spec.

Demonstrates the canonical library-mode pattern from
docs/guides/library-mode-bootstrap.md § Case D: a package that ships
its default configuration at <pkg>/etc/<pkg>.yaml loads it in one
call, with no CLI shell involved.

Layout:

    library_mode_from_spec.py           <- this file
    example_pkg/
        __init__.py                     <- the synthetic library
        etc/
            example-pkg.yaml            <- the packaged base config

Config.from_spec derives the base path as
    Path(example_pkg.__file__).parent / "etc" / "example-pkg.yaml"

(default filename: module_name.replace("_", "-") + ".yaml", matching
the PEP 8 module → dashed distribution name convention).

Running (assumes appinfra is installed in the active environment):

    python appinfra/examples/04_configuration/library_mode_from_spec.py

Expected output (assumes no XDG override at example-org/example-pkg.yaml):

    bootstrap ok  app[example-pkg] port[8080]
    hello from the packaged base config
"""

import sys
from pathlib import Path

# Allow running from a source checkout without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import example_pkg  # noqa: E402

from appinfra.config import Config  # noqa: E402
from appinfra.log import create_root_lg  # noqa: E402


def main() -> None:
    config = Config.from_spec("example-org", example_pkg)
    lg = create_root_lg(level="info")
    lg.info(
        "bootstrap ok",
        extra={"app": config.app.name, "port": config.app.port},
    )
    lg.info(config.app.greeting)


if __name__ == "__main__":
    main()
