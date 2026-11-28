# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Errors of channels."""


class ClosedError(Exception):
    """The channel is closed: a send on it, or a receive once it is drained.
    From select(), *index* is the position of the case whose channel it is."""

    index: int | None = None


class ResponseError(Exception):
    """A Correlator's reply that its *failed* function calls a failure; the
    reply is *response*."""

    def __init__(self, response: object) -> None:
        super().__init__(f"failed response: {response!r}")
        self.response = response
