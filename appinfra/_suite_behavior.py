# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""What each test does, as evidence of the lowest suite that allows it, for make check's Test
structure health row.

The suite rules (docs/guides/test-suites.md): a unit test stays in one process, with no files,
processes, sockets, databases, signal handlers or timers; an integration test stays on one machine;
an e2e test runs the project's code as its own process. While the health check runs, an audit hook
(PEP 578) and a few wrappers record each operation a test performs as a category and a detail:

- ``fs-write``: a file written, created, removed or renamed, anywhere but a device or a tool's
  cache: the bytecode an import writes, Hypothesis's example database;
- ``fs-read``: a file read outside the project, the interpreter and the system directories;
- ``process``: a process started, ``multiprocessing`` included;
- ``entry-point``: a process that runs the project's own code: ``-m <package>``, a ``.py`` file of
  a package, or one of its ``[project.scripts]``;
- ``socket``: a socket connected or bound;
- ``db``: a database connection other than ``sqlite3`` in memory;
- ``signal``: a signal handler or timer installed, other than asyncio's own;
- ``chdir``: the working directory changed.

Reading the project's own files, ``sqlite3 :memory:``, real sleeps and environment changes are
allowed in every suite. check_suite_health.py turns the evidence into findings.
"""

from __future__ import annotations

import contextlib
import importlib
import os
import re
import shlex
import signal
import sys
import sysconfig
import threading
import tomllib
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

FS_WRITE = "fs-write"
FS_READ = "fs-read"
PROCESS = "process"
ENTRY_POINT = "entry-point"
SOCKET = "socket"
DB = "db"
SIGNAL = "signal"
CHDIR = "chdir"

Evidence = tuple[str, str]

# Read-only opens under these are the interpreter, installed packages or system lookups
_SYSTEM = tuple(
    sorted(
        {
            os.path.normpath(p)
            for p in (
                sys.prefix,
                sys.base_prefix,
                sysconfig.get_paths()["stdlib"],
                sysconfig.get_paths()["purelib"],
                sysconfig.get_paths()["platlib"],
            )
        }
        | {"/etc", "/proc", "/sys", "/dev", "/usr", "/lib", "/lib64", "/opt"}
    )
)
_CODE_SUFFIXES = (".py", ".pyc", ".pyi", ".so", ".pth", ".typed")
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC
_FS_EVENTS = frozenset(
    {
        "os.mkdir", "os.rmdir", "os.remove", "os.rename", "os.symlink", "os.link",
        "os.truncate", "os.chmod", "os.chown", "shutil.rmtree", "shutil.copyfile",
        "shutil.move", "tempfile.mkstemp", "tempfile.mkdtemp",
    }
)  # fmt: skip
_PROCESS_EVENTS = frozenset(
    {
        "subprocess.Popen",
        "os.system",
        "os.posix_spawn",
        "os.exec",
        "os.spawn",
        "os.fork",
    }
)
_DETAIL_MAX = 160

# Directories a tool writes to on its own, whichever test happens to trigger it first: the
# bytecode an import compiles, and Hypothesis's example database
_TOOL_CACHES = frozenset({"__pycache__", ".hypothesis"})


@dataclass(frozen=True)
class Project:
    """What tells the project's own code apart: its root and the names it is run by."""

    root: str
    packages: frozenset[str]
    scripts: frozenset[str]


def _under(path: str, prefixes: Iterable[str]) -> bool:
    """Whether a normalized path is one of the prefixes or inside one."""
    return any(path == p or path.startswith(p + os.sep) for p in prefixes)


def _writes(mode: Any, flags: Any) -> bool:
    """Whether an open's mode string or flags write."""
    if isinstance(mode, str) and any(c in mode for c in "wax+"):
        return True
    return isinstance(flags, int) and bool(flags & _WRITE_FLAGS)


def _tool_cache(path: Any) -> bool:
    """Whether a path is in a tool's cache directory, or is one (_TOOL_CACHES)."""
    if not isinstance(path, (str, bytes, os.PathLike)):
        return False
    return not _TOOL_CACHES.isdisjoint(Path(os.fsdecode(path)).parts)


def open_evidence(
    project: Project, path: Any, mode: Any, flags: Any
) -> Evidence | None:
    """The evidence of an ``open`` audit event, if any."""
    if not isinstance(path, (str, bytes, os.PathLike)):
        return None  # a file descriptor
    name = os.path.abspath(os.fsdecode(path))
    if _writes(mode, flags):
        if _under(name, ("/dev",)) or _tool_cache(name):
            return None
        return (FS_WRITE, name)
    if name.endswith(_CODE_SUFFIXES) or _under(name, (project.root, *_SYSTEM)):
        return None
    return (FS_READ, name)


