# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Interpreter exit after closing a process channel that holds unread data."""

import subprocess
import sys
import textwrap

import pytest

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
