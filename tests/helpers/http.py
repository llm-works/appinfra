# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""HTTP helpers for tests that start a server in another process."""

import time

import requests


def wait_ready(url: str, deadline_secs: float) -> None:
    """Poll ``url`` until it answers with a success status, or fail at the deadline.

    A refused connection, a poll that times out and an error status all mean "not ready
    yet": a server whose socket is listening can accept a connection before it is able to
    answer, and a loaded machine may take longer than one poll's timeout to do so.
    """
    deadline = time.monotonic() + deadline_secs
    while time.monotonic() < deadline:
        try:
            if requests.get(url, timeout=0.5).ok:
                return
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            pass
        time.sleep(0.1)
    raise AssertionError(f"{url} did not become ready within {deadline_secs}s")