def _argv(command: Any) -> list[str]:
    """A process's arguments, from a list or a shell command string."""
    if isinstance(command, (str, bytes)):
        try:
            return shlex.split(os.fsdecode(command))
        except ValueError:
            return os.fsdecode(command).split()
    if isinstance(command, (list, tuple)):
        return [
            os.fsdecode(a) if isinstance(a, (str, bytes, os.PathLike)) else str(a)
            for a in command
        ]
    return []


def _project_file(project: Project, arg: str) -> bool:
    """Whether an argument is a .py file of one of the project's packages."""
    if not arg.endswith(".py"):
        return False
    parts = os.path.relpath(os.path.abspath(arg), project.root).split(os.sep)
    if parts[0] == "..":
        return False
    if parts[0] == "src" and len(parts) > 1:  # the src layout
        parts = parts[1:]
    return parts[0] in project.packages


def runs_project(project: Project, command: Any) -> bool:
    """Whether a process runs the project's own code."""
    argv = _argv(command)
    if not argv:
        return False
    if os.path.basename(argv[0]) in project.scripts:
        return True
    for i, arg in enumerate(argv):
        if arg == "-m" and i + 1 < len(argv):
            return argv[i + 1].split(".")[0] in project.packages
        if _project_file(project, arg):
            return True
    return False


def _detail(text: Any) -> str:
    """Evidence detail, cut to a length a report row can show."""
    return str(text)[:_DETAIL_MAX]


def _process_evidence(project: Project, event: str, args: tuple[Any, ...]) -> Evidence:
    """A started process: an entry point when it runs the project's code."""
    # subprocess.Popen: (executable, args, cwd, env); os.posix_spawn / os.exec: (path, argv,
    # env); os.system: (command,); os.fork: ()
    command = (
        args[1] if event != "os.system" and len(args) > 1 else (args[0] if args else "")
    )
    category = ENTRY_POINT if runs_project(project, command) else PROCESS
    return (category, _detail(f"{event} {command}"))


def event_evidence(
    project: Project, event: str, args: tuple[Any, ...]
) -> Evidence | None:
    """The evidence of an audit event other than ``open``, if any."""
    if event in _FS_EVENTS:
        target = args[0] if args else ""
        return None if _tool_cache(target) else (FS_WRITE, _detail(f"{event} {target}"))
    if event in _PROCESS_EVENTS:
        return _process_evidence(project, event, args)
    if event in ("socket.connect", "socket.bind"):
        return (SOCKET, _detail(f"{event} {args[1] if len(args) > 1 else ''}"))
    if event == "sqlite3.connect":
        target = (
            os.fsdecode(args[0]) if args and isinstance(args[0], (str, bytes)) else ""
        )
        return None if target == ":memory:" else (DB, _detail(f"sqlite3 {target}"))
    if event == "os.chdir":
        return (CHDIR, _detail(args[0] if args else ""))
    return None


def project_of(root: Path) -> Project:
    """The project at a pytest rootdir: its packages (top-level, or under ``src/``) and scripts."""
    packages = {
        d.name
        for base in (root, root / "src")
        if base.is_dir()
        for d in base.iterdir()
        if (d / "__init__.py").is_file() and d.name != "tests"
    }
    scripts: set[str] = set()
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        project = tomllib.loads(pyproject.read_text()).get("project", {})
        if project.get("name"):
            packages.add(re.sub(r"[-.]+", "_", str(project["name"])).lower())
        scripts.update(project.get("scripts", {}))
    return Project(str(root), frozenset(packages), frozenset(scripts))


# A caller that installs a signal handler and puts the old one back itself
_SIGNAL_CALLERS = frozenset({"asyncio.runners"})


class Recorder:
    """The evidence of each test and fixture, gathered while it runs.

    One per process: the audit hook it installs cannot be removed, so it only runs under make
    check's health check. Evidence goes to the test or fixture ``running`` names; operations
    outside one (collection, the session's own setup) are not recorded.
    """

    def __init__(self, project: Project) -> None:
        """Record evidence judged against ``project``."""
        self._project = project
        self._key: str | None = None
        self._evidence: dict[str, dict[str, str]] = {}
        self._local = threading.local()  # set while the recorder itself runs

    @contextlib.contextmanager
    def running(self, key: str | None) -> Iterator[None]:
        """Record the evidence of what runs inside, under ``key``."""
        previous, self._key = self._key, key
        try:
            yield
        finally:
            self._key = previous

    def evidence(self, key: str, fixtures: Iterable[str]) -> dict[str, str]:
        """A test's evidence, its own and that of the fixtures it uses: category -> detail."""
        found = dict(self._evidence.get(key, {}))
        for name in fixtures:
            for category, detail in self._evidence.get(f"fixture:{name}", {}).items():
                found.setdefault(category, detail)
        return found

    def note(self, found: Evidence | None) -> None:
        """Keep the first detail of each category for what is running."""
        if found is not None and self._key is not None:
            self._evidence.setdefault(self._key, {}).setdefault(found[0], found[1])

    def audit(self, event: str, args: tuple[Any, ...]) -> None:
        """The audit hook: map an event to evidence."""
        if self._key is None or getattr(self._local, "busy", False):
            return
        self._local.busy = True
        try:
            if event == "open":
                self.note(
                    open_evidence(
                        self._project, *(tuple(args) + (None, None, None))[:3]
                    )
                )
            else:
                self.note(event_evidence(self._project, event, args))
        finally:
            self._local.busy = False


