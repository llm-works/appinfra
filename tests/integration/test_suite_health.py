# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""The suite health reports appinfra.pytest_suites writes under make check
(appinfra/_suite_health.py), and check_suite_health.py reading them."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CHECK_SUITE_HEALTH_PY = _REPO_ROOT / "appinfra" / "scripts" / "check_suite_health.py"


def _run(
    pytester: pytest.Pytester,
    monkeypatch: pytest.MonkeyPatch,
    layout: dict[str, str],
    *args: str,
) -> Path:
    """Run pytest on a layout with the report directory set; returns the directory."""
    report_dir = pytester.path / "health"
    monkeypatch.setenv("PYTHONPATH", str(_REPO_ROOT))
    monkeypatch.setenv("_APPINFRA_CHECK_SUITE_HEALTH_DIR", str(report_dir))
    # Only the plugin under test: an installed plugin that reorders tests (pytest-randomly)
    # would break the layouts whose tests depend on running in file order
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    for path, source in layout.items():
        target = pytester.path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source)
    result = pytester.runpytest_subprocess("-p", "appinfra.pytest_suites", "-q", *args)
    assert result.ret == pytest.ExitCode.OK, result.stdout.str()
    return report_dir


def _report(report_dir: Path) -> dict[str, Any]:
    (path,) = report_dir.glob("*.json")
    return json.loads(path.read_text())


_MIXED = """\
import pytest


def test_module_unit():
    pass


@pytest.mark.integration
def test_module_integration():
    pass


class TestMixed:
    def test_unit(self):
        pass

    @pytest.mark.integration
    def test_integration(self):
        pass


class TestPure:
    def test_unit(self):
        pass
"""


