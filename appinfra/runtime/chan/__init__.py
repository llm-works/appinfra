# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Channels between tasks, like Go's chan."""

from .chan import Chan
from .errors import ClosedError

__all__ = [
    "Chan",
    "ClosedError",
]