_recorder: Recorder | None = None


def _note(found: Evidence | None) -> None:
    """Hand evidence from a wrapper to the process's recorder."""
    if _recorder is not None:
        _recorder.note(found)


def _audit(event: str, args: tuple[Any, ...]) -> None:
    """The audit hook installed once per process; it calls the current recorder."""
    if _recorder is not None:
        _recorder.audit(event, args)


def _wrap(owner: Any, name: str, describe: Callable[..., Evidence | None]) -> None:
    """Note what ``describe`` makes of each call to ``owner.name``, then make the call."""
    original = getattr(owner, name)

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        """Note the call, then make it."""
        _note(describe(sys._getframe(1).f_globals.get("__name__", ""), *args, **kwargs))
        return original(*args, **kwargs)

    # pickle finds a function by module and qualified name: point both at the wrapper's slot
    module = owner.__module__ if isinstance(owner, type) else owner.__name__
    wrapper.__module__ = module
    wrapper.__qualname__ = (
        f"{owner.__qualname__}.{name}" if isinstance(owner, type) else name
    )
    wrapper.__name__ = name
    wrapper.__doc__ = original.__doc__
    setattr(owner, name, wrapper)


def _signal_evidence(
    caller: str, signalnum: Any, *_: Any, **__: Any
) -> Evidence | None:
    """A signal handler installed, unless by a caller that restores it itself."""
    return None if caller in _SIGNAL_CALLERS else (SIGNAL, f"signal.signal {signalnum}")


def _timer_evidence(
    caller: str, which: Any, seconds: Any, *_: Any, **__: Any
) -> Evidence | None:
    """A timer armed; setting it to 0 disarms it."""
    return (SIGNAL, f"signal.setitimer {seconds}") if seconds else None


def _start_evidence(caller: str, process: Any, *_: Any, **__: Any) -> Evidence:
    """A multiprocessing process started; spawn and forkserver raise no audit event."""
    return (PROCESS, f"multiprocessing {getattr(process, 'name', '')}")


def _connect_evidence(caller: str, *_: Any, **__: Any) -> Evidence:
    """A psycopg connection made."""
    return (DB, "psycopg connect")


def _query_evidence(caller: str, *_: Any, **__: Any) -> Evidence:
    """A query run on a psycopg cursor."""
    return (DB, "psycopg query")


def _wrap_psycopg() -> None:
    """psycopg talks to the server in libpq, out of the audit hook's sight. A pool connects once
    and its later tests reuse the connection, so queries are noted as well as connections."""
    try:
        psycopg = importlib.import_module("psycopg")
    except (ImportError, OSError):  # not installed, or libpq missing
        return
    for cls in (psycopg.Connection, psycopg.AsyncConnection):
        wrapper = _noting_connect(cls.__dict__["connect"].__func__)
        wrapper.__qualname__ = f"{cls.__qualname__}.connect"
        wrapper.__module__ = cls.__module__
        cls.connect = classmethod(wrapper)
    # psycopg.connect is bound to Connection.connect at import, before the class is wrapped
    setattr(psycopg, "connect", psycopg.Connection.connect)  # noqa: B010 - a ModuleType
    for cursor in (psycopg.Cursor, psycopg.AsyncCursor):
        for method in ("execute", "executemany"):
            _wrap(cursor, method, _query_evidence)


def _noting_connect(connect: Callable[..., Any]) -> Callable[..., Any]:
    """A classmethod body that notes the connection, then makes it."""

    def wrapper(klass: Any, /, *args: Any, **kwargs: Any) -> Any:
        """Note the connection, then make it."""
        _note(_connect_evidence(""))
        return connect(klass, *args, **kwargs)

    return wrapper


def install(project: Project) -> Recorder:
    """Start recording for this process; a later call only takes the new project."""
    global _recorder
    first = _recorder is None
    _recorder = Recorder(project)
    if first:
        sys.addaudithook(_audit)
        _wrap(signal, "signal", _signal_evidence)
        _wrap(signal, "setitimer", _timer_evidence)
        _wrap(
            importlib.import_module("multiprocessing.process").BaseProcess,
            "start",
            _start_evidence,
        )
        _wrap_psycopg()
    return _recorder
