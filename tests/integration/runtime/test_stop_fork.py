# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""StopToken in a child forked while another thread used tokens."""

import multiprocessing as mp
import threading

import pytest

from appinfra.runtime import StopToken, stop


def _use_tokens() -> None:
    """Child target: each call takes the module lock."""
    token = StopToken()
    child = token.child()
    token.stop()
    assert child.wait(timeout=1.0)


@pytest.mark.skipif(
    "fork" not in mp.get_all_start_methods(), reason="needs the fork start method"
)
# Forks from a thread while another thread runs, on purpose: that is the case tested
@pytest.mark.filterwarnings(
    "ignore:This process .* is multi-threaded:DeprecationWarning"
)
def test_a_child_forked_while_the_lock_is_held_can_use_tokens():
    """A fork copies the module lock as it is; held by a parent thread at that
    moment, it would stay held in the child, where no thread releases it."""
    held, release = threading.Event(), threading.Event()

    def hold() -> None:
        with stop._lock:  # Private: the lock every token shares
            held.set()
            release.wait(10.0)

    holder = threading.Thread(target=hold, daemon=True)
    holder.start()
    assert held.wait(5.0)
    process = mp.get_context("fork").Process(target=_use_tokens, daemon=True)
    try:
        process.start()
        process.join(timeout=10.0)  # the deadline is the failure path
        assert not process.is_alive()
        assert process.exitcode == 0
    finally:
        release.set()
        holder.join(5.0)
        if process.is_alive():
            process.kill()
            process.join(5.0)
