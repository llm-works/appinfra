# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Channels between tasks, like Go's chan, and select over them."""

from .chan import Chan
from .errors import ClosedError
from .select import Recv, Send, aselect, select

__all__ = [
    "Chan",
    "ClosedError",
    "Recv",
    "Send",
    "aselect",
    "select",
]
