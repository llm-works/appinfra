# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""tests/fixtures/suite_markers.py: a test under a suite directory runs in that suite unless it
names another; a test elsewhere names its suite; collection stops on a test that names none."""

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]

_SUITES = ("unit", "integration", "e2e", "security", "performance")

_PLAIN = "def test_plain():\n    pass\n"


def _marked(suite: str) -> str:
    return f"import pytest\n\n\n@pytest.mark.{suite}\ndef test_marked():\n    pass\n"


def _run(
    pytester: pytest.Pytester,
    monkeypatch: pytest.MonkeyPatch,
    layout: dict[str, str],
    *args: str,
) -> pytest.RunResult:
    monkeypatch.setenv("PYTHONPATH", str(_REPO_ROOT))
    for path, source in layout.items():
        target = pytester.path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source)
    return pytester.runpytest_subprocess(
        "-p", "tests.fixtures.suite_markers", "--collect-only", "-q", *args
    )


def _ids(result: pytest.RunResult) -> set[str]:
    return {line for line in result.outlines if "::" in line}


_DIRECTORY_LAYOUT = {
    f"tests/{suite}/sub/test_{suite}_plain.py": _PLAIN for suite in _SUITES
} | {"tests/mixed/test_mixed_marked.py": _marked("integration")}


@pytest.mark.parametrize("suite", _SUITES)
def test_a_test_runs_in_the_suite_of_its_directory(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, suite: str
) -> None:
    expected = {f"tests/{suite}/sub/test_{suite}_plain.py::test_plain"}
    if suite == "integration":
        expected.add("tests/mixed/test_mixed_marked.py::test_marked")
    assert _ids(_run(pytester, monkeypatch, _DIRECTORY_LAYOUT, "-m", suite)) == expected


def test_a_marker_matching_the_directory_is_accepted(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = {"tests/unit/test_unit_marked.py": _marked("unit")}
    result = _run(pytester, monkeypatch, layout, "-m", "unit")
    assert _ids(result) == {"tests/unit/test_unit_marked.py::test_marked"}


@pytest.mark.parametrize(
    ("suite", "expected"), [("integration", True), ("unit", False)]
)
def test_a_marker_naming_another_suite_overrides_the_directory(
    pytester: pytest.Pytester,
    monkeypatch: pytest.MonkeyPatch,
    suite: str,
    expected: bool,
) -> None:
    layout = {"tests/unit/test_unit_overridden.py": _marked("integration")}
    result = _run(pytester, monkeypatch, layout, "-m", suite)
    nodeid = "tests/unit/test_unit_overridden.py::test_marked"
    assert result.ret != pytest.ExitCode.USAGE_ERROR
    assert (nodeid in _ids(result)) is expected


def test_a_test_with_two_suite_markers_stops_collection(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = (
        "import pytest\n\n\n@pytest.mark.unit\nclass TestBoth:\n"
        "    @pytest.mark.integration\n    def test_both(self):\n        pass\n"
    )
    layout = {"tests/unit/test_unit_both.py": source}
    result = _run(pytester, monkeypatch, layout)
    assert result.ret == pytest.ExitCode.USAGE_ERROR
    assert "tests/unit/test_unit_both.py::TestBoth::test_both" in result.stderr.str()


def test_a_test_outside_the_suite_directories_must_name_its_suite(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = {"tests/cli/test_cli_plain.py": _PLAIN}
    result = _run(pytester, monkeypatch, layout)
    assert result.ret == pytest.ExitCode.USAGE_ERROR
    assert "tests/cli/test_cli_plain.py::test_plain" in result.stderr.str()