def test_the_report_counts_each_scope_holding_another_suite(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = _report(_run(pytester, monkeypatch, {"tests/unit/test_mixed.py": _MIXED}))
    assert report["total"] == 5
    assert report["leaks"] == []
    assert sorted(report["scopes"], key=lambda s: s["scope"]) == [
        {
            "scope": "tests/unit/test_mixed.py",
            "directory": "unit",
            "suites": {"unit": 1, "integration": 1},
            "file_suites": {"unit": 3, "integration": 2},
        },
        {
            "scope": "tests/unit/test_mixed.py::TestMixed",
            "directory": "unit",
            "suites": {"unit": 1, "integration": 1},
        },
    ]


_LEAKS = """\
import os
import signal

import pytest


def test_signal():
    signal.signal(signal.SIGUSR1, lambda *_: None)


def test_timer():
    signal.setitimer(signal.ITIMER_REAL, 3600)


def test_env():
    os.environ["SUITE_HEALTH_LEAK"] = "1"


def test_cwd():
    os.chdir("/")


def test_restored(monkeypatch):
    monkeypatch.setenv("SUITE_HEALTH_RESTORED", "1")
    monkeypatch.chdir("/")


def test_imports_a_library_that_sets_env():
    import sets_env_on_import  # noqa: F401


def test_changes_what_an_import_set():
    os.environ["SUITE_HEALTH_IMPORT"] = "2"


def test_patches_what_its_import_set(monkeypatch):
    import sets_env_on_import_too  # noqa: F401

    monkeypatch.setenv("SUITE_HEALTH_IMPORT_TOO", "2")


@pytest.mark.integration
def test_integration_may_change_state():
    os.environ["SUITE_HEALTH_INTEGRATION"] = "1"


def test_imports_a_library_that_sets_env_again():
    import sets_env_stale  # noqa: F401


@pytest.mark.integration
def test_integration_removes_what_an_import_set():
    del os.environ["SUITE_HEALTH_STALE"]


def test_sets_what_an_earlier_import_set():
    os.environ["SUITE_HEALTH_STALE"] = "1"
"""


def test_unit_tests_that_leave_state_changed_are_reported(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = {
        "tests/unit/test_leaks.py": _LEAKS,
        # a library configuring itself on first import, as torch or vllm do
        "tests/unit/sets_env_on_import.py": (
            'import os\nos.environ["SUITE_HEALTH_IMPORT"] = "1"\n'
        ),
        "tests/unit/sets_env_on_import_too.py": (
            'import os\nos.environ["SUITE_HEALTH_IMPORT_TOO"] = "1"\n'
        ),
        "tests/unit/sets_env_stale.py": (
            'import os\nos.environ["SUITE_HEALTH_STALE"] = "1"\n'
        ),
    }
    report = _report(_run(pytester, monkeypatch, layout))
    changed = {
        leak["test"].split("::")[-1]: leak["changed"] for leak in report["leaks"]
    }
    assert changed == {
        "test_signal": ["SIGUSR1"],
        "test_timer": ["ITIMER_REAL"],
        "test_env": ["$SUITE_HEALTH_LEAK"],
        "test_cwd": ["cwd"],
        # an import set it earlier, but this test changed it
        "test_changes_what_an_import_set": ["$SUITE_HEALTH_IMPORT"],
        # the value an import set in an earlier test does not excuse this test's change
        "test_sets_what_an_earlier_import_set": ["$SUITE_HEALTH_STALE"],
    }


def test_no_report_without_the_report_directory(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    report_dir = _run(pytester, monkeypatch, {"tests/unit/test_mixed.py": _MIXED})
    monkeypatch.delenv("_APPINFRA_CHECK_SUITE_HEALTH_DIR")
    for path in report_dir.glob("*.json"):
        path.unlink()
    result = pytester.runpytest_subprocess("-p", "appinfra.pytest_suites", "-q")
    assert result.ret == pytest.ExitCode.OK
    assert list(report_dir.glob("*.json")) == []


_PROJECT = {
    "pyproject.toml": '[project]\nname = "myapp"\n[project.scripts]\nmyapp-cli = "myapp:main"\n',
    "myapp/__init__.py": "",
    "myapp/__main__.py": "",
    "tests/data.txt": "data\n",
}

_BEHAVIOR = """\
import asyncio
import multiprocessing
import signal
import socket
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest


def test_pure():
    assert 1 + 1 == 2


def test_reads_a_project_file():
    Path(__file__).parents[1].joinpath("data.txt").read_text()


def test_memory_db():
    sqlite3.connect(":memory:").close()


def test_asyncio_run():
    asyncio.run(asyncio.sleep(0))


def test_writes(tmp_path):
    (tmp_path / "f").write_text("x")


def test_process():
    subprocess.run([sys.executable, "-c", "pass"], check=True)


def test_multiprocessing():
    process = multiprocessing.get_context("spawn").Process(target=print)
    process.start()
    process.join()


def test_signal():
    old = signal.signal(signal.SIGUSR1, lambda *_: None)
    signal.signal(signal.SIGUSR1, old)


def test_socket():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))


@pytest.fixture(scope="module")
def made_dir(tmp_path_factory):
    return tmp_path_factory.mktemp("made")


def test_first_user_of_a_module_fixture(made_dir):
    pass


def test_second_user_of_a_module_fixture(made_dir):
    pass


@pytest.mark.suite_exempt(reason="checks the real file system on purpose")
def test_exempt(tmp_path):
    (tmp_path / "f").write_text("x")


def test_runs_the_project():
    subprocess.run([sys.executable, "-m", "myapp"], check=True)


@pytest.mark.integration
def test_integration_is_not_recorded(tmp_path):
    (tmp_path / "f").write_text("x")


@pytest.mark.e2e
def test_e2e_is_not_recorded():
    subprocess.run([sys.executable, "-m", "myapp"], check=True)
"""


def test_the_report_records_what_each_test_does(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = {**_PROJECT, "tests/unit/test_behavior.py": _BEHAVIOR}
    behavior = _report(_run(pytester, monkeypatch, layout))["behavior"]
    found = {
        nodeid.split("::")[-1]: (
            entry["suite"],
            sorted(entry["evidence"]),
            entry.get("exempt"),
        )
        for nodeid, entry in behavior.items()
    }
    assert found == {
        "test_writes": ("unit", ["fs-write"], None),
        "test_process": ("unit", ["process"], None),
        "test_multiprocessing": ("unit", ["process"], None),
        "test_signal": ("unit", ["signal"], None),
        "test_socket": ("unit", ["socket"], None),
        "test_first_user_of_a_module_fixture": ("unit", ["fs-write"], None),
        "test_second_user_of_a_module_fixture": ("unit", ["fs-write"], None),
        "test_exempt": ("unit", ["fs-write"], "checks the real file system on purpose"),
        "test_runs_the_project": ("unit", ["entry-point"], None),
    }


_AUTOUSE = """\
import pytest


@pytest.fixture(scope="module", autouse=True)
def prepared(tmp_path_factory):
    (tmp_path_factory.mktemp("prepared") / "f").write_text("x")


def test_after_module_setup():
    pass


class TestEachInTmp:
    @pytest.fixture(autouse=True)
    def in_tmp(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

    def test_in_tmp(self):
        pass
"""


def test_a_test_is_charged_with_what_it_asks_for_and_per_test_autouse(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An autouse fixture wider than a test sets up for every test, not for this one."""
    layout = {**_PROJECT, "tests/unit/test_autouse.py": _AUTOUSE}
    behavior = _report(_run(pytester, monkeypatch, layout))["behavior"]
    found = {
        nodeid.split("::")[-1]: sorted(entry["evidence"])
        for nodeid, entry in behavior.items()
    }
    assert found == {"test_in_tmp": ["chdir", "fs-write"]}


_TEARDOWN = """\
import pytest


@pytest.fixture(scope="module")
def leaves_a_file(tmp_path_factory):
    path = tmp_path_factory.mktemp("teardown")
    yield path
    (path / "done").write_text("x")


def test_uses_it(leaves_a_file):
    pass


def test_changes_directory(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)


def test_only_sets_the_environment(monkeypatch):
    monkeypatch.setenv("SUITE_HEALTH_ONLY_ENV", "1")


def test_last_of_the_module():
    pass
"""


def test_a_fixture_teardown_is_charged_to_the_tests_it_belongs_to(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A wider fixture ends during the teardown of the last test of its scope; a test's own
    fixture undoes what that test did, and no other."""
    layout = {**_PROJECT, "tests/unit/test_teardown.py": _TEARDOWN}
    behavior = _report(_run(pytester, monkeypatch, layout))["behavior"]
    assert sorted(nodeid.split("::")[-1] for nodeid in behavior) == [
        "test_changes_directory",
        "test_uses_it",
    ]


_WRITES_DATA = """\
import pytest


@pytest.fixture(scope="module")
def data(tmp_path_factory):
    path = tmp_path_factory.mktemp("data") / "f"
    path.write_text("x")
    return path


def test_uses_written_data(data):
    pass
"""

_PURE_DATA = """\
import pytest


@pytest.fixture(scope="module")
def data():
    return "x"


def test_uses_pure_data(data):
    pass
"""

_PARAMETRIZED = """\
import pytest


@pytest.fixture(scope="module", params=["write", "pure"])
def source(request, tmp_path_factory):
    if request.param == "write":
        (tmp_path_factory.mktemp("source") / "f").write_text("x")
    return request.param


def test_uses_source(source):
    pass
"""


def test_a_fixture_setup_is_charged_only_to_the_tests_that_used_it(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same-named fixtures of two files, and the parameters of one fixture, are separate
    setups: what one did is not charged to the tests of another."""
    layout = {
        "tests/unit/test_a_writes.py": _WRITES_DATA,
        "tests/unit/test_b_pure.py": _PURE_DATA,
        "tests/unit/test_c_parametrized.py": _PARAMETRIZED,
    }
    behavior = _report(_run(pytester, monkeypatch, layout))["behavior"]
    assert sorted(nodeid.split("::")[-1] for nodeid in behavior) == [
        "test_uses_source[write]",
        "test_uses_written_data",
    ]


def test_an_exemption_needs_a_reason(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PYTHONPATH", str(_REPO_ROOT))
    pytester.makepyfile(
        test_no_reason="import pytest\n\n\n@pytest.mark.unit\n@pytest.mark.suite_exempt\n"
        "def test_x():\n    pass\n"
    )
    result = pytester.runpytest_subprocess("-p", "appinfra.pytest_suites", "-q")
    assert result.ret == pytest.ExitCode.USAGE_ERROR
    assert "suite_exempt needs a reason" in result.stderr.str()


def _check(report_dir: Path) -> subprocess.CompletedProcess[str]:
    """check_suite_health.py over a run of _run, whose rootdir holds the report directory."""
    root = report_dir.parent
    return subprocess.run(
        [
            sys.executable,
            str(_CHECK_SUITE_HEALTH_PY),
            str(report_dir),
            "--root",
            str(root),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


_CHECKED = """\
import os

import pytest


def test_leak():
    os.environ["SUITE_HEALTH_LEAK"] = "1"


def test_clean():
    pass


@pytest.mark.integration
class TestMisplaced:
    def test_a(self):
        pass

    def test_b(self):
        pass

    def test_c(self):
        pass

    def test_d(self):
        pass
"""


def test_the_check_prints_the_health_then_the_findings(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = {"tests/unit/test_checked.py": _CHECKED}
    result = _check(_run(pytester, monkeypatch, layout))
    assert result.returncode == 0
    # 2 of the 6 tests run in their directory's suite
    assert result.stdout.splitlines() == [
        "33.3",
        "placement\ttests/unit/test_checked.py::TestMisplaced\t4 of 4 tests (100%) are "
        "integration, the majority: move them to tests/integration/",
        "leak\ttests/unit/test_checked.py::test_leak\tleft changed: $SUITE_HEALTH_LEAK",
    ]


def test_reports_of_another_rootdir_are_ignored(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pytest the tests start inherits the report directory; its report is not the project's."""
    report_dir = _run(pytester, monkeypatch, {"tests/unit/test_checked.py": _CHECKED})
    result = subprocess.run(
        [
            sys.executable,
            str(_CHECK_SUITE_HEALTH_PY),
            str(report_dir),
            "--root",
            "/elsewhere",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert (result.returncode, result.stdout) == (3, "")


def test_the_check_without_reports_says_so(tmp_path: Path) -> None:
    result = _check(tmp_path)
    assert (result.returncode, result.stdout) == (3, "")
