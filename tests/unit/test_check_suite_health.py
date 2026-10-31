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
    *scopes: dict[str, Any], leaks: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    return {"scopes": list(scopes), "leaks": leaks or []}


def _judge(
    *reports: dict[str, Any], threshold: float = 15, outliers: int = 2
) -> list[tuple[str, str, str]]:
    return check_suite_health.judge(reports, threshold, outliers)


def _kinds(*reports: dict[str, Any], **limits: Any) -> list[str]:
    return [kind for kind, _, _ in _judge(*reports, **limits)]


class TestScopeRules:
    def test_a_majority_of_another_suite_moves_the_scope(self) -> None:
        report = _report(_scope("u.py::A", "unit", unit=2, integration=3))
        assert _judge(report) == [
            (
                "placement",
                "u.py::A",
                "3 of 5 tests (60%) are integration, the majority: "
                "move them to tests/integration/",
            )
        ]

    def test_up_to_the_outliers_a_small_scope_is_clean(self) -> None:
        report = _report(
            _scope("u.py::A", "unit", unit=3, integration=1),
            _scope("u.py::B", "unit", unit=2, integration=2),
        )
        assert _judge(report) == []

    def test_up_to_the_outliers_a_scope_of_another_suite_stays(self) -> None:
        report = _report(_scope("u.py::A", "unit", unit=1, integration=2))
        assert _judge(report) == []

    def test_past_the_outliers_the_threshold_applies(self) -> None:
        report = _report(_scope("u.py::A", "unit", unit=5, integration=3))
        assert _kinds(report) == ["overrides"]

    def test_the_outliers_are_configurable(self) -> None:
        report = _report(_scope("u.py::A", "unit", unit=3, integration=1))
        assert _kinds(report, outliers=0) == ["overrides"]

    def test_the_outliers_count_every_other_suite(self) -> None:
        report = _report(_scope("u.py::A", "unit", unit=3, integration=2, e2e=1))
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
        report = _report(_scope("u.py::A", "unit", unit=3, integration=3))
        assert _kinds(report) == ["overrides"]

    def test_module_level_tests_are_judged_against_the_whole_file(self) -> None:
        scope = _scope("u.py", "unit", integration=1)
        scope["file_suites"] = {"unit": 40, "integration": 1}
        assert _judge(_report(scope)) == []

    def test_module_level_overrides_past_the_threshold_of_the_file(self) -> None:
        scope = _scope("u.py", "unit", integration=3)
        scope["file_suites"] = {"unit": 7, "integration": 3}
        ((kind, _, detail),) = _judge(_report(scope))
        assert kind == "overrides"
        assert detail.startswith("3 integration of 10 tests")

    def test_a_file_mostly_of_another_suite_moves(self) -> None:
        scope = _scope("u.py", "unit", integration=4)
        scope["file_suites"] = {"unit": 1, "integration": 4}
        assert _kinds(_report(scope)) == ["placement"]


class TestMerge:
    def test_reports_of_one_run_count_each_scope_once(self) -> None:
        scope = _scope("u.py::A", "unit", integration=3)
        assert _kinds(_report(scope), _report(scope)) == ["placement"]

    def test_a_leak_is_always_a_finding(self) -> None:
        leak = {"test": "u.py::B::test_y", "changed": ["SIGINT", "$X"]}
        assert _judge(_report(leaks=[leak])) == [
            ("leak", "u.py::B::test_y", "left changed: SIGINT, $X")
        ]

    def test_findings_order_placement_overrides_leaks(self) -> None:
        leak = {"test": "a.py::test_z", "changed": ["cwd"]}
        report = _report(
            _scope("b.py::Split", "unit", unit=5, integration=3),
            _scope("c.py::Move", "unit", integration=3),
            leaks=[leak],
        )
        assert _kinds(report) == ["placement", "overrides", "leak"]
