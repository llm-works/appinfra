# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""describe(): an error as text, safe for one whose str() raises."""

from __future__ import annotations

from appinfra.runtime.chan.link import describe


class _UnprintableError(Exception):
    """An error whose str() raises."""

    def __str__(self) -> str:
        raise ValueError("cannot be printed")


class TestDescribe:
    def test_an_error_with_a_message_is_its_type_and_message(self) -> None:
        assert describe(OSError("no room")) == "OSError: no room"

    def test_an_error_without_a_message_is_its_type(self) -> None:
        assert describe(TimeoutError()) == "TimeoutError"

    def test_an_error_whose_str_raises_is_its_type(self) -> None:
        assert describe(_UnprintableError()) == "_UnprintableError"
