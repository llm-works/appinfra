# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for appinfra.ui.prompts that drive a real InquirerPy prompt.

prompt_toolkit installs SIGWINCH and SIGINT handlers while the prompt runs.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from appinfra.ui import prompts


def _run_select_with_keys(keys: str) -> tuple[str | None, list[BaseException]]:
    """Run a real InquirerPy select on piped keys.

    Returns the result and every exception that reached the event loop's
    exception handler, where prompt_toolkit reports errors raised in key
    handlers.
    """
    from prompt_toolkit.application import create_app_session
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    loop_errors: list[BaseException] = []

    def record(_loop: asyncio.AbstractEventLoop, context: dict) -> None:
        loop_errors.append(context["exception"])

    with (
        patch.object(asyncio.BaseEventLoop, "call_exception_handler", record),
        create_pipe_input() as pipe,
    ):
        pipe.send_text(keys)
        with create_app_session(input=pipe, output=DummyOutput()):
            result = prompts._inquirer_select(
                "Choose:", ["a", "b", "c"], 0, 10, "#005fff", "#ffffff"
            )
    return result, loop_errors


@pytest.mark.skipif(not prompts.INQUIRER_AVAILABLE, reason="InquirerPy not installed")
class TestInquirerSelectKeys:
    """Key handling of a real InquirerPy select prompt.

    prompt_toolkit holds a lone Esc until the next key arrives and then
    handles both in one batch, so Esc followed by another exit key used to
    call ``app.exit()`` twice and raise "Return value already set" inside
    the event loop.
    """

    @pytest.mark.parametrize(
        ("keys", "expected"),
        [("\x1b", None), ("q", None), ("\r", "a"), ("\x1b[B\r", "b")],
        ids=["esc", "q", "enter", "down-enter"],
    )
    def test_single_action(self, keys, expected):
        """A single skip key returns None; Enter returns the highlighted choice."""
        assert _run_select_with_keys(keys) == (expected, [])

    @pytest.mark.parametrize(
        "keys",
        ["\x1bq", "\x1b\r", "\x1b\x1b", "qq", "q\x1b", "\x1b\x1bq"],
        ids=["esc-q", "esc-enter", "esc-esc", "q-q", "q-esc", "esc-esc-q"],
    )
    def test_second_exit_key_is_ignored(self, keys):
        """Keys handled after the prompt exited do not exit it again."""
        assert _run_select_with_keys(keys) == (None, [])

    def test_enter_then_esc_keeps_the_answer(self):
        """A skip key after Enter does not replace the selected choice."""
        assert _run_select_with_keys("\r\x1b") == ("a", [])
