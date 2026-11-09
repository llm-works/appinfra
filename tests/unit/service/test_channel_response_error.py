# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for ChannelResponseError: the error response is kept on the exception."""

from __future__ import annotations

import pytest

from appinfra.service import (
    AsyncQueueChannelFactory,
    ChannelError,
    ChannelResponseError,
    Message,
)
from appinfra.service.channel.base import validate_response
from tests.helpers.service.response_error import AsyncSubmitTests


class TestValidateResponse:
    """validate_response() raises ChannelResponseError carrying the message."""

    def test_raises_with_response(self) -> None:
        msg = Message(error="fail")

        with pytest.raises(ChannelResponseError, match="Request failed: fail") as exc:
            validate_response(msg)

        assert exc.value.response is msg

    def test_is_channel_error(self) -> None:
        with pytest.raises(ChannelError):
            validate_response(Message(error="fail"))


@pytest.mark.parametrize("factory", [AsyncQueueChannelFactory])
class TestAsyncSubmit(AsyncSubmitTests):
    """AsyncBufferedChannel.submit() and submit_stream() over asyncio.Queue."""
