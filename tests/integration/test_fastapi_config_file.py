# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""The shipped etc/fastapi.yaml loads into the config classes, as its usage
comment shows."""

from __future__ import annotations

from pathlib import Path

import yaml

from appinfra.app.fastapi import ApiConfig, IPCConfig, UvicornConfig

CONFIG = Path(__file__).resolve().parents[2] / "appinfra/etc/fastapi.yaml"


def test_each_section_loads_into_its_config() -> None:
    config = yaml.safe_load(CONFIG.read_text())
    ipc = IPCConfig(**config["ipc"])
    api = ApiConfig(**config["api"], ipc=ipc)
    uvicorn = UvicornConfig(**config["uvicorn"])
    assert (api.port, api.ipc, uvicorn.workers) == (8000, ipc, 1)
