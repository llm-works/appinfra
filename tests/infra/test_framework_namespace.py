# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Every name appinfra defines or reads is INFRA_*, APPINFRA_* or _APPINFRA_*.

- INFRA_*      config override of a yaml path
- APPINFRA_*   public framework setting, declared once in Makefile.config and
               documented
- _APPINFRA_*  internal (Make helpers, script wire protocol, per-run flags)

Make shares one namespace with the project Makefile, so every Make variable
the framework defines counts, internal helpers and loop variables included.
Only names owned by external standards are exempt.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PKG = REPO_ROOT / "appinfra"
MAKE_DIR = PKG / "scripts" / "make"
MAKEFILE_CONFIG = MAKE_DIR / "Makefile.config"
DOCS = [
    PKG / "docs" / "guides" / "makefile-customization.md",
    PKG / "docs" / "guides" / "environment-variables.md",
]

NAMESPACE = re.compile(r"^(INFRA_|APPINFRA_|_APPINFRA_)[A-Z0-9_]+$")

# Names owned by external standards: the environment, Python, color conventions
STANDARD = {
    "HOME",
    "PATH",
    "PWD",
    "TERM",
    "TMPDIR",
    "PYTHON",
    "PYTHONPATH",
    "MAKEFLAGS",
    "NO_COLOR",
    "FORCE_COLOR",
    "XDG_CONFIG_HOME",
    "XDG_CONFIG_DIRS",
    # libpq, set for psql
    "PGCONNECT_TIMEOUT",
    "PGPASSWORD",
}
# Shell and awk builtins, never environment variables
SHELL_BUILTINS = {
    "BASH_SOURCE",
    "BASH_REMATCH",
    "BASHPID",
    "SECONDS",
    "RANDOM",
    "LINENO",
    "FUNCNAME",
    "PIPESTATUS",
    "IFS",
    "NF",
    "NR",
}

_MAKE_ASSIGN = re.compile(
    r"^\s*(?:(?:override|export|undefine)\s+)*([A-Za-z_][A-Za-z0-9_.]*)\s*(?:\?|:|\+|!)?="
)
_MAKE_DEFINE = re.compile(r"^\s*define\s+([A-Za-z_][A-Za-z0-9_]*)")
_MAKE_EXPORT = re.compile(
    r"^\s*(?:export|undefine|override\s+undefine)\s+([A-Za-z_][A-Za-z0-9_ ]*)$"
)
_MAKE_FOREACH = re.compile(r"\$\(foreach\s+([A-Za-z_][A-Za-z0-9_]*)\s*,")
_APPINFRA_REF = re.compile(
    r"(?<![A-Za-z0-9_])APPINFRA_[A-Z0-9_]*[A-Z0-9](?![A-Za-z0-9_])"
)


def _makefiles() -> list[Path]:
    return sorted(MAKE_DIR.glob("Makefile.*"))


