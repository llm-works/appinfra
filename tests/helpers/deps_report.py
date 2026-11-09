# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Loading appinfra/scripts/deps_report.py as a module, and version lists for its tests."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest
from packaging.version import Version

SCRIPTS = Path(__file__).resolve().parents[2] / "appinfra" / "scripts"


def load_deps_report(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Load the script as a module; it imports install_deps from its own directory."""
    monkeypatch.syspath_prepend(str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(
        "deps_report", SCRIPTS / "deps_report.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # @dataclass resolves the module's names through sys.modules
    monkeypatch.setitem(sys.modules, "deps_report", module)
    spec.loader.exec_module(module)
    return module


def V(*versions: str) -> list[Version]:
    return [Version(v) for v in versions]


def v(text: str | None) -> Version | None:
    return Version(text) if text else None
