# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Errors of the runtime."""


class StoppedError(Exception):
    """A wait ended because the token of the task it runs in was stopped: a
    channel's send or receive, or Runtime.wait() for a task its stop ended
    before it returned. A task that ends with it while its token is stopped is
    stopped, not failed."""
