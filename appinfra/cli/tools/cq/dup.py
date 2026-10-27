# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Duplicated code check.

Runs pylint's duplicate-code checker (``R0801``) over the selected files and
reports each group of similar blocks as ``path:first-last`` locations. Comments,
docstrings, imports and function signatures are ignored when comparing, so
blocks that differ only in those still count as duplicates. pylint must be
installed; it is part of the ``dev`` extra.

Exit Codes:
    0: No duplicates
    1: Duplicates (in strict mode), or pylint failed to run
    42: Duplicates but non-strict mode (warning)
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ....app.tools import Tool, ToolConfig
from .common import EXIT_CODE_WARNING, collect_python_files

DEFAULT_MIN_LINES = 8

# One location line in an R0801 message: ==<module>:[<start>:<end>], 0-based, end exclusive
_LOCATION = re.compile(r"^==(?P<module>[\w.]+):\[(?P<start>\d+):(?P<end>\d+)\]$")

# pylint exit status bits that mean it did not complete (fatal, usage error)
_PYLINT_FAILED = 1 | 32


@dataclass(frozen=True)
class Block:
    """One occurrence of a duplicated block, 1-based inclusive lines."""

    location: str
    first_line: int
    last_line: int

    @property
    def size(self) -> int:
        """Lines the block spans, including comments and docstrings."""
        return self.last_line - self.first_line + 1


def pylint_command(files: list[Path], min_lines: int) -> list[str]:
    """Build the pylint invocation that reports only duplicate-code."""
    return [
        sys.executable,
        "-m",
        "pylint",
        "--disable=all",
        "--enable=duplicate-code",
        "--output-format=json2",
        "--score=n",
        f"--min-similarity-lines={min_lines}",
        "--ignore-comments=y",
        "--ignore-docstrings=y",
        "--ignore-imports=y",
        "--ignore-signatures=y",
        *(str(f) for f in files),
    ]


def module_paths(files: list[Path]) -> dict[str, Path]:
    """Map each file's dotted module suffixes to the file, for resolving pylint's names."""
    paths: dict[str, Path] = {}
    for f in files:
        parts = f.with_suffix("").parts
        for i in range(len(parts)):
            paths.setdefault(".".join(parts[i:]), f)
    return paths


def parse_message(message: str, paths: dict[str, Path]) -> list[Block]:
    """Parse the location lines of one R0801 message into blocks."""
    blocks = []
    for line in message.splitlines():
        match = _LOCATION.match(line)
        if match is None:
            continue
        path = paths.get(match["module"])
        location = str(path) if path else match["module"]
        blocks.append(Block(location, int(match["start"]) + 1, int(match["end"])))
    return blocks


def parse_groups(output: str, paths: dict[str, Path]) -> list[list[Block]]:
    """Parse pylint json2 output into groups of duplicated blocks."""
    messages = json.loads(output).get("messages", [])
    groups = [
        parse_message(m["message"], paths)
        for m in messages
        if m.get("symbol") == "duplicate-code"
    ]
    return [g for g in groups if g]


def format_report(groups: list[list[Block]], files_checked: int) -> str:
    """Render each group as its locations, largest first, plus totals.

    Copies of one block can span different line counts, since comments and docstrings are
    ignored when comparing. The duplicated total counts the smallest copy once per extra copy.
    """
    lines = []
    for group in sorted(groups, key=lambda g: min(b.size for b in g), reverse=True):
        lines.append(f"duplicate block in {len(group)} places:")
        lines.extend(
            f"  {b.location}:{b.first_line}-{b.last_line} ({b.size} lines)"
            for b in group
        )
    duplicated = sum(min(b.size for b in g) * (len(g) - 1) for g in groups)
    lines.append(f"Files checked: {files_checked}")
    lines.append(f"Duplicated lines: {duplicated}")
    lines.append(f"Violations: {len(groups)}")
    return "\n".join(lines)


class CheckDupTool(Tool):
    """Tool for reporting duplicated code blocks."""

    def __init__(self, parent: Any = None):
        """Initialize the duplicated code check tool."""
        config = ToolConfig(
            name="check-dup",
            aliases=["dup"],
            help_text="Report duplicated code blocks (pylint duplicate-code)",
            description=(
                "Report blocks of similar lines found in more than one place, "
                "using pylint's duplicate-code checker. Comments, docstrings, "
                "imports and signatures are ignored when comparing."
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
            "--min-lines",
            type=int,
            default=DEFAULT_MIN_LINES,
            help=f"Minimum similar lines to report (default: {DEFAULT_MIN_LINES})",
        )
        parser.add_argument(
            "--strict",
            action="store_true",
            help="Exit with code 1 if duplicates exist (for CI)",
        )
        parser.add_argument(
            "--exclude",
            action="append",
            help="Patterns to exclude (can be used multiple times)",
        )

    def run(self, **kwargs: Any) -> int:
        """Run pylint over the selected files and print the report."""
        files = collect_python_files(
            self.lg, [self.args.dir], self.args.exclude or [], include_tests=False
        )
        if not files:
            self.lg.warning("no Python files found to analyze")
            return 0
        result = self._run_pylint(files)
        if result is None:
            return 1
        groups = parse_groups(result.stdout, module_paths(files))
        sys.stdout.write(format_report(groups, len(files)) + "\n")
        if not groups:
            return 0
        return 1 if self.args.strict else EXIT_CODE_WARNING

    def _run_pylint(self, files: list[Path]) -> subprocess.CompletedProcess[str] | None:
        """Run pylint; log and return None if it is missing or did not complete."""
        cmd = pylint_command(files, self.args.min_lines)
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode & _PYLINT_FAILED or not result.stdout:
            self.lg.warning(
                "pylint did not complete (is it installed?)",
                extra={
                    "returncode": result.returncode,
                    "stderr": result.stderr[-2000:],
                },
            )
            return None
        return result
