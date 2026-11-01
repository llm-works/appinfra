# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for the rules of appinfra/scripts/check_suite_health.py, on in-memory reports."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECK_SUITE_HEALTH_PY = REPO_ROOT / "appinfra" / "scripts" / "check_suite_health.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "check_suite_health", CHECK_SUITE_HEALTH_PY
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check_suite_health = _load()


def _scope(name: str, home: str, **suites: int) -> dict[str, Any]:
    return {"scope": name, "directory": home, "suites": suites}


def _report(
    *scopes: dict[str, Any],
    leaks: list[dict[str, Any]] | None = None,
    total: int = 100,
    behavior: dict[str, dict[str, Any]] | None = None,
    suited: int | None = None,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "total": total,
        "scopes": list(scopes),
        "leaks": leaks or [],
    }
    if behavior is not None:
        report["behavior"] = behavior
    if suited is not None:
        report["suited"] = suited
    return report


def _ran(
    suite: str, directory: str | None = None, exempt: str | None = None, **evidence: str
) -> dict[str, Any]:
    """A behavior entry; evidence categories are given with _ for -, as fs_write."""
    entry: dict[str, Any] = {
        "suite": suite,
        "directory": directory if directory is not None else suite,
        "evidence": {k.replace("_", "-"): v for k, v in evidence.items()},
    }
    if exempt is not None:
        entry["exempt"] = exempt
    return entry


def _judge(
    *reports: dict[str, Any], threshold: float = 15, outliers: int = 3
) -> list[tuple[str, str, str]]:
    return check_suite_health.judge(reports, threshold, outliers)


def _kinds(*reports: dict[str, Any], **limits: Any) -> list[str]:
    return [kind for kind, _, _ in _judge(*reports, **limits)]


class TestScopeRules:
    def test_a_majority_of_another_suite_moves_the_scope(self) -> None:
        report = _report(_scope("u.py::A", "unit", unit=2, integration=4))
        assert _judge(report) == [
            (
                "placement",
                "u.py::A",
                "4 of 6 tests (67%) are integration, the majority: "
                "move them to tests/integration/",
            )
        ]

    def test_up_to_the_outliers_a_small_scope_is_clean(self) -> None:
        report = _report(
            _scope("u.py::A", "unit", unit=3, integration=1),
            _scope("u.py::B", "unit", unit=3, integration=3),
        )
        assert _judge(report) == []

    def test_up_to_the_outliers_a_scope_of_another_suite_stays(self) -> None:
        report = _report(_scope("u.py::A", "unit", unit=1, integration=3))
        assert _judge(report) == []

    def test_past_the_outliers_the_threshold_applies(self) -> None:
        report = _report(_scope("u.py::A", "unit", unit=5, integration=4))
        assert _kinds(report) == ["overrides"]

    def test_the_outliers_are_configurable(self) -> None:
        report = _report(_scope("u.py::A", "unit", unit=3, integration=1))
        assert _kinds(report, outliers=0) == ["overrides"]

    def test_the_outliers_count_every_other_suite(self) -> None:
        report = _report(_scope("u.py::A", "unit", unit=5, integration=3, e2e=1))
        assert _kinds(report) == ["overrides"]

    def test_overrides_up_to_the_threshold_are_clean(self) -> None:
        report = _report(_scope("u.py::A", "unit", unit=17, integration=3))
        assert _judge(report) == []

    def test_overrides_past_the_threshold_split_the_scope(self) -> None:
        report = _report(_scope("u.py::A", "unit", unit=16, integration=4))
        ((kind, _, detail),) = _judge(report)
        assert kind == "overrides"
        assert detail.startswith("4 integration of 20 tests (20%, over 15%)")

    def test_the_threshold_is_configurable(self) -> None:
        report = _report(_scope("u.py::A", "unit", unit=16, integration=4))
        assert _judge(report, threshold=20) == []

    def test_a_tie_is_not_a_majority(self) -> None:
        report = _report(_scope("u.py::A", "unit", unit=4, integration=4))
        assert _kinds(report) == ["overrides"]

    def test_module_level_tests_are_judged_against_the_whole_file(self) -> None:
        scope = _scope("u.py", "unit", integration=1)
        scope["file_suites"] = {"unit": 40, "integration": 1}
        assert _judge(_report(scope)) == []

    def test_module_level_overrides_past_the_threshold_of_the_file(self) -> None:
        scope = _scope("u.py", "unit", integration=4)
        scope["file_suites"] = {"unit": 6, "integration": 4}
        ((kind, _, detail),) = _judge(_report(scope))
        assert kind == "overrides"
        assert detail.startswith("4 integration of 10 tests")

    def test_a_file_mostly_of_another_suite_moves(self) -> None:
        scope = _scope("u.py", "unit", integration=4)
        scope["file_suites"] = {"unit": 1, "integration": 4}
        assert _kinds(_report(scope)) == ["placement"]


