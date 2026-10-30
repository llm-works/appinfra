# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""SIGALRM-based timeout for a block of code.

A leaf module with no appinfra imports, so the logging package can use it without
an import cycle.
"""

import signal
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from types import FrameType


def _can_arm() -> bool:
    """SIGALRM exists and this is the main thread, the only one that can set a
    signal handler."""
    return (
        hasattr(signal, "SIGALRM")
        and threading.current_thread() is threading.main_thread()
    )


@contextmanager
def alarm_timeout(
    seconds: float, make_exc: Callable[[], BaseException]
) -> Iterator[None]:
    """Raise ``make_exc()`` in the block if it runs longer than ``seconds``.

    The block runs without a timeout when ``seconds`` is not positive, off the main
    thread, where Python cannot set a signal handler, on platforms without SIGALRM,
    when a timer is already armed (the outer deadline then applies, and its timer
    and handler are left untouched), and when the current SIGALRM handler was not
    installed from Python (``getsignal`` returns None): it could not be put back.

    The previous SIGALRM handler is restored on exit.
    """
    if (
        seconds <= 0
        or not _can_arm()
        or signal.getitimer(signal.ITIMER_REAL)[0] > 0
        or signal.getsignal(signal.SIGALRM) is None
    ):
        yield
        return

    def expired(signum: int, frame: FrameType | None) -> None:
        raise make_exc()

    previous = signal.signal(signal.SIGALRM, expired)
    try:
        signal.setitimer(signal.ITIMER_REAL, seconds)
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
