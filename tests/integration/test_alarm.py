# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for alarm_timeout, the SIGALRM-based timeout for a block of code.

Expiry is mostly exercised by calling the installed handler directly;
test_expiry_interrupts_a_blocked_wait lets the kernel deliver SIGALRM.
"""

import signal
import threading
from collections.abc import Iterator
from typing import Any

import pytest

from appinfra.alarm import alarm_timeout

pytestmark = pytest.mark.skipif(
    not hasattr(signal, "SIGALRM"), reason="Requires SIGALRM (Unix only)"
)


class _ExpiredError(Exception):
    pass


def _sentinel_handler(signum: int, frame: Any) -> None:
    pass


def _fire_installed_handler() -> None:
    """Run the SIGALRM handler as the kernel would on expiry."""
    signal.getsignal(signal.SIGALRM)(signal.SIGALRM, None)


@pytest.fixture(autouse=True)
def _restore_sigalrm() -> Iterator[None]:
    """Leave SIGALRM's handler and timer as each test found them."""
    before = signal.getsignal(signal.SIGALRM)
    yield
    signal.setitimer(signal.ITIMER_REAL, 0)
    signal.signal(signal.SIGALRM, before)


def test_expiry_interrupts_a_blocked_wait() -> None:
    """The wait would block 5 s; the 50 ms timer interrupts it. A late signal only
    delays the interruption, so no elapsed time is asserted."""
    with pytest.raises(_ExpiredError), alarm_timeout(0.05, _ExpiredError):
        threading.Event().wait(5.0)


def test_expiry_raises_the_given_exception() -> None:
    with pytest.raises(_ExpiredError), alarm_timeout(5.0, _ExpiredError):
        _fire_installed_handler()


def test_disarms_the_timer_after_the_block() -> None:
    with alarm_timeout(5.0, _ExpiredError):
        pass
    assert signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0)


def test_sub_second_timeout_arms_the_timer() -> None:
    with alarm_timeout(0.5, _ExpiredError):
        remaining, _ = signal.getitimer(signal.ITIMER_REAL)
    assert 0.0 < remaining <= 0.5


def test_zero_timeout_arms_nothing() -> None:
    signal.signal(signal.SIGALRM, _sentinel_handler)
    with alarm_timeout(0, _ExpiredError):
        assert signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0)
        assert signal.getsignal(signal.SIGALRM) is _sentinel_handler


def test_restores_the_previous_handler() -> None:
    signal.signal(signal.SIGALRM, _sentinel_handler)
    with alarm_timeout(5.0, _ExpiredError):
        assert signal.getsignal(signal.SIGALRM) is not _sentinel_handler
    assert signal.getsignal(signal.SIGALRM) is _sentinel_handler


def test_restores_the_previous_handler_after_expiry() -> None:
    signal.signal(signal.SIGALRM, _sentinel_handler)
    with pytest.raises(_ExpiredError), alarm_timeout(5.0, _ExpiredError):
        _fire_installed_handler()
    assert signal.getsignal(signal.SIGALRM) is _sentinel_handler
    assert signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0)


def test_restores_the_default_handler() -> None:
    """SIG_DFL is 0, so a truthiness check on the saved handler would skip it."""
    signal.signal(signal.SIGALRM, signal.SIG_DFL)
    with alarm_timeout(5.0, _ExpiredError):
        pass
    assert signal.getsignal(signal.SIGALRM) == signal.SIG_DFL


def test_runs_the_block_without_a_timeout_off_the_main_thread() -> None:
    signal.signal(signal.SIGALRM, _sentinel_handler)
    seen: dict[str, Any] = {}

    def worker() -> None:
        try:
            with alarm_timeout(5.0, _ExpiredError):
                seen["handler"] = signal.getsignal(signal.SIGALRM)
                seen["timer"] = signal.getitimer(signal.ITIMER_REAL)
        except BaseException as e:
            seen["error"] = e

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()

    assert "error" not in seen
    assert seen["handler"] is _sentinel_handler
    assert seen["timer"] == (0.0, 0.0)


def test_leaves_an_outer_timer_alone() -> None:
    signal.signal(signal.SIGALRM, _sentinel_handler)
    signal.setitimer(signal.ITIMER_REAL, 60.0)

    with alarm_timeout(0.5, _ExpiredError):
        assert signal.getsignal(signal.SIGALRM) is _sentinel_handler
        assert signal.getitimer(signal.ITIMER_REAL)[0] > 0.5

    assert signal.getsignal(signal.SIGALRM) is _sentinel_handler
    assert signal.getitimer(signal.ITIMER_REAL)[0] > 0.5
