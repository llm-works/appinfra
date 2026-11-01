# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Records how a project's tests follow the suite rules, for make check's Test structure health
row.

appinfra.pytest_suites registers it when ``_APPINFRA_CHECK_SUITE_HEALTH_DIR`` names a directory,
which make check sets for its pytest checks. Each pytest process (the main one, or each
pytest-xdist worker) writes one JSON report there at the end of the session, ``<pid>.json``:

- ``rootdir``: the pytest rootdir, which tells the project's reports from those of a pytest its
  tests start, which inherits the report directory;
- ``total``: the number of tests under a ``tests/<suite>/`` directory;
- ``scopes``: each class, and each file's module-level tests, under a ``tests/<suite>/``
  directory holding at least one test of another suite, with its test count per suite; for
  module-level tests, also the count per suite of every test in the file (``file_suites``);
- ``leaks``: each unit test that left process-wide state changed (signal handlers, the
  ``ITIMER_REAL`` timer, environment variables by name, the working directory), compared from
  before its setup to after its teardown; an environment variable a module sets while being
  imported is the library's, not the test's.

The rules applied to these figures live in appinfra/scripts/check_suite_health.py.
"""

from __future__ import annotations

import json
import os
import signal
import sys
from collections import Counter
from collections.abc import Callable, Generator, Mapping
from pathlib import Path
from types import FrameType
from typing import Any

import pytest

REPORT_DIR_ENV = "_APPINFRA_CHECK_SUITE_HEALTH_DIR"

# Set by pytest for each test phase and removed after it; not the test's doing
_PYTEST_ENV = frozenset({"PYTEST_CURRENT_TEST"})

_SIGNALS = sorted(signal.valid_signals())

# The value each environment variable was last given while a module was being imported
# (_note_import_env), None for removed: a library configuring itself on first import, as torch
# or vllm do. A variable a test leaves at that value is the library's, not the test's.
_import_env: dict[str, str | None] = {}
_env_hook_installed = False

# The import machinery's files, frozen ("<frozen importlib._bootstrap>") or from source
_IMPORT_MACHINERY = ("importlib._bootstrap", os.path.join("importlib", "_bootstrap"))


def _importing(frame: FrameType | None) -> bool:
    """Whether the import machinery is on the stack from ``frame`` up: a module is loading."""
    while frame is not None:
        filename = frame.f_code.co_filename
        if any(part in filename for part in _IMPORT_MACHINERY):
            return True
        frame = frame.f_back
    return False


def _note_import_env(event: str, args: tuple[Any, ...]) -> None:
    """Audit hook: keep the value an import gives an environment variable, None for removed;
    pytest's own (_PYTEST_ENV) is not kept. The event comes before the write, with the value."""
    if event not in ("os.putenv", "os.unsetenv"):
        return
    name = os.fsdecode(args[0])
    if name not in _PYTEST_ENV and _importing(sys._getframe(1)):
        _import_env[name] = os.fsdecode(args[1]) if event == "os.putenv" else None


def _install_env_hook() -> None:
    """Install _note_import_env once per process; an audit hook cannot be removed, so only the
    health check installs it."""
    global _env_hook_installed
    if not _env_hook_installed:
        sys.addaudithook(_note_import_env)
        _env_hook_installed = True


def _signal_name(signum: int) -> str:
    try:
        return signal.Signals(signum).name
    except ValueError:  # a real-time signal has no name
        return f"signal {signum}"


def _snapshot() -> dict[str, Any]:
    """The process-wide state a unit test must leave as it found it."""
    return {
        "signals": {signum: signal.getsignal(signum) for signum in _SIGNALS},
        "timer": signal.getitimer(signal.ITIMER_REAL)[0] > 0,
        "env": {k: v for k, v in os.environ.items() if k not in _PYTEST_ENV},
        "cwd": os.getcwd(),
    }


