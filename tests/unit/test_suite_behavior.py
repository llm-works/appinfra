# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""What a test does, as evidence of the lowest suite that allows it (appinfra._suite_behavior)."""

from __future__ import annotations

import os
import sys
import threading

import pytest

from appinfra._suite_behavior import (
    CHDIR,
    DB,
    ENTRY_POINT,
    FS_READ,
    FS_WRITE,
    PROCESS,
    SOCKET,
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
