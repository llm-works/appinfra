# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""How appinfra's own build generates _build_info.py.

setup.py's build_py writes the file into the build directory. No setuptools plugin may
be registered: a finalize_distribution_options entry point runs in every setuptools build
of the environment it is installed in, and writing from there reaches the source tree.
"""

import ast
import tomllib
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _setup_py_constant(name: str) -> str:
    """Return the string constant ``name`` assigned in setup.py, without running it."""
    tree = ast.parse((_REPO_ROOT / "setup.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == name for t in node.targets
        ):
            value = ast.literal_eval(node.value)
            assert isinstance(value, str)
            return value
    raise AssertionError(f"setup.py assigns no {name}")


def test_no_setuptools_plugin_is_registered():
    with (_REPO_ROOT / "pyproject.toml").open("rb") as f:
        project = tomllib.load(f)["project"]
    groups = project.get("entry-points", {})
    assert "setuptools.finalize_distribution_options" not in groups


def test_generated_build_info_carries_the_spdx_header():
    """Every .py in the wheel declares the license, the generated one included."""
    template = _setup_py_constant("_BUILD_INFO_TEMPLATE")
    assert template.startswith(
        "# SPDX-License-Identifier: Apache-2.0\n"
        "# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors\n"
    )
