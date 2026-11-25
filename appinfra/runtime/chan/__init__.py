# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Channels between tasks, like Go's chan, select over them, and pipes: channels
between processes."""

from .chan import Chan
from .errors import ClosedError
from .pipe import PipeRecvEnd, PipeSendEnd, Receiver, Sender, pipe
from .select import Recv, Send, aselect, select

__all__ = [
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
]
