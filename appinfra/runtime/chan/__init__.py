# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Channels between tasks, like Go's chan, select over them, and pipes: channels
between processes."""

from .chan import Chan
from .correlator import Correlator
from .errors import ClosedError, ResponseError
from .pipe import PipeRecvEnd, PipeSendEnd, Receiver, Sender, pipe
from .select import Recv, Send, aselect, select

__all__ = [
    "Chan",
    "ClosedError",
    "Correlator",
    "ResponseError",
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
