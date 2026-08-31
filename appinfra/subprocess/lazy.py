# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Deferred value resolution across the multiprocessing pickle boundary."""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from typing import Any


class _Unset:
    """Picklable sentinel distinguishing omitted config from explicit ``None``."""

    __slots__ = ()

    def __reduce__(self) -> tuple[object, tuple[()]]:
        # Import at call time so _get_unset (defined after UNSET) is available.
        from appinfra.subprocess.lazy import _get_unset

        return (_get_unset, ())

    def __repr__(self) -> str:
        return "UNSET"


UNSET = _Unset()


def _get_unset() -> _Unset:
    """Pickle helper returning the singleton; preserves identity across pickle."""
    return UNSET


@dataclass
class Lazy:
    """Deferred value resolved from a module qualname + config in the subprocess.

    Wraps a callable or object so it never crosses the ``mp.Process`` pickle
    boundary directly. The child imports the factory module and calls the
    factory, so anything the factory constructs (nested closures, live
    resources) is created in the child rather than pickled from the parent.

    Required on Python 3.14+ where ``forkserver`` (default on POSIX except
    macOS) and ``spawn`` (default on Windows and macOS) pickle the target's
    args and reject nested closures / non-module-level callables. Optional
    on ``fork``.

    Fields:
        factory: Module qualname of a callable to import, in the form
            ``"pkg.mod:build_health"``. Split on the final ``":"``.
        config: Argument passed to the factory. Must be picklable (a dataclass
            with plain fields is the intended shape). Defaults to ``UNSET``;
            when omitted the factory is called with no arguments. Explicit
            ``None`` is passed through: ``Lazy("m:f", None)`` calls ``f(None)``.

    Example:
        # Module-level factory (produces something that can't be pickled)
        def build_counter(config):
            counter = {"n": 0}
            def increment():
                counter["n"] += 1
                return counter["n"]
            return increment

        # Anywhere the value has to cross a subprocess boundary
        lazy = Lazy("myapp.workers:build_counter", CounterConfig(...))
        # ... crosses pickle ...
        real_callable = lazy.resolve()

    Unsupported: capturing parent-process state created after subprocess spawn
    (e.g. an ``mp.Value`` shared post-spawn) cannot cross ``forkserver``. Such
    consumers must stay on ``fork`` start method or Python <=3.13.
    """

    factory: str
    config: Any = field(default_factory=lambda: UNSET)

    def resolve(self) -> Any:
        """Import the factory and invoke it (with ``config`` if provided)."""
        module_name, _, attr = self.factory.rpartition(":")
        if not module_name or not attr:
            raise ValueError(
                f"Lazy.factory must be 'module.path:attr', got {self.factory!r}"
            )
        fn = getattr(importlib.import_module(module_name), attr)
        return fn() if isinstance(self.config, _Unset) else fn(self.config)
