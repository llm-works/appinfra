# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Deferred value resolution across the multiprocessing pickle boundary."""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any


@dataclass
class Lazy:
    """Deferred value resolved from a module qualname + config in the subprocess.

    Wraps a callable or object so it never crosses the ``mp.Process`` pickle
    boundary directly. The child imports the factory module and calls the
    factory, so anything the factory constructs (nested closures, live
    resources) is created in the child rather than pickled from the parent.

    Required on Python 3.14+ where the default multiprocessing start method
    (``forkserver``) pickles the target's args and rejects nested closures /
    non-module-level callables. Optional on ``fork``.

    Fields:
        factory: Module qualname of a callable to import, in the form
            ``"pkg.mod:build_health"``. Split on the final ``":"``.
        config: Optional argument passed to the factory. Must be picklable
            (a dataclass with plain fields is the intended shape).

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
    config: Any = None

    def resolve(self) -> Any:
        """Import the factory and invoke it (with ``config`` if set)."""
        module_name, _, attr = self.factory.rpartition(":")
        if not module_name or not attr:
            raise ValueError(
                f"Lazy.factory must be 'module.path:attr', got {self.factory!r}"
            )
        fn = getattr(importlib.import_module(module_name), attr)
        return fn(self.config) if self.config is not None else fn()
