# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""The public API of appinfra.runtime: what it exports, and nothing more. A
name added here is added to the API on purpose."""

import inspect

import pytest

import appinfra.runtime
import appinfra.runtime.chan
from appinfra.runtime import PipeReceiver, PipeRecvEnd, PipeSendEnd, PipeSender, Task


@pytest.mark.parametrize(
    ("cls", "maker"),
    [
        (Task, "spawn"),
        (PipeSendEnd, "pipe"),
        (PipeRecvEnd, "pipe"),
        (PipeSender, "open"),
        (PipeReceiver, "open"),
    ],
)
def test_what_the_api_makes_cannot_be_constructed(cls: type, maker: str) -> None:
    """As re.Match: its constructor takes nothing, and refuses, naming
    where one comes from."""
    assert not inspect.signature(cls).parameters
    with pytest.raises(TypeError, match=maker):
        cls()


def test_the_runtime_exports_its_api() -> None:
    assert set(appinfra.runtime.__all__) == {
        "Chan",
        "ChanClosedError",
        "ChanRecv",
        "ChanSend",
        "PipeReceiver",
        "PipeRecvEnd",
        "PipeSendEnd",
        "PipeSender",
        "Runtime",
        "StopToken",
        "StoppedError",
        "Task",
        "TaskDone",
        "aselect",
        "pipe",
        "select",
        "stopping",
        "task_id",
    }
    for name in appinfra.runtime.__all__:
        assert hasattr(appinfra.runtime, name)


def test_the_chan_package_exports_its_api() -> None:
    assert set(appinfra.runtime.chan.__all__) == {
        "Chan",
        "ClosedError",
        "PipeRecvEnd",
        "PipeSendEnd",
        "Receiver",
        "Recv",
        "Send",
        "Sender",
        "aselect",
        "pipe",
        "select",
    }
    for name in appinfra.runtime.chan.__all__:
        assert hasattr(appinfra.runtime.chan, name)