class TestMerge:
    def test_reports_of_one_run_count_each_scope_once(self) -> None:
        scope = _scope("u.py::A", "unit", integration=4)
        assert _kinds(_report(scope), _report(scope)) == ["placement"]

    def test_a_leak_is_always_a_finding(self) -> None:
        leak = {"test": "u.py::B::test_y", "changed": ["SIGINT", "$X"]}
        assert _judge(_report(leaks=[leak])) == [
            ("leak", "u.py::B::test_y", "left changed: SIGINT, $X")
        ]

    def test_findings_order_placement_overrides_leaks(self) -> None:
        leak = {"test": "a.py::test_z", "changed": ["cwd"]}
        report = _report(
            _scope("b.py::Split", "unit", unit=5, integration=4),
            _scope("c.py::Move", "unit", integration=4),
            leaks=[leak],
        )
        assert _kinds(report) == ["placement", "overrides", "leak"]


class TestBehavior:
    def test_unit_tests_doing_integration_work_are_misfiled_by_scope(self) -> None:
        behavior = {
            "t.py::A::test_a": _ran("unit", fs_write="/tmp/x"),
            "t.py::A::test_b": _ran("unit", process="subprocess.Popen git"),
        }
        assert _judge(_report(behavior=behavior)) == [
            (
                "misfiled",
                "t.py::A",
                "2 unit ➜ integration (fs-write /tmp/x)",
            )
        ]

    def test_module_level_tests_group_by_file(self) -> None:
        behavior = {"t.py::test_a": _ran("unit", socket="socket.bind")}
        ((kind, where, detail),) = _judge(_report(behavior=behavior))
        assert (kind, where) == ("misfiled", "t.py")
        assert detail == "1 unit ➜ integration (socket socket.bind)"

    def test_a_unit_test_running_the_project_belongs_in_e2e(self) -> None:
        behavior = {"t.py::test_a": _ran("unit", entry_point="python -m myapp")}
        ((_, _, detail),) = _judge(_report(behavior=behavior))
        assert detail == "1 unit ➜ e2e (entry-point python -m myapp)"

    def test_an_exempt_test_is_not_judged(self) -> None:
        behavior = {
            "t.py::test_a": _ran("unit", exempt="on purpose", fs_write="/tmp/x")
        }
        assert _judge(_report(behavior=behavior)) == []

    def test_an_e2e_test_must_run_the_project(self) -> None:
        behavior = {
            "e.py::test_ok": _ran("e2e", entry_point="python -m myapp"),
            "e.py::test_files": _ran("e2e", fs_write="/tmp/x"),
            "f.py::test_nothing": _ran("e2e"),
        }
        assert _judge(_report(behavior=behavior)) == [
            (
                "misfiled",
                "e.py",
                "1 e2e ➜ integration (fs-write /tmp/x)",
            ),
            ("misfiled", "f.py", "1 e2e ➜ unit"),
        ]

    def test_an_integration_test_without_integration_work_belongs_in_unit(self) -> None:
        behavior = {
            "i.py::A::test_a": _ran("integration"),
            "i.py::A::test_b": _ran("integration", fs_read="/srv/x"),
        }
        assert _judge(_report(behavior=behavior)) == [
            ("misfiled", "i.py::A", "1 integration ➜ unit")
        ]

    def test_a_test_reported_by_two_processes_counts_once(self) -> None:
        behavior = {"t.py::test_a": _ran("unit", chdir="/tmp")}
        report = _report(behavior=behavior)
        ((_, _, detail),) = _judge(report, report)
        assert detail.startswith("1 unit ➜")

    def test_tests_whose_work_fits_their_directory_are_not_placed_elsewhere(
        self,
    ) -> None:
        behavior = {
            f"u.py::A::test_{i}": _ran("integration", directory="unit")
            for i in range(4)
        }
        report = _report(_scope("u.py::A", "unit", integration=4), behavior=behavior)
        assert _judge(report) == [("misfiled", "u.py::A", "4 integration ➜ unit")]

    def test_only_tests_whose_work_fits_their_directory_leave_the_scope_finding(
        self,
    ) -> None:
        behavior = {
            "i.py::B::test_a": _ran("unit", directory="integration", fs_write="/tmp"),
            "i.py::B::test_b": _ran("unit", directory="integration", socket="bind"),
        }
        report = _report(
            _scope("i.py::B", "integration", integration=2, unit=7),
            behavior=behavior,
        )
        # the 2 unit tests doing integration work count as integration: 5 of 9 stay unit
        assert _judge(report) == [
            (
                "placement",
                "i.py::B",
                "5 of 9 tests (56%) are unit, the majority: move them to tests/unit/",
            ),
            ("misfiled", "i.py::B", "2 unit ➜ integration (fs-write /tmp)"),
        ]

    def test_findings_order_placement_misfiled_leaks(self) -> None:
        report = _report(
            _scope("c.py::Move", "unit", integration=4),
            leaks=[{"test": "a.py::test_z", "changed": ["cwd"]}],
            behavior={
                "d.py::test_a": _ran("unit", db="sqlite3 /tmp/a.db"),
                "i.py::test_b": _ran("integration"),
            },
        )
        assert _kinds(report) == ["placement", "misfiled", "misfiled", "leak"]


