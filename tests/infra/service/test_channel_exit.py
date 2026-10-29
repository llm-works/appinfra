# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Interpreter exit after closing a process channel: no hang, no lost messages."""

import asyncio
import multiprocessing
import queue
import subprocess
import sys
import textwrap
from typing import Any

import pytest

from appinfra.service import AsyncProcessQueueTransport, ProcessQueueTransport

pytestmark = pytest.mark.integration

# 16 x 64 KiB is well past the OS pipe buffer (64 KiB on Linux), so the
# queue's feeder thread blocks writing to a pipe nobody reads.
_SYNC = """
from appinfra.service import ProcessQueueChannelFactory

pair = ProcessQueueChannelFactory().create_pair()
for i in range(16):
    pair.parent.send({"id": str(i), "data": "x" * 65536})
pair.close()
"""

_ASYNC = """
import asyncio

from appinfra.service import AsyncProcessQueueChannelFactory

async def main():
    pair = AsyncProcessQueueChannelFactory().create_pair()
    for i in range(16):
        await pair.parent.send({"id": str(i), "data": "x" * 65536})
    await pair.close()

asyncio.run(main())
"""


@pytest.mark.parametrize("script", [_SYNC, _ASYNC], ids=["sync", "async"])
def test_exit_does_not_block_on_unread_data(script: str) -> None:
    """A closed channel with unread data does not keep the interpreter alive."""
    try:
        result = subprocess.run(
            [sys.executable, "-c", textwrap.dedent(script)],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        pytest.fail("interpreter exit blocked on the closed channel's feeder thread")
    assert result.returncode == 0, result.stderr


# Many small messages, each under PIPE_BUF (4 KiB) so the feeder writes each one
# atomically: a feeder cut off at exit loses whole messages and never leaves a
# partial one for the reader to block on.
_COUNT = 5000
_DATA = "x" * 1000


def _send_then_exit(outbound: Any, inbound: Any, use_async: bool) -> None:
    """Send _COUNT messages, close the transport and return, ending the process."""
    if use_async:

        async def main() -> None:
            transport = AsyncProcessQueueTransport(outbound=outbound, inbound=inbound)
            # Put directly: each awaited send() goes through the executor, which is
            # slow enough for the feeder to keep up, so the buffer would stay empty
            for _ in range(_COUNT):
                outbound.put(_DATA)
            await transport.close()

        asyncio.run(main())
    else:
        transport = ProcessQueueTransport(outbound=outbound, inbound=inbound)
        for _ in range(_COUNT):
            transport.send(_DATA)
        transport.close()


@pytest.mark.parametrize("use_async", [False, True], ids=["sync", "async"])
def test_close_delivers_to_a_live_reader(use_async: bool) -> None:
    """Messages sent before close() reach a reader that is still reading."""
    ctx = multiprocessing.get_context("spawn")
    outbound, inbound = ctx.Queue(), ctx.Queue()
    proc = ctx.Process(target=_send_then_exit, args=(outbound, inbound, use_async))
    proc.start()
    received = 0
    try:
        while received < _COUNT:
            outbound.get(timeout=10)
            received += 1
    except queue.Empty:
        pass
    finally:
        proc.join(timeout=30)
        outbound.close()
        inbound.close()
    assert received == _COUNT, f"lost {_COUNT - received} of {_COUNT} messages"
