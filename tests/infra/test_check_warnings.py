# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for appinfra/scripts/check_warnings.py, which finds the warnings in a check's log.

The sample logs are real output: pytest's warnings summary, warnings and ignored exceptions
printed at interpreter exit (by the main process or a pytest-xdist worker, whose line can follow
pytest's progress dots), and the warning lines of tools.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECK_WARNINGS_PY = REPO_ROOT / "appinfra" / "scripts" / "check_warnings.py"
ROOT = "/home/dev/project"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_warnings", CHECK_WARNINGS_PY)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check_warnings = _load()


def _found(log: str) -> list[tuple[int, str, str]]:
    return check_warnings.distinct_warnings(log, ROOT)


_SESSION = f"""\
..                                                                       [100%]
=============================== warnings summary ===============================
tests/test_a.py::test_one
tests/test_a.py::test_two
  {ROOT}/tests/test_a.py:24: DeprecationWarning: old api used in a test
    warnings.warn("old api used in a test", DeprecationWarning, stacklevel=1)

tests/test_b.py::test_three
  {ROOT}/src/pkg/mod.py:7: UserWarning: something odd
    warnings.warn("something odd", UserWarning, stacklevel=1)

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
3 passed, 3 warnings in 0.05s
"""


@pytest.mark.unit
def test_session_warnings_from_pytest_summary() -> None:
    """Each summary entry counts once per test listed above it; paths become relative."""
    assert _found(_SESSION) == [
        (
            2,
            "session",
            "DeprecationWarning: old api used in a test (tests/test_a.py:24)",
        ),
        (1, "session", "UserWarning: something odd (src/pkg/mod.py:7)"),
    ]


@pytest.mark.unit
def test_colored_pytest_output() -> None:
    """pytest in color (a terminal, PY_COLORS=1) wraps its section headers in ANSI codes."""
    log = (
        "\x1b[33m=============================== warnings summary "
        "===============================\x1b[0m\n"
        "tests/test_a.py::test_one\n"
        f"  {ROOT}/tests/test_a.py:24: DeprecationWarning: old api used in a test\n"
        "\n"
        "-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html\n"
        "\x1b[33m\x1b[32m1 passed\x1b[0m, \x1b[33m\x1b[1m1 warning\x1b[0m\x1b[33m in 0.05s\x1b[0m\n"
    )

    assert _found(log) == [
        (
            1,
            "session",
            "DeprecationWarning: old api used in a test (tests/test_a.py:24)",
        )
    ]


_EXIT = f"""\
.                                                                        [100%]sys:1: ResourceWarning: unclosed file <_io.TextIOWrapper name='{ROOT}/tests/data.csv' mode='r' encoding='UTF-8'>
Exception ignored in: <function _Pool.__del__ at 0x7f61b1663380>
Traceback (most recent call last):
  File "{ROOT}/src/pkg/pool.py", line 17, in __del__
RuntimeError: close failed at exit
{ROOT}/src/pkg/api.py:10: DeprecationWarning: old api used at exit
1 passed in 0.31s
sys:1: ResourceWarning: unclosed file <_io.TextIOWrapper name='{ROOT}/tests/data.csv' mode='r' encoding='UTF-8'>
"""


@pytest.mark.unit
def test_exit_warnings_and_ignored_exceptions() -> None:
    """A worker's line may follow the progress dots; a file shows as its name; repeats count."""
    assert _found(_EXIT) == [
        (2, "exit", "ResourceWarning: unclosed file tests/data.csv"),
        (1, "exit", "RuntimeError: close failed at exit (in _Pool.__del__)"),
        (1, "exit", "DeprecationWarning: old api used at exit (src/pkg/api.py:10)"),
    ]


@pytest.mark.unit
def test_warning_raised_as_an_error_at_exit() -> None:
    """With an error filter, a warning at exit is an ignored exception: the warning is the error."""
    log = (
        "Exception ignored in: <_io.FileIO name='/tmp/x.txt' mode='rb' closefd=True>\n"
        "ResourceWarning: unclosed file <_io.TextIOWrapper name='/tmp/x.txt' mode='r'>\n"
    )

    assert _found(log) == [(1, "exit", "ResourceWarning: unclosed file /tmp/x.txt")]


@pytest.mark.unit
def test_warning_raised_as_an_error_keeps_its_location() -> None:
    """The traceback's last frame is where the warning was raised, as for a printed warning."""
    log = (
        "Exception ignored in: <function _Old.__del__ at 0x76aa5a75f6a0>\n"
        "Traceback (most recent call last):\n"
        f'  File "{ROOT}/src/pkg/api.py", line 12, in __del__\n'
        "DeprecationWarning: old api used at exit\n"
    )

    assert _found(log) == [
        (1, "exit", "DeprecationWarning: old api used at exit (src/pkg/api.py:12)")
    ]


@pytest.mark.unit
def test_python_3_14_exit_formats() -> None:
    """3.14 writes '<sys>:0:' for a warning without a source line, and reports an unclosed
    file as an exception ignored 'while finalizing' it."""
    log = (
        f"<sys>:0: ResourceWarning: unclosed file <_io.TextIOWrapper name='{ROOT}/a.txt'>\n"
        f"Exception ignored while finalizing file <_io.FileIO name='{ROOT}/b.txt' mode='rb'>:\n"
        f"ResourceWarning: unclosed file <_io.TextIOWrapper name='{ROOT}/b.txt' mode='r'>\n"
    )

    assert _found(log) == [
        (1, "exit", "ResourceWarning: unclosed file a.txt"),
        (1, "exit", "ResourceWarning: unclosed file b.txt"),
    ]


_SPACED_ROOT = "/Users/me/My Projects/app"


@pytest.mark.unit
def test_session_warning_under_a_path_with_spaces() -> None:
    log = (
        "=============================== warnings summary ===============================\n"
        "tests/test_a.py::test_one\n"
        f"  {_SPACED_ROOT}/tests/test_a.py:12: DeprecationWarning: old api\n"
        "\n"
        "-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html\n"
    )

    assert check_warnings.distinct_warnings(log, _SPACED_ROOT) == [
        (1, "session", "DeprecationWarning: old api (tests/test_a.py:12)")
    ]


@pytest.mark.unit
def test_exit_warning_under_a_path_with_spaces() -> None:
    log = (
        f"{_SPACED_ROOT}/src/pkg/api.py:10: DeprecationWarning: old api used at exit\n"
    )

    assert check_warnings.distinct_warnings(log, _SPACED_ROOT) == [
        (1, "exit", "DeprecationWarning: old api used at exit (src/pkg/api.py:10)")
    ]


@pytest.mark.unit
def test_addresses_are_masked_so_repeats_count_together() -> None:
    log = (
        "Exception ignored in: <function C.__del__ at 0x7f0001>\n"
        "ValueError: boom\n"
        "Exception ignored in: <function C.__del__ at 0x7f0002>\n"
        "ValueError: boom\n"
    )

    assert _found(log) == [(2, "exit", "ValueError: boom (in C.__del__)")]


@pytest.mark.unit
def test_tool_warning_lines() -> None:
    log = (
        "warning: The top-level linter settings are deprecated in favour of `lint`.\n"
        "pyproject.toml: warning: unused section [tool.mypy-foo]\n"
        "All checks passed!\n"
    )

    assert _found(log) == [
        (
            1,
            "tool",
            "The top-level linter settings are deprecated in favour of `lint`.",
        ),
        (1, "tool", "pyproject.toml: unused section [tool.mypy-foo]"),
    ]


@pytest.mark.unit
@pytest.mark.parametrize(
    "line",
    [
        "Warnings: 9 dup, 22 dead",  # check.sh's own cq summary
        "=== exit warnings: strict ===",  # the plugin's mode line
        "3 passed, 3 warnings in 0.05s",  # pytest's counts: the summary has the entries
        "  - 1 skipped: needs PG",
    ],
)
def test_lines_that_are_not_warnings(line: str) -> None:
    assert _found(line + "\n") == []


@pytest.mark.unit
def test_command_line_prints_count_kind_message(tmp_path: Path) -> None:
    log = tmp_path / "check.log"
    log.write_text(_EXIT)

    result = subprocess.run(
        [sys.executable, str(CHECK_WARNINGS_PY), str(log), "--root", ROOT],
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.splitlines()[0] == (
        "2\texit\tResourceWarning: unclosed file tests/data.csv"
    )