class TestHealth:
    def test_misfiled_tests_count_against_the_share(self) -> None:
        behavior = {f"t.py::test_{i}": _ran("unit", fs_write="/tmp") for i in range(4)}
        assert (
            check_suite_health.health([_report(behavior=behavior, suited=100)])
            == "96.0"
        )

    def test_exempt_tests_do_not(self) -> None:
        behavior = {
            "i.py::test_a": _ran("integration", exempt="on purpose"),
            "t.py::test_b": _ran("unit", exempt="on purpose", fs_write="/tmp"),
        }
        assert (
            check_suite_health.health([_report(behavior=behavior, suited=10)])
            == "100.0"
        )

    def test_a_test_outside_its_directory_and_misfiled_counts_once(self) -> None:
        behavior = {
            "u.py::test_a": _ran("unit", directory="integration", fs_write="/tmp")
        }
        report = _report(
            _scope("u.py", "integration", unit=1), behavior=behavior, suited=10
        )
        assert check_suite_health.health([report]) == "90.0"

    def test_tests_outside_the_suite_directories_count_toward_the_whole(self) -> None:
        # 10 tests collected, 4 under tests/<suite>/; the share is of all 10
        behavior = {"cli.py::test_a": _ran("unit", directory="", fs_write="/tmp")}
        report = _report(total=4, behavior=behavior, suited=10)
        assert check_suite_health.health([report]) == "90.0"

    def test_tolerated_tests_outside_their_directory_count_too(self) -> None:
        report = _report(
            _scope("u.py::A", "unit", unit=3, integration=1),
            _scope("i.py::B", "integration", integration=5, unit=2),
            total=200,
        )
        # 3 of 200 tests run outside their directory's suite, with no finding
        assert _judge(report) == []
        assert check_suite_health.health([report]) == "98.5"

    def test_reports_of_one_run_count_each_scope_once(self) -> None:
        report = _report(_scope("u.py::A", "unit", unit=3, integration=1), total=10)
        assert check_suite_health.health([report, report]) == "90.0"

    def test_the_share_rounds_down(self) -> None:
        report = _report(_scope("u.py", "unit", integration=1), total=3)
        assert check_suite_health.health([report]) == "66.6"

    def test_no_tests_is_all_in_place(self) -> None:
        assert check_suite_health.health([_report(total=0)]) == "100.0"
