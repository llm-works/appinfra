# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""The setting registry of Makefile.config, read the way make expands it."""

from __future__ import annotations

import re
from pathlib import Path

MAKEFILE_CONFIG = (
    Path(__file__).resolve().parents[2]
    / "appinfra"
    / "scripts"
    / "make"
    / "Makefile.config"
)

REGISTRY_LISTS = [
    "_APPINFRA_BOOLEANS",
    "_APPINFRA_MODES",
    "_APPINFRA_PERCENTS",
    "_APPINFRA_INTEGERS",
    "_APPINFRA_WORKERS",
    "_APPINFRA_TEXTS",
]


def registry() -> dict[str, list[str]]:
    """Each registry type list (e.g. ``_APPINFRA_BOOLEANS``) and the settings it names."""
    text = MAKEFILE_CONFIG.read_text()
    lists = {}
    for name in REGISTRY_LISTS:
        m = re.search(rf"^{name} := ((?:.*\\\n)*.*)$", text, re.MULTILINE)
        assert m, f"{name} not found in Makefile.config"
        lists[name] = m[1].replace("\\\n", " ").split()
    return lists
