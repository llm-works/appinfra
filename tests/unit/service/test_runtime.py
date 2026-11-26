# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for the service Runtime's API that need no running runtime."""

from unittest.mock import MagicMock

import pytest

from appinfra.runtime import ChanClosedError
from appinfra.service import HealthTimeoutError, Runtime


def test_a_ready_timing_out_as_the_runtime_stops_raises_its_timeout() -> None:
    """ready() timed out, and the runtime's inbox closed before the follow-up
    request: the caller still gets HealthTimeoutError, not the closed inbox."""
    rt = Runtime(MagicMock())
    rt._ask = MagicMock(side_effect=[TimeoutError(), ChanClosedError()])  # type: ignore[method-assign]
    runner = MagicMock()
    runner.name = "svc"

    with pytest.raises(HealthTimeoutError):
        rt._await_ready(runner, left=0.1, timeout=5.0)
