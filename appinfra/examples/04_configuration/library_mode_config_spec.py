#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Library-mode bootstrap via ConfigSpec.

Demonstrates the canonical library-mode pattern from
docs/guides/library-mode-bootstrap.md § Case D: a package that ships
its default configuration at <pkg>/etc/<pkg>.yaml resolves the file to
load and loads it, with no CLI shell involved.

Layout:

    library_mode_config_spec.py         <- this file
    example_pkg/
        __init__.py                     <- the synthetic library
        etc/
            example-pkg.yaml            <- the packaged base config

ConfigSpec("example-org", "example-pkg") locates the module `example_pkg`
(config name with "-" mapped to "_") without importing it and derives the
base as <example_pkg>/etc/example-pkg.yaml. resolve() then walks the
precedence chain (project-local, XDG overlay, packaged base) and Config
loads the file it picked.

Running (assumes appinfra is installed in the active environment):

    python appinfra/examples/04_configuration/library_mode_config_spec.py

Expected output (assumes no XDG override at example-org/example-pkg.yaml):

    bootstrap ok  app[example-pkg] port[8080] rule[6]
    hello from the packaged base config
"""

import sys
from pathlib import Path

# Allow running from a source checkout without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from appinfra.config import Config, ConfigSpec  # noqa: E402
from appinfra.log import create_root_lg  # noqa: E402


def main() -> None:
    source = ConfigSpec("example-org", "example-pkg").resolve()
    config = Config(source)
    lg = create_root_lg(level="info")
    lg.info(
        "bootstrap ok",
        extra={"app": config.app.name, "port": config.app.port, "rule": source.rule},
    )
    lg.info(config.app.greeting)


if __name__ == "__main__":
    main()
