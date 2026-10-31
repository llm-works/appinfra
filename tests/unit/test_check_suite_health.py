# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for the rules of appinfra/scripts/check_suite_health.py, on in-memory reports."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

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
    *scopes: dict[str, Any], leaks: list[dict[str, Any]] | None = None, total: int = 100
) -> dict[str, Any]:
    return {"total": total, "scopes": list(scopes), "leaks": leaks or []}


def _judge(*reports: dict[str, Any], threshold: float = 15) -> Any:
    return check_suite_health.judge(reports, threshold)


class TestScopeRules:
    def test_a_majority_of_another_suite_moves_the_scope(self) -> None:
        unclean, total, findings = _judge(
            _report(_scope("u.py::A", "unit", unit=2, integration=3))
        )
        assert findings == [
            (
                "placement",
                "u.py::A",
                "3 of 5 tests (60%) are integration, the majority: "
                "move to tests/integration/",
            )
        ]
        # The 3 integration tests need moving; the 2 unit tests are where they belong
        assert (unclean, total) == (3, 100)

    def test_overrides_up_to_the_threshold_are_clean(self) -> None:
        report = _report(_scope("u.py::A", "unit", unit=17, integration=3))
        assert _judge(report)[2] == []

    def test_overrides_past_the_threshold_split_the_scope(self) -> None:
        report = _report(_scope("u.py::A", "unit", unit=16, integration=4))
        unclean, _, findings = _judge(report)
        assert [f[0] for f in findings] == ["overrides"]
        assert findings[0][2].startswith("4 integration of 20 tests (20%, over 15%)")
        assert unclean == 4

    def test_the_threshold_is_configurable(self) -> None:
        report = _report(_scope("u.py::A", "unit", unit=16, integration=4))
        assert _judge(report, threshold=20)[2] == []

    def test_a_tie_is_not_a_majority(self) -> None:
        _, _, findings = _judge(
            _report(_scope("u.py::A", "unit", unit=3, integration=3))
        )
        assert [f[0] for f in findings] == ["overrides"]

    def test_module_level_tests_are_judged_against_the_whole_file(self) -> None:
        scope = _scope("u.py", "unit", integration=1)
        scope["file_suites"] = {"unit": 40, "integration": 1}
        assert _judge(_report(scope))[2] == []

    def test_module_level_overrides_past_the_threshold_of_the_file(self) -> None:
        scope = _scope("u.py", "unit", integration=2)
        scope["file_suites"] = {"unit": 8, "integration": 2}
        _, _, findings = _judge(_report(scope))
        assert [f[0] for f in findings] == ["overrides"]
        assert findings[0][2].startswith("2 integration of 10 tests")

    def test_a_file_mostly_of_another_suite_moves(self) -> None:
        scope = _scope("u.py", "unit", integration=4)
        scope["file_suites"] = {"unit": 1, "integration": 4}
        _, _, findings = _judge(_report(scope))
        assert [f[0] for f in findings] == ["placement"]


class TestMerge:
    def test_reports_of_one_run_count_each_scope_once(self) -> None:
        scope = _scope("u.py::A", "unit", integration=3)
        unclean, total, findings = _judge(_report(scope), _report(scope))
        assert (unclean, total, len(findings)) == (3, 100, 1)

    def test_a_leaking_unit_test_where_it_belongs_counts_on_top(self) -> None:
        leak = {"test": "u.py::A::test_x", "scope": "u.py::A", "changed": ["$X"]}
        report = _report(_scope("u.py::A", "unit", unit=1, integration=3), leaks=[leak])
        unclean, _, findings = _judge(report)
        assert unclean == 4
        assert findings[-1] == ("leak", "u.py::A::test_x", "left changed: $X")

    def test_a_leaking_unit_test_that_needs_moving_counts_once(self) -> None:
        leak = {"test": "i.py::A::test_x", "scope": "i.py::A", "changed": ["$X"]}
        report = _report(
            _scope("i.py::A", "integration", integration=1, unit=3), leaks=[leak]
        )
        assert _judge(report)[0] == 3

    def test_a_leak_elsewhere_counts_its_test(self) -> None:
        leak = {"test": "u.py::B::test_y", "scope": "u.py::B", "changed": ["SIGINT"]}
        assert _judge(_report(leaks=[leak]))[0] == 1

    def test_findings_order_placement_overrides_leaks(self) -> None:
        leak = {"test": "a.py::test_z", "scope": "a.py", "changed": ["cwd"]}
        report = _report(
            _scope("b.py::Split", "unit", unit=5, integration=3),
            _scope("c.py::Move", "unit", integration=3),
            leaks=[leak],
        )
        assert [f[0] for f in _judge(report)[2]] == ["placement", "overrides", "leak"]


@pytest.mark.parametrize(
    ("unclean", "total", "expected"),
    [(0, 5937, "100.0"), (1, 5937, "99.9"), (138, 5937, "97.6"), (0, 0, "100.0")],
)
def test_clean_percent_rounds_down(unclean: int, total: int, expected: str) -> None:
    assert check_suite_health.clean_percent(unclean, total) == expected