def _changed(
    before: dict[str, Any], after: dict[str, Any], import_env: Mapping[str, str | None]
) -> list[str]:
    """What differs between two snapshots; environment variables by name, never by value, and
    not those left at the value an import gave them (``import_env``)."""
    changed = [
        _signal_name(signum)
        for signum, handler in before["signals"].items()
        if after["signals"][signum] != handler
    ]
    if after["timer"] != before["timer"]:
        changed.append("ITIMER_REAL")
    env_before, env_after = before["env"], after["env"]
    changed.extend(
        f"${name}"
        for name in sorted(env_before.keys() | env_after.keys())
        if env_before.get(name) != env_after.get(name)
        and not (name in import_env and import_env[name] == env_after.get(name))
    )
    if after["cwd"] != before["cwd"]:
        changed.append("cwd")
    return changed


def _scope(item: pytest.Item) -> str:
    """The node id of the test's class, or of its file for a module-level test."""
    parent = item.getparent(pytest.Class) or item.getparent(pytest.Module)
    return parent.nodeid if parent is not None else item.nodeid


def _scope_entry(
    scope: str, home: str, own: Counter[str], whole_file: Counter[str] | None
) -> dict[str, Any]:
    """A scope's report entry: its tests by suite, and for a file's module-level tests (whose
    scope is the file), every test of the file by suite as well, which decides placement."""
    entry: dict[str, Any] = {"scope": scope, "directory": home, "suites": dict(own)}
    if whole_file is not None:
        entry["file_suites"] = dict(whole_file)
    return entry


class SuiteHealth:
    """Collects the report of one pytest process and writes it at the end of the session."""

    def __init__(self, report_dir: Path) -> None:
        _install_env_hook()
        self._report_dir = report_dir
        self._rootdir = ""
        self._collected = 0
        self._total = 0
        self._suite_of: dict[str, str] = {}
        self._scopes: list[dict[str, Any]] = []
        self._leaks: list[dict[str, Any]] = []

    def record_collection(
        self,
        rootdir: Path,
        items: list[pytest.Item],
        suite_of: dict[str, str],
        home_of: Callable[[pytest.Item], str | None],
    ) -> None:
        """Count each scope's tests by suite, keeping the scopes that hold another suite."""
        self._rootdir = str(rootdir)
        self._collected = len(items)
        self._total = 0
        self._suite_of = suite_of
        own: dict[str, Counter[str]] = {}
        files: dict[str, Counter[str]] = {}
        homes: dict[str, str] = {}
        for item in items:
            home = home_of(item)
            if home is None:
                continue
            self._total += 1
            suite = suite_of[item.nodeid]
            scope = _scope(item)
            own.setdefault(scope, Counter())[suite] += 1
            homes[scope] = home
            files.setdefault(item.nodeid.split("::")[0], Counter())[suite] += 1
        self._scopes = [
            _scope_entry(scope, homes[scope], suites, files.get(scope))
            for scope, suites in own.items()
            if set(suites) != {homes[scope]}
        ]

    @pytest.hookimpl(wrapper=True)
    def pytest_runtest_protocol(
        self, item: pytest.Item, nextitem: pytest.Item | None
    ) -> Generator[None, object, object]:
        """Compare the process-wide state from before a unit test's setup to after its teardown."""
        if self._suite_of.get(item.nodeid) != "unit":
            return (yield)
        before = _snapshot()
        try:
            return (yield)
        finally:
            changed = _changed(before, _snapshot(), _import_env)
            if changed:
                self._leaks.append({"test": item.nodeid, "changed": changed})

    def pytest_sessionfinish(self, session: pytest.Session) -> None:
        """Write the report; a process that collected nothing (the xdist controller) writes none."""
        if not self._collected:
            return
        self._report_dir.mkdir(parents=True, exist_ok=True)
        report = {
            "rootdir": self._rootdir,
            "total": self._total,
            "scopes": self._scopes,
            "leaks": self._leaks,
        }
        (self._report_dir / f"{os.getpid()}.json").write_text(json.dumps(report))
