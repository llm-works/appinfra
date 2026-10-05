#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Install dependencies from pyproject.toml without installing the package.

Installs the project's dependencies plus every optional-dependency group.
Requirements naming the project itself (self-referencing extras such as
``pkg[extra]`` inside pkg's own pyproject.toml) are dropped: the referenced
extras are already installed directly, and passing such a requirement to pip
would resolve it against the published package on the index rather than the
checked-out source.
"""

import re
import subprocess
import sys
import tomllib
from typing import Any

# Distribution name at the start of a PEP 508 requirement string.
_NAME_RE = re.compile(r"\s*([A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)")


def normalize_name(name: str) -> str:
    """Normalize a distribution name per PEP 503."""
    return re.sub(r"[-_.]+", "-", name).lower()


def requirement_name(requirement: str) -> str | None:
    """Return the normalized distribution name of a requirement string."""
    match = _NAME_RE.match(requirement)
    return normalize_name(match.group(1)) if match else None


def collect_deps(project: dict[str, Any]) -> list[str]:
    """Collect dependencies and all extras, minus requirements on the project."""
    own_name = normalize_name(project["name"])
    deps = list(project["dependencies"])
    for extras in project["optional-dependencies"].values():
        deps.extend(extras)
    return [dep for dep in deps if requirement_name(dep) != own_name]


def main() -> None:
    """Install the dependencies of ./pyproject.toml into the running interpreter."""
    with open("pyproject.toml", "rb") as f:
        project = tomllib.load(f)["project"]
    deps = collect_deps(project)
    subprocess.run([sys.executable, "-m", "pip", "install"] + deps, check=True)


if __name__ == "__main__":
    main()
