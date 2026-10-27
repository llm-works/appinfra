# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Dead private code check.

Reports private definitions that nothing in the analyzed files refers to:
module-level functions, classes and constants, class members, and instance
attributes assigned through ``self`` but never read. A name is private when it
starts with one underscore or two (name mangling); dunder (``__x__``) and sunder
(``_x_``) names are protocol hooks and are not checked.

Public names are out of reach: in a library, callers outside the analyzed files
use them. Tests are not counted as users, so a private helper that only tests
call is reported.

Matching is by name across all analyzed files: a definition counts as used when
any file loads that name, as a variable, an attribute, an import or a string
literal (getattr, ``__all__``). Two unrelated definitions sharing a name hide
each other. A definition used only through dynamic dispatch or by a base class
outside the analyzed files (e.g. a stdlib hook) is kept with ``# cq: keep`` on
its line, followed by the reason. One kept definition keeps the name throughout
its file, so an attribute assigned in several places needs the directive once.

Exit Codes:
    0: No findings
    1: Findings (in strict mode)
    42: Findings but non-strict mode (warning)
"""

from __future__ import annotations

import argparse
import ast
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ....app.tools import Tool, ToolConfig
from .common import (
    EXIT_CODE_WARNING,
    collect_python_files,
    has_keep,
    keep_lines,
    read_source,
)


@dataclass(frozen=True)
class Definition:
    """A private definition found in a source file."""

    name: str
    kind: str
    file_path: Path
    line_number: int


def is_private(name: str) -> bool:
    """True for ``_x`` and ``__x``; False for ``_``, dunder and sunder names."""
    if not name.startswith("_") or name.strip("_") == "":
        return False
    if name.startswith("__") and name.endswith("__"):
        return False
    return not (name.endswith("_") and not name.startswith("__"))


def _assigned_names(stmt: ast.stmt) -> Iterator[str]:
    """Yield the plain names an Assign/AnnAssign statement binds."""
    targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]  # type: ignore[attr-defined]
    for target in targets:
        for node in ast.walk(target):
            if isinstance(node, ast.Name):
                yield node.id


def _scope_definitions(
    body: list[ast.stmt], in_class: bool
) -> Iterator[tuple[str, str, ast.AST]]:
    """Yield (name, kind, node) for definitions in a module or class body."""
    for stmt in body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield stmt.name, "method" if in_class else "function", stmt
        elif isinstance(stmt, ast.ClassDef):
            yield stmt.name, "class", stmt
            yield from _scope_definitions(stmt.body, in_class=True)
        elif isinstance(stmt, (ast.Assign, ast.AnnAssign)):
            kind = "class attribute" if in_class else "constant"
            for name in _assigned_names(stmt):
                yield name, kind, stmt
        elif isinstance(stmt, (ast.If, ast.Try)):
            for block in _stmt_blocks(stmt):
                yield from _scope_definitions(block, in_class)


def _stmt_blocks(stmt: ast.If | ast.Try) -> list[list[ast.stmt]]:
    """Return the statement lists nested in an if or try statement."""
    if isinstance(stmt, ast.If):
        return [stmt.body, stmt.orelse]
    handlers = [h.body for h in stmt.handlers]
    return [stmt.body, *handlers, stmt.orelse, stmt.finalbody]


def _self_attribute_stores(tree: ast.Module) -> Iterator[tuple[str, str, ast.AST]]:
    """Yield (name, kind, node) for attributes assigned as ``self.<name> = ...``."""
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.ctx, ast.Store)
            and isinstance(node.value, ast.Name)
            and node.value.id == "self"
        ):
            yield node.attr, "instance attribute", node


def _used_names(tree: ast.Module) -> Iterator[str]:
    """Yield every name the module reads, imports or spells as a string."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Store):
            yield node.id
        elif isinstance(node, ast.Attribute) and not isinstance(node.ctx, ast.Store):
            yield node.attr
        elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Attribute):
            yield node.target.attr  # x._n += 1 reads x._n
        elif isinstance(node, ast.ImportFrom):
            yield from (alias.name for alias in node.names)
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value.isidentifier()
        ):
            yield node.value


class DeadCodeAnalyzer:
    """Collects private definitions and name uses across a set of files."""

    def __init__(self) -> None:
        """Initialize empty definition and use sets."""
        self.definitions: list[Definition] = []
        self.used: set[str] = set()
        self.kept: set[tuple[str, Path]] = set()
        self.unparsable: list[Path] = []

    def add_file(self, file_path: Path) -> None:
        """Parse one file and record its private definitions and its uses."""
        try:
            source = read_source(file_path)
            tree = ast.parse(source, filename=str(file_path))
        except (OSError, UnicodeDecodeError, SyntaxError):
            self.unparsable.append(file_path)
            return
        kept_lines = keep_lines(source)
        found = [
            *_scope_definitions(tree.body, in_class=False),
            *_self_attribute_stores(tree),
        ]
        for name, kind, node in found:
            line_number = node.lineno  # type: ignore[attr-defined]
            if not is_private(name):
                continue
            if has_keep(kept_lines, line_number, line_number):
                self.kept.add((name, file_path))
            else:
                self.definitions.append(Definition(name, kind, file_path, line_number))
        self.used.update(_used_names(tree))

    def unused(self) -> list[Definition]:
        """Return definitions whose name no analyzed file uses, one per name and file."""
        seen = set(self.kept)
        result = []
        for d in sorted(
            self.definitions, key=lambda d: (str(d.file_path), d.line_number)
        ):
            if d.name not in self.used and (d.name, d.file_path) not in seen:
                seen.add((d.name, d.file_path))
                result.append(d)
        return result


def format_report(findings: list[Definition], files_checked: int) -> str:
    """Render findings as one ``path:line: kind name`` line each, plus a total."""
    lines = [f"{d.file_path}:{d.line_number}: {d.kind} {d.name}" for d in findings]
    lines.append(f"Files checked: {files_checked}")
    lines.append(f"Violations: {len(findings)}")
    return "\n".join(lines)


class CheckDeadTool(Tool):
    """Tool for reporting unused private definitions."""

    def __init__(self, parent: Any = None):
        """Initialize the dead code check tool."""
        config = ToolConfig(
            name="check-dead",
            aliases=["dead"],
            help_text="Report private definitions nothing refers to",
            description=(
                "Report private functions, classes, constants, class members and "
                "instance attributes that no analyzed file uses. Mark intended "
                "ones with '# cq: keep <reason>' on the definition line."
            ),
        )
        super().__init__(parent, config)

    def add_args(self, parser: argparse.ArgumentParser) -> None:
        """Add CLI arguments."""
        parser.add_argument(
            "dir",
            nargs="?",
            default=".",
            help="Directory to analyze (default: current directory)",
        )
        parser.add_argument(
            "--strict",
            action="store_true",
            help="Exit with code 1 if findings exist (for CI)",
        )
        parser.add_argument(
            "--exclude",
            action="append",
            help="Patterns to exclude (can be used multiple times)",
        )

    def run(self, **kwargs: Any) -> int:
        """Run the analysis and print the report."""
        files = collect_python_files(
            self.lg, [self.args.dir], self.args.exclude or [], include_tests=False
        )
        analyzer = DeadCodeAnalyzer()
        for file_path in files:
            analyzer.add_file(file_path)
        for file_path in analyzer.unparsable:
            self.lg.warning("could not parse file", extra={"path": str(file_path)})
        findings = analyzer.unused()
        sys.stdout.write(format_report(findings, len(files)) + "\n")
        if not findings:
            return 0
        return 1 if self.args.strict else EXIT_CODE_WARNING
