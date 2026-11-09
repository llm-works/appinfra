# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""What a test does, as evidence of the lowest suite that allows it (appinfra._suite_behavior)."""

from __future__ import annotations

import importlib.abc
import importlib.util
import os
import sys
import threading
import types
from typing import Any

import pytest

from appinfra import _suite_behavior
from appinfra._suite_behavior import (
    CHDIR,
    DB,
    ENTRY_POINT,
    FS_READ,
    FS_WRITE,
    PROCESS,
    SIGNAL,
    SOCKET,
    THREAD,
    Project,
    Recorder,
    event_evidence,
    open_evidence,
    runs_project,
)

PROJECT = Project(
    root="/proj", packages=frozenset({"myapp"}), scripts=frozenset({"myapp-cli"})
)


def _category(evidence: tuple[str, str] | None) -> str | None:
    return evidence[0] if evidence else None


class TestOpen:
    def test_reading_a_project_file_is_no_evidence(self) -> None:
        assert open_evidence(PROJECT, "/proj/tests/data/case.yaml", "r", 0) is None

    def test_reading_code_anywhere_is_an_import(self) -> None:
        assert open_evidence(PROJECT, "/srv/other/mod.py", "rb", 0) is None

    def test_reading_under_the_interpreter_is_no_evidence(self) -> None:
        path = os.path.join(sys.prefix, "share", "data.txt")
        assert open_evidence(PROJECT, path, "r", 0) is None

    def test_reading_system_configuration_is_no_evidence(self) -> None:
        assert open_evidence(PROJECT, "/etc/hosts", "r", 0) is None

    def test_reading_elsewhere_is_a_file_read(self) -> None:
        found = open_evidence(PROJECT, "/tmp/pytest-1/case0/out.json", "r", 0)
        assert found == (FS_READ, "/tmp/pytest-1/case0/out.json")

    @pytest.mark.parametrize("mode", ["w", "a", "x", "r+", "wb"])
    def test_a_write_mode_is_a_file_write_even_in_the_project(self, mode: str) -> None:
        assert _category(open_evidence(PROJECT, "/proj/out.txt", mode, 0)) == FS_WRITE

    def test_write_flags_from_os_open_are_a_file_write(self) -> None:
        flags = os.O_WRONLY | os.O_CREAT
        assert _category(open_evidence(PROJECT, "/tmp/x", None, flags)) == FS_WRITE

    def test_writing_to_a_device_is_no_evidence(self) -> None:
        assert open_evidence(PROJECT, "/dev/null", "w", 0) is None

    def test_a_file_descriptor_is_no_evidence(self) -> None:
        assert open_evidence(PROJECT, 3, "r", 0) is None

    def test_bytes_paths_are_decoded(self) -> None:
        assert _category(open_evidence(PROJECT, b"/tmp/x", "w", 0)) == FS_WRITE

    def test_writing_the_bytecode_cache_is_an_import(self) -> None:
        path = "/venv/lib/anyio/__pycache__/abc.cpython-312.pyc.140234"
        flags = os.O_EXCL | os.O_CREAT | os.O_WRONLY
        assert open_evidence(PROJECT, path, None, flags) is None

    def test_writing_the_hypothesis_database_is_no_evidence(self) -> None:
        path = "/proj/.hypothesis/examples/0a1b/2c3d"
        assert open_evidence(PROJECT, path, "wb", 0) is None


