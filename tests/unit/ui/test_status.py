# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for appinfra.ui.status — shared CLI status/color primitives."""

from __future__ import annotations

from io import StringIO
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.unit

from appinfra.ui import status


class _TTYStream(StringIO):
    """StringIO that reports isatty() True — for asserting ANSI output."""

    def isatty(self) -> bool:  # noqa: D401
        return True


class _NonTTYStream(StringIO):
    """StringIO that reports isatty() False — for asserting plain output."""

    def isatty(self) -> bool:  # noqa: D401
        return False


def test_ansi_disabled_when_no_color_env_set() -> None:
    """NO_COLOR (any non-empty value) disables ANSI even on a TTY."""
    tty = _TTYStream()
    with patch.dict("os.environ", {"NO_COLOR": "1"}):
        assert status.mark_ok(tty) == "[✓]"
        assert status.red("bad", tty) == "bad"


def test_ansi_disabled_when_stream_is_not_a_tty() -> None:
    """Non-TTY streams (pipes, files) get plain text."""
    non_tty = _NonTTYStream()
    with patch.dict("os.environ", {}, clear=True):
        assert status.mark_ok(non_tty) == "[✓]"
        assert status.green("ok", non_tty) == "ok"


def test_marks_include_ansi_on_tty() -> None:
    """On a TTY (no NO_COLOR), marks wrap in the expected ANSI codes."""
    tty = _TTYStream()
    with patch.dict("os.environ", {}, clear=True):
        assert status.mark_pending(tty) == "\033[0;90m[ ]\033[0m"
        assert status.mark_running(tty) == "\033[0;33m[…]\033[0m"
        assert status.mark_ok(tty) == "\033[0;32m[✓]\033[0m"
        assert status.mark_warn(tty) == "\033[0;33m[⚠]\033[0m"
        assert status.mark_fail(tty) == "\033[0;31m[✗]\033[0m"


@pytest.mark.parametrize(
    "helper,code",
    [
        (status.bold, "1"),
        (status.red, "0;31"),
        (status.green, "0;32"),
        (status.yellow, "0;33"),
        (status.blue, "0;34"),
        (status.cyan, "0;36"),
        (status.gray, "0;90"),
    ],
)
def test_color_helpers_wrap_ansi_on_tty(helper, code) -> None:
    """Each color helper wraps the argument in its ANSI code on a TTY."""
    tty = _TTYStream()
    with patch.dict("os.environ", {}, clear=True):
        assert helper("x", tty) == f"\033[{code}mx\033[0m"


def test_ui_ok_prints_to_stream_with_mark_and_message() -> None:
    """ui_ok emits '<mark> <message>' to the given stream."""
    buf = _NonTTYStream()
    status.ui_ok("server ready", buf)
    assert buf.getvalue() == "[✓] server ready\n"


def test_ui_fail_defaults_to_stderr(capsys: pytest.CaptureFixture[str]) -> None:
    """ui_fail writes to stderr by default when no stream is given."""
    status.ui_fail("bad news")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "[✗] bad news\n" in captured.err


def test_ui_fail_explicit_stream_override() -> None:
    """ui_fail respects explicit stream override."""
    buf = _NonTTYStream()
    status.ui_fail("bad news", buf)
    assert buf.getvalue() == "[✗] bad news\n"


def test_ui_helpers_use_expected_marks() -> None:
    """ui_running/ui_warn/ui_pending emit the corresponding marks."""
    buf = _NonTTYStream()
    status.ui_running("working", buf)
    status.ui_warn("careful", buf)
    status.ui_pending("queued", buf)
    assert buf.getvalue() == "[…] working\n[⚠] careful\n[ ] queued\n"
