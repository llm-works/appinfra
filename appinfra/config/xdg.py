# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
XDG Base Directory Specification helpers for config-file discovery.

Provides `xdg_candidates`, a pure function that enumerates candidate config
file paths for a namespaced package in XDG load-order. Callers iterate the
returned list and load the first existing file. No filesystem I/O.
"""

from __future__ import annotations

import os
from pathlib import Path


def xdg_candidates(namespace: str, package: str) -> list[Path]:
    """Enumerate config candidates for ``<namespace>/<package>`` in XDG load-order.

    For each XDG dir in ``[$XDG_CONFIG_HOME, *$XDG_CONFIG_DIRS]``, emits the
    per-package file first, then the unified file:

    - ``D/<namespace>/<package>.yaml``
    - ``D/<namespace>/config.yaml``

    Defaults per XDG spec: ``XDG_CONFIG_HOME`` → ``~/.config``,
    ``XDG_CONFIG_DIRS`` → ``/etc/xdg``. Non-absolute ``XDG_CONFIG_HOME`` falls
    back to the default; empty and non-absolute entries in ``XDG_CONFIG_DIRS``
    are skipped. Pure function.
    """
    return [
        candidate
        for base in _xdg_config_dirs()
        for candidate in (
            base / namespace / f"{package}.yaml",
            base / namespace / "config.yaml",
        )
    ]


def _xdg_config_dirs() -> list[Path]:
    """Return XDG config dirs in search order: user home first, then system dirs."""
    home_env = os.environ.get("XDG_CONFIG_HOME")
    if home_env and Path(home_env).is_absolute():
        home = home_env
    else:
        home = str(Path.home() / ".config")
    system = os.environ.get("XDG_CONFIG_DIRS") or "/etc/xdg"
    dirs = [Path(home)]
    for entry in system.split(":"):
        if not entry:
            continue
        path = Path(entry)
        if not path.is_absolute():
            continue
        dirs.append(path)
    return dirs
