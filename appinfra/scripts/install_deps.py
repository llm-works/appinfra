#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Install dependencies from pyproject.toml without installing the package."""

import subprocess
import sys
import tomllib

with open("pyproject.toml", "rb") as f:
    data = tomllib.load(f)

deps = list(data["project"]["dependencies"])
for extras in data["project"]["optional-dependencies"].values():
    deps.extend(extras)

subprocess.run([sys.executable, "-m", "pip", "install"] + deps, check=True)