class TestEvents:
    @pytest.mark.parametrize(
        ("event", "args", "category"),
        [
            ("os.mkdir", ("/tmp/d", 0o777, -1), FS_WRITE),
            ("os.remove", ("/tmp/f", -1), FS_WRITE),
            ("tempfile.mkdtemp", ("/tmp/tmpab",), FS_WRITE),
            ("shutil.rmtree", ("/tmp/d", None), FS_WRITE),
            ("socket.connect", (object(), ("127.0.0.1", 5432)), SOCKET),
            ("socket.bind", (object(), ("127.0.0.1", 0)), SOCKET),
            ("os.chdir", ("/tmp/d",), CHDIR),
            ("sqlite3.connect", ("/tmp/app.db",), DB),
            ("subprocess.Popen", ("git", ["git", "status"], None, None), PROCESS),
            ("os.system", (b"ls",), PROCESS),
        ],
    )
    def test_audit_events_map_to_their_category(
        self, event: str, args: tuple[object, ...], category: str
    ) -> None:
        assert _category(event_evidence(PROJECT, event, args)) == category

    def test_an_in_memory_sqlite_database_is_no_evidence(self) -> None:
        assert event_evidence(PROJECT, "sqlite3.connect", (":memory:",)) is None

    @pytest.mark.parametrize(
        ("event", "args"),
        [
            ("os.mkdir", ("/venv/lib/anyio/__pycache__", 0o777, -1)),
            ("os.mkdir", ("/proj/.hypothesis/tmp", 0o777, -1)),
            (
                "os.rename",
                (
                    "/venv/lib/anyio/__pycache__/abc.cpython-312.pyc.140234",
                    "/venv/lib/anyio/__pycache__/abc.cpython-312.pyc",
                    -1,
                    -1,
                ),
            ),
        ],
    )
    def test_writing_a_tool_cache_is_no_evidence(
        self, event: str, args: tuple[object, ...]
    ) -> None:
        assert event_evidence(PROJECT, event, args) is None

    def test_an_unwatched_event_is_no_evidence(self) -> None:
        assert event_evidence(PROJECT, "import", ("json", None, [], [], [])) is None

    @pytest.mark.parametrize(
        "event", ["_thread.start_new_thread", "_thread.start_joinable_thread"]
    )
    def test_starting_a_thread_is_a_thread(self, event: str) -> None:
        """The event of the interpreter's version: start_joinable_thread from 3.13 on."""
        assert _category(event_evidence(PROJECT, event, (print, (), {}))) == THREAD

    def test_a_thread_is_named_by_its_threading_thread(self) -> None:
        """threading starts the thread's _bootstrap method: the detail is the Thread's name."""
        thread = threading.Thread(target=print, name="worker-1")
        found = event_evidence(
            PROJECT, "_thread.start_new_thread", (thread._bootstrap,)
        )
        assert found == (THREAD, "worker-1")

    def test_a_process_running_the_project_is_an_entry_point(self) -> None:
        args = (sys.executable, [sys.executable, "-m", "myapp", "run"], None, None)
        assert (
            _category(event_evidence(PROJECT, "subprocess.Popen", args)) == ENTRY_POINT
        )

    def test_the_detail_names_what_was_done(self) -> None:
        found = event_evidence(
            PROJECT, "subprocess.Popen", ("git", ["git", "log"], None, None)
        )
        assert found is not None and "git" in found[1]


def _frames(*filenames: str) -> Any:
    """A frame chain, innermost first, with each frame's code from a file."""
    frame = None
    for filename in reversed(filenames):
        frame = types.SimpleNamespace(
            f_code=types.SimpleNamespace(co_filename=filename), f_back=frame
        )
    return frame


class TestImporting:
    @pytest.mark.parametrize(
        "machinery",
        [
            "<frozen importlib._bootstrap>",
            "<frozen importlib._bootstrap_external>",
            "/usr/lib/python3.12/importlib/_bootstrap.py",  # -X frozen_modules=off
        ],
    )
    def test_the_import_machinery_on_the_stack_is_an_import(
        self, machinery: str
    ) -> None:
        frames = _frames("/venv/lib/somelib/config.py", machinery, "/proj/t.py")
        assert _suite_behavior.importing(frames)

    def test_a_call_outside_an_import_is_not(self) -> None:
        assert not _suite_behavior.importing(
            _frames("/usr/lib/python3.12/os.py", "/proj/t.py")
        )


class TestRunsProject:
    @pytest.mark.parametrize(
        "argv",
        [
            ["python", "-m", "myapp"],
            ["python", "-m", "myapp.cli", "scaffold"],
            ["python", "/proj/myapp/cli/cli.py", "scaffold"],
            ["python", "/proj/src/myapp/cli.py"],
            ["/venv/bin/myapp-cli", "--help"],
            ["myapp-cli"],
        ],
    )
    def test_the_project_code_or_its_scripts(self, argv: list[str]) -> None:
        assert runs_project(PROJECT, argv)

    @pytest.mark.parametrize(
        "argv",
        [
            ["git", "status"],
            ["python", "-m", "pylint", "/proj/myapp/x.py"],
            ["python", "/proj/tests/helper.py"],
            ["python", "-c", "print(1)"],
            [],
        ],
    )
    def test_other_programs_and_test_helpers(self, argv: list[str]) -> None:
        assert not runs_project(PROJECT, argv)

    def test_a_shell_command_string(self) -> None:
        assert runs_project(PROJECT, "python -m myapp run")
        assert not runs_project(PROJECT, "ls -l")


