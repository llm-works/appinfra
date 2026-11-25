# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Errors of channels."""


class ClosedError(Exception):
    """The channel is closed: a send on it, or a receive once it is drained.
    From select(), *index* is the position of the case whose channel it is."""

    index: int | None = None