def _make_code_lines(path: Path) -> list[tuple[int, str]]:
    """Non-recipe, non-comment lines outside define bodies."""
    lines, in_define = [], False
    for i, line in enumerate(path.read_text().splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("define "):
            lines.append((i, line))
            in_define = True
        elif stripped == "endef":
            in_define = False
        elif (
            not in_define and not line.startswith("\t") and not stripped.startswith("#")
        ):
            lines.append((i, line))
    return lines


def _make_defined_names() -> dict[str, list[str]]:
    """Every Make variable the framework assigns, defines, exports or loops over."""
    names: dict[str, list[str]] = {}
    for path in _makefiles():
        for i, line in _make_code_lines(path):
            found = [
                m[1] for rx in (_MAKE_ASSIGN, _MAKE_DEFINE) if (m := rx.match(line))
            ]
            if m := _MAKE_EXPORT.match(line):
                found += m[1].split()
            found += _MAKE_FOREACH.findall(line)
            for name in found:
                names.setdefault(name, []).append(f"{path.name}:{i}")
    return names


def _shell_env_names() -> dict[str, list[str]]:
    """Upper-case names a script reads or exports that it does not set itself."""
    ui_sh = (PKG / "scripts" / "_ui.sh").read_text()
    names: dict[str, list[str]] = {}
    for path in sorted((PKG / "scripts").rglob("*.sh")):
        text = path.read_text()
        local = _shell_assigned(text) | _shell_assigned(ui_sh)
        for i, line in enumerate(text.splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            read = {r for r in re.findall(r"\$\{?([A-Za-z_]\w*)", line) if r.isupper()}
            exported = set(_shell_exported(line))
            for ref in (read - local) | exported:
                names.setdefault(ref, []).append(f"{path.name}:{i}")
    return names


def _shell_exported(line: str) -> list[str]:
    """Names on an `export A B=value ...` line."""
    m = re.match(r"^\s*export\s+(.*)$", line)
    if not m:
        return []
    return [t.split("=")[0] for t in m[1].split() if re.match(r"^[A-Za-z_]\w*(=|$)", t)]


def _shell_assigned(text: str) -> set[str]:
    assigned = set(re.findall(r"(?:^|[\s;(])([A-Za-z_][A-Za-z0-9_]*)\+?=", text))
    assigned |= set(
        re.findall(r"\b(?:local|declare|readonly)\s+(?:-\w+\s+)*([A-Za-z_]\w*)", text)
    )
    assigned |= set(re.findall(r"\bfor\s+([A-Za-z_]\w*)\s+in\b", text))
    assigned |= set(re.findall(r"\bread\s+(?:-\w+\s+)*([A-Za-z_]\w*)", text))
    return assigned


def _python_env_names() -> dict[str, list[str]]:
    """Environment variables appinfra's Python code reads or writes by name."""
    names: dict[str, list[str]] = {}
    for path in sorted(PKG.rglob("*.py")):
        if "examples" in path.relative_to(PKG).parts:
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            name = _env_access_name(node)
            if name is not None:
                where = f"{path.relative_to(PKG)}:{node.lineno}"
                names.setdefault(name, []).append(where)
    return names


def _env_access_name(node: ast.AST) -> str | None:
    """The literal name in os.environ[...], os.environ.get(...), os.getenv(...)."""
    target, key = None, None
    if isinstance(node, ast.Subscript):
        target, key = node.value, node.slice
    elif (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.args
    ):
        if node.func.attr in ("get", "pop", "setdefault"):
            target, key = node.func.value, node.args[0]
        elif node.func.attr == "getenv":
            return _literal(node.args[0])
    if target is None or not _is_environ(target):
        return None
    return _literal(key)


def _is_environ(node: ast.AST) -> bool:
    return (isinstance(node, ast.Attribute) and node.attr == "environ") or (
        isinstance(node, ast.Name) and node.id == "environ"
    )


def _literal(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _compose_names() -> dict[str, list[str]]:
    names: dict[str, list[str]] = {}
    for path in sorted((PKG / "scripts" / "docker").rglob("*.yaml")):
        for i, line in enumerate(path.read_text().splitlines(), 1):
            for ref in re.findall(r"(?<!\$)\$\{?([A-Za-z_][A-Za-z0-9_]*)", line):
                names.setdefault(ref, []).append(f"{path.name}:{i}")
    return names


def _violations(names: dict[str, list[str]], allowed: set[str]) -> list[str]:
    return sorted(
        f"{name} ({', '.join(locs)})"
        for name, locs in names.items()
        if not NAMESPACE.match(name) and name not in allowed
    )


def _declared() -> dict[str, list[str]]:
    """APPINFRA_* settings declared with ?= in any framework Makefile."""
    decl: dict[str, list[str]] = {}
    for path in _makefiles():
        for i, line in _make_code_lines(path):
            if m := re.match(r"^\s*(APPINFRA_[A-Z0-9_]+)\s*\?=", line):
                decl.setdefault(m[1], []).append(f"{path.name}:{i}")
    return decl


def _referenced_settings() -> set[str]:
    refs: set[str] = set()
    for path in _makefiles():
        refs |= {
            r for _, line in _make_code_lines(path) for r in _APPINFRA_REF.findall(line)
        }
    for names in (_shell_env_names(), _python_env_names(), _compose_names()):
        refs |= {n for n in names if n.startswith("APPINFRA_")}
    # Make functions are called, not set: APPINFRA_RUN_PYTEST(_SERIAL)
    return refs - {n for n, _ in _make_defines()}


def _make_defines() -> list[tuple[str, str]]:
    return [
        (m[1], path.name)
        for path in _makefiles()
        for _, line in _make_code_lines(path)
        if (m := _MAKE_DEFINE.match(line))
    ]


@pytest.mark.unit
class TestFrameworkNamespace:
    def test_make_variables(self) -> None:
        assert _violations(_make_defined_names(), {"PYTHON"}) == []

    def test_shell_environment(self) -> None:
        assert _violations(_shell_env_names(), STANDARD | SHELL_BUILTINS) == []

    def test_python_environment(self) -> None:
        assert _violations(_python_env_names(), STANDARD) == []

    def test_compose_substitutions(self) -> None:
        assert _violations(_compose_names(), {"PWD"}) == []


@pytest.mark.unit
class TestPublicSettings:
    def test_every_setting_declared_in_makefile_config(self) -> None:
        declared = _declared()
        missing = sorted(_referenced_settings() - declared.keys())
        assert missing == []

    def test_declared_once_in_makefile_config_only(self) -> None:
        bad = {
            name: locs
            for name, locs in _declared().items()
            if len(locs) != 1 or not locs[0].startswith("Makefile.config:")
        }
        assert bad == {}

    def test_every_setting_documented(self) -> None:
        docs = " ".join(path.read_text() for path in DOCS)
        undocumented = sorted(
            n for n in _declared() if not re.search(rf"\b{n}\b", docs)
        )
        assert undocumented == []

    def test_registry_types_each_setting_once(self) -> None:
        """Every declared setting has exactly one type in Makefile.config's registry."""
        registry = _registry()
        names = [name for names in registry.values() for name in names]
        assert sorted(names) == sorted(set(names)), "a setting has more than one type"
        assert sorted(names) == sorted(_declared())


_REGISTRY_LISTS = [
    "_APPINFRA_BOOLEANS",
    "_APPINFRA_MODES",
    "_APPINFRA_PERCENTS",
    "_APPINFRA_INTEGERS",
    "_APPINFRA_WORKERS",
    "_APPINFRA_TEXTS",
]


def _registry() -> dict[str, list[str]]:
    """The type lists of Makefile.config's setting registry, as make expands them."""
    text = MAKEFILE_CONFIG.read_text()
    registry = {}
    for name in _REGISTRY_LISTS:
        m = re.search(rf"^{name} := ((?:.*\\\n)*.*)$", text, re.MULTILINE)
        assert m, f"{name} not found in Makefile.config"
        registry[name] = m[1].replace("\\\n", " ").split()
    return registry
