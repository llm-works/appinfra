# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Regression tests for the ``Lazy`` factory across the multiprocessing
pickle boundary.

Python 3.14 changed the default multiprocessing start method to
``forkserver``, which pickles the target's args at spawn time. Nested
closures / local functions raise ``AttributeError`` at that pickle step;
``Lazy`` wraps them so the closure never crosses the boundary and is
constructed in the child instead.

These tests exercise the boundary two ways:
  1. ``pickle.dumps`` directly — fast, models what ``ForkingPickler`` does.
  2. Real ``mp.get_context("forkserver").Process`` — end-to-end, without
     touching the process-global start method.
"""

from __future__ import annotations

import multiprocessing as mp
import pickle
from typing import Any

import pytest

from appinfra.app.fastapi import Lazy
from appinfra.app.fastapi.config.api import ApiConfig
from appinfra.app.fastapi.runtime.adapter import (
    FastAPIAdapter,
    RouteDefinition,
)


def _make_nested_closure_handler() -> Any:
    """Reproduce the user pattern that broke on 3.14 forkserver.

    A factory returns a nested closure; the closure's ``__qualname__``
    contains ``<locals>`` which the pickle protocol cannot round-trip.
    """

    def health() -> dict[str, bool]:
        return {"ready": True}

    return health


def _build_health(_cfg: Any = None) -> Any:
    """Module-level factory used with ``Lazy``.

    The returned coroutine is a nested closure — but it's constructed in
    the child process after unpickling, so it never crosses pickle.
    """

    async def health() -> dict[str, bool]:
        return {"ready": True}

    return health


def _child_verify(payload: bytes, result_q: mp.Queue[str]) -> None:
    """Child-process entry: unpickle adapter, resolve, verify handler."""
    try:
        adapter = pickle.loads(payload)
        assert isinstance(adapter._routes[0].handler, Lazy), "expected Lazy pre-resolve"
        adapter._resolve_lazy()
        assert callable(adapter._routes[0].handler), "expected callable post-resolve"
        result_q.put("ok")
    except BaseException as e:  # noqa: BLE001 — surface any failure to parent
        result_q.put(f"fail: {type(e).__name__}: {e}")


@pytest.mark.integration
class TestForkserverPickleBoundary:
    """Regression for pm ticket #151."""

    def test_nested_closure_handler_fails_pickle(self):
        """Baseline: nested closure inside a RouteDefinition cannot pickle.

        This is the failure mode users hit on 3.14 forkserver. Guards the
        test premise — if pickling ever starts silently accepting local
        functions, the whole ``Lazy`` design would be unnecessary.
        """
        adapter = FastAPIAdapter(ApiConfig())
        adapter.add_route(
            RouteDefinition(path="/health", handler=_make_nested_closure_handler())
        )
        with pytest.raises((AttributeError, pickle.PicklingError)):
            pickle.dumps(adapter)

    def test_lazy_handler_survives_pickle(self):
        """Lazy pickles as a plain dataclass; resolves to real callable after."""
        adapter = FastAPIAdapter(ApiConfig())
        adapter.add_route(
            RouteDefinition(path="/health", handler=Lazy(f"{__name__}:_build_health"))
        )

        restored = pickle.loads(pickle.dumps(adapter))

        assert isinstance(restored._routes[0].handler, Lazy)
        restored._resolve_lazy()
        assert callable(restored._routes[0].handler)

    def test_lazy_handler_under_real_forkserver(self):
        """End-to-end: spawn a real forkserver subprocess and verify the
        adapter unpickles + resolves + yields a callable handler.

        Uses ``mp.get_context("forkserver")`` so the test doesn't touch the
        process-global start method (which would leak to other tests).
        """
        if "forkserver" not in mp.get_all_start_methods():
            pytest.skip("forkserver start method not available on this platform")

        adapter = FastAPIAdapter(ApiConfig())
        adapter.add_route(
            RouteDefinition(path="/health", handler=Lazy(f"{__name__}:_build_health"))
        )
        payload = pickle.dumps(adapter)

        ctx = mp.get_context("forkserver")
        result_q: mp.Queue[str] = ctx.Queue()
        proc = ctx.Process(target=_child_verify, args=(payload, result_q))
        proc.start()
        proc.join(timeout=30.0)

        assert not proc.is_alive(), "child did not exit within 30s"
        assert proc.exitcode == 0, f"child exit code {proc.exitcode}"
        assert result_q.get(timeout=1.0) == "ok"
