# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""The pydantic config models: one definition each, and pydantic stays optional.

Static tools read one definition of a name: mypy the first, griffe (the API reference) the
last. A placeholder defined beside the real model would be what one of them reports.
"""

import ast
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CONFIG = _REPO_ROOT / "appinfra" / "config"
_MODELS = ("InfraConfig", "LoggingConfig", "DatabaseConfig", "validate_config")


def _module_level_names(body: list[ast.stmt]) -> list[str]:
    """Names a module body binds, including inside if/try blocks but not inside defs."""
    names: list[str] = []
    for node in body:
        if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            names.append(node.name)
        elif isinstance(node, ast.Assign | ast.AnnAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names += [t.id for t in targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.ImportFrom):
            names += [alias.asname or alias.name for alias in node.names]
        elif isinstance(node, ast.If):
            names += _module_level_names(node.body) + _module_level_names(node.orelse)
        elif isinstance(node, ast.Try):
            names += _module_level_names(node.body) + _module_level_names(node.orelse)
            for handler in node.handlers:
                names += _module_level_names(handler.body)
            names += _module_level_names(node.finalbody)
    return names


@pytest.mark.parametrize("module", ["schemas.py", "__init__.py"])
def test_each_model_is_defined_once(module: str):
    tree = ast.parse((_CONFIG / module).read_text(encoding="utf-8"))
    counts = Counter(_module_level_names(tree.body))
    assert {name: counts[name] for name in _MODELS} == dict.fromkeys(_MODELS, 1)


def test_config_imports_without_pydantic(tmp_path: Path):
    """Without pydantic the models are absent, and Config.validate() skips validation."""
    config_file = tmp_path / "app.yaml"
    config_file.write_text("name: app\n", encoding="utf-8")
    code = "\n".join(
        [
            "import sys",
            "sys.modules['pydantic'] = None",
            "import appinfra.config as c",
            "from appinfra.config import *",
            f"models = {_MODELS!r}",
            "print(c.PYDANTIC_AVAILABLE)",
            "print(sorted(n for n in models if hasattr(c, n) or n in c.__all__))",
            "print(c.Config(sys.argv[1], enable_env_overrides=False).validate())",
        ]
    )
    result = subprocess.run(
        [sys.executable, "-c", code, str(config_file)],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["False", "[]", "True"]
