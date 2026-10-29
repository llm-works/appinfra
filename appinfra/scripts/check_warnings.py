#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Find the warnings in a check's log, for check.sh.

check.sh shows a passing check's log to nobody, so a warning in it would go unseen. This script
reads one log and prints each distinct warning once, in order of first appearance, as
``count<TAB>kind<TAB>message``. The kind says where it came from:

- ``session``: an entry of pytest's warnings summary, counted once per test listed for it
- ``exit``: a warning, or an exception a finalizer raised ("Exception ignored in: ..."), printed
  at interpreter exit after pytest is done (see check_pytest/pytest_exit_warnings.py), by the
  main process or a pytest-xdist worker
- ``tool``: a tool's own ``warning: ...`` line (ruff, mypy, ...)

Messages are compact: paths relative to ``--root``, object addresses masked, so one warning
repeated across tests and workers counts once, and an object repr with a ``name='...'`` (a
file) shown as that name. Standard library only: check.sh runs it with the project's Python.
"""

from __future__ import annotations

import argparse
import re
from collections.abc import Iterator
from pathlib import Path

# "path.py:24: DeprecationWarning: message", or "sys:1: ..." for a warning without a source
# line; a worker's line can follow pytest's progress dots ("[100%]sys:1: ...")
_PY_WARNING = re.compile(
    r"(?P<loc>sys:\d+|[^\s\]]+:\d+): (?P<category>\w*Warning): (?P<message>.*)$"
)
_IGNORED = re.compile(r"Exception ignored (?P<what>.*)$")
_TOOL_WARNING = re.compile(r"^(?:(?P<source>\S+): )?[Ww]arning: (?P<message>.+)$")
_SUMMARY_START = re.compile(r"^=+ warnings summary =+$")
_SUMMARY_END = re.compile(r"^(-- Docs: |=+ )")
_FUNCTION = re.compile(r"<function (?P<name>\S+) at 0x[0-9a-fA-F]+>")
_FRAME = re.compile(r'^\s+File "(?P<path>[^"]+)", line (?P<line>\d+)')

Found = tuple[str, str, int]  # kind, message, count


def distinct_warnings(log: str, root: str) -> list[tuple[int, str, str]]:
    """The log's warnings as (count, kind, message), each distinct one once."""
    counts: dict[tuple[str, str], int] = {}
    for kind, message, count in _scan(log.splitlines()):
        key = (kind, _compact(message, root))
        counts[key] = counts.get(key, 0) + count
    return [(count, kind, message) for (kind, message), count in counts.items()]


def _scan(lines: list[str]) -> Iterator[Found]:
    """Walk the log: pytest's summary and ignored exceptions span lines, the rest is one."""
    i = 0
    while i < len(lines):
        line = lines[i]
        if _SUMMARY_START.match(line):
            i = yield from _summary(lines, i + 1)
            continue
        ignored = _IGNORED.search(line)
        if ignored:
            i = yield from _ignored(lines, i + 1, ignored.group("what"))
            continue
        found = _exit_warning(line) or _tool_warning(line)
        if found:
            yield found
        i += 1


def _summary(lines: list[str], i: int) -> Iterator[Found]:
    """Entries of pytest's warnings summary: test ids, then the indented warning they raised."""
    tests = 0
    while i < len(lines) and not _SUMMARY_END.match(lines[i]):
        line = lines[i]
        warning = _PY_WARNING.match(line.strip()) if line.startswith("  ") else None
        if warning:
            yield "session", _with_location(warning), max(tests, 1)
            tests = 0
        elif line and not line[0].isspace():
            tests += 1
        i += 1
    return i


def _ignored(lines: list[str], i: int, what: str) -> Iterator[Found]:
    """An exception a finalizer raised at exit: its traceback, then the exception line."""
    location = None
    while i < len(lines) and (
        lines[i].startswith("Traceback ") or lines[i][:1].isspace()
    ):
        frame = _FRAME.match(lines[i])
        if frame:
            location = f"{frame.group('path')}:{frame.group('line')}"
        i += 1
    if i < len(lines):
        error = lines[i].strip()
        name = error.split(":", 1)[0]
        if name.endswith("Warning"):
            # A warning an error filter raised: located like a printed one, at the last frame
            yield "exit", f"{error} ({location})" if location else error, 1
        else:
            function = _FUNCTION.search(what)
            source = function.group("name") if function else what.removeprefix("in: ")
            yield "exit", f"{error} (in {source})", 1
    return i + 1


def _exit_warning(line: str) -> Found | None:
    warning = _PY_WARNING.search(line)
    return ("exit", _with_location(warning), 1) if warning else None


def _tool_warning(line: str) -> Found | None:
    warning = _TOOL_WARNING.match(line)
    if not warning:
        return None
    source = warning.group("source")
    message = warning.group("message")
    return "tool", f"{source}: {message}" if source else message, 1


def _with_location(warning: re.Match[str]) -> str:
    """'Category: message (path:line)', without the location of a warning that has none."""
    text = f"{warning.group('category')}: {warning.group('message')}"
    location = warning.group("loc")
    return text if location.startswith("sys:") else f"{text} ({location})"


def _compact(message: str, root: str) -> str:
    message = message.replace(f"{root.rstrip('/')}/", "").replace("\t", " ")
    message = re.sub(r"<[^<>]* name='([^']*)'[^<>]*>", r"\1", message)
    return re.sub(r"0x[0-9a-fA-F]+", "0x…", message)


def main() -> None:
    """Print the warnings of the log given on the command line."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0].strip())
    parser.add_argument("log", type=Path, help="the check's log")
    parser.add_argument("--root", default=str(Path.cwd()), help="project root")
    ns = parser.parse_args()
    log = ns.log.read_text(errors="replace")
    for count, kind, message in distinct_warnings(log, ns.root):
        print(f"{count}\t{kind}\t{message}")


if __name__ == "__main__":
    main()
