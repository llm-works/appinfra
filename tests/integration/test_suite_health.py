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


@pytest.mark.integration
def test_integration_may_change_state():
    os.environ["SUITE_HEALTH_INTEGRATION"] = "1"
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
        "placement\ttests/unit/test_checked.py::TestMisplaced\t"
        "4 of 4 tests (100%) are integration, the majority: "
        "move them to tests/integration/",
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