def _fake_psycopg() -> types.ModuleType:
    """A psycopg whose connection classes inherit connect from a shared base class."""

    class _BaseConnection:
        @classmethod
        def connect(cls, conninfo: str) -> tuple[str, str]:
            return (cls.__name__, conninfo)

    class Connection(_BaseConnection):
        pass

    class AsyncConnection(_BaseConnection):
        pass

    class Cursor:
        def execute(self, query: str) -> str:
            return query

        def executemany(self, query: str) -> str:
            return query

    class AsyncCursor(Cursor):
        pass

    module = types.ModuleType("psycopg")
    module.Connection = Connection  # type: ignore[attr-defined]
    module.AsyncConnection = AsyncConnection  # type: ignore[attr-defined]
    module.Cursor = Cursor  # type: ignore[attr-defined]
    module.AsyncCursor = AsyncCursor  # type: ignore[attr-defined]
    module.connect = Connection.connect  # type: ignore[attr-defined]
    return module


class TestWrapPsycopg:
    def test_connect_inherited_from_a_base_class_is_wrapped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """psycopg 3.x may define connect on a base class rather than on each class."""
        fake = _fake_psycopg()
        monkeypatch.setitem(sys.modules, "psycopg", fake)
        # Under make check's health check the process has a live recorder: the fake connects
        # the wrappers note would be charged to this test
        monkeypatch.setattr(_suite_behavior, "_recorder", None)
        _suite_behavior._wrap_psycopg()
        assert fake.connect("db") == ("Connection", "db")
        assert fake.AsyncConnection.connect("db") == ("AsyncConnection", "db")
        assert (
            fake.Connection.connect.__qualname__
            == f"{fake.Connection.__qualname__}.connect"
        )


class TestRecorder:
    """The recorder here is not installed: events are handed to it directly."""

    def test_the_running_thread_is_charged(self) -> None:
        recorder = Recorder(PROJECT)
        with recorder.running("t.py::test_a"):
            recorder.audit("os.chdir", ("/x",))
            recorder.note((SOCKET, "socket.bind"))
        assert recorder.evidence("t.py::test_a", []) == {
            CHDIR: "/x",
            SOCKET: "socket.bind",
        }

    def test_another_thread_is_not_charged(self) -> None:
        """A thread left running by an earlier test works on its own time: its events are
        not the running test's."""
        recorder = Recorder(PROJECT)

        def elsewhere() -> None:
            recorder.audit("os.chdir", ("/x",))
            recorder.note((SOCKET, "socket.bind"))

        with recorder.running("t.py::test_a"):
            thread = threading.Thread(target=elsewhere)
            thread.start()
            thread.join()
        assert recorder.evidence("t.py::test_a", []) == {}

    def test_what_a_module_does_while_being_imported_is_not_charged(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A module does its import-time work for whichever test imports it first: the work is
        the module's, not the test's."""
        recorder = Recorder(PROJECT)
        name = "_suite_behavior_imported_probe"

        class Loader(importlib.abc.Loader):
            def create_module(self, spec: Any) -> None:
                return None

            def exec_module(self, module: types.ModuleType) -> None:
                recorder.audit("os.mkdir", ("/tmp/made_on_import", 0o777, -1))
                recorder.note((SIGNAL, "signal.signal 10"))

        class Finder(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname: str, path: Any, target: Any = None) -> Any:
                if fullname != name:
                    return None
                return importlib.util.spec_from_loader(fullname, Loader())

        monkeypatch.setattr(sys, "meta_path", [Finder(), *sys.meta_path])
        try:
            with recorder.running("t.py::test_a"):
                importlib.import_module(name)
        finally:
            sys.modules.pop(name, None)
        assert recorder.evidence("t.py::test_a", []) == {}
