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
  1. ``pickle.dumps`` directly — fast smoke of the underlying pickle
     protocol behavior (nested closure fails, ``Lazy`` succeeds).
  2. Real ``mp.get_context("forkserver").Process`` with the adapter
     passed as a target arg — reproduces the production code path
     where ``ForkingPickler`` serializes the ``Service`` (which holds
     the adapter) at ``.start()`` time. This is what actually fires
     in production; the pickle tests only cover the mechanism it uses.

Neither path touches the process-global start method, so these tests
are safe to run alongside the rest of the suite regardless of the host
Python's default.
"""

from __future__ import annotations

import multiprocessing as mp
import pickle
from typing import Any

import pytest

from appinfra.app.fastapi.config.api import ApiConfig
from appinfra.app.fastapi.runtime.adapter import (
    FastAPIAdapter,
    LifecycleCallbackDefinition,
    RouteDefinition,
)
from appinfra.subprocess import Lazy


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


def _build_startup_callback(_cfg: Any = None) -> Any:
    """Module-level factory for a startup callback.

    Lifecycle callbacks (startup, shutdown) also need to cross the pickle
    boundary; this exercises that path.
    """

    async def on_startup(app: Any) -> None:
        app.state.started = True

    return on_startup


def _child_verify_lifecycle(adapter: FastAPIAdapter, result_q: mp.Queue[str]) -> None:
    """Child-process entry for lifecycle callback verification."""
    try:
        assert isinstance(adapter._startup_callbacks[0].callback, Lazy), (
            "expected Lazy pre-resolve"
        )
        adapter._resolve_lazy()
        assert callable(adapter._startup_callbacks[0].callback), (
            "expected callable post-resolve"
        )
        result_q.put("ok")
    except BaseException as e:  # noqa: BLE001
        result_q.put(f"fail: {type(e).__name__}: {e}")


def _child_verify(adapter: FastAPIAdapter, result_q: mp.Queue[str]) -> None:
    """Child-process entry: adapter arrives already-unpickled by ForkingPickler.

    Mirrors production: ``ProcessRunner`` passes ``self.service`` (which
    holds the adapter) as an arg to ``mp.Process(target=_process_entry,
    args=(self.service, ...))``. ForkingPickler pickles the args on
    ``.start()`` and the child receives them via its own unpickle.
    """
    try:
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

    def test_nested_closure_adapter_fails_forkserver_spawn(self):
        """Reproduce #151: passing an adapter with a nested-closure handler
        as a ``Process`` arg fails at spawn.

        This is the exact production code path: ``ForkingPickler`` walks
        the arg tuple during ``Process.start()`` and rejects the nested
        closure. Without ``Lazy``, users get this failure the first time
        their service spawns under 3.14 forkserver.
        """
        if "forkserver" not in mp.get_all_start_methods():
            pytest.skip("forkserver start method not available on this platform")

        adapter = FastAPIAdapter(ApiConfig())
        adapter.add_route(
            RouteDefinition(path="/health", handler=_make_nested_closure_handler())
        )

        ctx = mp.get_context("forkserver")
        result_q: mp.Queue[str] = ctx.Queue()
        proc = ctx.Process(target=_child_verify, args=(adapter, result_q))

        # ForkingPickler serializes args synchronously in .start(); a
        # nested closure raises before the child is spawned.
        with pytest.raises((AttributeError, pickle.PicklingError)):
            proc.start()

    def test_lazy_adapter_survives_forkserver_spawn(self):
        """Fix: adapter with ``Lazy`` handler crosses forkserver as a
        ``Process`` arg and resolves in the child.

        Uses ``mp.get_context("forkserver")`` so the test doesn't touch the
        process-global start method (which would leak to other tests).
        """
        if "forkserver" not in mp.get_all_start_methods():
            pytest.skip("forkserver start method not available on this platform")

        adapter = FastAPIAdapter(ApiConfig())
        adapter.add_route(
            RouteDefinition(path="/health", handler=Lazy(f"{__name__}:_build_health"))
        )

        ctx = mp.get_context("forkserver")
        result_q: mp.Queue[str] = ctx.Queue()
        proc = ctx.Process(target=_child_verify, args=(adapter, result_q))
        proc.start()
        proc.join(timeout=30.0)

        assert not proc.is_alive(), "child did not exit within 30s"
        assert proc.exitcode == 0, f"child exit code {proc.exitcode}"
        assert result_q.get(timeout=1.0) == "ok"

    def test_lazy_lifecycle_callback_survives_forkserver_spawn(self):
        """Lifecycle callbacks with Lazy cross forkserver and resolve in child.

        Extends route handler coverage to lifecycle callbacks (startup,
        shutdown), which use the same _resolve_lazy mechanism but have their
        own walker entry in FastAPIAdapter._resolve_lazy().
        """
        if "forkserver" not in mp.get_all_start_methods():
            pytest.skip("forkserver start method not available on this platform")

        adapter = FastAPIAdapter(ApiConfig())
        adapter.add_startup_callback(
            LifecycleCallbackDefinition(
                callback=Lazy(f"{__name__}:_build_startup_callback"),
                after_lifespan=False,
            )
        )

        ctx = mp.get_context("forkserver")
        result_q: mp.Queue[str] = ctx.Queue()
        proc = ctx.Process(target=_child_verify_lifecycle, args=(adapter, result_q))
        proc.start()
        proc.join(timeout=30.0)

        assert not proc.is_alive(), "child did not exit within 30s"
        assert proc.exitcode == 0, f"child exit code {proc.exitcode}"
        assert result_q.get(timeout=1.0) == "ok"
