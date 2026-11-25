# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Errors of the runtime."""


class StoppedError(Exception):
    """A wait, such as a channel's send or receive, ended because the token of
    the task it runs in was stopped. A task that ends with it ends cleanly, as
    it would on a cancel."""
