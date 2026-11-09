# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for ChannelResponseError with a responder on another thread or process queue."""

from __future__ import annotations

import threading
from typing import Any

import pytest

from appinfra.service import (
    AsyncProcessQueueChannelFactory,
    ChannelResponseError,
    ProcessQueueChannelFactory,
    QueueChannelFactory,
)
from tests.helpers.service.response_error import AsyncSubmitTests, Request, Response

SYNC_FACTORIES = [QueueChannelFactory, ProcessQueueChannelFactory]


@pytest.mark.parametrize("factory", SYNC_FACTORIES)
class TestSyncSubmit:
    """BufferedChannel.submit() over queue.Queue / mp.Queue."""

    def test_error_response_is_attached(self, factory: Any) -> None:
        pair = factory().create_pair()

        def responder() -> None:
            req = pair.child.recv(timeout=1.0)
            pair.child.send(Response(id=req.id, status="rejected", error="busy"))

        thread = threading.Thread(target=responder)
        thread.start()

        with pytest.raises(ChannelResponseError, match="busy") as exc:
            pair.parent.submit(Request("1"), timeout=2.0)

        thread.join()
        assert exc.value.response == Response(id="1", status="rejected", error="busy")
        pair.close()


@pytest.mark.parametrize("factory", [AsyncProcessQueueChannelFactory])
class TestAsyncSubmit(AsyncSubmitTests):
    """AsyncBufferedChannel.submit() and submit_stream() over mp.Queue."""
