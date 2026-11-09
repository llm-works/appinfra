# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""check.sh's live display in a terminal too short for it: the checklist and the rows below it
are taller than the screen, so the top of the checklist scrolls off while checks still run."""

import fcntl
import os
import pty
import re
import select
import signal
import struct
import subprocess
import sys
import termios
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
CHECK_SH = REPO / "appinfra" / "scripts" / "check.sh"
HEIGHT = 12
NARROW = 50
DEADLINE_S = 300

# Eight tests, each with a warning of its own: more distinct warnings than rows are shown for
_WARNING_TESTS = "".join(
    f'\n\ndef test_{i}():\n    warnings.warn("warning number {i}", UserWarning, stacklevel=1)\n'
    for i in range(8)
)


def _project(root: Path) -> None:
    """A one-module package whose unit tests raise the eight warnings, formatted and linted
    as the check wants them; the suite plugin gives the tests their suite."""
    (root / "pkg").mkdir()
    (root / "pkg" / "__init__.py").write_text('"""A package for the check."""\n')
    tests = root / "tests" / "unit"
    tests.mkdir(parents=True)
    (root / "tests" / "conftest.py").write_text(
        '"""Suites."""\n\npytest_plugins = ["appinfra.pytest_suites"]\n'
    )
    (tests / "test_w.py").write_text(
        f'"""Warnings."""\n\nimport warnings\n{_WARNING_TESTS}'
    )


def _env(root: Path) -> dict[str, str]:
    """The settings for the fixture project, without those a surrounding make check exports."""
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("INFRA_", "APPINFRA_", "_APPINFRA_", "MAKE"))
    }
    return {
        **env,
        "PYTHON": sys.executable,
        "PYTHONPATH": str(REPO),
        "APPINFRA_DEV_PKG_NAME": "pkg",
        "APPINFRA_DEV_PROJECT_ROOT": str(root),
        "APPINFRA_DEV_DOCSTRING_THRESHOLD": "0",
        "APPINFRA_PYTEST_COVERAGE_THRESHOLD": "0",
        "TERM": "xterm",
    }


def _run_in_terminal(script: Path, root: Path, cols: int) -> str:
    """check.sh's output in a pseudo-terminal HEIGHT lines tall. Its stdin is not the terminal,
    so the terminal is not its controlling one: the size has to come from stdout."""
    controller, terminal = pty.openpty()
    fcntl.ioctl(terminal, termios.TIOCSWINSZ, struct.pack("HHHH", HEIGHT, cols, 0, 0))
    proc = subprocess.Popen(
        ["bash", str(script), "--sequential"],
        cwd=root,
        env=_env(root),
        stdin=subprocess.DEVNULL,
        stdout=terminal,
        stderr=terminal,
        start_new_session=True,
    )
    os.close(terminal)
    try:
        output = _read_all(controller, proc)
    finally:
        os.close(controller)
    proc.wait(timeout=DEADLINE_S)
    return output.decode(errors="replace")


def _read_all(controller: int, proc: subprocess.Popen[bytes]) -> bytes:
    """Everything written to the terminal until the last process holding it exits; past the
    deadline, check.sh's session is killed and the test fails."""
    deadline = time.monotonic() + DEADLINE_S
    chunks = []
    while True:
        remaining = deadline - time.monotonic()
        ready, _, _ = select.select([controller], [], [], max(remaining, 0))
        if not ready:
            os.killpg(proc.pid, signal.SIGKILL)
            pytest.fail(f"check.sh still running after {DEADLINE_S}s")
        try:
            chunk = os.read(controller, 65536)
        except OSError:  # the terminal closed: check.sh and its children are done
            break
        if not chunk:
            break
        chunks.append(chunk)
    return b"".join(chunks)


@pytest.fixture(scope="module")
def output(tmp_path_factory: pytest.TempPathFactory) -> str:
    """A terminal wide enough that no row below the checklist is cut."""
    root = tmp_path_factory.mktemp("display")
    _project(root)
    return _run_in_terminal(CHECK_SH, root, 200)


@pytest.fixture(scope="module")
def narrow_output(tmp_path_factory: pytest.TempPathFactory) -> str:
    """A terminal narrower than the rows below the checklist."""
    root = tmp_path_factory.mktemp("narrow")
    _project(root)
    return _run_in_terminal(CHECK_SH, root, NARROW)


def _plain(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", text)


def test_no_redraw_moves_above_the_screen(output: str) -> None:
    """A move up as far as the screen is tall or further lands on the wrong line."""
    moves = [int(n) for n in re.findall(r"\x1b\[(\d+)A", output)]
    assert moves, "nothing was redrawn"
    assert max(moves) < HEIGHT


def test_the_checklist_is_printed_again_as_it_ends(output: str) -> None:
    """Lines scrolled off before their check ended show their final state after the run."""
    after = _plain(output.rsplit("\x1b[?25h", 1)[-1]).splitlines()
    assert any(line.startswith("[✓]  Formatting check") for line in after)
    assert any(re.match(r"\[.\]  Test suite", line) for line in after)
    assert not any(line.startswith("[…]") for line in after)


def test_warnings_beyond_the_first_rows_are_counted_not_listed(output: str) -> None:
    """At least the eight test warnings, more if an installed plugin warns too: five rows,
    then one that counts the rest."""
    rows = {
        line
        for line in _plain(output).splitlines()
        if line.startswith("[⚠] Unit tests: ") and " more in " not in line
    }
    assert len(rows) == 5
    more = re.search(
        r"Unit tests: (\d+) more in \.build/check/unit-tests\.log", _plain(output)
    )
    assert more is not None and int(more.group(1)) >= 3


def test_rows_below_the_checklist_fit_a_narrow_terminal(narrow_output: str) -> None:
    """A row that wraps takes two lines but is counted as one, so every redraw after it lands
    on the wrong line. The row counting the rest carries the kept log's path, the longest."""
    rows = [
        line
        for line in _plain(narrow_output).splitlines()
        if line.startswith("[⚠] Unit tests: ")
    ]
    assert any(" more" in row for row in rows)
    assert [row for row in rows if len(row) >= NARROW] == []
